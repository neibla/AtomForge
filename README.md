# AtomForge

AtomForge is a materials science research and discovery platform.

> *"You just keep on trying till you run out of cake. And the Science gets done."*
> — **GLaDOS**, autoresearcher


## Components:
1. Agent loop - eg Claude Code
2. Arxiv Skill for research
4. AtomForge skill for interfacing with AtomForgePlatform
4. AtomForge cli for running experiments/validating hypotheses via Modal compute (cpu/gpu)
5. Agent for iterating or generating a report
6. React frontend for visualizing result 

## Setup
1. Install deps:
```bash
uv sync --extra dev --extra physics
```
2. Run tests:
```bash
uv run pytest -q
```
3. Run one DAG on Modal:
```bash
uv run modal run atomforge/api.py --spec-path dags/w_cascade_2023_repro_v1.json
```
4. Inspect outputs (local artifacts persisted by run):
```bash
ls research
ls research/manifests
```
Expected evidence:
- `research/w-cascade-2023-repro-v1.json` (result bundle)
- `research/w-cascade-2023-repro-v1.md` (human-readable report)
- `research/manifests/w-cascade-2023-repro-v1_manifest.json` (reproducibility metadata)

## Quickstart

```bash
uv sync
uv run atomforge serve
```