import pytest

from atomforge.schemas import DagNode, ExperimentSpec
from atomforge.validators import validate_experiment_spec


def test_validate_experiment_spec_rejects_invalid_simulation_mode():
    spec = ExperimentSpec(
        experiment_id="invalid-mode",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="s1",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "not-a-mode", "trials": 1},
            ),
        ],
    )

    with pytest.raises(ValueError, match="invalid mode"):
        validate_experiment_spec(spec)
