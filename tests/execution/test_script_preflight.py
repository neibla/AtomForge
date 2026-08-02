import json

import pytest

from atomforge.execution.script_runner import _validate_physics_provenance
from atomforge.schemas import ScriptOutput


def test_physics_provenance_requires_schema_compatible_identity_and_exact_hash():
    base = {
        "contract_version": "v1",
        "metrics": {},
        "visualizations": [],
        "data": {
            "model_info": {
                "name": "MACE-MH-1",
                "version": "mace_mh_1",
                "checkpoint": f"mace-mh-1.model sha256:{'a' * 64}",
                "head": "omat_pbe",
                "dtype": "float64",
                "device": "cuda",
            }
        },
    }
    _validate_physics_provenance(ScriptOutput.model_validate(base))

    wrong_identity = json.loads(json.dumps(base))
    wrong_identity["data"]["model_info"]["model"] = wrong_identity["data"]["model_info"].pop("name")
    with pytest.raises(ValueError, match="name"):
        _validate_physics_provenance(ScriptOutput.model_validate(wrong_identity))

    short_hash = json.loads(json.dumps(base))
    short_hash["data"]["model_info"]["checkpoint"] = "model sha256:abc"
    with pytest.raises(ValueError, match="64 hex"):
        _validate_physics_provenance(ScriptOutput.model_validate(short_hash))
