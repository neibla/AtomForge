"""Application run lifecycle behind the HTTP control plane.

This module owns the stateful workflow around persisted runs: loading the current
evidence set, reconciling unresolved Modal calls, and synchronizing remote evidence.
The HTTP module adapts these operations to FastAPI responses; it does not implement
the lifecycle itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from atomforge.execution.evidence_artifacts import ArtifactKind
from atomforge.execution.evidence_repository import EvidenceAdapter, EvidenceRepository
from atomforge.schemas import ExperimentBundleResponse, ExperimentSpec, RunRecord
from atomforge.storage import read_json


class RunLifecycle:
    """Own current-run reads, state transitions, and remote evidence recovery."""

    def __init__(
        self,
        *,
        results_dir: Callable[[], Path],
        repository: Callable[[], EvidenceRepository],
        remote_adapter: Callable[[], EvidenceAdapter],
        modal: Any,
        logger: logging.Logger,
    ) -> None:
        self._results_dir = results_dir
        self._repository = repository
        self._remote_adapter = remote_adapter
        self._modal = modal
        self._logger = logger

    def path(self, experiment_id: str, kind: ArtifactKind) -> Path:
        try:
            return self._repository().path(experiment_id, kind)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def read_call_id(self, experiment_id: str) -> str | None:
        try:
            return self._repository().read_call_id(experiment_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def transition(
        self,
        experiment_id: str,
        state: str,
        *,
        error: str | None = None,
        script_snapshot_id: str | None = None,
    ) -> RunRecord:
        try:
            return self._repository().transition(
                experiment_id,
                state,
                error=error,
                script_snapshot_id=script_snapshot_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def commit(self) -> None:
        await self._repository().commit()

    async def _prepare_submission(self, spec: ExperimentSpec) -> RunRecord | None:
        """Create the durable submission record or return an idempotent result."""

        if self.path(spec.experiment_id, ArtifactKind.RESULT).exists():
            raise HTTPException(
                status_code=409,
                detail="Experiment id already exists; use a new immutable id",
            )

        run_path = self.path(spec.experiment_id, ArtifactKind.RUN)
        if not run_path.exists():
            record = RunRecord(
                experiment_id=spec.experiment_id,
                state="QUEUED",
                parent_experiment_id=spec.parent_experiment_id,
                revision=spec.revision,
            )
            try:
                repository = self._repository()
                repository.create_json(
                    spec.experiment_id,
                    ArtifactKind.RUN,
                    record.model_dump(mode="json"),
                )
                repository.create_json(
                    spec.experiment_id,
                    ArtifactKind.SPEC,
                    spec.model_dump(mode="json"),
                )
            except FileExistsError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="Experiment id already exists; retry the request",
                ) from exc
            await self.commit()
            return None

        existing_spec = self.load_current_spec(spec.experiment_id)
        record = self.load_current_run(spec.experiment_id)
        requested = spec.model_copy(update={"script_snapshot_id": None})
        persisted = existing_spec.model_copy(update={"script_snapshot_id": None})
        if requested != persisted:
            raise HTTPException(
                status_code=409,
                detail="Experiment id already exists with a different specification",
            )

        call_id = self.read_call_id(spec.experiment_id)
        if not call_id and record.state == "FAILED":
            try:
                self._repository().reset_failed_submission(spec.experiment_id)
                await self.commit()
            except ValueError:
                return record.model_copy(update={"call_id": call_id})
            return None
        if call_id or record.state not in {"QUEUED", "RUNNING"}:
            return record.model_copy(update={"call_id": call_id})
        return None

    async def submit_experiment(
        self,
        spec: ExperimentSpec,
        *,
        script_source_volume: Callable[[], Any],
        sync_script_sources: Callable[[Any], Awaitable[str]],
        dispatch: Callable[[ExperimentSpec], Awaitable[str]],
        validate: Callable[[ExperimentSpec], None],
    ) -> RunRecord:
        """Persist, publish, dispatch, and record one immutable experiment run."""
        try:
            validate(spec)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        existing_record = await self._prepare_submission(spec)
        if existing_record is not None:
            return existing_record

        try:
            snapshot_id = await sync_script_sources(script_source_volume())
            submitted_spec = spec.model_copy(update={"script_snapshot_id": snapshot_id})
            self._repository().write_json(
                spec.experiment_id,
                ArtifactKind.SPEC,
                submitted_spec.model_dump(mode="json"),
            )
            self.transition(spec.experiment_id, "QUEUED", script_snapshot_id=snapshot_id)
            await self.commit()
        except Exception as exc:
            self._logger.exception(
                "Experiment submission failed while publishing SCRIPT snapshot: %s: %s",
                type(exc).__name__,
                exc,
                extra={
                    "experiment_id": spec.experiment_id,
                    "stage": "script_snapshot_publication",
                    "exception_type": type(exc).__name__,
                },
            )
            self.transition(
                spec.experiment_id,
                "FAILED",
                error=f"SCRIPT snapshot publication failed: {type(exc).__name__}: {exc}",
            )
            await self.commit()
            raise HTTPException(
                status_code=503,
                detail=f"SCRIPT snapshot publication failed: {type(exc).__name__}: {exc}",
            ) from exc

        try:
            call_id = await dispatch(submitted_spec)
        except Exception as exc:
            transient = self.is_transient_modal_error(exc)
            self._logger.exception(
                "Experiment submission failed while dispatching Modal job: %s: %s",
                type(exc).__name__,
                exc,
                extra={
                    "experiment_id": spec.experiment_id,
                    "stage": "modal_dispatch",
                    "exception_type": type(exc).__name__,
                    "transient": transient,
                },
            )
            if not transient:
                self.transition(
                    spec.experiment_id,
                    "FAILED",
                    error=f"Submission failed: {type(exc).__name__}: {exc}",
                )
            await self.commit()
            detail = (
                "Experiment submission status is uncertain; retry with the same experiment id"
                if transient
                else "Experiment submission failed"
            )
            if self._modal.is_local():
                detail = f"{detail}: {type(exc).__name__}: {exc}"
            raise HTTPException(status_code=503, detail=detail) from exc

        self._repository().write_json(spec.experiment_id, ArtifactKind.CALL, {"call_id": call_id})
        record = self.transition(spec.experiment_id, "QUEUED")
        await self.commit()
        return record.model_copy(update={"call_id": call_id})

    async def queue_rerun_experiment(
        self,
        source_id: str,
        *,
        validate: Callable[[ExperimentSpec], None],
        submit: Callable[[ExperimentSpec], Awaitable[RunRecord]],
    ) -> RunRecord:
        source_spec = self.load_current_spec(source_id)
        if source_spec.revision >= 1_000:
            raise HTTPException(status_code=409, detail="Maximum rerun lineage depth reached")
        suffix = f"-rerun-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
        base_id = source_id[: 100 - len(suffix)].rstrip("_-") or "experiment"
        derived_spec = source_spec.model_copy(
            update={
                "experiment_id": f"{base_id}{suffix}",
                "parent_experiment_id": source_id,
                "revision": source_spec.revision + 1,
                "change_summary": f"Rerun of {source_id} with the same DAG and parameters.",
                "force_recompute": True,
                "script_snapshot_id": None,
            }
        )
        validate(derived_spec)
        return await submit(derived_spec)

    def reload(self) -> None:
        self._repository().reload()

    def contract_error(self, experiment_id: str, detail: str) -> HTTPException:
        return HTTPException(
            status_code=409,
            detail=(
                f"Experiment '{experiment_id}' does not satisfy the current evidence contract "
                f"({detail}). Delete the experiment artifacts and rerun it."
            ),
        )

    def load_current_run(self, experiment_id: str) -> RunRecord:
        path = self.path(experiment_id, ArtifactKind.RUN)
        if not path.is_file():
            if (
                self.path(experiment_id, ArtifactKind.SPEC).exists()
                or self.path(experiment_id, ArtifactKind.RESULT).exists()
            ):
                raise self.contract_error(experiment_id, "missing _run.json")
            raise HTTPException(status_code=404, detail="Run not found")
        try:
            record = RunRecord.model_validate(read_json(path))
        except (OSError, ValueError) as exc:
            raise self.contract_error(experiment_id, "invalid _run.json") from exc
        if record.experiment_id != experiment_id:
            raise self.contract_error(experiment_id, "run experiment_id mismatch")
        return record

    async def read_run(self, experiment_id: str) -> RunRecord:
        """Refresh and read one run using the same policy as the run list."""

        await self.refresh_local_run(experiment_id)
        self.reload()
        self.load_current_spec(experiment_id)
        record = self.load_current_run(experiment_id)
        if record.state in {"COMPLETED", "PARTIAL"}:
            # A terminal evidence-bearing state is not reader-visible until its
            # bundle and manifest-referenced artifacts satisfy the contract.
            self.load_current_bundle(experiment_id)
        return record.model_copy(update={"call_id": self.read_call_id(experiment_id)})

    def load_current_spec(self, experiment_id: str) -> ExperimentSpec:
        path = self.path(experiment_id, ArtifactKind.SPEC)
        if not path.is_file():
            if (
                self.path(experiment_id, ArtifactKind.RUN).exists()
                or self.path(experiment_id, ArtifactKind.RESULT).exists()
            ):
                raise self.contract_error(experiment_id, "missing _spec.json")
            raise HTTPException(status_code=404, detail="Experiment specification not found")
        try:
            spec = ExperimentSpec.model_validate(read_json(path))
        except (OSError, ValueError) as exc:
            raise self.contract_error(experiment_id, "invalid _spec.json") from exc
        if spec.experiment_id != experiment_id:
            raise self.contract_error(experiment_id, "spec experiment_id mismatch")
        return spec

    def load_current_bundle(self, experiment_id: str) -> ExperimentBundleResponse:
        run = self.load_current_run(experiment_id)
        persisted_spec = self.load_current_spec(experiment_id)
        path = self.path(experiment_id, ArtifactKind.RESULT)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Experiment not found")
        try:
            bundle = ExperimentBundleResponse.model_validate(read_json(path))
        except (OSError, ValueError) as exc:
            raise self.contract_error(experiment_id, "invalid result bundle") from exc
        if bundle.results.experiment_id != experiment_id:
            raise self.contract_error(experiment_id, "result experiment_id mismatch")
        expected_status = {
            "COMPLETED": "SUCCESS",
            "PARTIAL": "PARTIAL",
            "FAILED": "FAILED",
        }
        if run.state in {"QUEUED", "RUNNING"}:
            raise self.contract_error(experiment_id, "result exists before terminal run state")
        if expected_status[run.state] != bundle.results.status:
            raise self.contract_error(experiment_id, "run state and result status disagree")
        if bundle.spec != persisted_spec:
            raise self.contract_error(
                experiment_id,
                "result bundle specification does not match _spec.json",
            )
        try:
            self._verify_manifest_if_present(experiment_id, bundle)
        except (OSError, ValueError) as exc:
            raise self.contract_error(experiment_id, "invalid evidence manifest") from exc
        return bundle

    def _verify_manifest_if_present(
        self,
        experiment_id: str,
        bundle: ExperimentBundleResponse,
    ) -> None:
        """Verify new manifests while preserving read access to legacy bundles."""

        manifest_path = self.path(experiment_id, ArtifactKind.MANIFEST)
        if not manifest_path.is_file():
            return
        payload = read_json(manifest_path)
        if not isinstance(payload, dict) or payload.get("experiment_id") != experiment_id:
            raise ValueError("manifest experiment id mismatch")
        hashes = payload.get("artifact_sha256")
        if not isinstance(hashes, dict):
            raise ValueError("manifest artifact hashes are missing")

        required = {
            self.path(experiment_id, ArtifactKind.RESULT).name,
            self.path(experiment_id, ArtifactKind.REPORT).name,
            self.path(experiment_id, ArtifactKind.VISUALIZATIONS).name,
        }
        if bundle.sweep_results_ref is not None:
            required.add(self.path(experiment_id, ArtifactKind.SWEEPS).name)
        if not required.issubset(hashes):
            raise ValueError("manifest does not cover every required artifact")

        for name, expected_sha256 in hashes.items():
            if not isinstance(name, str) or Path(name).name != name:
                raise ValueError("manifest contains an unsafe artifact filename")
            if not isinstance(expected_sha256, str):
                raise ValueError("manifest contains an invalid artifact checksum")
            artifact = self._results_dir() / name
            if not artifact.is_file():
                raise ValueError(f"manifest artifact is missing: {name}")
            actual_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if actual_sha256 != expected_sha256:
                raise ValueError(f"manifest checksum mismatch: {name}")

    def is_transient_modal_error(self, exc: Exception) -> bool:
        if isinstance(exc, ConnectionError):
            return True
        modal_exception = getattr(self._modal, "exception", None)
        for name in ("ConnectionError", "TimeoutError"):
            error_type = getattr(modal_exception, name, None)
            if isinstance(error_type, type) and isinstance(exc, error_type):
                return True
        return False

    async def sync_local_remote_run(self, experiment_id: str, call_id: str) -> None:
        if not self._modal.is_local():
            return
        try:
            # Modal control-plane calls can hang when the local network path is
            # unavailable. Keep the operator list responsive; the persisted
            # run remains RUNNING and will be reconciled on a later refresh.
            await asyncio.wait_for(
                self._modal.FunctionCall.from_id(call_id).get.aio(timeout=0),
                timeout=2.0,
            )
        except TimeoutError:
            self.transition(experiment_id, "RUNNING")
            return
        except Exception as exc:
            if self.is_transient_modal_error(exc):
                self._logger.warning(
                    "Unable to reach Modal while refreshing run; keeping it active",
                    extra={"experiment_id": experiment_id, "call_id": call_id},
                )
                self.transition(experiment_id, "RUNNING")
                return
            self.transition(
                experiment_id,
                "FAILED",
                error=f"Remote execution failed: {type(exc).__name__}: {exc}",
            )
            return
        try:
            await self._repository().sync_from(
                self._remote_adapter(),
                experiment_id,
                require_complete_terminal=True,
            )
        except Exception:
            self._logger.exception(
                "Unable to sync remote evidence",
                extra={"experiment_id": experiment_id},
            )

    async def refresh_local_run(self, experiment_id: str) -> None:
        path = self.path(experiment_id, ArtifactKind.RUN)
        if not self._modal.is_local() or not path.exists():
            return
        try:
            record = RunRecord.model_validate(read_json(path))
        except (OSError, ValueError):
            return
        call_id = self.read_call_id(experiment_id)
        if call_id and record.state in {"QUEUED", "RUNNING"}:
            await self.sync_local_remote_run(experiment_id, call_id)

    async def reconcile_unresolved_runs(self) -> None:
        if not self._modal.is_local() or not self._results_dir().exists():
            return
        for experiment_id in self._repository().iter_experiment_ids(ArtifactKind.RUN):
            try:
                record = self.load_current_run(experiment_id)
                self.load_current_spec(experiment_id)
            except HTTPException:
                self._logger.warning(
                    "Ignoring incomplete run during reconciliation",
                    extra={"experiment_id": experiment_id},
                )
                continue
            if record.state not in {"QUEUED", "RUNNING"}:
                continue
            call_id = self.read_call_id(experiment_id)
            if call_id:
                await self.sync_local_remote_run(experiment_id, call_id)
                continue
            try:
                await self._repository().sync_from(
                    self._remote_adapter(),
                    experiment_id,
                    require_complete_terminal=True,
                )
            except Exception:
                self._logger.warning(
                    "Unable to recover unresolved run without a Modal call ID",
                    extra={"experiment_id": experiment_id},
                )
