import json
import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from atomforge.api import http as api
from atomforge.schemas import ExperimentSpec, RunRecord

client = TestClient(api.web_app)


def experiment_payload(experiment_id: str) -> dict:
    return {
        "experiment_id": experiment_id,
        "dag": [{"id": "f1", "type": "FETCH", "params": {"element": "W"}}],
    }


def mock_script_snapshot(monkeypatch, snapshot_id: str = "a" * 64) -> None:
    async def sync_sources(_volume):
        return snapshot_id

    monkeypatch.setattr(api, "sync_script_sources", sync_sources)


def test_loopback_submission_persists_current_control_plane(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    mock_script_snapshot(monkeypatch)

    async def fake_submit(_spec):
        return "fc-local"

    monkeypatch.setattr(api, "_submit_experiment", fake_submit)

    response = client.post("/experiments", json=experiment_payload("local-run"))

    assert response.status_code == 202
    assert response.json()["call_id"] == "fc-local"
    assert (tmp_path / "local-run_run.json").is_file()
    assert (tmp_path / "local-run_spec.json").is_file()
    assert (tmp_path / "local-run_call.json").is_file()


def test_uncertain_submission_remains_retryable_with_same_id(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    mock_script_snapshot(monkeypatch)
    attempts = 0

    async def submit(_spec):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("connection dropped after submission")
        return "fc-recovered"

    monkeypatch.setattr(api, "_submit_experiment", submit)
    payload = experiment_payload("uncertain-run")

    uncertain = client.post("/experiments", json=payload)
    recovered = client.post("/experiments", json=payload)

    assert uncertain.status_code == 503
    assert recovered.status_code == 202
    assert recovered.json()["call_id"] == "fc-recovered"
    assert attempts == 2


def test_failed_snapshot_submission_can_be_reopened_with_same_id(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    attempts = 0

    async def sync_sources(_volume):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("snapshot volume unavailable")
        return "a" * 64

    monkeypatch.setattr(api, "sync_script_sources", sync_sources)

    async def submit(_spec):
        return "fc-snapshot-retry"

    monkeypatch.setattr(api, "_submit_experiment", submit)

    payload = experiment_payload("snapshot-retry")
    first = client.post("/experiments", json=payload)
    second = client.post("/experiments", json=payload)

    assert first.status_code == 503
    assert second.status_code == 202
    assert attempts == 2


def test_snapshot_submission_failure_logs_stage_and_exception(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)

    async def sync_sources(_volume):
        raise OSError("snapshot volume unavailable")

    monkeypatch.setattr(api, "sync_script_sources", sync_sources)
    caplog.set_level(logging.ERROR, logger="atomforge.api.http")

    response = client.post("/experiments", json=experiment_payload("snapshot-log"))

    assert response.status_code == 503
    record = next(
        record
        for record in caplog.records
        if record.name == "atomforge.api.http"
        and record.stage == "script_snapshot_publication"
    )
    assert record.exception_type == "OSError"
    assert "snapshot volume unavailable" in record.getMessage()
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_rerun_does_not_write_generated_dag_files(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    source_spec = ExperimentSpec.model_validate(experiment_payload("source-run"))
    (tmp_path / "source-run_spec.json").write_text(source_spec.model_dump_json())
    captured = None

    async def submit(derived_spec):
        nonlocal captured
        captured = derived_spec
        return RunRecord(experiment_id=derived_spec.experiment_id, state="QUEUED")

    monkeypatch.setattr(api, "submit_experiment", submit)
    monkeypatch.setattr(api, "validate_experiment_spec", lambda _spec: None)

    record = await api.lifecycle.queue_rerun_experiment(
        "source-run",
        validate=lambda _spec: None,
        submit=submit,
    )

    assert captured is not None
    assert captured.parent_experiment_id == "source-run"
    assert captured.force_recompute is True
    assert record.experiment_id == captured.experiment_id
    assert list(tmp_path.glob("*.json")) == [tmp_path / "source-run_spec.json"]


def test_delete_removes_current_and_legacy_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(api.modal, "is_local", lambda: True)
    experiment_id = "delete-run"
    spec = ExperimentSpec.model_validate(experiment_payload(experiment_id))
    run = RunRecord(experiment_id=experiment_id, state="COMPLETED")
    (tmp_path / f"{experiment_id}_spec.json").write_text(spec.model_dump_json())
    (tmp_path / f"{experiment_id}_run.json").write_text(run.model_dump_json())
    (tmp_path / f"{experiment_id}.json").write_text("{}")
    (tmp_path / f"{experiment_id}_call.json").write_text(json.dumps({"call_id": "fc"}))

    response = client.delete(f"/experiments/{experiment_id}")

    assert response.status_code == 200
    assert not list(tmp_path.glob(f"{experiment_id}*"))


@pytest.mark.asyncio
async def test_startup_reconciliation_ignores_legacy_run_without_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(api.modal, "is_local", lambda: True)
    run = RunRecord(experiment_id="legacy-run", state="QUEUED")
    (tmp_path / "legacy-run_run.json").write_text(run.model_dump_json())
    called = False

    class RemoteEvidence:
        async def read_text(self, _name):
            nonlocal called
            called = True
            raise FileNotFoundError

    monkeypatch.setattr(api, "_remote_evidence_adapter", lambda: RemoteEvidence())

    await api.lifecycle.reconcile_unresolved_runs()

    assert called is False


@pytest.mark.asyncio
async def test_refresh_keeps_active_run_when_modal_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(api.modal, "is_local", lambda: True)
    run = RunRecord(experiment_id="pending-run", state="QUEUED")
    (tmp_path / "pending-run_run.json").write_text(run.model_dump_json())
    (tmp_path / "pending-run_call.json").write_text(json.dumps({"call_id": "fc"}))

    class Get:
        async def aio(self, *, timeout):
            assert timeout == 0
            raise api.modal.exception.ConnectionError("unavailable")

    monkeypatch.setattr(
        api.modal.FunctionCall,
        "from_id",
        lambda _call_id: SimpleNamespace(get=Get()),
    )

    await api.lifecycle.refresh_local_run("pending-run")

    refreshed = RunRecord.model_validate_json((tmp_path / "pending-run_run.json").read_text())
    assert refreshed.state == "RUNNING"
    assert refreshed.error is None
