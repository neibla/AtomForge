from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import modal
from dotenv import load_dotenv

from atomforge.contracts import ScriptExecutionProfile, SimulationMode
from atomforge.execution.evidence_repository import (
    EvidenceRepository,
    ModalVolumeAdapter,
    default_results_dir,
)
from atomforge.execution.experiment import execute_experiment
from atomforge.execution.orchestrator import BaseExecutor
from atomforge.execution.script_sources import (
    SCRIPT_SOURCE_MOUNT,
    SCRIPT_SOURCE_VOLUME_NAME,
    script_root,
)
from atomforge.schemas import (
    AtomsData,
    ExperimentSpec,
    ModelMetadata,
    ResultsGraph,
    ScriptResult,
    SimulationResult,
)

load_dotenv()

ATOMFORGE_SOURCE_ROOT = Path(__file__).resolve().parents[2]

MACE_MH1_SHA256 = "a522eb7f59c7879963d41586528f4980baf33e086c94aa92e3eafdeccad3be47"
UV_VERSION = "0.11.21"
MACE_MODEL_PATH = "/root/.cache/mace/mace-mh-1.model"
MACE_MODEL_URL = (
    "https://github.com/ACEsuit/mace-foundations/releases/download/mace_mh_1/mace-mh-1.model"
)
MACE_MP0_MEDIUM_SHA256 = "01bfe22100139f424713cf921144e5509cbe353d67aa9fa1be9c6e1e0ed35845"
MACE_MP0_MEDIUM_MODEL_PATH = "/root/.cache/mace/2023-12-03-mace-128-L1_epoch-199.model"
MACE_MP0_MEDIUM_MODEL_URL = (
    "https://github.com/ACEsuit/mace-foundations/releases/download/"
    "mace_mp_0/2023-12-03-mace-128-L1_epoch-199.model"
)

RESULTS_DIR = default_results_dir()

results_volume = modal.Volume.from_name("atomforge-results-v2", create_if_missing=True)
script_source_volume = modal.Volume.from_name(SCRIPT_SOURCE_VOLUME_NAME, create_if_missing=True)
script_source_readonly_volume = script_source_volume.with_mount_options(read_only=True)
benchmark_cache_volume = modal.Volume.from_name(
    "atomforge-benchmark-cache-v1", create_if_missing=True
)
dft_artifact_volume = modal.Volume.from_name("atomforge-dft-artifacts-v1", create_if_missing=True)
node_cache = modal.Dict.from_name("atomforge-node-cache-v03", create_if_missing=True)
runtime_secret = modal.Secret.from_dict({"MP_API_KEY": os.environ.get("MP_API_KEY", "")})
results_repository = EvidenceRepository(ModalVolumeAdapter(RESULTS_DIR, results_volume))


def _reload_script_sources() -> None:
    """Refresh a reused Modal container's view of committed immutable sources."""
    if not modal.is_local():
        script_source_volume.reload()


