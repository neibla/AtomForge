# AtomForge Cloud Execution

## Ordinary Research Dispatch

```bash
uv run atomforge experiment run --spec-path experiments/dags/<study>.json
```

Use the full-spec command for research so DAG validation, hypotheses, result persistence, manifest
generation, and reporting provenance remain intact. Do not substitute direct function invocation
for a normal study run.

Modal dispatch is an external action. The loopback API persists the DAG, publishes an immutable
SCRIPT snapshot and invokes the deployed worker application, which may use configured secrets such
as `MP_API_KEY`. Obtain approval when the active environment requires it, and record dispatch
failures in the living research log.

## Current Worker Routing

Do not promise a fixed GPU from this document; verify `atomforge/platform/modal/runtime.py` before making
cost, capacity, or performance claims. At the time of writing, simulation routing is:

| Atom count | Worker |
|---:|---|
| `< 50` | CPU |
| `50–499` | T4 |
| `500–9,999` | A100-40GB |
| `>= 10,000` | A100-80GB |

SCRIPT nodes with `execution_profile: analysis` use CPU workers. SCRIPT nodes with
`execution_profile: physics_gpu` use a dedicated T4 worker. These choices may change with the live
runtime.

## Updating the Cloud Engine

The research command submits through the local API to the named private deployment. Deploy the
workers application only when intentionally updating that persistent deployment; follow the
[canonical deployment procedure](../../../../README.md#deploy-private-workers).

Verify the deployed app and local operator path after deployment. Do not infer that a public API
has been created or authorized.
