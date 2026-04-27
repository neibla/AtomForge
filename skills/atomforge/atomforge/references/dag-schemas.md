# AtomForge DAG & Experiment Schemas

All experiments are defined as an `ExperimentSpec`, which contains a Directed Acyclic Graph (DAG) of nodes and a set of hypotheses to evaluate.

## ExperimentSpec
- **experiment_id** (string): Unique identifier for the study.
- **dag** (List[DagNode]): Sequential or parallel steps of the experiment.
- **hypotheses** (List[Hypothesis]): Logical assertions to evaluate against the results.

## DagNode
- **id** (string): Node identifier (e.g., "f1", "s1").
- **type** (enum):
    - `FETCH`: Retrieve structure from Materials Project.
    - `ALLOY`: Expand lattice and perform element substitution.
    - `SIMULATE`: Dispatch GPU ensemble (PKA or Relaxation).
    - `ANALYZE`: Perform statistical post-processing.
- **depends_on** (string | list): ID(s) of parent nodes.
- **params** (dict): Configuration for the node.

## Hypothesis
- **id** (string): Identifier for the report (e.g., "radiation_tolerance").
- **target_node** (string): The node whose results are being evaluated (usually a SIMULATE node).
- **metric** (string): The primary metric (default: "n_defects").
- **assertion** (string): A logical expression evaluated by `simpleeval`.
    - Example: `"s1.avg_defects < 50"`
    - Example: `"target.avg_defects < f1.dft_energy * -0.5"`
