# AtomForge Cloud Execution

## Core Execution Pattern
AtomForge research workflows MUST use the Modal CLI for execution. This ensures full access to GPU resources and keeps the experiment state local to the execution context.

### Dispatching an Experiment
To execute an experiment defined in an `ExperimentSpec` JSON file:

```bash
uv run modal run atomforge/api.py --spec-path path/to/spec.json
```

### Direct Function Invocation
If you need to trigger specific parts of the engine without a full spec:

```bash
uv run modal run atomforge/api.py::f_execute_dag --spec-json '{"experiment_id": "test", ...}'
```

## Cloud Engine Specs
The engine is deployed on Modal infrastructure:
- **Compute:** A100-80GB GPUs (Inference/Simulation)
- **Coordination:** High-performance CPU workers
- **Environment:** Custom Docker image with `torch`, `lammps`, and `ase` pre-installed.

## Updating the Cloud Engine
If the core physics logic in `atomforge/` is updated, the cloud app must be redeployed:

```bash
modal deploy atomforge/api.py
```
