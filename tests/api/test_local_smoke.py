import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from atomforge.api import http as api
from atomforge.execution.evidence_artifacts import ArtifactKind
from atomforge.execution.evidence_repository import EvidenceRepository
from atomforge.execution.experiment import execute_experiment
from atomforge.execution.orchestrator import BaseExecutor
from atomforge.schemas import (
    AtomsData,
    ExperimentSpec,
    MetricResult,
    RelaxResult,
    ScriptResult,
)


class LocalSmokeExecutor(BaseExecutor):
    async def fetch(self, element=None, structure_path=None):
        return AtomsData(
            symbols=["W"],
            positions=[[0.0, 0.0, 0.0]],
            cell=[[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
            pbc=(True, True, True),
        )

    async def alloy(self, parent, supercell, dopants, seed=0, vacancy=False):
        return parent

    async def simulate(self, atoms_data, mode, params, seed=0):
        return RelaxResult(
            seed=seed,
            potential_energy=-1.0,
            max_force=0.01,
            force_norm=0.01,
            positions=atoms_data.positions,
            cell=atoms_data.cell,
            atomic_numbers=[74],
            pbc=atoms_data.pbc,
        )

    async def script(self, *_args, **_kwargs):
        return ScriptResult(
            metrics={"score": MetricResult(val=1.0, unit="score")},
            data={
                "scientific_decision": {
                    "outcome": "REVIEW",
                    "calibration": {
                        "status": "INSUFFICIENT_EVIDENCE",
                        "minimum_case_count": 0,
                    },
                    "scope": "Deterministic local smoke path.",
                    "headline": "Local execution completed; no scientific claim was evaluated.",
                    "limitations": ["Smoke validation is not scientific evidence."],
                }
            },
        )


def test_local_end_to_end_smoke_publishes_and_reads_verified_bundle(tmp_path, monkeypatch):
    client = TestClient(api.web_app)
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)

    async def no_refresh(_experiment_id):
        return None

    monkeypatch.setattr(api.lifecycle, "refresh_local_run", no_refresh)
    monkeypatch.setattr(api, "_script_source_volume", lambda: object())

    async def sync_sources(_volume):
        return "a" * 64

    async def dispatch(_spec):
        return "local-smoke-call"

    monkeypatch.setattr(api, "sync_script_sources", sync_sources)
    monkeypatch.setattr(api, "_submit_experiment", dispatch)

    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "local-smoke",
            "dag": [
                {"id": "source", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "relax",
                    "type": "SIMULATE",
                    "depends_on": "source",
                    "params": {"mode": "relax", "trials": 1},
                },
                {
                    "id": "decision",
                    "type": "SCRIPT",
                    "depends_on": "relax",
                    "params": {
                        "script": "vacancy_disagreement_rank.py",
                        "output_metrics": {"score": "score"},
                    },
                },
            ],
            "decision_node_id": "decision",
        }
    )
    submitted = client.post("/experiments", json=spec.model_dump(mode="json"))
    assert submitted.status_code == 202
    assert submitted.json()["state"] == "QUEUED"

    repository = EvidenceRepository(api.LocalFilesystemAdapter(tmp_path))
    submitted_spec = ExperimentSpec.model_validate(
        repository.read_json("local-smoke", ArtifactKind.SPEC)
    )
    asyncio.run(
        execute_experiment(
            submitted_spec,
            LocalSmokeExecutor(),
            repository,
            script_source_root=Path("atomforge/node_scripts"),
        )
    )

    response = client.get("/experiments/local-smoke")
    assert response.status_code == 200
    bundle = response.json()
    assert bundle["results"]["node_statuses"] == {
        "source": "COMPLETE",
        "relax": "COMPLETE",
        "decision": "REVIEW",
    }
    assert bundle["visualization_catalog_ref"]["visualization_count"] == 1
