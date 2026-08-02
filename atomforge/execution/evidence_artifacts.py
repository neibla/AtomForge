from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class ArtifactKind(StrEnum):
    RUN = "_run.json"
    SPEC = "_spec.json"
    RESULT = ".json"
    REPORT = ".md"
    VISUALIZATIONS = "_visualizations.json"
    SWEEPS = "_sweeps.json"
    MANIFEST = "_manifest.json"
    CALL = "_call.json"


_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def artifact_path(results_dir: Path, experiment_id: str, kind: ArtifactKind) -> Path:
    if not _EXPERIMENT_ID.fullmatch(experiment_id):
        raise ValueError("Invalid experiment id")
    return results_dir / f"{experiment_id}{kind.value}"


# Result bundles are the only unsuffixed JSON artifact. Every other suffix is
# either a synchronized result artifact or local control-plane state.
SYNCED_ARTIFACT_KINDS = (
    ArtifactKind.SPEC,
    ArtifactKind.REPORT,
    ArtifactKind.VISUALIZATIONS,
    ArtifactKind.SWEEPS,
    ArtifactKind.MANIFEST,
    ArtifactKind.RESULT,
    # Publish the run record last so a terminal state is not visible locally
    # until the complete reader-visible evidence set has been synchronized.
    ArtifactKind.RUN,
)
CONTROL_PLANE_ARTIFACT_KINDS = (ArtifactKind.CALL,)
DELETABLE_ARTIFACT_KINDS = SYNCED_ARTIFACT_KINDS + CONTROL_PLANE_ARTIFACT_KINDS


@dataclass(frozen=True, slots=True)
class ArtifactIntegrity:
    artifact_path: str
    sha256: str


def artifact_integrity(path: Path) -> ArtifactIntegrity:
    return ArtifactIntegrity(
        artifact_path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def read_verified_json[T](
    path: Path,
    *,
    expected_artifact_path: str,
    expected_sha256: str,
    parse: Callable[[Any], T],
) -> T:
    """Verify and decode one trusted artifact from the exact bytes read."""

    if path.name != expected_artifact_path:
        raise ValueError("artifact filename does not match its reference")
    if not path.is_file():
        raise ValueError("artifact is missing")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("artifact checksum mismatch")
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("artifact contains invalid JSON") from exc
    return parse(payload)
