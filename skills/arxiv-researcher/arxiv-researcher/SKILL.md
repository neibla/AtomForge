---
name: arxiv-researcher
description: Search, download, and extract parameters from arXiv research papers. Use when the user wants to find relevant physics papers, download PDFs for analysis, or extract simulation parameters (lattice constants, RMSE benchmarks) to ground AtomForge experiments.
---

# arXiv Researcher Skill

Use the committed helper from the AtomForge repository root and preserve versioned provenance.

## Search

For a live or quick demo, issue at most two focused metadata queries in parallel and stop when one
source is both relevant and executable. Return the selected paper and direct execution plan before
doing optional deep extraction, then continue through the real DAG and evidence workflow.

```bash
uv run skills/arxiv-researcher/arxiv-researcher/scripts/search_arxiv.py \
  --limit 10 --sort relevance \
  'cat:cond-mat.mtrl-sci AND all:"machine learning interatomic potential"'
```

Use specific formulas, properties, methods, and material classes. The helper uses a bounded retry
for transient API failures and sizes each API page to the requested result limit. Record the exact
query, result version, canonical URL, title, authors, and search date in
`experiments/studies/study-<id>.md` for rigorous studies.

## Download

```bash
uv run skills/arxiv-researcher/arxiv-researcher/scripts/search_arxiv.py \
  --download 2305.15324v2 --dir experiments/artifacts/<study-id>/papers
```

The helper first uses the arXiv client and then retries the canonical PDF endpoint for bounded
download failures. Treat a JSON error and nonzero exit as a failed retrieval. Keep papers in the
study-scoped `experiments/artifacts/<study-id>/papers/` directory; persist extracted facts and
provenance in the study log, not downloaded PDFs in Git, unless the user asks otherwise.

## Extract

Read [parameter-extraction.md](references/parameter-extraction.md). At minimum record:

- material, structure, lattice/supercell, boundary conditions, and defect definition;
- model/checkpoint and DFT or experimental reference method;
- optimizer, force threshold, timestep, temperature, sampling, and seeds where relevant;
- benchmark value, uncertainty/sample size, and exact units;
- whether AtomForge offers the same observable and method.

Read the methods, relevant table/figure caption, and limitations rather than relying only on the
abstract. Do not compare RMSE values across incompatible units, normalizations, datasets, or
reference methods.

## Failure Handling

- Preserve the version suffix when the source exposes one.
- For transient search failures (HTTP 429/5xx), allow the helper's bounded retry before switching
  to a different focused query. For partial transfers, use bounded retries and the canonical
  `https://arxiv.org/pdf/<versioned-id>` endpoint.
- Record retrieval errors and fallback commands in the living research log.
- Use web search as a supplement, not as a substitute for source verification.
- Never invent a citation, method parameter, benchmark, or threshold.
