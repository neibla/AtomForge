from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path

import modal
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse

from atomforge.api.evidence_views import load_sweep_results, load_visualization_catalog
from atomforge.api.lifecycle import RunLifecycle
from atomforge.execution.evidence_artifacts import ArtifactKind
from atomforge.execution.evidence_repository import (
    EvidenceRepository,
    LocalFilesystemAdapter,
    ModalVolumeAdapter,
    default_results_dir,
)
from atomforge.execution.script_sources import SCRIPT_SOURCE_VOLUME_NAME, sync_script_sources
from atomforge.reporting.html import render_html_report
from atomforge.schemas import (
    DeleteExperimentResponse,
    ExperimentBundleResponse,
    ExperimentSpec,
    HealthResponse,
    ReportResponse,
    RunRecord,
    RunRecordResponse,
    SweepResultsArtifact,
    VisualizationCatalog,
)
from atomforge.storage import read_json
from atomforge.validators import validate_experiment_spec

logger = logging.getLogger("atomforge.api.http")
load_dotenv()

RESULTS_DIR = default_results_dir()


@cache
def _results_volume():
    return modal.Volume.from_name("atomforge-results-v2", create_if_missing=True)


@cache
def _script_source_volume():
    return modal.Volume.from_name(SCRIPT_SOURCE_VOLUME_NAME, create_if_missing=True)


def _evidence_repository() -> EvidenceRepository:
    adapter = (
        ModalVolumeAdapter(RESULTS_DIR, _results_volume())
        if RESULTS_DIR == Path("/results")
        else LocalFilesystemAdapter(RESULTS_DIR)
    )
    return EvidenceRepository(adapter)


def _remote_evidence_adapter() -> ModalVolumeAdapter:
    return ModalVolumeAdapter(Path("/results"), _results_volume())


lifecycle = RunLifecycle(
    results_dir=lambda: RESULTS_DIR,
    repository=lambda: _evidence_repository(),
    remote_adapter=lambda: _remote_evidence_adapter(),
    modal=modal,
    logger=logger,
)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    try:
        await lifecycle.reconcile_unresolved_runs()
    except Exception:
        logger.exception("Unable to reconcile unresolved runs during API startup")
    yield


web_app = FastAPI(lifespan=_lifespan)


async def _submit_experiment(spec: ExperimentSpec) -> str:
    app_name = os.environ.get("ATOMFORGE_MODAL_APP_NAME", "atomforge-workers")
    orchestrator = modal.Cls.from_name(app_name, "Orchestrator")()
    call = await orchestrator.execute.spawn.aio(spec=spec)
    return call.object_id


@web_app.get("/healthz", response_model=HealthResponse, operation_id="healthcheck")
def healthcheck():
    return {"status": "ok"}


@web_app.get("/runs", response_model=list[RunRecordResponse], operation_id="listRuns")
async def list_runs():
    lifecycle.reload()
    if not RESULTS_DIR.exists():
        return []
    records: list[RunRecord] = []
    for experiment_id in _evidence_repository().iter_experiment_ids(ArtifactKind.RUN):
        try:
            refreshed = await lifecycle.read_run(experiment_id)
        except HTTPException:
            continue
        records.append(refreshed)
    return sorted(records, key=lambda record: record.updated_at, reverse=True)


@web_app.get("/runs/{id}", response_model=RunRecordResponse, operation_id="getRun")
async def get_run(id: str):
    return await lifecycle.read_run(id)


@web_app.post(
    "/experiments",
    response_model=RunRecordResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createExperiment",
)
async def submit_experiment(spec: ExperimentSpec):
    lifecycle.reload()
    return await lifecycle.submit_experiment(
        spec,
        script_source_volume=_script_source_volume,
        sync_script_sources=sync_script_sources,
        dispatch=_submit_experiment,
        validate=validate_experiment_spec,
    )


