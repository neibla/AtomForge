import hashlib

import pytest

from atomforge.manifest import RunManifestContext, build_run_manifest
from atomforge.schemas import AtomsData, DagNode, ExperimentSpec, ResultsGraph


def test_manifest_keeps_public_identity_small():
    spec = ExperimentSpec(
        experiment_id="manifest-fixture",
        dag=[DagNode(id="f1", type="FETCH", params={"element": "W"})],
    )

    manifest = build_run_manifest(RunManifestContext(spec=spec))

    assert manifest["manifest_version"] == "v3"
    assert manifest["script_snapshot_id"] is None
    assert manifest["seed_policy"] == {
        "alloy": "explicit params.seed; defaults to 0",
        "simulation_trials": "local per-trial RNG with deterministic trial index [0..trials-1]",
    }
    assert "git_commit" not in manifest
    assert "worktree_dirty" not in manifest
    assert "spec_sha256" not in manifest
    assert "source_tree_sha256" not in manifest
    assert "dependency_lock_sha256" not in manifest
    assert "python_version" not in manifest
    assert "platform" not in manifest


def test_manifest_records_resolved_structure_identity():
    spec = ExperimentSpec(
        experiment_id="manifest-structure",
        dag=[DagNode(id="f1", type="FETCH", params={"element": "W"})],
    )
    structure = AtomsData(
        symbols=["W"],
        positions=[[0.0, 0.0, 0.0]],
        cell=[[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
        metadata={"mp_id": "mp-test"},
    )

    manifest = build_run_manifest(RunManifestContext(spec=spec, node_results={"f1": structure}))

    assert manifest["resolved_structures"]["f1"]["n_atoms"] == 1
    assert manifest["resolved_structures"]["f1"]["metadata"] == {"mp_id": "mp-test"}
    assert len(manifest["resolved_structures"]["f1"]["sha256"]) == 64


def test_manifest_records_script_identity_without_duplicate_hashes():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "manifest-script",
            "dag": [
                {"id": "f1", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "custom",
                    "type": "SCRIPT",
                    "depends_on": "f1",
                    "params": {
                        "script": "vacancy_disagreement_rank.py",
                        "output_metrics": {"vacancy_formation_energy": "eV"},
                    },
                },
            ],
        }
    )

    manifest = build_run_manifest(RunManifestContext(spec=spec))

    assert manifest["script_nodes"]["custom"]["script"] == "vacancy_disagreement_rank.py"
    assert "script_sha256" not in manifest["script_nodes"]["custom"]


def test_manifest_records_the_script_snapshot_id():
    snapshot_id = "a" * 64
    spec = ExperimentSpec(
        experiment_id="manifest-snapshot",
        script_snapshot_id=snapshot_id,
        dag=[
            DagNode(
                id="analysis",
                type="SCRIPT",
                params={"script": "analysis.py", "output_metrics": {}},
            )
        ],
    )

    manifest = build_run_manifest(RunManifestContext(spec=spec))

    assert manifest["script_snapshot_id"] == snapshot_id
    assert manifest["script_nodes"]["analysis"]["script"] == "analysis.py"


def test_manifest_rejects_result_from_another_experiment():
    spec = ExperimentSpec(
        experiment_id="manifest-spec",
        dag=[DagNode(id="f1", type="FETCH", params={"element": "W"})],
    )
    result = {
        "experiment_id": "different-run",
        "metrics": {},
        "hypotheses": [],
        "summary": "wrong result",
    }

    with pytest.raises(ValueError, match="does not match"):
        build_run_manifest(
            RunManifestContext(
                spec=spec,
                result=ResultsGraph.model_validate(result),
            )
        )


def test_manifest_rejects_unknown_node_results():
    spec = ExperimentSpec(
        experiment_id="manifest-nodes",
        dag=[DagNode(id="f1", type="FETCH", params={"element": "W"})],
    )

    with pytest.raises(ValueError, match="unknown node ids"):
        build_run_manifest(
            RunManifestContext(
                spec=spec,
                node_results={"not-in-spec": object()},
            )
        )


def test_manifest_rejects_missing_and_duplicate_artifacts(tmp_path):
    spec = ExperimentSpec(
        experiment_id="manifest-artifacts",
        dag=[DagNode(id="f1", type="FETCH", params={"element": "W"})],
    )
    first = tmp_path / "one" / "artifact.json"
    second = tmp_path / "two" / "artifact.json"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("one")
    second.write_text("two")

    with pytest.raises(ValueError, match="filenames must be unique"):
        build_run_manifest(
            RunManifestContext(
                spec=spec,
                artifact_paths=(first, second),
            )
        )

    with pytest.raises(FileNotFoundError, match="does not exist"):
        build_run_manifest(
            RunManifestContext(
                spec=spec,
                artifact_paths=(tmp_path / "missing.json",),
            )
        )


def test_manifest_can_hash_a_reader_visible_result_before_final_write(tmp_path):
    spec = ExperimentSpec(
        experiment_id="manifest-staged-result",
        dag=[DagNode(id="f1", type="FETCH", params={"element": "W"})],
    )
    report = tmp_path / "manifest-staged-result.md"
    visualizations = tmp_path / "manifest-staged-result_visualizations.json"
    result = tmp_path / "manifest-staged-result.json"
    report.write_text("report")
    visualizations.write_text("{}")
    result_blob = '{"results": {}}'

    manifest = build_run_manifest(
        RunManifestContext(
            spec=spec,
            artifact_paths=(result, report, visualizations),
        ),
        artifact_hash_overrides={
            result.name: hashlib.sha256(result_blob.encode()).hexdigest(),
        },
    )

    assert (
        manifest["artifact_sha256"][result.name] == hashlib.sha256(result_blob.encode()).hexdigest()
    )
