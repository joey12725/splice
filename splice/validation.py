"""Input/output validation against a spec's contracts.

Validation runs in the trusted parent process: it checks the arguments before
they enter the sandbox and the value that comes back out.
"""

from __future__ import annotations

import builtins
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import ValidationError
from .specs import FunctionSpec

Validator = Callable[[Any], Any]

_BUILTIN_TYPES: dict[str, type] = {
    t.__name__: t
    for t in (int, float, str, bool, bytes, list, dict, tuple, set, frozenset, complex, object)
}


def _import_from_string(path: str) -> Any:
    module_name, _, attr = path.rpartition(".")
    if not module_name:
        return getattr(builtins, path)
    return getattr(importlib.import_module(module_name), attr)


def _resolve_type(type_path: str) -> Any:
    """Resolve a contract type string to a class; unknown types disable the check."""

    if type_path in _BUILTIN_TYPES:
        return _BUILTIN_TYPES[type_path]
    try:
        resolved = _import_from_string(type_path)
    except (ImportError, AttributeError, ValueError):
        return object
    return resolved if isinstance(resolved, type) else object


def _maybe_resolve_model(path: str | None) -> Any:
    if not path:
        return None
    try:
        return _import_from_string(path)
    except (ImportError, AttributeError, ValueError):
        return None


def _model_check(model: Any, value: Any) -> None:
    """Validate ``value`` with a pydantic model (v2 ``model_validate`` or v1 ``parse_obj``)."""

    validate = getattr(model, "model_validate", None) or model.parse_obj
    validate(value)


def _accepts(expected: Any, value: Any) -> bool:
    if expected is object:
        return True
    if expected is float and isinstance(value, int) and not isinstance(value, bool):
        return True  # PEP 484 numeric tower: int is acceptable where float is declared
    try:
        return isinstance(value, expected)
    except TypeError:
        return True


@dataclass
class Validators:
    input_validators: dict[str, Validator]
    output_validator: Validator


def _make_validator(label: str, type_path: str, model_path: str | None) -> Validator:
    model = _maybe_resolve_model(model_path)
    expected = _resolve_type(type_path)

    if model is not None:

        def validate_model(value: Any) -> Any:
            try:
                _model_check(model, value)
            except Exception as exc:
                raise ValidationError(f"Invalid {label}: {exc}") from exc
            return value

        return validate_model

    def validate_type(value: Any) -> Any:
        if _accepts(expected, value):
            return value
        raise ValidationError(
            f"Invalid type for {label}: expected {getattr(expected, '__name__', expected)}, "
            f"got {type(value).__name__}"
        )

    return validate_type


def build_validators(spec: FunctionSpec) -> Validators:
    """Build validators from ``spec.contracts``.

    A pydantic model listed under ``contracts.pydantic`` (by parameter name or
    ``output``) takes precedence; otherwise a best-effort ``isinstance`` check
    against the declared type is used.
    """

    inputs = {
        name: _make_validator(f"input '{name}'", type_path, spec.contracts.pydantic.get(name))
        for name, type_path in spec.contracts.inputs.items()
    }
    output = _make_validator("output", spec.contracts.output, spec.contracts.pydantic.get("output"))
    return Validators(input_validators=inputs, output_validator=output)
