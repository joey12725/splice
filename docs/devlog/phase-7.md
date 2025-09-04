# Phase 7 — Context docs (DocGen)

Phase 7 adds a tiny doc generation engine that introspects classes you list in `type_sources` and writes Markdown docs to `.splice/context/<Name>.md`. Existing files are preserved to allow manual edits.

## What it builds
- `splice.docgen.generate_docs(sources, start_path=None) -> list[Path]`
  - Each source has `{ name, import_path, doc_strategy }`.
  - Strategy `class` introspects attributes and methods.
  - If the file already exists, it is left unchanged.

## Usage
```python
from splice.docgen import DocSource, generate_docs

sources = [DocSource(name="User", import_path="app.domain.user.User", doc_strategy="class")]
generate_docs(sources)
```

## Tests
- See `tests/test_phase7_docgen.py` for creation and idempotency behavior.