API_IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(f"uv=={UV_VERSION}")
    .add_local_file("pyproject.toml", remote_path="/root/pyproject.toml", copy=True)
    .add_local_file("uv.lock", remote_path="/root/uv.lock", copy=True)
    .uv_sync(extras=["orchestrator"])
    .add_local_dir(
        str(ATOMFORGE_SOURCE_ROOT),
        remote_path="/root/atomforge",
        copy=True,
    )
)
SCRIPT_IMAGE = API_IMAGE
PHYSICS_IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(f"uv=={UV_VERSION}")
    .apt_install("wget", "git")
    .add_local_file("pyproject.toml", remote_path="/root/pyproject.toml", copy=True)
    .add_local_file("uv.lock", remote_path="/root/uv.lock", copy=True)
    .uv_sync(extras=["physics"])
    .run_commands(
        "mkdir -p /root/.cache/mace",
        f"wget {MACE_MODEL_URL} -O {MACE_MODEL_PATH}",
        f"echo '{MACE_MH1_SHA256}  {MACE_MODEL_PATH}' | sha256sum -c -",
        f"wget {MACE_MP0_MEDIUM_MODEL_URL} -O {MACE_MP0_MEDIUM_MODEL_PATH}",
        f"echo '{MACE_MP0_MEDIUM_SHA256}  {MACE_MP0_MEDIUM_MODEL_PATH}' | sha256sum -c -",
    )
    .add_local_dir(
        str(ATOMFORGE_SOURCE_ROOT),
        remote_path="/root/atomforge",
        copy=True,
    )
)
PHYSICS_GPU_SCRIPT_IMAGE = PHYSICS_IMAGE.run_commands(
    "uv sync --script /root/atomforge/node_scripts/berger_vacancy_mattersim.py"
)
DFT_IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(f"uv=={UV_VERSION}")
    .apt_install("cp2k")
    .add_local_file("pyproject.toml", remote_path="/root/pyproject.toml", copy=True)
    .add_local_file("uv.lock", remote_path="/root/uv.lock", copy=True)
    .uv_sync()
    .uv_pip_install("ase==3.28.0")
    .add_local_dir(
        str(ATOMFORGE_SOURCE_ROOT),
        remote_path="/root/atomforge",
        copy=True,
    )
)
GPAW_GPU_IMAGE = (
    modal.Image.from_registry(
        "nvidia/cuda:12.9.1-devel-ubuntu22.04",
        add_python="3.12",
    )
    .apt_install(
        "build-essential",
        "git",
        "libfftw3-dev",
        "libopenblas-dev",
        "libscalapack-openmpi-dev",
        "libxc-dev",
        "openmpi-bin",
        "libopenmpi-dev",
    )
    .pip_install(
        "ase==3.29.0",
        "cupy-cuda12x",
        "numpy<3",
        "scipy",
        "python-dotenv",
        "pydantic>=2.9.2",
        "simpleeval==1.0.3",
    )
    .add_local_file(
        "atomforge/gpaw_siteconfig.py",
        remote_path="/root/gpaw_siteconfig.py",
        copy=True,
    )
    .env({"GPAW_CONFIG": "/root/gpaw_siteconfig.py"})
    .run_commands(
        "git clone --depth 1 --branch 26.7.0 https://gitlab.com/gpaw/gpaw.git /tmp/gpaw-src",
        "python -m pip install /tmp/gpaw-src",
    )
    .run_commands(
        "mkdir -p /root/gpaw-setups",
        "yes | gpaw install-data --gpaw --version=24.11.0 /root/gpaw-setups",
        (
            "python -c 'import ase, gpaw, pydantic, simpleeval; "
            "from gpaw.mpi import world; "
            "print(ase.__version__, gpaw.__version__, world.backend)'"
        ),
    )
    .env(
        {
            "GPAW_SETUP_PATH": "/root/gpaw-setups",
            "GPAW_USE_GPUS": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "BLIS_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "OMP_DYNAMIC": "FALSE",
        }
    )
    .add_local_dir(
        str(ATOMFORGE_SOURCE_ROOT),
        remote_path="/root/atomforge",
        copy=True,
    )
)


@dataclass(frozen=True)
class ScriptExecutionProfilePolicy:
    """One source of truth for Modal script safety and resource policy."""

    name: ScriptExecutionProfile
    image: Any
    retries: int
    timeout_seconds: int
    max_containers: int
    gpu: str | None = None
    cpu: int | None = None
    memory_mb: int | None = None
    artifact_mount: str | None = None
    artifact_volume: Any | None = None

    @property
    def volumes(self) -> dict[str, Any]:
        volumes = {SCRIPT_SOURCE_MOUNT: script_source_readonly_volume}
        if self.artifact_mount is None or self.artifact_volume is None:
            return volumes
        volumes[self.artifact_mount] = self.artifact_volume
        return volumes


