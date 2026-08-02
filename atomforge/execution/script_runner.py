import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from atomforge.contracts import RESERVED_SCRIPT_ARGUMENTS, ScriptExecutionProfile
from atomforge.execution.artifact_paths import resolve_dft_artifact_dir
from atomforge.execution.script_sources import script_root
from atomforge.schemas import ScriptOutput, ScriptResult
from atomforge.serialization import to_jsonable


def resolve_script_destination(script: str, *, source_root: Path | None = None) -> Path:
    relative = PurePosixPath(script)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
        raise ValueError("SCRIPT node script must be a safe relative .py path")
    root = (source_root or script_root()).resolve()
    path = root.joinpath(*relative.parts).resolve()
    if root not in path.parents:
        raise ValueError("SCRIPT node script must remain inside the SCRIPT source root")
    return path


def resolve_script_path(script: str, *, source_root: Path | None = None) -> Path:
    path = resolve_script_destination(script, source_root=source_root)
    if not path.is_file():
        raise ValueError(f"SCRIPT node script does not exist: {script}")
    return path


def script_source_sha256(script: str, *, source_root: Path | None = None) -> str:
    return hashlib.sha256(
        resolve_script_path(script, source_root=source_root).read_bytes()
    ).hexdigest()


def _validate_arguments(arguments: dict[str, Any]) -> None:
    reserved = RESERVED_SCRIPT_ARGUMENTS.intersection(arguments)
    private_test_keys = {key for key in arguments if str(key).startswith("_test")}
    if reserved or private_test_keys:
        blocked = sorted(reserved | private_test_keys)
        raise ValueError(f"SCRIPT arguments contain reserved test-only keys: {blocked}")


def _validate_physics_provenance(output: ScriptOutput) -> None:
    model_info = output.data.get("model_info")
    if not isinstance(model_info, dict):
        raise ValueError(
            "physics_gpu SCRIPT output must include data.model_info provenance. "
            "Example: data.model_info={name, version, checkpoint='... sha256:<64 hex>', "
            "head, dtype, device}."
        )
    missing = [
        field
        for field in ("name", "version", "head", "dtype", "device")
        if not isinstance(model_info.get(field), str) or not model_info[field].strip()
    ]
    if missing:
        raise ValueError(
            "physics_gpu SCRIPT data.model_info has missing or empty provenance fields: "
            f"{missing}. Required fields are name, version, head, dtype, and device."
        )
    checkpoint = model_info.get("checkpoint")
    if not isinstance(checkpoint, str) or not re.search(
        r"sha256:[0-9a-fA-F]{64}(?:\s|$)", checkpoint
    ):
        raise ValueError(
            "physics_gpu SCRIPT data.model_info.checkpoint must include an exact sha256 "
            "in the form 'checkpoint-name sha256:<64 hex>'"
        )


def _claim_dft_attempt(script: str, arguments: dict[str, Any]) -> None:
    """Fail closed if Modal replays the same immutable DFT artifact target."""
    artifact_dir_value = arguments.get("artifact_dir")
    if not isinstance(artifact_dir_value, str):
        raise ValueError("dft_gpu SCRIPT requires an absolute artifact_dir")
    artifact_dir = resolve_dft_artifact_dir(artifact_dir_value)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    claim_path = artifact_dir / "attempt.json"
    claim = {
        "script": script,
        "started_unix_s": time.time(),
        "pid": os.getpid(),
    }
    try:
        with claim_path.open("x") as handle:
            json.dump(claim, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RuntimeError(
            "Refusing to replay a dft_gpu node against an existing immutable artifact target: "
            f"{artifact_dir}. Use a new run-specific artifact_dir."
        ) from exc


def _build_script_command(
    *,
    execution_profile: ScriptExecutionProfile,
    script_path: Path,
    input_path: Path,
    output_path: Path,
    arguments: dict[str, Any],
) -> list[str]:
    if execution_profile != "dft_gpu":
        return ["uv", "run", "--script", str(script_path), str(input_path), str(output_path)]

    mpi_ranks = int(arguments.get("mpi_ranks", 1))
    if mpi_ranks < 1 or mpi_ranks > 8:
        raise ValueError("dft_gpu mpi_ranks must be between 1 and 8")
    if mpi_ranks == 1:
        return ["python", "-u", str(script_path), str(input_path), str(output_path)]
    return [
        "mpiexec",
        "--allow-run-as-root",
        "--oversubscribe",
        "--bind-to",
        "none",
        "--mca",
        "pml",
        "ob1",
        "--mca",
        "btl",
        "self,vader,tcp",
        "-n",
        str(mpi_ranks),
        "gpaw",
        "python",
        "-u",
        str(script_path),
        str(input_path),
        str(output_path),
    ]


def _validate_output_metrics(
    output: ScriptOutput,
    output_metrics: dict[str, str],
) -> None:
    actual_metrics = set(output.metrics)
    declared_metrics = set(output_metrics)
    if actual_metrics != declared_metrics:
        raise ValueError(
            "SCRIPT node metrics do not match the DAG contract: "
            f"declared={sorted(declared_metrics)}, actual={sorted(actual_metrics)}"
        )
    for name, expected_unit in output_metrics.items():
        actual_unit = output.metrics[name].unit
        if actual_unit != expected_unit:
            raise ValueError(
                f"SCRIPT node metric '{name}' declared unit '{expected_unit}' "
                f"but emitted '{actual_unit}'"
            )


def run_script_node(
    *,
    script: str,
    inputs: dict[str, Any],
    arguments: dict[str, Any],
    output_metrics: dict[str, str],
    timeout_seconds: int,
    execution_profile: ScriptExecutionProfile = "analysis",
    source_root: Path | None = None,
) -> ScriptResult:
    _validate_arguments(arguments)
    if execution_profile == "dft_gpu":
        _claim_dft_attempt(script, arguments)
    script_path = resolve_script_path(script, source_root=source_root)
    payload = {
        "contract_version": "v1",
        "inputs": to_jsonable(inputs),
        "arguments": arguments,
    }

    with tempfile.TemporaryDirectory(prefix="atomforge-script-") as temp_dir:
        input_path = Path(temp_dir) / "input.json"
        output_path = Path(temp_dir) / "output.json"
        input_path.write_text(json.dumps(payload))
        env = os.environ.copy()
        repository_root = str(Path(__file__).resolve().parents[2])
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{repository_root}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else repository_root
        )
        command = _build_script_command(
            execution_profile=execution_profile,
            script_path=script_path,
            input_path=input_path,
            output_path=output_path,
            arguments=arguments,
        )
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
            # SCRIPT arguments may reference checked-in package data (for
            # example ``atomforge/data/...``).  Run from the repository root
            # rather than the immutable snapshot directory so those paths are
            # stable in local and Modal workers.
            cwd=repository_root,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise RuntimeError(f"SCRIPT node exited with code {completed.returncode}: {detail}")
        if not output_path.is_file():
            raise RuntimeError("SCRIPT node did not create its declared output file")
        output = ScriptOutput.model_validate_json(output_path.read_text())

    _validate_output_metrics(output, output_metrics)

    if execution_profile == "physics_gpu":
        _validate_physics_provenance(output)

    return ScriptResult(
        **output.model_dump(),
        stdout=completed.stdout.strip()[-2000:],
        execution_profile=execution_profile,
    )
