"""Canonical paths for worker-owned DFT evidence artifacts."""

from __future__ import annotations

from pathlib import Path

DFT_ARTIFACT_ROOT = Path("/dft-artifacts")


def resolve_dft_artifact_dir(value: object) -> Path:
    """Resolve a run-specific path beneath the DFT artifact mount."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("artifact_dir must be an absolute run-specific path")
    requested = Path(value)
    if not requested.is_absolute():
        raise ValueError("artifact_dir must be an absolute run-specific path")

    root = DFT_ARTIFACT_ROOT.resolve()
    destination = requested.resolve(strict=False)
    if destination == root or root not in destination.parents:
        raise ValueError("artifact_dir must resolve to a child of /dft-artifacts")
    return destination
