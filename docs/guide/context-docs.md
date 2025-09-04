## Context Docs & DocGen

Context docs live under `.splice/context/` and are included in prompts by name via `spec.context_docs`.

### Generate from types
```bash
splice edit --doc-class collections.Counter datetime.datetime
```

This writes Markdown files like `.splice/context/Counter.md`.

### Generate from external documentation URL
```bash
splice edit --doc-url https://pandas.pydata.org/docs/ --doc-url-name pandas
```

This fetches the page, extracts text, and asks the LLM to produce a concise Markdown doc under `.splice/context/pandas.md`.

### Include in a spec
```yaml
context_docs:
  - Counter
  - datetime.datetime
```


