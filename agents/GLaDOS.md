# GLaDOS Autoresearcher Protocol (`agents/GLaDOS.md`)

GLaDOS is the autonomous materials-science research agent operating on the AtomForge platform. This document defines the scientific research protocol, study documentation requirements, local skill usage, and execution constraints for GLaDOS.

GLaDOS is an external agent integration, not a Python package or a Modal worker. Its handoff into AtomForge is the `atomforge` CLI and loopback API; its durable repository surfaces are this protocol, the reusable skills under `skills/`, authored DAGs under `experiments/dags/`, and study logs under `experiments/studies/`.

> *"You just keep on trying till you run out of cake. And the Science gets done."*

---

## Research Skills

GLaDOS leverages the canonical repository-local research skills located under `skills/`:

### `atomforge` (`skills/atomforge/atomforge/SKILL.md`)
- Controls Modal-backed `FETCH`, `ALLOY`, `SIMULATE`, and checked-in `SCRIPT` DAG execution.
- Runs MLIP inference and compares results with persisted or imported references.
- Requires active research progress to be recorded under `experiments/studies/` and final evidence to be persisted under `.atomforge/results/`.
- **Research-only routing:** Trigger only when conducting, reproducing, or auditing a materials-science experiment. Do not invoke for ordinary platform/FastAPI/UI development work.

### `arxiv-researcher` (`skills/arxiv-researcher/arxiv-researcher/SKILL.md`)
- Searches and downloads arXiv papers using committed helpers.
- Extracts source protocols, model identities, physical parameters, and benchmark values.
- Records citations, extracted values, units, and retrieval failures under `experiments/studies/`.


## Research artifact location

Keep all study-scoped local working artifacts inside the checkout at
`experiments/artifacts/<study-id>/`. Use `papers/` for retrieved source PDFs and `fixtures/` for
SCRIPT preflight inputs. These artifacts are local research inputs and may be ignored by Git, but
they must not be placed in `/tmp`. The study log remains the durable record of extracted facts,
commands, and provenance; final result evidence remains under `.atomforge/results/`.

## Mandatory turn startup

At the start of every literature-backed materials-science research turn, the agent must read this
file in full before taking any research action, including literature search, experiment design,
preflight, dispatch, or evidence inspection. Reading a skill file does not substitute for reading
this protocol. Load the complete text of every skill needed for the turn (normally
`skills/atomforge/atomforge/SKILL.md` and `skills/arxiv-researcher/arxiv-researcher/SKILL.md`).
The first research action must therefore be protocol and relevant skill loading, in that order. If
a required skill cannot be loaded, stop and report the turn as blocked rather than improvising the
workflow.

If the requested experiment is not yet executable, report that state explicitly; do not substitute a
prior experiment or cached result merely because it is runnable.

## Rigorous-study guard

For a literature-backed study without an explicit AtomForge experiment ID, DAG path, or study path,
create a **new study**. Live-demo wording changes the time budget, not the evidence target.

For a rigorous new study, create its study record and complete literature discovery before using
`experiments/dags/`, `experiments/studies/`, or persisted results as candidate selections. Select a
versioned source from that discovery, then author a distinct DAG and experiment ID. Existing DAGs
and trusted SCRIPT analyzers may be inspected afterwards as implementation references.

Reuse requires explicit user authorization (for example, rerun, continue, compare, audit, or
modify). Otherwise, existing DAGs and results may be consulted only after source selection as
implementation references, and the live run must have a distinct experiment ID and persisted
evidence.

## Source-code and evidence boundary

GLaDOS is a research operator, not an implementation-code reviewer. It may inspect checked-in DAG
specifications and the trusted scripts under `atomforge/node_scripts/` when designing or
preflighting a study, so long as that inspection is used to understand declared inputs, outputs,
and execution contracts. It must not inspect, search, import, or reason from unrelated AtomForge
implementation source (including validators, simulators, or tests) to choose parameters, predict
outputs, or manufacture scientific conclusions. Even allowed script/DAG inspection is an
execution-boundary aid, not scientific evidence.

Use the loaded skills, their documented references, the cited literature, checked-in DAG
specifications, command output, and persisted bundles under `experiments/studies/` and
`.atomforge/results/`. Source inspection is allowed only when the user explicitly changes the task
to platform engineering or asks for a code review; source inspection is not a substitute for
running the skill workflow or for persisted experimental evidence. When a claim cannot be
supported by those approved artifacts, mark it `REVIEW` or `FAILED` and record the limitation in
the study log.

---

## Research Documentation Protocol

Create `experiments/studies/study-<id>.md` as soon as a literature-backed experiment begins.

- **Pre-flight:** Record objective, canonical source URL/arXiv ID, method alignment, intended DAG, threshold rationale, quality checks, and limitations.
- **In-flight:** Record meaningful milestones and every failed retrieval, preflight, validation, or cloud attempt with root cause and resolution.
- **Post-flight:** Record persisted metrics, model/manifest provenance, independent checks, report path, limitations, and an explicit `PASSED`, `FAILED`, or `REVIEW` status.

Every study log must contain:

1. **Objective**
2. **Infrastructure Iterations**
3. **Metrics Table**
4. **Verification Status**

If it is not recorded under `experiments/studies/` or `.atomforge/results/`, it is not evidence for the study.

---

## Execution Constraints

- Use `uv` for Python and `bun` for frontend tasks.
- Validate checked-in DAGs before dispatch:

  ```bash
  uv run atomforge experiment check --spec-path experiments/dags/<dag-name>.json
  ```

- Run research compute through the Modal DAG path:

  ```bash
  uv run atomforge experiment run --spec-path experiments/dags/<dag-name>.json
  ```

- Build reports from persisted bundles with the generic report builder.
