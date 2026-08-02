import hashlib
import json
import subprocess
import sys

from fastapi.testclient import TestClient

from atomforge.api import http as api
from atomforge.schemas import ExperimentSpec, RunRecord

client = TestClient(api.web_app)


def experiment_payload(experiment_id: str) -> dict:
    return {
        "experiment_id": experiment_id,
        "dag": [{"id": "f1", "type": "FETCH", "params": {"element": "W"}}],
    }


def write_current_evidence(
    root,
    experiment_id: str,
    *,
    visualizations: list[dict] | None = None,
) -> None:
    spec = ExperimentSpec.model_validate(experiment_payload(experiment_id))
    run = RunRecord(experiment_id=experiment_id, state="COMPLETED")
    catalog = {
        "contract_version": "v1",
        "experiment_id": experiment_id,
        "visualizations": visualizations or [],
    }
    catalog_content = json.dumps(catalog, sort_keys=True)
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
        "spec": spec.model_dump(mode="json"),
        "scientific_decision": {
            "contract_version": "scientific-decision.v1",
            "outcome": "REVIEW",
            "calibration": {
                "status": "INSUFFICIENT_EVIDENCE",
                "accepted_case_count": 0,
                "minimum_case_count": 0,
            },
            "scope": "Test evidence.",
            "headline": "Review test evidence.",
            "supported_claims": [],
            "limitations": ["Test-only evidence."],
            "quality_checks": [],
        },
        "visualization_catalog_ref": {
            "contract_version": "catalog-reference.v1",
            "artifact_path": f"{experiment_id}_visualizations.json",
            "sha256": hashlib.sha256(catalog_content.encode()).hexdigest(),
            "visualization_count": len(catalog["visualizations"]),
        },
    }
    (root / f"{experiment_id}_run.json").write_text(run.model_dump_json())
    (root / f"{experiment_id}_spec.json").write_text(spec.model_dump_json())
    (root / f"{experiment_id}.json").write_text(json.dumps(bundle))
    (root / f"{experiment_id}_visualizations.json").write_text(catalog_content)


def test_http_api_does_not_import_privileged_runtime():
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import atomforge.api.http; "
                "assert 'atomforge.platform.modal.runtime' not in sys.modules; "
                "assert 'ase' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr


def test_artifact_endpoint_is_experiment_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    write_current_evidence(tmp_path, "golden-run")
    artifact_dir = tmp_path / "golden-run_artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "plot.png").write_bytes(b"png-data")

    response = client.get("/experiments/golden-run/artifacts/plot.png")
    traversal = client.get("/experiments/golden-run/artifacts/../secret.txt")

    assert response.status_code == 200
    assert response.content == b"png-data"
    assert traversal.status_code == 404