ANALYSIS_SCRIPT_PROFILE = ScriptExecutionProfilePolicy(
    name="analysis",
    image=SCRIPT_IMAGE,
    retries=0,
    timeout_seconds=3600,
    max_containers=10,
)
PHYSICS_GPU_SCRIPT_PROFILE = ScriptExecutionProfilePolicy(
    name="physics_gpu",
    image=PHYSICS_GPU_SCRIPT_IMAGE,
    retries=0,
    timeout_seconds=3600,
    max_containers=4,
    gpu="T4",
    artifact_mount="/benchmark-cache",
    artifact_volume=benchmark_cache_volume,
)
DFT_CPU_SCRIPT_PROFILE = ScriptExecutionProfilePolicy(
    name="dft_cpu",
    image=DFT_IMAGE,
    retries=0,
    timeout_seconds=7200,
    max_containers=2,
    cpu=64,
    memory_mb=131072,
    artifact_mount="/dft-artifacts",
    artifact_volume=dft_artifact_volume,
)
DFT_GPU_SCRIPT_PROFILE = ScriptExecutionProfilePolicy(
    name="dft_gpu",
    image=GPAW_GPU_IMAGE,
    retries=0,
    timeout_seconds=7200,
    max_containers=1,
    gpu="H100",
    cpu=1,
    memory_mb=65536,
    artifact_mount="/dft-artifacts",
    artifact_volume=dft_artifact_volume,
)
SCRIPT_EXECUTION_PROFILES = {
    profile.name: profile
    for profile in (
        ANALYSIS_SCRIPT_PROFILE,
        PHYSICS_GPU_SCRIPT_PROFILE,
        DFT_CPU_SCRIPT_PROFILE,
        DFT_GPU_SCRIPT_PROFILE,
    )
}


async def _run_profile_script(
    policy: ScriptExecutionProfilePolicy,
    *,
    inputs: dict[str, Any],
    script: str,
    arguments: dict[str, Any],
    output_metrics: dict[str, str],
    timeout_seconds: int,
    execution_profile: ScriptExecutionProfile,
    script_snapshot_id: str,
) -> ScriptResult:
    _reload_script_sources()
    source_root = script_root(script_snapshot_id)
    if not source_root.is_dir():
        raise ValueError(f"SCRIPT snapshot is unavailable: {script_snapshot_id}")
    if execution_profile != policy.name:
        raise ValueError(f"Worker profile {policy.name!r} cannot execute {execution_profile!r}")
    if timeout_seconds > policy.timeout_seconds:
        raise ValueError(
            f"Requested timeout {timeout_seconds}s exceeds {policy.name} "
            f"profile limit {policy.timeout_seconds}s"
        )
    from atomforge.execution.script_runner import run_script_node

    result = run_script_node(
        script=script,
        inputs=inputs,
        arguments=arguments,
        output_metrics=output_metrics,
        timeout_seconds=timeout_seconds,
        execution_profile=execution_profile,
        source_root=source_root,
    )
    if policy.artifact_volume is not None:
        await policy.artifact_volume.commit.aio()
    return result


workers_app = modal.App("atomforge-workers")
app = workers_app


async def _commit_results() -> None:
    await results_repository.commit()


