import json

import pytest

from atomforge.execution.evidence_artifacts import (
    ArtifactKind,
    artifact_integrity,
    artifact_path,
    read_verified_json,
)


def test_artifact_kind_owns_persisted_filename_convention(tmp_path):
    path = artifact_path(tmp_path, "run-1", ArtifactKind.VISUALIZATIONS)

    assert path.name == "run-1_visualizations.json"


def test_read_verified_json_uses_filename_and_exact_bytes(tmp_path):
    path = tmp_path / "run_visualizations.json"
    payload = {"experiment_id": "run", "visualizations": []}
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    integrity = artifact_integrity(path)

    assert (
        read_verified_json(
            path,
            expected_artifact_path=integrity.artifact_path,
            expected_sha256=integrity.sha256,
            parse=lambda value: value,
        )
        == payload
    )

    path.write_text(json.dumps({"changed": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        read_verified_json(
            path,
            expected_artifact_path=integrity.artifact_path,
            expected_sha256=integrity.sha256,
            parse=lambda value: value,
        )
