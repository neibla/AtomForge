# Agent Onboarding & Specialized Skills

Welcome to AtomForge. This repository is equipped with specialized skills to automate materials science research

## 🛠 Skill Bootstrap

New agents entering this workspace should immediately install the local skills and request a reload. These skills provide the procedural knowledge required to use the DAG engine and the arXiv research pipeline.

```bash
# skill for using atomforce for running physics experiments
npx skills add ./skills/atomforge/dist/atomforge.skill 
# skill for searching/downloading arxiv research papers
npx skills add ./skills/arxiv-researcher/dist/arxiv-researcher.skill
```

## 🔬 Specialized Skills

### `atomforge`
- **Purpose:** Controls the Modal-based DAG engine. Handles `FETCH`, `ALLOY`, `SIMULATE`, and `ANALYZE` nodes.
- **Key Capability:** Executes high-throughput MD cascades on A100 GPUs and evaluates hypotheses via string-based assertions (e.g., `target.avg_defects < 50`).
- **Persistence:** All simulation reports and **active research progress** MUST be streamed to the `research/` directory.

### `arxiv-researcher`
- **Purpose:** Searches arXiv and extracts physical constants (lattice parameters, space groups) to ground simulations.
- **Key Capability:** Uses `uv run scripts/search_arxiv.py` for dependency-free research searches.
- **Persistence:** Extracted parameters, summaries, and search progress MUST be documented in the `research/` directory.

## 📋 Research Documentation Protocol (CRITICAL)

Agents MUST maintain a "Source of Truth" in the `research/` directory. Operating without visible documentation in this folder is a violation of protocol.

### 1. The Living Log (`research/study-[id].md`)
As soon as a task starts, create a research file. Do NOT wait for completion.
- **Pre-Flight:** Document the objective, the source paper URL/arXiv ID, and the intended DAG configuration.
- **In-Flight:** If a simulation fails, document the traceback, the root cause analysis, and the code fix applied to the engine. **Never hide infrastructure fixes.**
- **Post-Flight:** Finalize with the verification status (`PROVEN`/`DISPROVEN`) and a summary of findings.

### 2. Mandatory Report Structure
Every research file must contain:
1.  **Objective:** What are we verifying?
2.  **Infrastructure Iterations:** Documentation of any bugs, ASE/MACE compatibility issues, or logic fixes encountered during the run.
3.  **Metrics Table:** Clear comparison of simulation values vs. research benchmarks.
4.  **Verification Status:** Unambiguous statement on whether the hypothesis held.

## ⚠️ Critical Constraints
- **Package Management:** Use `uv` for Python and `bun` for the frontend.
- **GPU Cloud:** Simulations MUST run via ` uv run modal run atomforge/api.py --spec-path mic/dags/{dag_name}.json `.
- **Transparency:** If it isn't in the `research/` directory, the research did not happen. Every failure is a valuable data point for the engine's evolution.