@workers_app.cls(
    image=PHYSICS_IMAGE,
    secrets=[runtime_secret],
    retries=0,
    timeout=3600,
    max_containers=10,
)
class PhysicsWorker:
    @modal.enter()
    def setup(self):
        import torch
        from mace.calculators import MACECalculator

        from atomforge.simulator import SimulationEngine

        device = "cuda" if torch.cuda.is_available() else "cpu"
        calculator = MACECalculator(
            model_paths=MACE_MODEL_PATH,
            device=device,
            default_dtype="float64",
            compute_stress=True,
            head="matpes_r2scan",
        )
        self.engine = SimulationEngine(device=device, calculator=calculator)

    @modal.method()
    async def simulate(
        self,
        atoms_data: AtomsData,
        mode: SimulationMode,
        params: dict,
        seed: int = 0,
    ) -> SimulationResult:
        return self.engine.run(atoms_data, mode, params, seed)

    @modal.method()
    async def fetch(
        self,
        element: str | None = None,
        structure_path: str | None = None,
    ) -> AtomsData:
        if structure_path:
            from ase.io import read

            relative = Path(structure_path)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("structure_path must be a relative safe path")
            input_path = Path("/root/atomforge/data/lunar_regolith") / relative
            if not input_path.is_file():
                raise FileNotFoundError(f"Structure file not found: {structure_path}")
            atoms = read(input_path, index=0)
            return AtomsData(
                symbols=atoms.get_chemical_symbols(),
                positions=atoms.get_positions().tolist(),
                cell=atoms.get_cell().tolist(),
                pbc=tuple(bool(value) for value in atoms.get_pbc()),
                metadata={
                    "source": "lunar-regolith-benchmark-repository",
                    "structure_path": structure_path,
                    "input_atoms": len(atoms),
                },
            )
        if not element:
            raise ValueError("fetch requires element or structure_path")
        from atomforge.materials_project import fetch_structure

        result = fetch_structure(element)
        return AtomsData(
            symbols=result.atoms.get_chemical_symbols(),
            positions=result.atoms.get_positions().tolist(),
            cell=result.atoms.get_cell().tolist(),
            pbc=tuple(bool(value) for value in result.atoms.get_pbc()),
            dft_energy=result.dft_energy_per_atom,
            metadata=result.metadata,
        )

    @modal.method()
    async def alloy(
        self,
        parent: AtomsData,
        supercell: list[int],
        dopants: dict[str, float],
        seed: int = 0,
        vacancy: bool = False,
    ) -> AtomsData:
        from ase import Atoms

        from atomforge.structure_transforms import make_alloy_supercell, make_vacancy_supercell
        from atomforge.structures import StructureRecord

        atoms = Atoms(
            symbols=parent.symbols,
            positions=parent.positions,
            cell=parent.cell,
            pbc=parent.pbc,
        )
        record = StructureRecord(
            material_id="tmp",
            formula="Tmp",
            atoms=atoms,
            dft_energy_per_atom=parent.dft_energy or 0,
            dft_forces=[],
            metadata=parent.metadata or {},
        )
        transformed = (
            make_vacancy_supercell(record, supercell=tuple(supercell))
            if vacancy
            else make_alloy_supercell(
                record,
                supercell=tuple(supercell),
                dopants=dopants,
                seed=seed,
            )
        )
        return AtomsData(
            symbols=transformed.atoms.get_chemical_symbols(),
            positions=transformed.atoms.get_positions().tolist(),
            cell=transformed.atoms.get_cell().tolist(),
            pbc=tuple(bool(value) for value in transformed.atoms.get_pbc()),
            metadata=transformed.metadata,
        )


def _worker_options(n_atoms: int) -> dict[str, Any]:
    if n_atoms < 50:
        return {"gpu": None, "cpu": 8, "memory": 16384}
    if n_atoms < 500:
        return {"gpu": "T4", "cpu": 4, "memory": 8192}
    if n_atoms < 10000:
        return {"gpu": "A100-40GB", "cpu": 8, "memory": 32768}
    return {"gpu": "A100-80GB", "cpu": 12, "memory": 65536}


@workers_app.cls(
    image=ANALYSIS_SCRIPT_PROFILE.image,
    env={"ATOMFORGE_SCRIPT_ROOT": SCRIPT_SOURCE_MOUNT},
    volumes=ANALYSIS_SCRIPT_PROFILE.volumes,
    retries=ANALYSIS_SCRIPT_PROFILE.retries,
    timeout=ANALYSIS_SCRIPT_PROFILE.timeout_seconds,
    max_containers=ANALYSIS_SCRIPT_PROFILE.max_containers,
)
class ScriptWorker:
    @modal.method()
    async def run(
        self,
        inputs: dict[str, Any],
        script: str,
        arguments: dict[str, Any],
        output_metrics: dict[str, str],
        timeout_seconds: int,
        execution_profile: ScriptExecutionProfile = "analysis",
        script_snapshot_id: str = "",
    ) -> ScriptResult:
        return await _run_profile_script(
            ANALYSIS_SCRIPT_PROFILE,
            inputs=inputs,
            script=script,
            arguments=arguments,
            output_metrics=output_metrics,
            timeout_seconds=timeout_seconds,
            execution_profile=execution_profile,
            script_snapshot_id=script_snapshot_id,
        )


