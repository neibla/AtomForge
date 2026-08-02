import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from atomforge.api import http as api
from atomforge.schemas import DagNode, ExperimentSpec, RunRecord

client = TestClient(api.web_app)


def experiment_payload(experiment_id: str) -> dict:
    return {
        "experiment_id": experiment_id,
        "dag": [{"id": "f1", "type": "FETCH", "params": {"element": "W"}}],
    }


def write_control_plane(root, experiment_id: str, state: str, *, revision: int = 0) -> None:
    spec = ExperimentSpec.model_validate(
        {**experiment_payload(experiment_id), "revision": revision}
    )
    run = RunRecord(
        experiment_id=experiment_id,
        state=state,
        revision=revision,
    )
    (root / f"{experiment_id}_spec.json").write_text(spec.model_dump_json())
    (root / f"{experiment_id}_run.json").write_text(run.model_dump_json())


def mock_script_snapshot(monkeypatch, snapshot_id: str = "a" * 64) -> None:
    async def sync_sources(_volume):
        return snapshot_id

    monkeypatch.setattr(api, "sync_script_sources", sync_sources)


@pytest.mark.asyncio
async def test_refresh_marks_pending_remote_run_as_running(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(api.modal, "is_local", lambda: True)
    write_control_plane(tmp_path, "pending-run", "QUEUED")
    (tmp_path / "pending-run_call.json").write_text(json.dumps({"call_id": "fc-pending"}))

    class PendingGet:
        async def aio(self, *, timeout):
            assert timeout == 0
            raise TimeoutError

    monkeypatch.setattr(
        api.modal.FunctionCall,
        "from_id",
        lambda _call_id: SimpleNamespace(get=PendingGet()),
    )

    await api.lifecycle.refresh_local_run("pending-run")

    refreshed = RunRecord.model_validate_json((tmp_path / "pending-run_run.json").read_text())
    assert refreshed.state == "RUNNING"


@pytest.mark.asyncio
async def test_submit_resolves_named_deployed_modal_class(monkeypatch):
    seen: dict[str, str] = {}

    class Spawn:
        async def aio(self, *, spec):
            seen["experiment_id"] = spec.experiment_id
            return SimpleNamespace(object_id="fc-local")

    class RemoteOrchestrator:
        execute = SimpleNamespace(spawn=Spawn())

    monkeypatch.setattr(
        api.modal.Cls,
        "from_name",
        lambda app_name, class_name: (
            seen.update(app_name=app_name, class_name=class_name) or (lambda: RemoteOrchestrator())
        ),
    )

    result = await api._submit_experiment(
        ExperimentSpec(
            experiment_id="local-dispatch",
            dag=[DagNode(id="f1", type="FETCH", params={"element": "W"})],
        )
    )

    assert result == "fc-local"
    assert seen == {
        "app_name": "atomforge-workers",
        "class_name": "Orchestrator",
        "experiment_id": "local-dispatch",
    }


def test_submission_persists_lineage(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    mock_script_snapshot(monkeypatch)

    async def submit(_spec):
        return "fc-child"

    monkeypatch.setattr(api, "_submit_experiment", submit)
    payload = experiment_payload("child-run")
    payload.update(
        {
            "parent_experiment_id": "parent-run",
            "revision": 1,
            "change_summary": "Use a smaller bounded calculation",
        }
    )

    response = client.post("/experiments", json=payload)

    assert response.status_code == 202
    assert response.json()["parent_experiment_id"] == "parent-run"
    assert response.json()["revision"] == 1
    persisted = RunRecord.model_validate_json((tmp_path / "child-run_run.json").read_text())
    assert persisted.parent_experiment_id == "parent-run"
    assert persisted.revision == 1


def test_run_detail_refreshes_with_the_same_policy_as_run_list(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(api.modal, "is_local", lambda: True)
    write_control_plane(tmp_path, "detail-refresh", "QUEUED")
    (tmp_path / "detail-refresh_call.json").write_text(json.dumps({"call_id": "fc-detail"}))

    async def refresh(experiment_id: str) -> None:
        assert experiment_id == "detail-refresh"
        api.lifecycle.transition(experiment_id, "RUNNING")

    monkeypatch.setattr(api.lifecycle, "refresh_local_run", refresh)

    response = client.get("/runs/detail-refresh")

    assert response.status_code == 200
    assert response.json()["state"] == "RUNNING"


def test_submission_rejects_reserved_script_test_data(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    response = client.post(
        "/experiments",
        json={
            "experiment_id": "fixture-injection",
            "dag": [
                {
                    "id": "script",
                    "type": "SCRIPT",
                    "params": {
                        "script": "berger_vacancy_mace.py",
                        "arguments": {"fixture_results": {"fake": True}},
                        "output_metrics": {"quality_gate_passed": "dimensionless"},
                    },
                }
            ],
        },
    )

    assert response.status_code == 422
    assert "reserved test-only" in response.json()["detail"]


def test_rerun_clones_persisted_spec_with_lineage(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    write_control_plane(tmp_path, "completed-run", "COMPLETED", revision=2)
    mock_script_snapshot(monkeypatch)
    submitted: list[ExperimentSpec] = []

    async def submit(spec):
        submitted.append(spec)
        return "fc-rerun"

    monkeypatch.setattr(api, "_submit_experiment", submit)

    response = client.post("/experiments/completed-run/rerun")

    assert response.status_code == 202
    rerun = response.json()
    assert rerun["experiment_id"].startswith("completed-run-rerun-")
    assert rerun["parent_experiment_id"] == "completed-run"
    assert rerun["revision"] == 3
    assert submitted[0].force_recompute is True
    assert (
        submitted[0].dag == ExperimentSpec.model_validate(experiment_payload("completed-run")).dag
    )


def test_rerun_rejects_active_current_run(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    write_control_plane(tmp_path, "active-run", "RUNNING")

    response = client.post("/experiments/active-run/rerun")

    assert response.status_code == 409
    assert response.json()["detail"] == "An active experiment cannot be rerun"
