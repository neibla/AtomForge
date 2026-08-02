# AtomForge DAG & Experiment Schemas

Validate the actual checked-in spec before dispatch:

```bash
uv run atomforge experiment check --spec-path experiments/dags/<study>.json
```

## ExperimentSpec

- **experiment_id** (string): Unique identifier for the study.
- **dag** (List[DagNode]): Sequential or parallel steps of the experiment.
- **hypotheses** (List[Hypothesis]): Logical assertions to evaluate against the results.
- **parent_experiment_id** (string, optional): Persisted parent for a revised experiment.
- **revision** (integer, default `0`): Revision number.
- **change_summary** (string, optional): What changed from the parent and why.

## DagNode

- **id** (string): Node identifier (e.g., "f1", "s1").
- **type** (enum):
    - `FETCH`: Retrieve structure from Materials Project.
    - `ALLOY`: Expand lattice and perform element substitution.
    - `SIMULATE`: Dispatch a GPU/CPU ensemble (`pka`, `relax`, `single_point`, or `nvt`).
    - `SCRIPT`: Run a trusted checked-in PEP 723 script against serialized dependency outputs.
- **depends_on** (string | list): ID(s) of parent nodes.
- **params** (dict): Configuration for the node.

## Node Parameters

- `SIMULATE` requires `mode` (`pka`, `relax`, `single_point`, or `nvt`) and a positive `trials`
  value. Mode-specific fields are strictly validated by `atomforge.validators`.
- `SCRIPT` requires:
  - `script`: safe relative `.py` path under `atomforge/node_scripts/`;
  - `output_metrics`: non-empty metric-to-unit mapping;
  - `execution_profile`: `analysis`, `physics_gpu`, `dft_cpu`, or `dft_gpu`, declared directly
    in `params`;
  - optional `arguments` and `timeout_seconds`.

Do not put execution configuration under `arguments.runtime`. SCRIPT nodes receive a v1 JSON input
file and must write a v1 JSON output file. Outputs may contain declarative `atomistic.v1`,
`chart.v1`, `table.v1`, or `image.v1` visualizations; scripts cannot supply frontend code.

## Hypothesis

- **id** (string): Identifier for the report (e.g., "radiation_tolerance").
- **target_node** (string): The node whose result is evaluated.
- **metric** (string): The primary metric (default: "n_defects").
- **assertion** (string): A logical expression evaluated by `simpleeval`.
    - Example: `"s1.n_defects < 50"`
    - Example: `"target.max_force <= 0.05"`

Use hypotheses for predeclared gates with sourced or physically justified thresholds. A passing
workflow or convergence gate does not by itself establish model applicability or scientific
validation.
