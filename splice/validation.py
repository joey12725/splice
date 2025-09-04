from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .errors import ValidationError
from .specs import FunctionSpec


def _import_from_string(path: str) -> Any:
    module_name, _, attr = path.rpartition(".")
    if not module_name:
        # builtin or simple name
        return __import__(path)
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _resolve_type(type_path: str) -> Any:
    # Support builtins
    builtins_map = {
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "bytes": bytes,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "object": object,
    }
    if type_path in builtins_map:
        return builtins_map[type_path]
    try:
        return _import_from_string(type_path)
    except Exception as exc:
        # If a type cannot be imported, we allow runtime to proceed; validation will be best-effort
        return object


def _maybe_resolve_pydantic_model(path: Optional[str]) -> Optional[Any]:
    if not path:
        return None
    try:
        return _import_from_string(path)
    except Exception:
        return None


@dataclass
class Validators:
    input_validators: dict[str, Callable[[Any], Any]]
    output_validator: Callable[[Any], Any]


def build_validators(spec: FunctionSpec) -> Validators:
    """Create input/output validators based on spec contracts (Phase 6).

    - If pydantic model provided for a param/output, use it for validation.
    - Else, perform a simple isinstance check when possible (best-effort).
    """

    input_validators: dict[str, Callable[[Any], Any]] = {}

    for name, type_path in spec.contracts.inputs.items():
        model_path = spec.contracts.pydantic.get(name)
        pyd_model = _maybe_resolve_pydantic_model(model_path)
        expected_type = _resolve_type(type_path)

        if pyd_model is not None:
            def make_pydantic_validator(model):
                def _validate(value: Any) -> Any:
                    try:
                        model.parse_obj(value)  # type: ignore[attr-defined]
                        return value
                    except Exception as exc:
                        raise ValidationError(f"Invalid input '{name}': {exc}")
                return _validate
            input_validators[name] = make_pydantic_validator(pyd_model)
        else:
            def make_isinstance_validator(t):
                def _validate(value: Any) -> Any:
                    # Skip for Any-like sentinel
                    try:
                        if t is object:
                            return value
                        if isinstance(value, t):
                            return value
                    except Exception:
                        return value
                    raise ValidationError(f"Invalid type for '{name}': expected {t}, got {type(value)}")
                return _validate
            input_validators[name] = make_isinstance_validator(expected_type)

    # Output validator
    out_model_path = spec.contracts.pydantic.get("output")
    out_model = _maybe_resolve_pydantic_model(out_model_path)
    out_type = _resolve_type(spec.contracts.output)

    if out_model is not None:
        def _validate_output(value: Any) -> Any:
            try:
                out_model.parse_obj(value)  # type: ignore[attr-defined]
                return value
            except Exception as exc:
                raise ValidationError(f"Invalid output: {exc}")
    else:
        def _validate_output(value: Any) -> Any:
            try:
                if out_type is object:
                    return value
                if isinstance(value, out_type):
                    return value
            except Exception:
                return value
            raise ValidationError(f"Invalid output type: expected {out_type}, got {type(value)}")

    return Validators(input_validators=input_validators, output_validator=_validate_output)


