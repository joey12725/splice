from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING


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
    """Top-level entry point for the Splice runtime (Phase 0 stub).

    This class will later accept configuration and manage code generation, caching,
    and execution. For Phase 0 we only provide a constructor with no side effects.
    """

    def __init__(self, config_path: str | None = None) -> None:
        # Phase 0: we store the path but do not load anything yet.
        self._config_path: str | None = config_path
        # Phase 1: lazy-loaders for config/specs
        self._config_cache = None

    def spec(self, name: str) -> "FunctionSpec":
        """Return a typed FunctionSpec loaded from `.splice/functions/`.

        Delayed import to avoid circulars on phase boundaries.
        """
        from .specs import FunctionSpec, load_function_spec

        spec: FunctionSpec = load_function_spec(name)
        return spec

if TYPE_CHECKING:  # pragma: no cover
    from .specs import FunctionSpec


