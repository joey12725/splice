from __future__ import annotations

from pathlib import Path

from splice.docgen import DocSource, generate_docs


class Sample:
    """Sample class for docgen test."""

    x: int = 0

    def foo(self, a: int) -> int:
        return a + 1


def test_docgen_creates_files_idempotently(tmp_path: Path) -> None:
    sources = [DocSource(name="Sample", import_path="tests.test_phase7_docgen.Sample", doc_strategy="class")]
    # First run writes file
    paths = generate_docs(sources, start_path=tmp_path)
    assert paths and paths[0].exists()
    content1 = paths[0].read_text()
    assert "Sample" in content1 and "foo" in content1

    # Second run keeps existing content
    paths2 = generate_docs(sources, start_path=tmp_path)
    assert paths2[0].read_text() == content1


