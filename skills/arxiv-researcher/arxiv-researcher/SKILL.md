---
name: arxiv-researcher
description: Search, download, and extract parameters from arXiv research papers. Use when the user wants to find relevant physics papers, download PDFs for analysis, or extract simulation parameters (lattice constants, RMSE benchmarks) to ground AtomForge experiments.
---

# arXiv Researcher Skill

This skill allows agents to systematically explore scientific literature on arXiv to inform simulation parameters and benchmark results.

## Core Workflows

### 1. Searching for Papers
Use the bundled script to find relevant research. Always use `uv run` to ensure dependencies like `arxiv` are automatically installed and managed.
```bash
uv run scripts/search_arxiv.py "Universal MLIP defects metals"
```

### 2. Exploring & Extracting
Once a paper is identified (via `web_fetch` or abstract reading):
- Extract key physics parameters (lattice constants, space groups).
- Identify the MLIP models and DFT references used.
- Compare reported RMSE values with current AtomForge results.

**Reference:** See [parameter-extraction.md](references/parameter-extraction.md) for a checklist of what to look for.

### 3. Downloading for Full Context
If the abstract is insufficient, download the paper for detailed analysis using `uv run`:
```bash
uv run scripts/search_arxiv.py --download "2305.15324" --dir "./papers"
```
Note: PDF content is best processed by identifying specific tables or figure captions in the text.

## Best Practices
- **Be Specific:** Search for chemical formulas and property names (e.g., "W vacancy formation energy MACE").
- **Validate Units:** Always verify if energies are in eV, meV, or Hartrees.
- **Identify Baselines:** Always note the DFT functional (PBE, SCAN) used for the ground truth.
