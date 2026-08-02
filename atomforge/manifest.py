import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atomforge.schemas import AtomsData, ExperimentSpec, ResultsGraph


@dataclass(frozen=True)
class RunManifestContext:
    """Immutable inputs used to assemble one run's provenance manifest.

    Keeping the execution snapshot together makes it harder for callers to
    accidentally pair a result, node outputs, and artifacts from different runs.
    """

    spec: ExperimentSpec
    result: ResultsGraph | None = None
    node_results: Mapping[str, Any] = field(default_factory=dict)
    artifact_paths: tuple[str | Path, ...] = ()


def dependency_lock_path() -> Path:
    lock_path = Path.cwd() / "uv.lock"
    if not lock_path.exists():
        lock_path = Path(__file__).resolve().parent.parent / "uv.lock"
    return lock_path


def source_tree_sha256() -> str:
    package_root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        digest.update(path.relative_to(package_root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def sha256_file(path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.exists():
        return "unavailable"
    return hashlib.sha256(resolved.read_bytes()).hexdigest()


def runtime_fingerprint() -> dict[str, str]:
    return {
        "source_tree_sha256": source_tree_sha256(),
        "dependency_lock_sha256": sha256_file(dependency_lock_path()),
    }


def _script_nodes_manifest(
    spec: ExperimentSpec,
) -> dict[str, dict[str, Any]]:
    nodes = [node for node in spec.dag if node.type == "SCRIPT"]
    if not nodes:
        return {}

    return {
        node.id: {
            "script": node.params["script"],
            "execution_profile": node.params.get("execution_profile", "analysis"),
            "output_metrics": node.params["output_metrics"],
        }
        for node in nodes
    }


def _artifact_hashes(
    paths: tuple[str | Path, ...],
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    overrides = overrides or {}
    hashes: dict[str, str] = {}
    for raw_path in paths:
        path = Path(raw_path)
        if path.name in overrides:
            hashes[path.name] = overrides[path.name]
            continue
        if not path.is_file():
            raise FileNotFoundError(f"Manifest artifact does not exist: {path}")
        if path.name in hashes:
            raise ValueError(f"Manifest artifact filenames must be unique: {path.name!r}")
        hashes[path.name] = sha256_file(path)
    return hashes


def build_run_manifest(
    context: RunManifestContext,
    *,
    artifact_hash_overrides: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    spec = context.spec
    result = context.result
    node_results = context.node_results

    if result is not None and result.experiment_id != spec.experiment_id:
        raise ValueError(
            "Manifest result experiment_id does not match the specification: "
            f"{result.experiment_id!r} != {spec.experiment_id!r}"
        )

    known_node_ids = {node.id for node in spec.dag}
    unexpected_node_results = set(node_results) - known_node_ids
    if unexpected_node_results:
        raise ValueError(
            f"Manifest node_results contain unknown node ids: {sorted(unexpected_node_results)}"
        )

    model_info = result.model_info.model_dump(mode="json") if result else {}
    node_model_info = (
        {
            node_id: metadata.model_dump(mode="json")
            for node_id, metadata in result.node_model_info.items()
        }
        if result
        else {}
    )
    resolved_structures = {}
    for node_id, node_result in (node_results or {}).items():
        if isinstance(node_result, AtomsData):
            structure_blob = json.dumps(
                node_result.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
            resolved_structures[node_id] = {
                "sha256": hashlib.sha256(structure_blob.encode()).hexdigest(),
                "metadata": node_result.metadata or {},
                "n_atoms": len(node_result.symbols),
                "pbc": list(node_result.pbc),
            }

    manifest = {
        "manifest_version": "v3",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "experiment_id": spec.experiment_id,
        "script_snapshot_id": spec.script_snapshot_id,
        "dag_node_ids": [node.id for node in spec.dag],
        "seed_policy": {
            "alloy": "explicit params.seed; defaults to 0",
            "simulation_trials": "local per-trial RNG with deterministic trial index [0..trials-1]",
        },
        "model_info": model_info,
        "node_model_info": node_model_info,
        "resolved_structures": resolved_structures,
        "script_nodes": _script_nodes_manifest(spec),
        "artifact_sha256": _artifact_hashes(
            context.artifact_paths,
            overrides=artifact_hash_overrides,
        ),
    }
    return manifest