@web_app.post(
    "/experiments/{id}/rerun",
    response_model=RunRecordResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="rerunExperiment",
)
async def rerun_experiment(id: str):
    lifecycle.load_current_spec(id)
    existing = lifecycle.load_current_run(id)
    if existing.state in {"QUEUED", "RUNNING"}:
        raise HTTPException(
            status_code=409,
            detail="An active experiment cannot be rerun",
        )
    return await lifecycle.queue_rerun_experiment(
        id,
        validate=validate_experiment_spec,
        submit=submit_experiment,
    )


@web_app.delete(
    "/experiments/{id}",
    response_model=DeleteExperimentResponse,
    operation_id="deleteExperiment",
)
async def delete_experiment(id: str):
    lifecycle.path(id, ArtifactKind.RESULT)
    run_path = lifecycle.path(id, ArtifactKind.RUN)
    call_id = lifecycle.read_call_id(id)
    if call_id and run_path.exists():
        try:
            record = RunRecord.model_validate(read_json(run_path))
        except (OSError, ValueError):
            record = None
        if record and record.state in {"QUEUED", "RUNNING"}:
            try:
                await modal.FunctionCall.from_id(call_id).cancel.aio()
            except Exception:
                logger.exception(
                    "Unable to cancel remote call",
                    extra={"experiment_id": id},
                )
    _evidence_repository().delete_experiment(id)
    if not modal.is_local():
        await lifecycle.commit()
    return {"deleted": id}


@web_app.get(
    "/experiments/{id}",
    response_model=ExperimentBundleResponse,
    operation_id="getExperiment",
)
async def get_experiment(id: str):
    await lifecycle.refresh_local_run(id)
    lifecycle.reload()
    return lifecycle.load_current_bundle(id)


@web_app.get(
    "/experiments/{id}/report",
    response_model=ReportResponse,
    operation_id="getReport",
)
async def get_report(id: str):
    await lifecycle.refresh_local_run(id)
    lifecycle.reload()
    bundle_path = lifecycle.path(id, ArtifactKind.RESULT)
    bundle = lifecycle.load_current_bundle(id)
    return {
        "content": render_html_report(
            bundle.model_dump(mode="json"),
            source_path=bundle_path,
        )
    }


@web_app.get(
    "/experiments/{id}/visualizations",
    response_model=VisualizationCatalog,
    operation_id="getVisualizationCatalog",
)
async def get_visualizations(id: str):
    await lifecycle.refresh_local_run(id)
    lifecycle.reload()
    bundle = lifecycle.load_current_bundle(id)
    try:
        return load_visualization_catalog(_evidence_repository(), id, bundle)
    except (OSError, ValueError) as exc:
        raise lifecycle.contract_error(id, "invalid visualization catalog") from exc


@web_app.get(
    "/experiments/{id}/sweeps",
    response_model=SweepResultsArtifact,
    operation_id="getSweepResults",
)
async def get_sweep_results(id: str):
    await lifecycle.refresh_local_run(id)
    lifecycle.reload()
    bundle = lifecycle.load_current_bundle(id)
    try:
        return load_sweep_results(_evidence_repository(), id, bundle)
    except (OSError, ValueError) as exc:
        raise lifecycle.contract_error(id, "invalid sweep results artifact") from exc


@web_app.get(
    "/experiments/{id}/artifacts/{artifact_path:path}",
    response_class=FileResponse,
    operation_id="getVisualizationArtifact",
    responses={
        200: {
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"},
                }
            }
        }
    },
)
def get_visualization_artifact(id: str, artifact_path: str):
    lifecycle.reload()
    lifecycle.load_current_bundle(id)
    base = (RESULTS_DIR / f"{id}_artifacts").resolve()
    candidate = (base / artifact_path).resolve()
    if base not in candidate.parents or not candidate.is_file():
        raise HTTPException(
            status_code=404,
            detail="Visualization artifact not found",
        )
    return FileResponse(candidate)
