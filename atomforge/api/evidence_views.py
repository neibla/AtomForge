"""Read and verify result artifacts exposed by the operator surface."""

from __future__ import annotations

from atomforge.execution.evidence_artifacts import ArtifactKind
from atomforge.execution.evidence_repository import EvidenceRepository
from atomforge.schemas import (
    ExperimentBundleResponse,
    SweepResultsArtifact,
    VisualizationCatalog,
)


def load_visualization_catalog(
    repository: EvidenceRepository,
    experiment_id: str,
    bundle: ExperimentBundleResponse,
) -> VisualizationCatalog:
    reference = bundle.visualization_catalog_ref
    if reference is None:
        raise ValueError("missing visualization catalog reference")
    catalog = repository.read_verified_json(
        experiment_id,
        ArtifactKind.VISUALIZATIONS,
        expected_artifact_path=reference.artifact_path,
        sha256=reference.sha256,
        parse=VisualizationCatalog.model_validate,
    )
    if catalog.experiment_id != experiment_id:
        raise ValueError("visualization catalog experiment id mismatch")
    if len(catalog.visualizations) != reference.visualization_count:
        raise ValueError("visualization catalog count mismatch")
    return catalog


def load_sweep_results(
    repository: EvidenceRepository,
    experiment_id: str,
    bundle: ExperimentBundleResponse,
) -> SweepResultsArtifact:
    reference = bundle.sweep_results_ref
    if reference is None:
        raise ValueError("missing sweep results reference")
    artifact = repository.read_verified_json(
        experiment_id,
        ArtifactKind.SWEEPS,
        expected_artifact_path=reference.artifact_path,
        sha256=reference.sha256,
        parse=SweepResultsArtifact.model_validate,
    )
    if artifact.experiment_id != experiment_id:
        raise ValueError("sweep results experiment id mismatch")
    if len(artifact.results) != reference.sweep_count:
        raise ValueError("sweep results count mismatch")
    sweep_node_ids = {node.id for node in bundle.spec.dag if node.type == "SWEEP"}
    if not set(artifact.results).issubset(sweep_node_ids):
        raise ValueError("sweep results contain undeclared sweep nodes")
    if bundle.results.status == "SUCCESS" and set(artifact.results) != sweep_node_ids:
        raise ValueError("successful sweep results do not cover every sweep node")
    return artifact
