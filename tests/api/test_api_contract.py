import hashlib
import json

from fastapi.testclient import TestClient

from atomforge.api import http as api
from atomforge.schemas import ExperimentSpec, RunRecord

client = TestClient(api.web_app)


def experiment_payload(experiment_id: str) -> dict:
    return {
        "experiment_id": experiment_id,
        "dag": [{"id": "f1", "type": "FETCH", "params": {"element": "W"}}],
    }


def current_bundle(
    experiment_id: str,
    visualizations: list[dict] | None = None,
) -> tuple[dict, dict]:
    catalog = {
        "contract_version": "v1",
        "experiment_id": experiment_id,
        "visualizations": visualizations or [],
    }
    catalog_content = json.dumps(catalog, indent=2)
    bundle = {
        "results": {
            "experiment_id": experiment_id,
            "status": "SUCCESS",
            "metrics": {},
            "hypotheses": [],
            "model_info": {
                "name": "unknown",
                "version": "unknown",
                "device": "unknown",
            },
            "node_model_info": {},
            "summary": "",
            "errors": {},
        },
        "spec": experiment_payload(experiment_id),
        "scientific_decision": {
            "contract_version": "scientific-decision.v1",
            "outcome": "REVIEW",
            "calibration": {
                "status": "INSUFFICIENT_EVIDENCE",
                "accepted_case_count": 0,
                "minimum_case_count": 0,
            },
            "scope": "Configured test run.",
            "headline": "Evidence requires review.",
            "supported_claims": [],
            "limitations": ["Test fixture contains no scientific evidence."],
            "quality_checks": [],
        },
        "visualization_catalog_ref": {
            "contract_version": "catalog-reference.v1",
            "artifact_path": f"{experiment_id}_visualizations.json",
            "sha256": hashlib.sha256(catalog_content.encode()).hexdigest(),
            "visualization_count": len(catalog["visualizations"]),
        },
    }
    return bundle, catalog


def write_current_evidence(
    root,
    experiment_id: str,
    visualizations: list[dict] | None = None,
) -> None:
    spec = ExperimentSpec.model_validate(experiment_payload(experiment_id))
    run = RunRecord(experiment_id=experiment_id, state="COMPLETED")
    bundle, catalog = current_bundle(experiment_id, visualizations)
    (root / f"{experiment_id}_spec.json").write_text(spec.model_dump_json())
    (root / f"{experiment_id}_run.json").write_text(run.model_dump_json())
    (root / f"{experiment_id}.json").write_text(json.dumps(bundle))
    (root / f"{experiment_id}_visualizations.json").write_text(json.dumps(catalog, indent=2))


def write_sweep_evidence(root, experiment_id: str) -> None:
    payload = {
        "experiment_id": experiment_id,
        "dag": [
            {"id": "f1", "type": "FETCH", "params": {"element": "W"}},
            {
                "id": "scan",
                "type": "SWEEP",
                "depends_on": "f1",
                "params": {
                    "operation": {"mode": "single_point"},
                    "coordinate": {
                        "name": "cell_scale",
                        "label": "Cell scale",
                        "grid": {"values": [0.9, 1.0]},
                    },
                    "apply": {"target": "cell_scale"},
                },
            },
        ],
    }
    spec = ExperimentSpec.model_validate(payload)
    run = RunRecord(experiment_id=experiment_id, state="PARTIAL")
    bundle, catalog = current_bundle(experiment_id)
    bundle["spec"] = payload
    bundle["results"]["status"] = "PARTIAL"
    artifact = {
        "contract_version": "sweep-results.v1",
        "experiment_id": experiment_id,
        "results": {
            "scan": {
                "contract_version": "sweep-result.v1",
                "coordinate": payload["dag"][1]["params"]["coordinate"],
                "apply": payload["dag"][1]["params"]["apply"],
                "points": [
                    {
                        "id": f"scan-point-{index:04d}",
                        "index": index,
                        "value": value,
                        "applied_value": value,
                        "simulation_params": {"cell_scale": value},
                        "status": "FAILED",
                        "error": "fixture failure",
                    }
                    for index, value in enumerate((0.9, 1.0))
                ],
            }
        },
    }
    artifact_content = json.dumps(artifact, indent=2)
    bundle["sweep_results_ref"] = {
        "contract_version": "sweep-results-reference.v1",
        "artifact_path": f"{experiment_id}_sweeps.json",
        "sha256": hashlib.sha256(artifact_content.encode()).hexdigest(),
        "sweep_count": 1,
    }
    (root / f"{experiment_id}_spec.json").write_text(spec.model_dump_json())
    (root / f"{experiment_id}_run.json").write_text(run.model_dump_json())
    (root / f"{experiment_id}.json").write_text(json.dumps(bundle))
    (root / f"{experiment_id}_visualizations.json").write_text(json.dumps(catalog, indent=2))
    (root / f"{experiment_id}_sweeps.json").write_text(artifact_content)


