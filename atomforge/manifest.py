from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atomforge.schemas import ExperimentSpec, ResultsGraph


def build_run_manifest(spec: ExperimentSpec, result: ResultsGraph | None = None) -> dict[str, Any]:
    spec_blob = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    model_info = result.model_info.model_dump(mode="json") if result else {}
    return {
        "manifest_version": "v1",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "experiment_id": spec.experiment_id,
        "spec_sha256": hashlib.sha256(spec_blob.encode()).hexdigest(),
        "dag_node_ids": [n.id for n in spec.dag],
        "seed_policy": "per-trial seed is deterministic index [0..trials-1]",
        "model_info": model_info,
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def write_run_manifest(path: str | Path, manifest: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2))


def _git_commit() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL)
            .strip()
        )
    except Exception:
        return "unknown"