@workers_app.cls(
    image=PHYSICS_GPU_SCRIPT_PROFILE.image,
    env={"ATOMFORGE_SCRIPT_ROOT": SCRIPT_SOURCE_MOUNT},
    gpu=PHYSICS_GPU_SCRIPT_PROFILE.gpu,
    volumes=PHYSICS_GPU_SCRIPT_PROFILE.volumes,
    retries=PHYSICS_GPU_SCRIPT_PROFILE.retries,
    timeout=PHYSICS_GPU_SCRIPT_PROFILE.timeout_seconds,
    max_containers=PHYSICS_GPU_SCRIPT_PROFILE.max_containers,
)
class PhysicsGpuScriptWorker:
    @modal.method()
    async def run(
        self,
        inputs: dict[str, Any],
        script: str,
        arguments: dict[str, Any],
        output_metrics: dict[str, str],
        timeout_seconds: int,
        execution_profile: ScriptExecutionProfile = "physics_gpu",
        script_snapshot_id: str = "",
    ) -> ScriptResult:
        return await _run_profile_script(
            PHYSICS_GPU_SCRIPT_PROFILE,
            inputs=inputs,
            script=script,
            arguments=arguments,
            output_metrics=output_metrics,
            timeout_seconds=timeout_seconds,
            execution_profile=execution_profile,
            script_snapshot_id=script_snapshot_id,
        )


@workers_app.cls(
    image=DFT_CPU_SCRIPT_PROFILE.image,
    env={"ATOMFORGE_SCRIPT_ROOT": SCRIPT_SOURCE_MOUNT},
    cpu=DFT_CPU_SCRIPT_PROFILE.cpu,
    memory=DFT_CPU_SCRIPT_PROFILE.memory_mb,
    volumes=DFT_CPU_SCRIPT_PROFILE.volumes,
    retries=DFT_CPU_SCRIPT_PROFILE.retries,
    timeout=DFT_CPU_SCRIPT_PROFILE.timeout_seconds,
    max_containers=DFT_CPU_SCRIPT_PROFILE.max_containers,
)
class DftCpuScriptWorker:
    @modal.method()
    async def run(
        self,
        inputs: dict[str, Any],
        script: str,
        arguments: dict[str, Any],
        output_metrics: dict[str, str],
        timeout_seconds: int,
        execution_profile: ScriptExecutionProfile = "dft_cpu",
        script_snapshot_id: str = "",
    ) -> ScriptResult:
        return await _run_profile_script(
            DFT_CPU_SCRIPT_PROFILE,
            inputs=inputs,
            script=script,
            arguments=arguments,
            output_metrics=output_metrics,
            timeout_seconds=timeout_seconds,
            execution_profile=execution_profile,
            script_snapshot_id=script_snapshot_id,
        )


