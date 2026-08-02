from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from atomforge.execution.evidence_artifacts import (
    DELETABLE_ARTIFACT_KINDS,
    SYNCED_ARTIFACT_KINDS,
    ArtifactIntegrity,
    ArtifactKind,
    artifact_integrity,
    artifact_path,
    read_verified_json,
)
from atomforge.schemas import RunRecord
from atomforge.storage import (
    create_json_exclusive,
    file_lock,
    read_json,
    write_json_atomic,
    write_text_atomic,
)

_TERMINAL_STATES = {"COMPLETED", "PARTIAL", "FAILED"}
_ALLOWED_TRANSITIONS = {
    "QUEUED": {"QUEUED", "RUNNING", "FAILED"},
    "RUNNING": {"RUNNING", "COMPLETED", "PARTIAL", "FAILED"},
    "COMPLETED": {"COMPLETED"},
    "PARTIAL": {"PARTIAL"},
    "FAILED": {"FAILED"},
}


def default_results_dir() -> Path:
    configured = os.environ.get("ATOMFORGE_RESULTS_DIR")
    if configured:
        return Path(configured)
    modal_results = Path("/results")
    if modal_results.is_dir() and os.access(modal_results, os.W_OK):
        return modal_results
    return Path(__file__).resolve().parents[2] / ".atomforge" / "results"


def _run_path(results_dir: Path, experiment_id: str) -> Path:
    return artifact_path(results_dir, experiment_id, ArtifactKind.RUN)


def _call_path(results_dir: Path, experiment_id: str) -> Path:
    return artifact_path(results_dir, experiment_id, ArtifactKind.CALL)


def _read_call_id(results_dir: Path, experiment_id: str) -> str | None:
    path = _call_path(results_dir, experiment_id)
    if not path.exists():
        return None
    payload = read_json(path)
    call_id = payload.get("call_id") if isinstance(payload, dict) else None
    return call_id if isinstance(call_id, str) else None


def transition_run(
    results_dir: Path,
    experiment_id: str,
    state: str,
    *,
    error: str | None = None,
    parent_experiment_id: str | None = None,
    revision: int = 0,
    script_snapshot_id: str | None = None,
) -> RunRecord:
    path = _run_path(results_dir, experiment_id)
    with file_lock(path):
        existing = RunRecord.model_validate(read_json(path)) if path.exists() else None
        if state not in _ALLOWED_TRANSITIONS:
            raise ValueError(f"Unknown run state: {state}")

        if existing and state not in _ALLOWED_TRANSITIONS[existing.state]:
            # A stale worker cannot replace a terminal outcome. Returning the
            # stored record also makes duplicate terminal writes safe.
            if existing.state in _TERMINAL_STATES:
                return existing
            raise ValueError(f"Invalid run transition: {existing.state} -> {state}")

        effective_error = existing.error if existing else None
        if state in {"PARTIAL", "FAILED"}:
            effective_error = error
        if existing and existing.state == state and state in _TERMINAL_STATES:
            effective_error = existing.error
        record = RunRecord(
            experiment_id=experiment_id,
            state=state,
            call_id=_read_call_id(results_dir, experiment_id)
            or (existing.call_id if existing else None),
            created_at=existing.created_at if existing else datetime.now(UTC),
            updated_at=datetime.now(UTC),
            error=effective_error,
            parent_experiment_id=(
                existing.parent_experiment_id if existing else parent_experiment_id
            ),
            revision=existing.revision if existing else revision,
            script_snapshot_id=(
                script_snapshot_id or (existing.script_snapshot_id if existing else None)
            ),
        )
        write_json_atomic(path, record.model_dump(mode="json"))
        return record


def reset_failed_submission(results_dir: Path, experiment_id: str) -> RunRecord:
    """Reopen a failed submission that never reached a worker."""

    path = _run_path(results_dir, experiment_id)
    with file_lock(path):
        if not path.exists():
            raise ValueError(f"Run does not exist: {experiment_id}")
        existing = RunRecord.model_validate(read_json(path))
        if existing.state != "FAILED":
            raise ValueError(
                f"Only failed submissions can be reopened; current state is {existing.state}"
            )
        if (
            _call_path(results_dir, experiment_id).exists()
            or artifact_path(results_dir, experiment_id, ArtifactKind.RESULT).exists()
        ):
            raise ValueError("A dispatched call or result already exists")
        reopened = existing.model_copy(
            update={
                "state": "QUEUED",
                "updated_at": datetime.now(UTC),
                "error": None,
                "call_id": None,
                "script_snapshot_id": None,
            }
        )
        write_json_atomic(path, reopened.model_dump(mode="json"))
        return reopened


class EvidenceAdapter(Protocol):
    root: Path

    def reload(self) -> None: ...

    async def commit(self) -> None: ...

    async def read_text(self, name: str) -> str: ...


