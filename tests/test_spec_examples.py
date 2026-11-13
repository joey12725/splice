from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from splice.errors import SpecError
from splice.specs import load_function_spec


def _write_spec(tmp_path: Path, name: str, data: dict) -> Path:
    base = tmp_path / ".splice" / "functions"
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{name}.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_example_verification_flags_bad_name(tmp_path: Path) -> None:
    name = "adder"
    data = {
        "name": name,
        "version": "0.0.1",
        "description": "",
        "prompt": "",
        "contracts": {
            "signature": "def adder(a: int, b: int) -> int",
            "inputs": {"a": "int", "b": "int"},
            "output": "int",
        },
        "examples": [
            {"prompt": "Add", "function": "def wrong(a: int, b: int) -> int:\n    return a + b\n"}
        ],
    }
    _write_spec(tmp_path, name, data)
    with pytest.raises(SpecError):
        load_function_spec(name, start_path=tmp_path)


def test_example_verification_allows_good_name(tmp_path: Path) -> None:
    name = "adder"
    data = {
        "name": name,
        "version": "0.0.1",
        "description": "",
        "prompt": "",
        "contracts": {
            "signature": "def adder(a: int, b: int) -> int",
            "inputs": {"a": "int", "b": "int"},
            "output": "int",
        },
        "examples": [
            {"prompt": "Add", "function": "def adder(a: int, b: int) -> int:\n    return a + b\n"}
        ],
    }
    _write_spec(tmp_path, name, data)
    spec = load_function_spec(name, start_path=tmp_path)
    assert spec.name == name
