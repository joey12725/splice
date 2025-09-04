from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


@dataclass(frozen=True)
class Session:
    """Opaque session token wrapper.

    Phase 0: minimal implementation with a helper to ensure a session exists.
    """

    id: str

    @staticmethod
    def ensure(existing: Session | None = None) -> Session:
        """Return the provided session or create a new one.

        Parameters
        ----------
        existing: Optional[Session]
            An existing session to reuse.
        """

        if existing is not None:
            return existing
        return Session(id=str(uuid.uuid4()))


class Splice:
    """Top-level entry point for the Splice runtime (Phases 1–5).

    Provides spec loading and `run` which generates code via the client,
    caches it per-session in SQLite, and executes it in the sandbox.
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path: str | None = config_path
        self._config_cache = None

    def _config(self) -> "SpliceConfig":
        from .config import SpliceConfig

        if self._config_cache is None:
            self._config_cache = SpliceConfig.load(self._config_path)
        return self._config_cache

    def spec(self, name: str) -> "FunctionSpec":
        from .specs import FunctionSpec, load_function_spec

        spec: FunctionSpec = load_function_spec(name)
        return spec

    def run(
        self,
        name: str,
        *,
        session: "Session",
        prompt: str | None = None,
        start_path: "Path | None" = None,
        run_now: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Generate or reuse code for `name` and execute with kwargs.

        - Requires `prompt` on first call for (session, name) with given inputs.
        - Caches by (session_id, name, prompt_hash, spec_hash, context_hash, config_hash).
        """

        from pathlib import Path
        from .client import OpenRouterClient
        from .executor import Executor
        from .prompt import bundle_prompt
        from .store import ArtifactStore, ArtifactKey
        from .paths import require_splice_directory
        from .deps import prepare_dependencies
        import time

        base = require_splice_directory(start_path)
        # Load config relative to base so tests using tmp .splice work
        from .config import SpliceConfig
        cfg = SpliceConfig.load(self._config_path, start_path=base)
        from .specs import load_function_spec
        spec = load_function_spec(name, start_path=start_path)
        # Initialize client once per run to allow stateful fakes in tests
        client = OpenRouterClient()
        db_path = Path(cfg.logging.database)
        if not db_path.is_absolute():
            db_path = (base / Path(cfg.logging.database)).resolve()
        store = ArtifactStore(database_path=db_path, start_path=base)
        store.ensure_session(session.id)
        # Purge expired artifacts before attempting a cache read, so TTL is enforced
        try:
            store.purge_expired(cfg.sessions.ttl)
        except Exception:
            pass

        # Compute cache keys
        # Spec hash: use the raw YAML file contents
        spec_path = base / "functions" / f"{name}.yaml"
        spec_text = spec_path.read_text() if spec_path.exists() else ""
        config_path = base / "splice.yaml"
        config_text = config_path.read_text() if config_path.exists() else ""

        # Context docs merged text
        from .prompt import _load_context_docs  # reuse loader

        context_pairs = _load_context_docs(spec.context_docs, base)
        merged_docs = "\n\n".join([content for _, content in context_pairs])

        # If caller explicitly does not want to run and provided no prompt,
        # there is nothing to do (no generation or execution). Emit a warning and return.
        if not run_now and prompt is None:
            import warnings as _warnings

            _warnings.warn(
                "Splice.run(run_now=False) called without a prompt: nothing to generate or run.",
                stacklevel=2,
            )
            return None

        # Prompt is session-scoped. If missing and no cached artifact, error (unless run_now=False handled above).
        active_prompt = prompt if prompt is not None else spec.prompt
        from .store import ArtifactStore as _AS
        prompt_hash = _AS.hash_prompt(active_prompt)
        key = ArtifactKey(
            session_id=session.id,
            function_name=name,
            prompt_hash=prompt_hash,
            spec_hash=_AS.hash_spec_yaml(spec_text),
            context_hash=_AS.hash_context_docs(merged_docs),
            config_hash=_AS.hash_config_yaml(config_text),
        )

        # Enforce TTL by using get_fresh which deletes expired entries
        art = store.get_fresh(key, cfg.sessions.ttl)
        if art is None:
            # Allow reusing latest code for this session/function if spec/context/config match
            latest = store.get_latest_for_session(
                session_id=session.id,
                function_name=name,
                spec_hash=key.spec_hash,
                context_hash=key.context_hash,
                config_hash=key.config_hash,
            )
            if latest is not None and prompt is None:
                art_code = latest.code
            else:
                if prompt is None:
                    raise ValueError("Prompt required on first call for this session/function")
                bundle = bundle_prompt(spec, cfg, session_prompt=prompt, start_path=base)
                # Phase 10: generation timing and event
                store.write_event("generation_requested", session.id, name, "")
                gen_start = time.perf_counter()
                code_text = client.generate_code(bundle, cfg)
                gen_ms = (time.perf_counter() - gen_start) * 1000.0
                store.put(key, code_text)
                store.write_event("generation_succeeded", session.id, name, f"duration_ms={gen_ms:.1f}")
                art_code = code_text
        else:
            art_code = art.code

        # If generation-only was requested (run_now=False with a prompt), return without executing.
        if not run_now:
            return None

        # Phase 6: validate inputs pre-execution
        from .validation import build_validators
        validators = build_validators(spec)
        for arg_name, validator in validators.input_validators.items():
            if arg_name in kwargs:
                kwargs[arg_name] = validator(kwargs[arg_name])

        # Phase 11: dependency policy hookup — compute required modules from spec
        # Derive root module names from contracts types and type_sources import paths
        def _root_module(path_str: str) -> str | None:
            if not isinstance(path_str, str) or not path_str:
                return None
            root = (path_str.split(".")[0]).strip()
            # skip builtins and typing
            if root in {"int", "float", "str", "bool", "bytes", "list", "dict", "tuple", "set", "object"}:
                return None
            if root == "typing":
                return None
            return root

        required_modules_set: set[str] = set()
        for t in list(spec.contracts.inputs.values()) + [spec.contracts.output]:
            r = _root_module(str(t))
            if r:
                required_modules_set.add(r)
        for ts in spec.type_sources:
            imp = str(ts.get("import", ""))
            r = _root_module(imp)
            if r:
                required_modules_set.add(r)
        required_modules = sorted(required_modules_set)
        extra_sys_paths = prepare_dependencies(
            policy=cfg.dependencies.policy,
            modules=required_modules,
            start_path=base,
            session_id=session.id,
        )

        # Phase 10: auto-repair loop around execution
        # Ensure at least one repair attempt (2 total tries)
        attempts = max(int(cfg.retries.repair), 0) + 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            exec_start = time.perf_counter()
            try:
                result = Executor.run(art_code, spec.contracts.signature, kwargs, cfg, extra_sys_paths=extra_sys_paths)
                exec_ms = (time.perf_counter() - exec_start) * 1000.0
                # Phase 6: validate output post-execution
                result = validators.output_validator(result)
                store.write_event("execution_succeeded", session.id, name, f"duration_ms={exec_ms:.1f}")
                break
            except BaseException as exc:  # noqa: BLE001
                last_exc = exc
                store.write_event("execution_failed", session.id, name, f"{exc.__class__.__name__}: {exc}")
                if attempt >= attempts - 1:
                    raise
                # Repair attempt: ask model with minimal error context
                repair_prompt = (
                    f"The previous generated function raised {exc.__class__.__name__}: {exc}. "
                    f"Return a fixed function for signature: {spec.contracts.signature}"
                )
                bundle = bundle_prompt(spec, cfg, session_prompt=repair_prompt, start_path=base)
                store.write_event("generation_requested", session.id, name, "repair")
                gen_start = time.perf_counter()
                art_code = client.generate_code(bundle, cfg)
                gen_ms = (time.perf_counter() - gen_start) * 1000.0
                store.put(key, art_code)
                store.write_event("generation_succeeded", session.id, name, f"repair duration_ms={gen_ms:.1f}")
        # Optional GC after use (best-effort)
        try:
            store.purge_expired(cfg.sessions.ttl)
        except Exception:
            pass
        return result

if TYPE_CHECKING:  # pragma: no cover
    from .specs import FunctionSpec


