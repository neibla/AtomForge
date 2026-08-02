from argparse import Namespace
from pathlib import Path

import main
from main import (
    cmd_experiment_check,
    cmd_experiment_run,
    cmd_source_check,
)


def test_source_check_is_an_explicit_preflight(monkeypatch, capsys):
    called = False

    def validate():
        nonlocal called
        called = True

    monkeypatch.setattr("atomforge.validators.validate_runtime_sources", validate)

    cmd_source_check(Namespace())

    assert called is True
    assert "Python sources: valid" in capsys.readouterr().out


def test_experiment_check_validates_and_prints_plan(tmp_path, capsys):
    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(
        """
        {
          "experiment_id": "local-preflight",
          "dag": [
            {"id": "source", "type": "FETCH", "params": {"element": "W"}}
          ],
          "hypotheses": []
        }
        """,
        encoding="utf-8",
    )

    cmd_experiment_check(Namespace(spec_path=Path(spec_path)))

    output = capsys.readouterr().out
    assert "Experiment local-preflight: valid" in output
    assert "- source: FETCH <- root" in output
    assert "No compute was dispatched." in output


def test_experiment_run_submits_through_http_api(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(
        """
        {
          "experiment_id": "agent-submission",
          "dag": [
            {"id": "source", "type": "FETCH", "params": {"element": "W"}}
          ]
        }
        """,
        encoding="utf-8",
    )
    observed = {}

    def api_json(method, path, *, api_url, payload=None):
        observed.update(method=method, path=path, api_url=api_url, payload=payload)
        return {
            "experiment_id": "agent-submission",
            "state": "QUEUED",
            "call_id": "fc-agent",
        }

    monkeypatch.setattr(main, "_api_json", api_json)
    cmd_experiment_run(
        Namespace(
            spec_path=Path(spec_path),
            api_url="http://127.0.0.1:8000",
        )
    )

    assert observed["method"] == "POST"
    assert observed["path"] == "/experiments"
    assert "script_snapshot_id" not in observed["payload"]
    assert '"call_id": "fc-agent"' in capsys.readouterr().out
