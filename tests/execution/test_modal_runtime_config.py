import pytest


def test_checkpoint_and_cache_identity_are_versioned():
    from atomforge.platform.modal import runtime as modal_runtime

    assert modal_runtime.ATOMFORGE_SOURCE_ROOT.name == "atomforge"
    assert len(modal_runtime.MACE_MH1_SHA256) == 64


def test_script_profiles_fail_closed_and_pin_validated_hardware():
    from atomforge.platform.modal import runtime as modal_runtime

    profiles = modal_runtime.SCRIPT_EXECUTION_PROFILES
    assert set(profiles) == {"analysis", "physics_gpu", "dft_cpu", "dft_gpu"}
    assert all(profile.retries == 0 for profile in profiles.values())
    assert profiles["dft_gpu"].gpu == "H100"
    assert profiles["dft_gpu"].max_containers == 1
    assert profiles["dft_gpu"].artifact_mount == "/dft-artifacts"


def test_existing_result_loader_does_not_reuse_an_active_run(tmp_path):
    from atomforge.execution.evidence_artifacts import ArtifactKind
    from atomforge.execution.evidence_repository import EvidenceRepository, LocalFilesystemAdapter
    from atomforge.execution.experiment import _load_existing_result
    from atomforge.schemas import ResultsGraph, RunRecord

    repository = EvidenceRepository(LocalFilesystemAdapter(tmp_path))
    graph = ResultsGraph(
        experiment_id="reuse-run",
        metrics={},
        hypotheses=[],
        summary="completed",
    )
    repository.write_json("reuse-run", ArtifactKind.RESULT, {"results": graph.model_dump()})
    repository.write_json(
        "reuse-run",
        ArtifactKind.RUN,
        RunRecord(experiment_id="reuse-run", state="RUNNING").model_dump(mode="json"),
    )
    assert _load_existing_result(repository, "reuse-run") is None

    repository.write_json(
        "reuse-run",
        ArtifactKind.RUN,
        RunRecord(experiment_id="reuse-run", state="COMPLETED").model_dump(mode="json"),
    )
    reused = _load_existing_result(repository, "reuse-run")
    assert reused is not None
    assert reused.experiment_id == "reuse-run"

    repository.path("reuse-run", ArtifactKind.RUN).unlink()
    with pytest.raises(ValueError, match="_run.json is missing"):
        _load_existing_result(repository, "reuse-run")

    repository.write_json(
        "reuse-run",
        ArtifactKind.RUN,
        RunRecord(experiment_id="reuse-run", state="PARTIAL").model_dump(mode="json"),
    )
    with pytest.raises(ValueError, match="state and result status disagree"):
        _load_existing_result(repository, "reuse-run")