@workers_app.cls(
    image=DFT_GPU_SCRIPT_PROFILE.image,
    env={"ATOMFORGE_SCRIPT_ROOT": SCRIPT_SOURCE_MOUNT},
    gpu=DFT_GPU_SCRIPT_PROFILE.gpu,
    cpu=DFT_GPU_SCRIPT_PROFILE.cpu,
    memory=DFT_GPU_SCRIPT_PROFILE.memory_mb,
    volumes=DFT_GPU_SCRIPT_PROFILE.volumes,
    retries=DFT_GPU_SCRIPT_PROFILE.retries,
    timeout=DFT_GPU_SCRIPT_PROFILE.timeout_seconds,
    max_containers=DFT_GPU_SCRIPT_PROFILE.max_containers,
)
class DftGpuScriptWorker:
    @modal.method()
    async def run(
        self,
        inputs: dict[str, Any],
        script: str,
        arguments: dict[str, Any],
        output_metrics: dict[str, str],
        timeout_seconds: int,
        execution_profile: ScriptExecutionProfile = "dft_gpu",
        script_snapshot_id: str = "",
    ) -> ScriptResult:
        return await _run_profile_script(
            DFT_GPU_SCRIPT_PROFILE,
            inputs=inputs,
            script=script,
            arguments=arguments,
            output_metrics=output_metrics,
            timeout_seconds=timeout_seconds,
            execution_profile=execution_profile,
            script_snapshot_id=script_snapshot_id,
        )


SCRIPT_WORKERS = {
    "analysis": ScriptWorker,
    "physics_gpu": PhysicsGpuScriptWorker,
    "dft_cpu": DftCpuScriptWorker,
    "dft_gpu": DftGpuScriptWorker,
}


class ModalExecutor(BaseExecutor):
    """Modal implementation of the physics executor."""

    def __init__(self, script_snapshot_id: str):
        self.script_snapshot_id = script_snapshot_id

    def model_metadata(self) -> ModelMetadata:
        return ModelMetadata(
            name="MACE-MH-1",
            version="mace_mh_1",
            checkpoint="mace-mh-1.model",
            checkpoint_sha256=MACE_MH1_SHA256,
            head="matpes_r2scan",
            dtype="float64",
            hardware="routed by atom count",
            device="auto",
        )

    async def fetch(
        self,
        element: str | None = None,
        structure_path: str | None = None,
    ) -> AtomsData:
        return await PhysicsWorker().fetch.remote.aio(element, structure_path)

    async def alloy(
        self,
        parent: AtomsData,
        supercell: list[int],
        dopants: dict[str, float],
        seed: int = 0,
        vacancy: bool = False,
    ) -> AtomsData:
        return await PhysicsWorker().alloy.remote.aio(
            parent,
            supercell,
            dopants,
            seed,
            vacancy,
        )

    async def simulate(
        self,
        atoms_data: AtomsData,
        mode: SimulationMode,
        params: dict,
        seed: int = 0,
    ) -> SimulationResult:
        resources = _worker_options(len(atoms_data.symbols))
        worker = PhysicsWorker.with_options(**resources)
        return await worker().simulate.remote.aio(atoms_data, mode, params, seed)

    async def script(
        self,
        inputs: dict[str, Any],
        script: str,
        arguments: dict[str, Any],
        output_metrics: dict[str, str],
        timeout_seconds: int,
        execution_profile: ScriptExecutionProfile,
    ) -> ScriptResult:
        policy = SCRIPT_EXECUTION_PROFILES[execution_profile]
        worker = SCRIPT_WORKERS[policy.name]
        return await worker().run.remote.aio(
            inputs,
            script,
            arguments,
            output_metrics,
            timeout_seconds,
            execution_profile,
            self.script_snapshot_id,
        )


@workers_app.cls(
    image=API_IMAGE,
    env={"ATOMFORGE_SCRIPT_ROOT": SCRIPT_SOURCE_MOUNT},
    secrets=[runtime_secret],
    volumes={"/results": results_volume, SCRIPT_SOURCE_MOUNT: script_source_readonly_volume},
    timeout=3600,
    max_containers=1,
)
class Orchestrator:
    @modal.method()
    async def execute(self, spec: ExperimentSpec) -> ResultsGraph:
        results_repository.reload()
        _reload_script_sources()
        return await execute_experiment(
            spec,
            ModalExecutor(spec.script_snapshot_id),
            results_repository,
            node_cache=node_cache,
            script_source_root=(
                script_root(spec.script_snapshot_id) if spec.script_snapshot_id else None
            ),
            require_script_snapshot=True,
            commit=_commit_results,
        )
