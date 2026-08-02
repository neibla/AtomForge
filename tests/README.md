# Test layout

Tests are grouped by the boundary they exercise:

- `api/` — FastAPI endpoints and the command-line interface.
- `core/` — reusable domain, simulation, validation, storage, and visualization logic.
- `execution/` — orchestration, evidence persistence, provenance, and script preflight.
- `reporting/` — Markdown and HTML report contracts.
- `science/` — materials-science node scripts and vacancy-study protocols.
- `research/` — research helper and local skill-routing checks.

Pytest discovers all of these directories from the repository root, so the full suite
can still be run with:

```shell
uv run pytest
```
