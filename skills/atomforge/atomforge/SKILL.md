---
name: atomforge
description: Automatic materials-research operator for using the AtomForge platform to discover or reproduce literature, formulate a scientific hypothesis, design and dispatch a research DAG, run MLIP simulations, and audit persisted experimental evidence. Use only when the task's objective is conducting or evaluating a materials-science study. Do not use for ordinary AtomForge repository development such as FastAPI/API routes, frontend/UI work, platform architecture, worker deployment, infrastructure, refactors, generic debugging, tests, or documentation unless that work is explicitly required to execute an active research study.
---

# AtomForge Skill

Use the ordinary checked-in DAG path and preserve the distinction between successful execution,
numerical quality, model applicability, and scientific validation.

## Scope Guard

Treat this as a research-operator skill, not an AtomForge codebase-development skill.

- Trigger it for literature discovery, paper reproduction, hypothesis design, experiment DAGs,
  simulation dispatch, persisted-result analysis, or scientific report audits.
- Do not trigger it merely because the repository, package, API, frontend, or deployment is named
  AtomForge.
- For API/backend work, Vite/React UI changes, local developer experience, worker topology,
  authentication, infrastructure, refactors, generic tests, or code review, follow `AGENTS.md` and
  inspect the relevant code directly.
- If a task combines platform engineering with an active study, apply this skill only to the
  research-design, execution, evidence, and interpretation portion.

## Research evidence boundary

You may inspect checked-in DAGs and trusted scripts under `atomforge/node_scripts/` to understand
declared inputs, outputs, and execution contracts. Do not inspect unrelated AtomForge
implementation files (such as validators, simulators, or tests) to infer scientific inputs,
predict outputs, or conclusions. DAGs and scripts are execution-boundary aids, not literature or
experimental evidence, and they are never a substitute for this workflow. Ground decisions in the
cited paper, this skill and its references, command results, and persisted study/result artifacts.
If those artifacts are insufficient to support a claim, stop at `REVIEW` or `FAILED` and record
the limitation instead of reverse-engineering an expected answer from source.

## Workflow

1. Classify the request as a normal study or **live-demo mode**. Live-demo mode changes the
   latency budget, not the scientific target: it still requires fresh literature discovery, an
   actual run, and persisted evidence.
2. Create `experiments/studies/study-<id>.md` before searching or implementing.
3. In live-demo mode, run two focused metadata searches in parallel, select the first source whose
   observable and protocol map directly to executable AtomForge capabilities, and stop searching.
   Do not download a full PDF or inspect old results unless the selected source requires it.
4. Complete source discovery before consulting existing studies, DAGs, or result bundles as
   candidate selections. Afterwards, use them only as implementation references and author a
   distinct experiment ID and DAG. Reuse requires explicit user authorization.
5. Construct and check an `ExperimentSpec`:

   ```bash
   uv run atomforge experiment check --spec-path experiments/dags/<study>.json
   ```

6. Preflight every new or changed SCRIPT contract with an honest fixture in
   `experiments/artifacts/<study-id>/fixtures/`.
7. Dispatch only after any required external-service approval:

   ```bash
   uv run atomforge experiment run --spec-path experiments/dags/<study>.json
   ```

8. Inspect the persisted JSON bundle and manifest, independently recompute decision-driving
   quantities from persisted rows, and build the generic report:

   ```bash
   uv run atomforge report build --experiment-id <study> --format html
   ```

9. Finalize the living log with provenance, failures, metrics, report path, claim boundary, and
   `PASSED`, `FAILED`, or `REVIEW`.

## DAG Design

- Use `FETCH` for a baseline structure and Materials Project energy metadata.
- Use `ALLOY` for supercells and explicit seeded substitutions.
- Use `SIMULATE` for `relax`, `single_point`, `nvt`, or explicitly unvalidated `pka` work.
- Use `SCRIPT` for trusted, checked-in derived analysis with typed metric and visualization
  contracts.
- Prefer reusable analyzers. Put paper citations, material labels, thresholds, interpretation,
  limitations, and report prose in DAG arguments. Add paper-specific code only when the
  computation itself cannot be expressed by a reusable analyzer.
- Use hypotheses for predeclared workflow or scientific gates with a defensible threshold. Do not
  turn descriptive evidence into a passing claim.

Read [dag-schemas.md](references/dag-schemas.md) while authoring a DAG and
[metrics-dictionary.md](references/metrics-dictionary.md) while declaring hypotheses.

## Dispatch and Evidence Rules

- The Modal deployment entrypoint is intentionally `atomforge/platform/modal/deployment.py`; it dispatches the ordinary
  private-worker DAG and is not permission to expose a public research API. The local CLI is
  `main.py` and is exposed as `uv run atomforge`.
- Modal packaging may include application source, `pyproject.toml`, and `uv.lock`, and may use
  configured secrets such as `MP_API_KEY`. Explain this when approval is required. Do not edit
  dependency files unless the experiment implementation needs a dependency change.
- Record cloud failures and engine fixes in the living log before retrying.
- Treat `hypotheses[].status` as the configured-gate result, not a universal scientific verdict.
- A DFT value fetched from Materials Project or loaded from a released dataset is reference
  evidence; it is not a DFT calculation performed by AtomForge.

Read [modal-endpoints.md](references/modal-endpoints.md) only when dispatching or changing worker
deployment.
