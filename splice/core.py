"""The :class:`Splice` runtime: generate once, cache, execute in a sandbox, repair."""

from __future__ import annotations

import time
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .config import SpliceConfig
from .deps import prepare_dependencies
from .errors import ExecutionError, PromptRequiredError, SandboxViolation, ValidationError
from .executor import Executor
from .paths import require_splice_directory
from .prompt import PromptBundle, bundle_prompt, load_context_docs
from .specs import FunctionSpec, load_function_spec
from .store import ArtifactKey, ArtifactStore, resolve_database_path
from .validation import build_validators

if TYPE_CHECKING:
    from .sandbox import Sandbox

_BUILTIN_TYPE_NAMES = frozenset(
    {
        "int",
        "float",
        "str",
        "bool",
        "bytes",
        "list",
        "dict",
        "tuple",
        "set",
        "object",
        "typing",
        "None",
        "Any",
    }
)


class CodeGenerator(Protocol):
    """Anything that turns a prompt bundle into Python source.

    :class:`splice.client.OpenRouterClient` is the default; tests and offline
    demos pass their own.
    """

    def generate_code(self, bundle: PromptBundle, config: SpliceConfig) -> str: ...


@dataclass(frozen=True)
class Session:
    """Opaque session token. Generated code is cached per session."""

    id: str

    @staticmethod
    def ensure(existing: Session | None = None) -> Session:
        """Return ``existing`` or create a fresh session."""

        if existing is not None:
            return existing
        return Session(id=str(uuid.uuid4()))


def _required_modules(spec: FunctionSpec) -> list[str]:
    """Top-level modules named by the contract types and ``type_sources``."""

    roots: set[str] = set()
    paths = [*spec.contracts.inputs.values(), spec.contracts.output]
    paths += [str(ts.get("import", "")) for ts in spec.type_sources]
    for path in paths:
        root = str(path).split(".")[0].split("[")[0].strip()
        if root and root.isidentifier() and root not in _BUILTIN_TYPE_NAMES and "." in str(path):
            roots.add(root)
    return sorted(roots)


