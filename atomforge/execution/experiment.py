"""Run one experiment and publish its reader-visible evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from atomforge.analysis import build_analysis_payload
from atomforge.execution.evidence_artifacts import ArtifactKind
from atomforge.execution.evidence_repository import EvidenceRepository
from atomforge.execution.orchestrator import BaseExecutor, CoreOrchestrator
from atomforge.manifest import RunManifestContext, build_run_manifest
from atomforge.reporting import render_research_report
from atomforge.schemas import (
    ExperimentSpec,
    ResultsGraph,
    RunRecord,
    ScriptResult,
    SweepResult,
    SweepResultsArtifact,
)
from atomforge.scientific_decision import (
    blocked_decision_from_execution,
    decision_from_script_results,
)
from atomforge.validators import validate_experiment_spec
from atomforge.visualizations import build_visualization_catalog


async def execute_experiment(
    spec: ExperimentSpec,
    executor: BaseExecutor,
    repository: EvidenceRepository,
    *,
    node_cache: Any = None,
    script_source_root: Path | None = None,
    require_script_snapshot: bool = False,
    commit: Callable[[], Awaitable[None]] | None = None,
) -> ResultsGraph:
    """Execute, assemble, and publish one experiment through one seam."""

    save = commit or _noop_commit
    try:
        existing = _load_existing_result(repository, spec.experiment_id)
        if existing is not None:
            return existing

        if require_script_snapshot and not spec.script_snapshot_id:
            raise ValueError("Experiment is missing its immutable SCRIPT snapshot ID")
        if script_source_root is None:
            validate_experiment_spec(spec)
        else:
            validate_experiment_spec(spec, source_root=script_source_root)
        # The worker owns the shared results volume. Publish the immutable spec
        # before exposing a RUNNING state so remote reconciliation can always
        # recover the complete evidence lineage, including failed runs.
        repository.write_json(
            spec.experiment_id,
            ArtifactKind.SPEC,
            spec.model_dump(mode="json"),
        )
        repository.transition(
            spec.experiment_id,
            "RUNNING",
            parent_experiment_id=spec.parent_experiment_id,
            revision=spec.revision,
            script_snapshot_id=spec.script_snapshot_id,
        )
        await save()

        final_result, trial_bundle, node_results = await CoreOrchestrator(
            executor,
            node_cache=node_cache,
            script_source_root=script_source_root,
        ).execute(spec)
        analysis = build_analysis_payload(
            spec,
            final_result,
            trial_bundle.get("trial_metrics_by_node", {}),
            trial_data=trial_bundle.get("trial_data", {}),
        )
        visualizations = build_visualization_catalog(
            spec,
            trial_data=trial_bundle.get("trial_data", {}),
            node_results=node_results,
        )
        script_results = {
            node.id: node_results[node.id]
            for node in spec.dag
            if isinstance(node_results.get(node.id), ScriptResult)
        }
        scientific_decision = decision_from_script_results(
            {
                node_id: result.model_dump(mode="json")
                for node_id, result in script_results.items()
            },
            decision_node_id=spec.decision_node_id,
            node_order=[node.id for node in spec.dag if node.type == "SCRIPT"],
        )
        if scientific_decision is None:
            if final_result.status == "SUCCESS":
                raise ValueError("Completed experiment is missing scientific-decision.v1")
            scientific_decision = blocked_decision_from_execution(final_result.errors)

        visualization_path = repository.write_json(
            spec.experiment_id,
            ArtifactKind.VISUALIZATIONS,
            visualizations.model_dump(mode="json"),
        )
        visualization_integrity = repository.artifact_integrity(visualization_path)
        sweep_results = {
            node.id: node_results[node.id]
            for node in spec.dag
            if isinstance(node_results.get(node.id), SweepResult)
        }
        sweep_path = (
            repository.write_json(
                spec.experiment_id,
                ArtifactKind.SWEEPS,
                SweepResultsArtifact(
                    experiment_id=spec.experiment_id,
                    results=sweep_results,
                ).model_dump(mode="json"),
            )
            if sweep_results
            else None
        )
        sweep_integrity = (
            repository.artifact_integrity(sweep_path) if sweep_path is not None else None
        )
        result_path = repository.path(spec.experiment_id, ArtifactKind.RESULT)
        result_payload = {
            "results": final_result.model_dump(),
            "spec": spec.model_dump(),
            "scientific_decision": scientific_decision.model_dump(mode="json"),
            "analysis": analysis,
            "visualization_catalog_ref": {
                "contract_version": "catalog-reference.v1",
                "artifact_path": visualization_path.name,
                "sha256": visualization_integrity.sha256,
                "visualization_count": len(visualizations.visualizations),
            },
            "sweep_results_ref": (
                {
                    "contract_version": "sweep-results-reference.v1",
                    "artifact_path": sweep_path.name,
                    "sha256": sweep_integrity.sha256,
                    "sweep_count": len(sweep_results),
                }
                if sweep_path is not None
                else None
            ),
            "script_results": {
                node_id: result.model_dump(mode="json")
                for node_id, result in script_results.items()
            },
        }

        # Publish companion evidence before the result bundle. Readers only
        # see a terminal run after every required artifact is in place.
        result_blob = json.dumps(result_payload, indent=2)
        result_sha256 = hashlib.sha256(result_blob.encode("utf-8")).hexdigest()
        report_path = repository.write_text(
            spec.experiment_id,
            ArtifactKind.REPORT,
            render_research_report(spec, final_result, script_results=script_results),
        )
        repository.write_json(
            spec.experiment_id,
            ArtifactKind.MANIFEST,
            build_run_manifest(
                RunManifestContext(
                    spec=spec,
                    result=final_result,
                    node_results=node_results,
                    artifact_paths=(
                        result_path,
                        report_path,
                        visualization_path,
                        *((sweep_path,) if sweep_path is not None else ()),
                    ),
                ),
                artifact_hash_overrides={result_path.name: result_sha256},
            ),
        )
        repository.write_json(spec.experiment_id, ArtifactKind.RESULT, result_payload)
        if repository.artifact_integrity(result_path).sha256 != result_sha256:
            raise ValueError("Result bundle changed while it was being published")

        final_state = {
            "SUCCESS": "COMPLETED",
            "PARTIAL": "PARTIAL",
            "FAILED": "FAILED",
        }[final_result.status]
        repository.transition(
            spec.experiment_id,
            final_state,
            error="One or more nodes failed." if final_state == "PARTIAL" else None,
        )
        await save()
        return final_result
    except Exception as exc:
        repository.transition(
            spec.experiment_id,
            "FAILED",
            error=f"{type(exc).__name__}: {exc}",
        )
        await save()
        raise


def _load_existing_result(
    repository: EvidenceRepository,
    experiment_id: str,
) -> ResultsGraph | None:
    """Reuse only a published result whose run state agrees with it."""

    result_path = repository.path(experiment_id, ArtifactKind.RESULT)
    if not result_path.is_file():
        return None
    run_path = repository.path(experiment_id, ArtifactKind.RUN)
    if not run_path.is_file():
        raise ValueError("result exists but _run.json is missing")
    try:
        run = RunRecord.model_validate(repository.read_json(experiment_id, ArtifactKind.RUN))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("result exists but _run.json is invalid") from exc
    if run.state in {"QUEUED", "RUNNING"}:
        return None
    try:
        bundle = repository.read_json(experiment_id, ArtifactKind.RESULT)
        graph = ResultsGraph.model_validate(bundle["results"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("result bundle is invalid") from exc
    expected_status = {"COMPLETED": "SUCCESS", "PARTIAL": "PARTIAL", "FAILED": "FAILED"}
    if graph.status != expected_status[run.state]:
        raise ValueError("run state and result status disagree")
    return graph


async def _noop_commit() -> None:
    return None
