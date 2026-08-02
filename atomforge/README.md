# AtomForge backend

The backend validates experiment DAGs, coordinates private Modal compute, persists evidence artifacts, and exposes a loopback FastAPI operator surface. It is a trusted-operator prototype, not a public multi-tenant service.

For setup and repository orientation, start with the [root README](../README.md). Current domain terms and ownership boundaries live in [`CONTEXT.md`](../CONTEXT.md).

## Runtime architecture

```text
React / CLI / AI agent
          │ HTTP
          ▼
loopback FastAPI (`api/http.py`)
  validate ExperimentSpec
  create immutable run + spec
  publish SCRIPT snapshot
  spawn named Modal Orchestrator
  persist call ID and recover state
          │
          ▼
private Modal app (`platform/modal/runtime.py`)
  Orchestrator
    └── execution/experiment.py
          └── CoreOrchestrator
  PhysicsWorker
  ScriptWorker
  PhysicsGpuScriptWorker
  DftCpuScriptWorker
  DftGpuScriptWorker
          │
          ▼
execution + evidence publication
          │
          ▼
Modal results volume ── sync ──▶ `.atomforge/results`
```

## Main boundaries

| Path | Responsibility |
|---|---|
| `api/http.py` | Core loopback routes for submission, runs, reruns, reports, and verified evidence |
| `api/evidence_views.py` | Verified visualization and sweep artifact views |
| `api/lifecycle.py` | Run loading, immutable submission/rerun workflows, state transitions, unresolved-run reconciliation, and remote evidence synchronization |
| `platform/modal/deployment.py` | Stable Modal deployment entrypoint exporting only `app` |
| `platform/modal/runtime.py` | Modal images, volumes, workers, and executor adapter |
| `execution/experiment.py` | Provider-independent DAG execution and evidence publication |
| `execution/orchestrator.py` | Infrastructure-independent DAG ordering, bounded concurrency, cache semantics, and hypothesis evaluation |
| `execution/result_assembly.py` | Result graph, trial evidence, metric, and workflow provenance assembly |
| `execution/simulation_trials.py` | Seeded simulation trials, workflow-wide worker concurrency, and sibling cancellation |
| `execution/sweep_runner.py` | Internal parameter-sweep points, coordinate binding, point concurrency, evidence, and failure policy |
| `execution/evidence_artifacts.py` | Canonical artifact kinds and filename conventions, byte-level integrity, and verified JSON loading |
| `execution/evidence_repository.py` | Evidence naming, atomic persistence, synchronization, state transitions, and deletion |
| `simulation_modes.py` | Central simulation parameter/result contracts and mode-specific metric allowlists |
| `execution/script_runner.py` | Safe SCRIPT resolution, subprocess execution, and output-contract validation |
| `execution/script_sources.py` | Content-addressed SCRIPT snapshots and local/remote source roots |
| `schemas.py` | Pydantic contracts used by execution, API generation, and the frontend |
| `validators.py` | DAG and node validation before dispatch |
| `manifest.py` | Compact model identity and artifact integrity manifest |
| `reporting/` | Markdown and self-contained HTML rendering from result bundles |
| `visualizations.py` | Typed visualization catalogs derived from recorded node outputs |
| `node_scripts/` | Trusted, reviewable study-specific methods |

The Modal control plane uses the lightweight `orchestrator` extra (ASE only for
structure rehydration); model, Materials Project, and GPU dependencies remain in
the `physics` worker image. SCRIPT files run from immutable PEP 723 snapshots.

## Execution lifecycle

1. FastAPI accepts and validates an `ExperimentSpec`.
2. It atomically creates `<id>_run.json` and `<id>_spec.json`.
3. It publishes the complete SCRIPT source tree as an immutable snapshot and pins the snapshot in both records.
4. It spawns the named private Modal `Orchestrator` and writes `<id>_call.json`.
5. `CoreOrchestrator` executes ready nodes with bounded concurrency and blocks descendants of failed nodes.
6. `ModalExecutor` routes standard nodes and SCRIPT profiles to the appropriate worker.
7. The shared experiment runner writes the report, visualization catalog, sweep evidence, and manifest first; the result bundle is the reader-visible publication boundary, followed by terminal run state. Local reconciliation stages remote artifacts before copying a terminal run and requires the core evidence set to be present.
8. The local API polls the Modal call and synchronizes authoritative evidence into `.atomforge/results`.

Run state and scientific status are separate. `COMPLETED` means execution reached a terminal result; it does not establish convergence, model applicability, reproduction, or validation.

Terminal bundles include per-node `node_statuses` and hypotheses retain their
target node and structured review reason.

## Current artifact contract

```text
<id>_run.json
<id>_spec.json
<id>_call.json
<id>.json
<id>.md
<id>_visualizations.json
<id>_manifest.json
<id>_artifacts/
```

The API does not synthesize missing records, remap historical node IDs, backfill scientific decisions, or load fallback specifications from checked-in DAGs. Incomplete or inconsistent evidence is rejected and must be regenerated with the current contract.

The manifest keeps one immutable SCRIPT snapshot ID, the model/checkpoint identity,
and SHA-256 values for reader-visible artifacts. Runtime fingerprints stay inside
the execution cache; they are not repeated in the evidence bundle.

Reruns receive immutable derived IDs and persist their exact submitted
specification as `<derived-id>_spec.json`. They do not write generated DAGs into
the source tree.

## SCRIPT boundary

SCRIPT nodes are trusted repository source, not arbitrary uploads:

- paths resolve safely under the active SCRIPT source root;
- source snapshots are immutable and content-addressed;
- saved source is syntax-checked;
- emitted metric names and units must exactly match the DAG contract;
- physics profiles must emit structured model provenance;
- runtime, timeout, hardware, retry, and concurrency policy come from the declared execution profile.

## Change rules

- Change backend contracts first, then regenerate and verify the frontend client.
- Keep DAG semantics in `CoreOrchestrator` and provider behavior in the runtime/executor layer.
- Keep study-specific scientific methods in checked-in SCRIPT nodes.
- Build all views and reports from persisted evidence rather than bespoke success paths.
- Preserve failures, limitations, provenance, and calibration through the API and UI.
- Never make caches, checked-in rerun files, or frontend state authoritative.
