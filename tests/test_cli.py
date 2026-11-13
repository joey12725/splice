from __future__ import annotations

from pathlib import Path

from splice.cli import cmd_cache_purge, cmd_docgen, cmd_init


def test_cli_init_creates_scaffold(tmp_path: Path) -> None:
    base = cmd_init(start_path=tmp_path)
    assert (base / "functions").is_dir()
    assert (base / "context").is_dir()
    assert (base / "splice.yaml").is_file()


def test_cli_docgen_and_cache_purge(tmp_path: Path) -> None:
    base = cmd_init(start_path=tmp_path)
    cmd_docgen(["splice.tests.doesnotexist.Foo"], start_path=tmp_path)
    # A placeholder doc is created
    ctx_files = list((base / "context").glob("*.md"))
    assert ctx_files, "Expected a generated doc file"

    # Cache purge works on empty DB
    deleted = cmd_cache_purge(start_path=tmp_path)
    assert isinstance(deleted, int)
