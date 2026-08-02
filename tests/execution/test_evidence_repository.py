import asyncio

import pytest

from atomforge.execution.evidence_artifacts import ArtifactKind
from atomforge.execution.evidence_repository import (
    EvidenceRepository,
    LocalFilesystemAdapter,
    transition_run,
)
from atomforge.schemas import RunRecord


def test_terminal_outcome_is_not_replaced_by_a_late_failure(tmp_path):
    transition_run(tmp_path, "terminal-run", "RUNNING")
    completed = transition_run(tmp_path, "terminal-run", "COMPLETED")

    stale = transition_run(
        tmp_path,
        "terminal-run",
        "FAILED",
        error="stale worker error",
    )

    assert completed.state == "COMPLETED"
    assert stale.state == "COMPLETED"
    assert (
        RunRecord.model_validate_json((tmp_path / "terminal-run_run.json").read_text()).state
        == "COMPLETED"
    )


def test_active_state_rejects_an_illegal_terminal_jump(tmp_path):
    transition_run(tmp_path, "queued-run", "QUEUED")

    with pytest.raises(ValueError, match="QUEUED -> COMPLETED"):
        transition_run(tmp_path, "queued-run", "COMPLETED")


def test_duplicate_terminal_write_is_idempotent(tmp_path):
    transition_run(tmp_path, "partial-run", "RUNNING")
    first = transition_run(tmp_path, "partial-run", "PARTIAL", error="one point failed")
    second = transition_run(tmp_path, "partial-run", "PARTIAL", error="different wording")

    assert second.state == "PARTIAL"
    assert second.error == first.error


def test_local_evidence_repository_owns_artifact_naming_and_sync(tmp_path):
    source_root = tmp_path / "remote"
    destination_root = tmp_path / "local"
    source_root.mkdir()
    destination_root.mkdir()
    source = LocalFilesystemAdapter(source_root)
    repository = EvidenceRepository(LocalFilesystemAdapter(destination_root))
    experiment_id = "evidence-run"
    (source_root / f"{experiment_id}.json").write_text('{"results": {}}', encoding="utf-8")
    (source_root / f"{experiment_id}_manifest.json").write_text(
        '{"artifacts": []}',
        encoding="utf-8",
    )

    synced = asyncio.run(repository.sync_from(source, experiment_id))

    assert {path.name for path in synced} == {
        f"{experiment_id}.json",
        f"{experiment_id}_manifest.json",
    }
    assert repository.path(experiment_id, ArtifactKind.RESULT).read_text(encoding="utf-8") == (
        '{"results": {}}'
    )


def test_local_evidence_repository_owns_run_transitions_and_deletion(tmp_path):
    repository = EvidenceRepository(LocalFilesystemAdapter(tmp_path))

    record = repository.transition(
        "run-1",
        "RUNNING",
        parent_experiment_id="parent-run",
        revision=2,
    )
    repository.write_json("run-1", ArtifactKind.RESULT, {"results": {}})
    repository.write_json("run-1", ArtifactKind.CALL, {"call_id": "call-1"})
    deleted = repository.delete_experiment("run-1")

    assert record.state == "RUNNING"
    assert record.parent_experiment_id == "parent-run"
    assert record.revision == 2
    assert {path.name for path in deleted} == {
        "run-1_run.json",
        "run-1.json",
        "run-1_call.json",
    }


def test_experiment_listing_skips_invalid_filenames(tmp_path):
    repository = EvidenceRepository(LocalFilesystemAdapter(tmp_path))
    (tmp_path / "_run.json").write_text("{}", encoding="utf-8")
    (tmp_path / "valid-run_run.json").write_text("{}", encoding="utf-8")

    assert list(repository.iter_experiment_ids(ArtifactKind.RUN)) == ["valid-run"]


def test_terminal_sync_requires_reader_visible_evidence_before_copying_run(tmp_path):
    source_root = tmp_path / "remote"
    destination_root = tmp_path / "local"
    source_root.mkdir()
    destination_root.mkdir()
    source = LocalFilesystemAdapter(source_root)
    repository = EvidenceRepository(LocalFilesystemAdapter(destination_root))
    experiment_id = "incomplete-terminal"
    (source_root / f"{experiment_id}_run.json").write_text(
        '{"experiment_id":"incomplete-terminal","state":"COMPLETED"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required evidence"):
        asyncio.run(repository.sync_from(source, experiment_id, require_complete_terminal=True))

    assert not repository.path(experiment_id, ArtifactKind.RUN).exists()


def test_terminal_sync_copies_the_complete_evidence_set_together(tmp_path):
    source_root = tmp_path / "remote"
    destination_root = tmp_path / "local"
    source_root.mkdir()
    destination_root.mkdir()
    source = LocalFilesystemAdapter(source_root)
    repository = EvidenceRepository(LocalFilesystemAdapter(destination_root))
    experiment_id = "complete-terminal"
    (source_root / f"{experiment_id}_run.json").write_text(
        '{"experiment_id":"complete-terminal","state":"COMPLETED"}',
        encoding="utf-8",
    )
    for suffix, content in (
        ("_spec.json", "{}"),
        (".json", "{}"),
        (".md", "report"),
        ("_visualizations.json", "{}"),
    ):
        (source_root / f"{experiment_id}{suffix}").write_text(content, encoding="utf-8")

    synced = asyncio.run(
        repository.sync_from(source, experiment_id, require_complete_terminal=True)
    )

    assert {path.name for path in synced} == {
        f"{experiment_id}_run.json",
        f"{experiment_id}_spec.json",
        f"{experiment_id}.json",
        f"{experiment_id}.md",
        f"{experiment_id}_visualizations.json",
    }
