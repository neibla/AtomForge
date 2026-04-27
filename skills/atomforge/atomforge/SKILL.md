---
name: atomforge
description: Automated physics research engine for MLIP inference and DFT validation. Use when the user wants to run distributed simulations, alloy crystal structures, fetch material data from Materials Project, or evaluate scientific hypotheses using the AtomForge DAG engine.
---

# AtomForge Skill

This skill enables AI agents to interface with the AtomForge distributed physics platform. It provides the procedural knowledge to design experiments, dispatch them to the cloud, and interpret scientific results.

## Core Workflows

### 1. Designing an Experiment
To run a study, you must construct a `ExperimentSpec` JSON object.
- Use `FETCH` nodes to get baseline materials (W, Fe, Cu, etc.).
- Use `ALLOY` nodes to create supercells and add dopants.
- Use `SIMULATE` nodes for GPU-intensive molecular dynamics (PKA cascades or Relaxation).
- Use `hypotheses` to define the success criteria for the experiment.

**Reference:** See [dag-schemas.md](references/dag-schemas.md) for field definitions.

### 2. Dispatching to Cloud
Execute the study via the Modal CLI. Do NOT use the API server for research tasks.
```bash
uv run modal run atomforge/api.py --spec-path path/to/spec.json
```

**Persistence:** All outcomes and real-time execution logs MUST be documented in the `research/` directory.

### 3. Evaluating Results
Results are returned as a `ResultsGraph`. The engine automatically evaluates your assertions using `simpleeval`.
- Check `evaluations[].status` to see if a hypothesis was `PROVEN` or `DISPROVEN`.
- Inspect `metrics` for aggregated data across simulation trials.

**Metric Dictionary:** See [metrics-dictionary.md](references/metrics-dictionary.md) for available variables.

## Example Usage

**Prompt:** "Simulate a Tungsten vacancy and verify its radiation tolerance."

**Action:**
1. Generate `ExperimentSpec`:
```json
{
  "experiment_id": "w-vacancy-study",
  "dag": [
    { "id": "f1", "type": "FETCH", "params": { "element": "W" } },
    { "id": "s1", "type": "SIMULATE", "depends_on": "f1", "params": { "mode": "pka", "trials": 3 } }
  ],
  "hypotheses": [
    { "id": "vac_stability", "target_node": "s1", "assertion": "s1.avg_defects < 50" }
  ]
}
```
2. Dispatch via `uv run modal run atomforge/api.py --spec-path path/to/spec.json`.
3. Document progress and results in `research/study-w-vacancy.md`.
