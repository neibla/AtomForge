import pytest
from fastapi.testclient import TestClient

from atomforge.api import http as api
from atomforge.schemas import ExperimentSpec, RunRecord


def write_control_plane(root, experiment_id: str, state: str) -> None:
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": experiment_id,
            "dag": [{"id": "f1", "type": "FETCH", "params": {"element": "W"}}],
        }
    )
    run = RunRecord(experiment_id=experiment_id, state=state)
    (root / f"{experiment_id}_spec.json").write_text(spec.model_dump_json())
    (root / f"{experiment_id}_run.json").write_text(run.model_dump_json())


@pytest.mark.asyncio
async def test_startup_reconciliation_does_not_expose_incomplete_terminal_run(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(api.modal, "is_local", lambda: True)
    write_control_plane(tmp_path, "orphaned-run", "QUEUED")

    class RemoteEvidence:
        async def read_text(self, name):
            if name == "orphaned-run_run.json":
                return RunRecord(
                    experiment_id="orphaned-run",
                    state="COMPLETED",
                ).model_dump_json()
            raise FileNotFoundError(name)

    monkeypatch.setattr(api, "_remote_evidence_adapter", lambda: RemoteEvidence())

    await api.lifecycle.reconcile_unresolved_runs()

    recovered = RunRecord.model_validate_json((tmp_path / "orphaned-run_run.json").read_text())
    assert recovered.state == "QUEUED"


def test_loopback_operator_surface_requires_no_application_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    local_client = TestClient(api.web_app, client=("::1", 50000))

    response = local_client.get("/runs")

    assert response.status_code == 200
    assert response.json() == []