class LocalFilesystemAdapter:
    def __init__(self, root: Path) -> None:
        self.root = root

    def reload(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def read_text(self, name: str) -> str:
        return (self.root / name).read_text(encoding="utf-8")


class ModalVolumeAdapter:
    """Adapt a mounted Modal volume to the evidence repository seam."""

    def __init__(self, root: Path, volume: Any) -> None:
        self.root = root
        self._volume = volume

    def reload(self) -> None:
        if self.root.exists():
            self._volume.reload()

    async def commit(self) -> None:
        if self.root.exists():
            await self._volume.commit.aio()

    async def read_text(self, name: str) -> str:
        chunks = [chunk async for chunk in self._volume.read_file.aio(name)]
        return b"".join(chunks).decode("utf-8")


class EvidenceRepository:
    """Own evidence naming, atomic persistence, synchronization, and run state."""

    def __init__(self, adapter: EvidenceAdapter) -> None:
        self.adapter = adapter

    @property
    def root(self) -> Path:
        return self.adapter.root

    def path(self, experiment_id: str, kind: ArtifactKind) -> Path:
        return artifact_path(self.root, experiment_id, kind)

    def iter_experiment_ids(self, kind: ArtifactKind) -> Iterator[str]:
        if not self.root.exists():
            return
        for path in self.root.glob(f"*{kind.value}"):
            if kind is ArtifactKind.RESULT and any(
                path.name.endswith(other.value) for other in ArtifactKind if other is not kind
            ):
                continue
            experiment_id = path.name.removesuffix(kind.value)
            if experiment_id:
                yield experiment_id

    def reload(self) -> None:
        self.adapter.reload()

    async def commit(self) -> None:
        await self.adapter.commit()

    def read_json(self, experiment_id: str, kind: ArtifactKind) -> Any:
        return read_json(self.path(experiment_id, kind))

    def read_call_id(self, experiment_id: str) -> str | None:
        return _read_call_id(self.root, experiment_id)

    def create_json(self, experiment_id: str, kind: ArtifactKind, payload: Any) -> Path:
        path = self.path(experiment_id, kind)
        create_json_exclusive(path, payload)
        return path

    def write_json(self, experiment_id: str, kind: ArtifactKind, payload: Any) -> Path:
        path = self.path(experiment_id, kind)
        write_json_atomic(path, payload)
        return path

    def write_text(self, experiment_id: str, kind: ArtifactKind, content: str) -> Path:
        path = self.path(experiment_id, kind)
        write_text_atomic(path, content)
        return path

    def artifact_integrity(self, path: Path) -> ArtifactIntegrity:
        return artifact_integrity(path)

    def read_verified_json[T](
        self,
        experiment_id: str,
        kind: ArtifactKind,
        *,
        expected_artifact_path: str,
        sha256: str,
        parse: Callable[[Any], T],
    ) -> T:
        return read_verified_json(
            self.path(experiment_id, kind),
            expected_artifact_path=expected_artifact_path,
            expected_sha256=sha256,
            parse=parse,
        )

    def transition(
        self,
        experiment_id: str,
        state: str,
        *,
        error: str | None = None,
        parent_experiment_id: str | None = None,
        revision: int = 0,
        script_snapshot_id: str | None = None,
    ) -> RunRecord:
        return transition_run(
            self.root,
            experiment_id,
            state,
            error=error,
            parent_experiment_id=parent_experiment_id,
            revision=revision,
            script_snapshot_id=script_snapshot_id,
        )

    def reset_failed_submission(self, experiment_id: str) -> RunRecord:
        return reset_failed_submission(self.root, experiment_id)

    async def sync_from(
        self,
        source: EvidenceAdapter,
        experiment_id: str,
        *,
        kinds: Iterable[ArtifactKind] = SYNCED_ARTIFACT_KINDS,
        require_complete_terminal: bool = False,
    ) -> list[Path]:
        selected_kinds = tuple(kinds)
        contents: dict[ArtifactKind, str] = {}
        for kind in selected_kinds:
            try:
                contents[kind] = await source.read_text(f"{experiment_id}{kind.value}")
            except FileNotFoundError:
                continue

        if require_complete_terminal and ArtifactKind.RUN in contents:
            try:
                run = RunRecord.model_validate(json.loads(contents[ArtifactKind.RUN]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("remote run record is invalid") from exc
            if run.state in {"COMPLETED", "PARTIAL"}:
                required = {
                    ArtifactKind.SPEC,
                    ArtifactKind.RESULT,
                    ArtifactKind.REPORT,
                    ArtifactKind.VISUALIZATIONS,
                }
                missing = sorted(kind.value for kind in required if kind not in contents)
                if missing:
                    raise ValueError(
                        "remote terminal run is missing required evidence: " + ", ".join(missing)
                    )

        synced: list[Path] = []
        for kind in selected_kinds:
            content = contents.get(kind)
            if content is not None:
                synced.append(self.write_text(experiment_id, kind, content))
        return synced

    def delete_experiment(
        self,
        experiment_id: str,
        *,
        extra_kinds: Iterable[ArtifactKind] = (),
    ) -> list[Path]:
        deleted: list[Path] = []
        for kind in (*DELETABLE_ARTIFACT_KINDS, *extra_kinds):
            path = self.path(experiment_id, kind)
            if path.exists():
                path.unlink()
                deleted.append(path)
        artifact_dir = self.root / f"{experiment_id}_artifacts"
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
            deleted.append(artifact_dir)
        return deleted