def test_missing_experiment_returns_404():
    response = client.get("/experiments/does-not-exist")
    assert response.status_code == 404


def test_historical_bundle_requires_current_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    bundle, _ = current_bundle("historical-run")
    bundle.pop("scientific_decision")
    (tmp_path / "historical-run.json").write_text(json.dumps(bundle))

    response = client.get("/experiments/historical-run")

    assert response.status_code == 409
    assert "missing _run.json" in response.json()["detail"]
    assert not (tmp_path / "historical-run_spec.json").exists()
    assert not (tmp_path / "historical-run_run.json").exists()


def test_bundle_must_match_persisted_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    write_current_evidence(tmp_path, "mismatch-run")
    bundle = json.loads((tmp_path / "mismatch-run.json").read_text())
    bundle["spec"]["dag"][0]["params"]["element"] = "Ni"
    (tmp_path / "mismatch-run.json").write_text(json.dumps(bundle))

    response = client.get("/experiments/mismatch-run")

    assert response.status_code == 409
    assert "does not match _spec.json" in response.json()["detail"]


def test_result_is_not_read_while_run_is_active(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    write_current_evidence(tmp_path, "active-result")
    run_path = tmp_path / "active-result_run.json"
    run = RunRecord.model_validate_json(run_path.read_text())
    run_path.write_text(run.model_copy(update={"state": "RUNNING"}).model_dump_json())

    response = client.get("/experiments/active-result")

    assert response.status_code == 409
    assert "before terminal run state" in response.json()["detail"]


def test_published_manifest_is_verified_before_bundle_is_served(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    experiment_id = "manifest-verified"
    write_current_evidence(tmp_path, experiment_id)
    report_path = tmp_path / f"{experiment_id}.md"
    result_path = tmp_path / f"{experiment_id}.json"
    visualizations_path = tmp_path / f"{experiment_id}_visualizations.json"
    report_path.write_text("report", encoding="utf-8")
    manifest = {
        "manifest_version": "v3",
        "experiment_id": experiment_id,
        "artifact_sha256": {
            result_path.name: hashlib.sha256(result_path.read_bytes()).hexdigest(),
            report_path.name: hashlib.sha256(report_path.read_bytes()).hexdigest(),
            visualizations_path.name: hashlib.sha256(visualizations_path.read_bytes()).hexdigest(),
        },
    }
    (tmp_path / f"{experiment_id}_manifest.json").write_text(json.dumps(manifest))

    assert client.get(f"/experiments/{experiment_id}").status_code == 200

    report_path.write_text("tampered", encoding="utf-8")
    response = client.get(f"/experiments/{experiment_id}")

    assert response.status_code == 409
    assert "invalid evidence manifest" in response.json()["detail"]


def test_run_list_ignores_records_without_specs(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    (tmp_path / "incomplete_run.json").write_text(
        RunRecord(experiment_id="incomplete", state="COMPLETED").model_dump_json()
    )
    write_current_evidence(tmp_path, "current")

    response = client.get("/runs")

    assert response.status_code == 200
    assert [run["experiment_id"] for run in response.json()] == ["current"]


def test_current_result_visualization_and_report_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    write_current_evidence(tmp_path, "golden-run")

    result = client.get("/experiments/golden-run")
    visualizations = client.get("/experiments/golden-run/visualizations")
    report = client.get("/experiments/golden-run/report")

    assert result.status_code == 200
    assert result.json()["scientific_decision"]["outcome"] == "REVIEW"
    assert visualizations.status_code == 200
    assert report.status_code == 200
    assert report.json()["content"].startswith("<!doctype html>")


def test_sweep_results_endpoint_validates_durable_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    write_sweep_evidence(tmp_path, "sweep-run")

    response = client.get("/experiments/sweep-run/sweeps")

    assert response.status_code == 200
    assert list(response.json()["results"]) == ["scan"]
    assert response.json()["results"]["scan"]["points"][0]["status"] == "FAILED"


def test_sweep_results_endpoint_rejects_undeclared_node(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    write_sweep_evidence(tmp_path, "bad-sweep-run")
    path = tmp_path / "bad-sweep-run_sweeps.json"
    artifact = json.loads(path.read_text())
    artifact["results"]["undeclared"] = artifact["results"].pop("scan")
    content = json.dumps(artifact, indent=2)
    path.write_text(content)
    bundle_path = tmp_path / "bad-sweep-run.json"
    bundle = json.loads(bundle_path.read_text())
    bundle["sweep_results_ref"]["sha256"] = hashlib.sha256(content.encode()).hexdigest()
    bundle_path.write_text(json.dumps(bundle))

    response = client.get("/experiments/bad-sweep-run/sweeps")

    assert response.status_code == 409
    assert "invalid sweep results artifact" in response.json()["detail"]