class Splice:
    """Top-level entry point.

    >>> sp = Splice()
    >>> sp.run("my_op", session=Session.ensure(), prompt="Return (a + b) / 2", a=4.0, b=6.0)
    5.0

    Parameters
    ----------
    config_path:
        Explicit path to ``splice.yaml``. Defaults to the nearest ``.splice/``.
    client:
        Code generator. Defaults to :class:`~splice.client.OpenRouterClient`.
    sandbox:
        Execution backend. Defaults to ``sandbox.backend`` from config.
    """

    def __init__(
        self,
        config_path: str | None = None,
        *,
        client: CodeGenerator | None = None,
        sandbox: Sandbox | None = None,
    ) -> None:
        self._config_path = config_path
        self._client = client
        self._sandbox = sandbox

    def spec(self, name: str, start_path: Path | None = None) -> FunctionSpec:
        return load_function_spec(name, start_path=start_path)

    def _make_client(self) -> CodeGenerator:
        if self._client is not None:
            return self._client
        from . import client as client_module  # looked up at call time so tests can patch it

        return client_module.OpenRouterClient()

    def run(
        self,
        name: str,
        *,
        session: Session,
        prompt: str | None = None,
        start_path: Path | None = None,
        run_now: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Generate (or reuse) code for spec ``name`` and call it with ``kwargs``.

        * The first call for a ``(session, name)`` pair needs ``prompt``; later
          calls reuse the cached function as long as the spec, context docs and
          config are unchanged.
        * ``run_now=False`` generates and caches without executing.
        * If execution fails, the error is fed back to the model for up to
          ``retries.repair`` repair attempts.
        """

        base = require_splice_directory(start_path)
        cfg = SpliceConfig.load(self._config_path, start_path=base)
        spec = load_function_spec(name, start_path=base)
        store = self._open_store(cfg, base)
        store.ensure_session(session.id)
        store.purge_expired(cfg.sessions.ttl)

        if not run_now and prompt is None:
            warnings.warn(
                "Splice.run(run_now=False) called without a prompt: nothing to generate or run.",
                stacklevel=2,
            )
            return None

        key = self._cache_key(session, name, spec, prompt, base)
        client: CodeGenerator | None = None

        def generate(session_prompt: str, note: str = "") -> str:
            nonlocal client
            client = client or self._make_client()
            bundle = bundle_prompt(spec, cfg, session_prompt=session_prompt, start_path=base)
            store.write_event("generation_requested", session.id, name, note)
            started = time.perf_counter()
            code = client.generate_code(bundle, cfg)
            elapsed = (time.perf_counter() - started) * 1000.0
            store.put(key, code)
            store.write_event(
                "generation_succeeded",
                session.id,
                name,
                f"{note + ' ' if note else ''}duration_ms={elapsed:.1f}",
            )
            return code

        code = self._cached_code(store, key, cfg, prompt_given=prompt is not None)
        if code is None:
            if prompt is None:
                raise PromptRequiredError(
                    f"No cached code for '{name}' in this session; pass prompt= on the first call"
                )
            code = generate(prompt)

        if not run_now:
            return None

        validators = build_validators(spec)
        for arg_name, validator in validators.input_validators.items():
            if arg_name in kwargs:
                kwargs[arg_name] = validator(kwargs[arg_name])

        extra_sys_paths = prepare_dependencies(
            policy=cfg.dependencies.policy,
            modules=_required_modules(spec),
            start_path=base,
            session_id=session.id,
        )

        attempts = max(int(cfg.retries.repair), 0) + 1
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                result = Executor.run(
                    code,
                    spec.contracts.signature,
                    kwargs,
                    cfg,
                    extra_sys_paths=extra_sys_paths,
                    sandbox=self._sandbox,
                )
                result = validators.output_validator(result)
            except (ExecutionError, SandboxViolation, ValidationError) as exc:
                store.write_event(
                    "execution_failed", session.id, name, f"{type(exc).__name__}: {exc}"
                )
                if attempt >= attempts - 1:
                    raise
                repair_prompt = (
                    f"The previous generated function raised {type(exc).__name__}: {exc}. "
                    f"Return a fixed function for signature: {spec.contracts.signature}"
                )
                code = generate(repair_prompt, note="repair")
                continue
            elapsed = (time.perf_counter() - started) * 1000.0
            store.write_event("execution_succeeded", session.id, name, f"duration_ms={elapsed:.1f}")
            return result
        raise AssertionError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _open_store(cfg: SpliceConfig, base: Path) -> ArtifactStore:
        return ArtifactStore(database_path=resolve_database_path(cfg, base))

    @staticmethod
    def _cache_key(
        session: Session, name: str, spec: FunctionSpec, prompt: str | None, base: Path
    ) -> ArtifactKey:
        spec_path = base / "functions" / f"{name}.yaml"
        config_path = base / "splice.yaml"
        docs = "\n\n".join(c for _, c in load_context_docs(spec.context_docs, base))
        return ArtifactKey(
            session_id=session.id,
            function_name=name,
            prompt_hash=ArtifactStore.hash_prompt(prompt if prompt is not None else spec.prompt),
            spec_hash=ArtifactStore.hash_spec_yaml(
                spec_path.read_text() if spec_path.exists() else ""
            ),
            context_hash=ArtifactStore.hash_context_docs(docs),
            config_hash=ArtifactStore.hash_config_yaml(
                config_path.read_text() if config_path.exists() else ""
            ),
        )

    @staticmethod
    def _cached_code(
        store: ArtifactStore, key: ArtifactKey, cfg: SpliceConfig, *, prompt_given: bool
    ) -> str | None:
        art = store.get_fresh(key, cfg.sessions.ttl)
        if art is not None:
            return art.code
        if prompt_given:
            return None
        latest = store.get_latest_for_session(
            session_id=key.session_id,
            function_name=key.function_name,
            spec_hash=key.spec_hash,
            context_hash=key.context_hash,
            config_hash=key.config_hash,
        )
        return latest.code if latest is not None else None
