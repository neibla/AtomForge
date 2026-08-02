# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "ase==3.23.0",
#   "mattersim==1.0.0rc9",
#   "numpy==1.26.4",
#   "phonopy==4.3.1",
#   "psutil==6.1.1",
#   "pydantic==2.9.2",
#   "pymatgen==2024.4.13",
#   "setuptools<81",
#   "torch==2.2.0",
# ]
# ///

"""Profile a deterministic scale pilot of the Han-Cheng phonon benchmark."""

from __future__ import annotations

import random
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import numpy as np
import psutil
from pydantic import BaseModel, ConfigDict

from atomforge.compute_scaling import partition_selection
from atomforge.node_scripts.mattersim_phonon_subset import (
    DATA_ARCHIVE_SHA256,
    DATA_URL,
    calculate_case,
    parse_supercell_matrix,
    sha256,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["v1"]
    inputs: dict[str, Any]
    arguments: dict[str, Any]


class Metric(BaseModel):
    val: float
    unit: str


class Output(BaseModel):
    contract_version: Literal["v1"] = "v1"
    metrics: dict[str, Metric]
    data: dict[str, Any]
    visualizations: list[dict[str, Any]]


class ResourceSampler:
    """Low-frequency utilization sampling around the complete worker workload."""

    def __init__(self, interval_s: float = 1.0) -> None:
        self.interval_s = interval_s
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._process = psutil.Process()
        psutil.cpu_percent(interval=None)
        self._process.cpu_percent(interval=None)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(self.interval_s * 2, 2.0))

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = {
                "host_cpu_pct": float(psutil.cpu_percent(interval=None)),
                "process_cpu_pct": float(self._process.cpu_percent(interval=None)),
            }
            completed = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                values = completed.stdout.strip().splitlines()[0].split(",")
                if len(values) == 3:
                    try:
                        sample.update(
                            {
                                "gpu_util_pct": float(values[0].strip()),
                                "gpu_memory_used_MiB": float(values[1].strip()),
                                "gpu_memory_total_MiB": float(values[2].strip()),
                            }
                        )
                    except ValueError:
                        pass
            self.samples.append(sample)
            self._stop.wait(self.interval_s)

    @staticmethod
    def _summary(values: list[float]) -> dict[str, float]:
        if not values:
            return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        return {
            "mean": float(statistics.fmean(values)),
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
            "max": float(max(values)),
        }

    def summary(self) -> dict[str, Any]:
        def values(name: str) -> list[float]:
            return [
                float(sample[name])
                for sample in self.samples
                if isinstance(sample.get(name), int | float)
            ]

        return {
            "sample_count": len(self.samples),
            "interval_s": self.interval_s,
            "gpu_util_pct": self._summary(values("gpu_util_pct")),
            "gpu_memory_used_MiB": self._summary(values("gpu_memory_used_MiB")),
            "gpu_memory_total_MiB": max(values("gpu_memory_total_MiB"), default=0.0),
            "host_cpu_pct": self._summary(values("host_cpu_pct")),
            "process_cpu_pct": self._summary(values("process_cpu_pct")),
        }


def _gpu_name() -> str:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name",
            "--format=csv,noheader",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else "unknown"


def _database_cases(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        directory
        for directory in sorted(root.iterdir())
        if directory.is_dir()
        and (directory / "POSCAR-unitcell").is_file()
        and (directory / "FORCE_SETS").is_file()
        and (directory / "mesh.conf").is_file()
    ]


def download_database(destination: Path, cache_dir: Path | None = None) -> tuple[Path, int, bool]:
    archive = destination / "phonon_benchmark_database.tar.gz"
    cached_archive = (
        cache_dir / "archives" / f"{DATA_ARCHIVE_SHA256}.tar.gz" if cache_dir is not None else None
    )
    cache_hit = (
        cached_archive is not None
        and cached_archive.is_file()
        and sha256(cached_archive) == DATA_ARCHIVE_SHA256
    )
    if cache_hit:
        shutil.copyfile(cached_archive, archive)
    else:
        urllib.request.urlretrieve(DATA_URL, archive)
    actual = sha256(archive)
    if actual != DATA_ARCHIVE_SHA256:
        raise ValueError(
            f"Zenodo archive checksum mismatch: expected {DATA_ARCHIVE_SHA256}, got {actual}"
        )
    if cached_archive is not None and not cache_hit:
        cached_archive.parent.mkdir(parents=True, exist_ok=True)
        temporary_cache_archive = cached_archive.with_suffix(".tmp")
        shutil.copyfile(archive, temporary_cache_archive)
        temporary_cache_archive.replace(cached_archive)
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        for member in members:
            if member.islnk() or member.issym() or ".." in Path(member.name).parts:
                raise ValueError(f"Unsafe member in benchmark archive: {member.name}")
        source.extractall(destination, members=members, filter="data")
    root = destination / "phonon_benchmark_database"
    cases = _database_cases(root)
    return root, len(cases), cache_hit


def select_cases(
    root: Path, sample_size: int, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from ase.io import read

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    excluded: list[dict[str, Any]] = []
    for directory in sorted(root.iterdir()):
        poscar = directory / "POSCAR-unitcell"
        if not directory.is_dir() or not poscar.is_file():
            continue
        if not (directory / "FORCE_SETS").is_file() or not (directory / "mesh.conf").is_file():
            continue
        atoms = read(poscar, format="vasp")
        supercell_matrix = parse_supercell_matrix(directory / "mesh.conf")
        expected_supercell_atoms = len(atoms) * int(np.prod(supercell_matrix))
        force_sets_header = (directory / "FORCE_SETS").read_text(encoding="utf-8").splitlines()
        if not force_sets_header:
            raise ValueError(f"Empty FORCE_SETS file: {directory / 'FORCE_SETS'}")
        force_sets_supercell_atoms = int(force_sets_header[0].strip())
        if force_sets_supercell_atoms != expected_supercell_atoms:
            excluded.append(
                {
                    "mp_id": directory.name.split("-Cheng23", 1)[0],
                    "directory": directory.name,
                    "unit_cell_atoms": len(atoms),
                    "supercell_matrix": supercell_matrix,
                    "expected_supercell_atoms": expected_supercell_atoms,
                    "force_sets_supercell_atoms": force_sets_supercell_atoms,
                    "reason": ("FORCE_SETS atom count does not match unit-cell atoms × DIM"),
                }
            )
            continue
        groups[len(atoms)].append(
            {
                "directory": directory,
                "formula": atoms.get_chemical_formula(mode="metal"),
                "unit_cell_atoms": len(atoms),
                "mp_id": directory.name.split("-Cheng23", 1)[0],
            }
        )
    population = sum(len(group) for group in groups.values())
    if sample_size < 1 or sample_size > population:
        raise ValueError(f"sample_size must be between 1 and released population {population}")
    rng = random.Random(seed)
    for group in groups.values():
        rng.shuffle(group)
    ordered = [case for atom_count in sorted(groups) for case in groups[atom_count]]
    # Select one case from the midpoint of each equally populated size bin.
    # This covers the released population's complexity distribution instead of
    # favoring the smallest distinct unit-cell sizes.
    selected = [
        ordered[min(population - 1, int((index + 0.5) * population / sample_size))]
        for index in range(sample_size)
    ]
    if len(selected) != sample_size:
        raise RuntimeError(f"Deterministic sampler selected {len(selected)} of {sample_size} cases")
    return selected, excluded


def select_requested_cases(
    root: Path, requested_ids: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select explicit Materials Project IDs for a protocol diagnostic."""
    from ase.io import read

    wanted = {str(value) for value in requested_ids}
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for directory in sorted(root.iterdir()):
        mp_id = directory.name.split("-Cheng23", 1)[0]
        if mp_id not in wanted:
            continue
        poscar = directory / "POSCAR-unitcell"
        if not all((directory / name).is_file() for name in ("FORCE_SETS", "mesh.conf")):
            raise ValueError(f"Requested case is missing benchmark inputs: {directory}")
        atoms = read(poscar, format="vasp")
        expected = len(atoms) * int(np.prod(parse_supercell_matrix(directory / "mesh.conf")))
        actual = int((directory / "FORCE_SETS").read_text(encoding="utf-8").splitlines()[0])
        if expected != actual:
            excluded.append({"mp_id": mp_id, "reason": "FORCE_SETS atom count mismatch"})
            continue
        selected.append(
            {
                "directory": directory,
                "formula": atoms.get_chemical_formula(mode="metal"),
                "unit_cell_atoms": len(atoms),
                "mp_id": mp_id,
            }
        )
    found = {case["mp_id"] for case in selected} | {case["mp_id"] for case in excluded}
    missing = sorted(wanted - found)
    if missing:
        raise ValueError(f"Requested benchmark cases were not found: {missing}")
    return selected, excluded


def run_benchmark(arguments: dict[str, Any]) -> dict[str, Any]:
    import ase
    import mattersim
    import phonopy
    import torch
    from mattersim.forcefield.potential import MatterSimCalculator

    device = str(arguments.get("device", "cuda"))
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("MatterSim scale pilot requires an available CUDA GPU")
    sample_size = int(arguments.get("sample_size", 20))
    population_sample_size = int(arguments.get("population_sample_size", sample_size))
    shard_index = int(arguments.get("shard_index", 0))
    shard_count = int(arguments.get("shard_count", 1))
    expected_sample_size = population_sample_size // shard_count + (
        1 if shard_index < population_sample_size % shard_count else 0
    )
    if sample_size != expected_sample_size:
        raise ValueError(
            "sample_size does not match this shard's deterministic partition; "
            f"expected {expected_sample_size} for shard {shard_index}/{shard_count} "
            f"of population {population_sample_size}"
        )
    selection_seed = int(arguments.get("selection_seed", 20260723))
    fmax = float(arguments.get("relax_fmax_eV_per_A", 0.005))
    max_steps = int(arguments.get("relax_max_steps", 200))
    displacement_A = float(arguments.get("finite_displacement_A", 0.03))
    inference_batch_size = int(arguments.get("inference_batch_size", 1))
    if inference_batch_size < 1:
        raise ValueError("inference_batch_size must be at least 1")
    dataset_cache_dir = arguments.get("dataset_cache_dir")
    cache_dir = Path(str(dataset_cache_dir)) if dataset_cache_dir else None
    if cache_dir is not None:
        allowed_cache_root = Path("/benchmark-cache")
        if (
            not cache_dir.is_absolute()
            or cache_dir == allowed_cache_root
            or allowed_cache_root not in cache_dir.parents
        ):
            raise ValueError("dataset_cache_dir must be an absolute child of /benchmark-cache")

    benchmark_started = time.perf_counter()
    sampler = ResourceSampler(interval_s=1.0)
    sampler.start()
    try:
        model_started = time.perf_counter()
        calculator = MatterSimCalculator(
            load_path="MatterSim-v1.0.0-5M.pth",
            device=device,
        )
        model_load_s = time.perf_counter() - model_started
        checkpoint = (
            Path.home() / ".local" / "mattersim" / "pretrained_models" / "mattersim-v1.0.0-5M.pth"
        )
        if not checkpoint.is_file():
            raise FileNotFoundError(f"MatterSim checkpoint not found after load: {checkpoint}")
        torch.cuda.reset_peak_memory_stats()
        with tempfile.TemporaryDirectory(prefix="atomforge-phonon-pilot-") as temp:
            archive_started = time.perf_counter()
            database, archive_case_count, dataset_cache_hit = download_database(
                Path(temp), cache_dir=cache_dir
            )
            archive_setup_s = time.perf_counter() - archive_started
            inventory_started = time.perf_counter()
            requested_ids = arguments.get("case_ids")
            if requested_ids:
                population_selection, excluded_incompatible_cases = select_requested_cases(
                    database, [str(value) for value in requested_ids]
                )
            else:
                population_selection, excluded_incompatible_cases = select_cases(
                    database, population_sample_size, selection_seed
                )
            selection = partition_selection(
                population_selection,
                shard_index=shard_index,
                shard_count=shard_count,
                expected_size=sample_size,
            )
            inventory_s = time.perf_counter() - inventory_started
            cases = []
            for index, selected in enumerate(selection, start=1):
                print(
                    f"[{index}/{sample_size}] {selected['formula']} "
                    f"{selected['mp_id']} ({selected['unit_cell_atoms']} atoms)",
                    flush=True,
                )
                try:
                    case = calculate_case(
                        label=selected["formula"],
                        case_dir=selected["directory"],
                        calculator=calculator,
                        fmax=fmax,
                        max_steps=max_steps,
                        displacement_A=displacement_A,
                        inference_batch_size=inference_batch_size,
                        validate_batch_equivalence=(inference_batch_size > 1 and index == 1),
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"Phonon case failed: {selected['mp_id']} "
                        f"({selected['formula']}, "
                        f"{selected['unit_cell_atoms']} unit-cell atoms)"
                    ) from exc
                cases.append(case)
        torch.cuda.synchronize()
        wall_time_s = time.perf_counter() - benchmark_started
    finally:
        sampler.stop()

    worst_index = max(range(len(cases)), key=lambda index: cases[index]["frequency_mae_meV"])
    for index, case in enumerate(cases):
        if index != worst_index:
            case.pop("scatter_rows", None)
            case.pop("structure", None)

    return {
        "cases": cases,
        "sample_size": sample_size,
        "population_sample_size": population_sample_size,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "selection_seed": selection_seed,
        "inference_batch_size": inference_batch_size,
        "selected_cases": {item["mp_id"]: item["directory"].name for item in selection},
        "selected_unit_cell_atom_counts": [item["unit_cell_atoms"] for item in selection],
        "excluded_incompatible_cases": excluded_incompatible_cases,
        "archive_case_count": archive_case_count,
        "dataset_cache_hit": dataset_cache_hit,
        "checkpoint_sha256": sha256(checkpoint),
        "checkpoint_name": checkpoint.name,
        "device": device,
        "gpu_name": _gpu_name(),
        "versions": {
            "mattersim": mattersim.__version__,
            "ase": ase.__version__,
            "phonopy": phonopy.__version__,
            "torch": torch.__version__,
        },
        "timing_s": {
            "wall": wall_time_s,
            "model_load": model_load_s,
            "archive_download_extract": archive_setup_s,
            "inventory_and_selection": inventory_s,
        },
        "resource_profile": sampler.summary(),
        "torch_peak_memory_MiB": float(torch.cuda.max_memory_allocated() / 2**20),
    }


def analyse(results: dict[str, Any], arguments: dict[str, Any]) -> Output:
    cases = results["cases"]
    expected_size = int(arguments.get("sample_size", 20))
    force_threshold = float(arguments.get("relax_fmax_eV_per_A", 0.005))
    mean_threshold = float(arguments.get("mean_frequency_mae_tolerance_meV", 2.0))
    worst_threshold = float(arguments.get("max_material_mae_tolerance_meV", 5.0))
    imaginary_threshold = float(
        arguments.get("significant_imaginary_frequency_threshold_meV", -1.0)
    )
    inference_batch_size = int(results.get("inference_batch_size", 1))
    batch_equivalence_tolerance = float(arguments.get("batch_equivalence_tolerance_eV_per_A", 1e-5))
    batch_equivalence_deltas = [
        float(case["batch_equivalence_max_force_delta_eV_per_A"])
        for case in cases
        if case.get("batch_equivalence_max_force_delta_eV_per_A") is not None
    ]
    batch_equivalence_max_delta = max(batch_equivalence_deltas, default=0.0)
    batch_equivalence_passed = inference_batch_size == 1 or (
        len(batch_equivalence_deltas) == 1
        and batch_equivalence_max_delta <= batch_equivalence_tolerance
    )
    mean_mae = float(statistics.fmean(case["frequency_mae_meV"] for case in cases))
    median_mae = float(statistics.median(case["frequency_mae_meV"] for case in cases))
    worst_mae = float(max(case["frequency_mae_meV"] for case in cases))
    max_force = float(max(case["max_force_eV_per_A"] for case in cases))
    imaginary_materials = sum(case["significant_imaginary_modes"] > 0 for case in cases)
    dft_imaginary_materials = sum(
        case.get("dft_significant_imaginary_modes", 0) > 0 for case in cases
    )
    completed = len(cases) == expected_size
    numerical_quality = (
        completed
        and all(case["optimizer_converged"] for case in cases)
        and max_force <= force_threshold * 1.001
    )
    profile = results["resource_profile"]
    telemetry_present = (
        profile["sample_count"] >= 5
        and profile["gpu_util_pct"]["max"] > 0
        and profile["gpu_memory_total_MiB"] > 0
    )
    case_times = [case["timing_s"]["total"] for case in cases]
    wall_time = float(results["timing_s"]["wall"])
    throughput = len(cases) / wall_time * 60 if wall_time > 0 else 0.0
    gpu_mean = float(profile["gpu_util_pct"]["mean"])
    gpu_p95 = float(profile["gpu_util_pct"]["p95"])
    gpu_memory_peak = max(
        float(profile["gpu_memory_used_MiB"]["max"]),
        float(results["torch_peak_memory_MiB"]),
    )
    gpu_memory_total = float(profile["gpu_memory_total_MiB"])
    gpu_memory_fraction = gpu_memory_peak / gpu_memory_total * 100 if gpu_memory_total > 0 else 0.0
    process_cpu_mean = float(profile["process_cpu_pct"]["mean"])
    host_cpu_mean = float(profile["host_cpu_pct"]["mean"])
    operational_pass = (
        completed and numerical_quality and telemetry_present and batch_equivalence_passed
    )

    phase_names = (
        "relaxation",
        "dft_force_constants",
        "model_force_constants",
        "mesh_and_comparison",
    )
    phase_rows = [
        {
            "phase": phase.replace("_", " "),
            "mean_time_s": float(statistics.fmean(case["timing_s"][phase] for case in cases)),
        }
        for phase in phase_names
    ]
    dominant_phase = max(phase_rows, key=lambda row: row["mean_time_s"])
    if gpu_mean < 40 and gpu_memory_fraction < 50:
        optimization = (
            "The T4 is under-filled. Prioritize case sharding and batching displaced "
            "supercells before paying for a larger GPU."
        )
    elif gpu_mean >= 70:
        optimization = (
            "GPU inference is substantially utilized. A matched L4 benchmark is justified "
            "before selecting hardware for the 1,000-case run."
        )
    else:
        optimization = (
            "The workload is mixed CPU/GPU. First overlap or shard cases, then benchmark "
            "T4 versus L4 using identical selected cases."
        )

    metrics = {
        "pilot_case_count": Metric(val=float(len(cases)), unit="count"),
        "pilot_wall_time": Metric(val=wall_time, unit="s"),
        "pilot_mean_case_time": Metric(val=float(statistics.fmean(case_times)), unit="s"),
        "pilot_p95_case_time": Metric(val=float(np.percentile(case_times, 95)), unit="s"),
        "pilot_throughput": Metric(val=throughput, unit="cases/min"),
        "pilot_gpu_average_utilization": Metric(val=gpu_mean, unit="%"),
        "pilot_gpu_p95_utilization": Metric(val=gpu_p95, unit="%"),
        "pilot_gpu_peak_memory": Metric(val=gpu_memory_peak, unit="MiB"),
        "pilot_gpu_peak_memory_fraction": Metric(val=gpu_memory_fraction, unit="%"),
        "pilot_host_cpu_average_utilization": Metric(val=host_cpu_mean, unit="%"),
        "pilot_process_cpu_average_utilization": Metric(val=process_cpu_mean, unit="%"),
        "pilot_telemetry_sample_count": Metric(val=float(profile["sample_count"]), unit="count"),
        "pilot_mean_phonon_frequency_mae": Metric(val=mean_mae, unit="meV"),
        "pilot_median_phonon_frequency_mae": Metric(val=median_mae, unit="meV"),
        "pilot_worst_material_phonon_frequency_mae": Metric(val=worst_mae, unit="meV"),
        "pilot_max_relaxation_force": Metric(val=max_force, unit="eV/Å"),
        "pilot_materials_with_imaginary_modes": Metric(
            val=float(imaginary_materials), unit="count"
        ),
        "pilot_dft_reference_materials_with_imaginary_modes": Metric(
            val=float(dft_imaginary_materials), unit="count"
        ),
        "pilot_numerical_quality_gate_passed": Metric(
            val=1.0 if numerical_quality else 0.0, unit="dimensionless"
        ),
        "pilot_resource_telemetry_gate_passed": Metric(
            val=1.0 if telemetry_present else 0.0, unit="dimensionless"
        ),
        "pilot_operational_gate_passed": Metric(
            val=1.0 if operational_pass else 0.0, unit="dimensionless"
        ),
    }
    if inference_batch_size > 1:
        metrics.update(
            {
                "pilot_inference_batch_size": Metric(val=float(inference_batch_size), unit="count"),
                "pilot_batch_equivalence_max_force_delta": Metric(
                    val=batch_equivalence_max_delta, unit="eV/Å"
                ),
                "pilot_batch_equivalence_gate_passed": Metric(
                    val=1.0 if batch_equivalence_passed else 0.0,
                    unit="dimensionless",
                ),
            }
        )
    if arguments.get("dataset_cache_dir"):
        metrics["pilot_dataset_cache_hit"] = Metric(
            val=1.0 if results["dataset_cache_hit"] else 0.0,
            unit="dimensionless",
        )

    table_rows = [
        {
            "material": case["material"],
            "mp_id": case["materials_project_id"],
            "unit_cell_atoms": case["n_atoms_unit_cell"],
            "supercell": case["supercell"],
            "supercell_atoms": case["n_atoms_supercell"],
            "displacements": case["n_displacements"],
            "q_mesh": case["q_mesh"],
            "frequency_mae_meV": case["frequency_mae_meV"],
            "p95_error_meV": case["frequency_p95_error_meV"],
            "case_time_s": case["timing_s"]["total"],
            "requested_batch_size": case["requested_inference_batch_size"],
            "effective_batch_size": case["inference_batch_size"],
            "batch_oom_retries": case["batch_oom_retries"],
            "max_force_eV_per_A": case["max_force_eV_per_A"],
            "imaginary_modes": case["significant_imaginary_modes"],
            "dft_imaginary_modes": case.get("dft_significant_imaginary_modes", 0),
            "status": (
                "PASS"
                if case["optimizer_converged"]
                and case["max_force_eV_per_A"] <= force_threshold * 1.001
                else "REVIEW"
            ),
        }
        for case in cases
    ]
    resource_rows = [
        {"metric": "Wall time", "value": wall_time, "unit": "s"},
        {"metric": "Throughput", "value": throughput, "unit": "cases/min"},
        {"metric": "Mean GPU utilization", "value": gpu_mean, "unit": "%"},
        {"metric": "95th pct GPU utilization", "value": gpu_p95, "unit": "%"},
        {"metric": "Peak GPU memory", "value": gpu_memory_peak, "unit": "MiB"},
        {
            "metric": "Peak GPU memory fraction",
            "value": gpu_memory_fraction,
            "unit": "%",
        },
        {"metric": "Mean host CPU utilization", "value": host_cpu_mean, "unit": "%"},
        {
            "metric": "Mean process CPU utilization",
            "value": process_cpu_mean,
            "unit": "% of one core",
        },
        {
            "metric": "Model load",
            "value": results["timing_s"]["model_load"],
            "unit": "s",
        },
        {
            "metric": "Archive download/extract",
            "value": results["timing_s"]["archive_download_extract"],
            "unit": "s",
        },
    ]
    worst = max(cases, key=lambda case: case["frequency_mae_meV"])
    explicit_case_panel = bool(arguments.get("case_ids"))
    visual_scope = "frozen released" if explicit_case_panel else "scale-pilot"
    visuals: list[dict[str, Any]] = [
        {
            "id": "pilot-resource-profile",
            "kind": "table.v1",
            "title": f"{results['gpu_name']} resource profile",
            "description": (
                f"One-second samples across the complete {len(cases)}-crystal worker "
                f"lifecycle. Dominant per-case phase: {dominant_phase['phase']}."
            ),
            "source_node": "phonon_pilot",
            "columns": [
                {"field": "metric", "label": "Metric"},
                {"field": "value", "label": "Measured value"},
                {"field": "unit", "label": "Unit"},
            ],
            "rows": resource_rows,
        },
        {
            "id": "pilot-phase-timing",
            "kind": "chart.v1",
            "title": "Mean per-crystal time by calculation phase",
            "description": (
                "Separates coordinate relaxation, DFT FORCE_SETS loading, MatterSim "
                "displacement-force inference, and reciprocal-space mesh comparison."
            ),
            "source_node": "phonon_pilot",
            "mark": "bar",
            "rows": phase_rows,
            "x": {"field": "phase", "label": "Calculation phase", "type": "nominal"},
            "y": {
                "field": "mean_time_s",
                "label": "Mean time",
                "type": "quantitative",
                "unit": "s",
            },
        },
        {
            "id": "pilot-case-timing",
            "kind": "chart.v1",
            "title": "Per-crystal wall time",
            "description": (
                "Cases are identified by Materials Project ID so slow structures can be "
                "traced back to their unit cells and displacement counts."
            ),
            "source_node": "phonon_pilot",
            "mark": "bar",
            "rows": [
                {
                    "mp_id": case["materials_project_id"],
                    "case_time_s": case["timing_s"]["total"],
                }
                for case in cases
            ],
            "x": {"field": "mp_id", "label": "Crystal", "type": "nominal"},
            "y": {
                "field": "case_time_s",
                "label": "Wall time",
                "type": "quantitative",
                "unit": "s",
            },
        },
        {
            "id": "pilot-phonon-mae",
            "kind": "chart.v1",
            "title": f"MatterSim phonon error across {len(cases)} {visual_scope} crystals",
            "description": (
                "Mean absolute phonon-frequency difference from the released DFT force "
                "sets. "
                + (
                    "These cases are explicit frozen released-paper IDs: chemistry-diverse "
                    "but small, and not a random or population-representative sample."
                    if explicit_case_panel
                    else "This size-stratified pilot profiles scale; it is not the final "
                    "chemistry-representative benchmark."
                )
            ),
            "source_node": "phonon_pilot",
            "mark": "bar",
            "rows": [
                {
                    "mp_id": case["materials_project_id"],
                    "frequency_mae_meV": case["frequency_mae_meV"],
                }
                for case in cases
            ],
            "x": {"field": "mp_id", "label": "Crystal", "type": "nominal"},
            "y": {
                "field": "frequency_mae_meV",
                "label": "Phonon-frequency MAE",
                "type": "quantitative",
                "unit": "meV",
            },
        },
        {
            "id": "pilot-evidence",
            "kind": "table.v1",
            "title": (
                f"{len(cases)}-crystal {'frozen-case' if explicit_case_panel else 'pilot'} evidence"
            ),
            "description": (
                "Decision metrics remain compact; expand calculation details for cell, "
                "mesh, displacement, timing, force, and stability information."
            ),
            "source_node": "phonon_pilot",
            "columns": [
                {"field": "material", "label": "Crystal"},
                {"field": "mp_id", "label": "Materials Project ID"},
                {"field": "unit_cell_atoms", "label": "Unit-cell atoms"},
                {"field": "supercell", "label": "Phonon supercell"},
                {"field": "supercell_atoms", "label": "Supercell atoms"},
                {"field": "displacements", "label": "Displacements"},
                {"field": "q_mesh", "label": "q mesh"},
                {
                    "field": "frequency_mae_meV",
                    "label": "Frequency MAE",
                    "unit": "meV",
                },
                {"field": "p95_error_meV", "label": "95th pct error", "unit": "meV"},
                {"field": "case_time_s", "label": "Case time", "unit": "s"},
                {
                    "field": "requested_batch_size",
                    "label": "Requested batch",
                },
                {
                    "field": "effective_batch_size",
                    "label": "Effective batch",
                },
                {
                    "field": "batch_oom_retries",
                    "label": "OOM backoffs",
                },
                {
                    "field": "max_force_eV_per_A",
                    "label": "Residual force",
                    "unit": "eV/Å",
                },
                {"field": "imaginary_modes", "label": "Model imaginary modes"},
                {"field": "dft_imaginary_modes", "label": "DFT reference imaginary modes"},
                {
                    "field": "status",
                    "label": "Numerical status",
                },
            ],
            "rows": table_rows,
        },
        {
            "id": "pilot-worst-frequency-agreement",
            "kind": "chart.v1",
            "title": (
                f"Worst {'frozen' if explicit_case_panel else 'pilot'} case: {worst['material']} "
                f"({worst['materials_project_id']}) MatterSim versus DFT"
            ),
            "description": (
                f"The highest-MAE {'frozen' if explicit_case_panel else 'pilot'} "
                "crystal is retained at mode level so the aggregate "
                "cannot hide its error distribution."
            ),
            "source_node": "phonon_pilot",
            "mark": "scatter",
            "rows": worst["scatter_rows"],
            "x": {
                "field": "dft_frequency_meV",
                "label": "DFT phonon frequency",
                "type": "quantitative",
                "unit": "meV",
            },
            "y": {
                "field": "mattersim_frequency_meV",
                "label": "MatterSim phonon frequency",
                "type": "quantitative",
                "unit": "meV",
            },
        },
        {
            "id": "pilot-worst-structure",
            "kind": "atomistic.v1",
            "title": (
                f"Worst {'frozen-case' if explicit_case_panel else 'pilot case'} "
                f"structure: {worst['material']} "
                f"({worst['materials_project_id']})"
            ),
            "description": (
                f"Fixed-cell relaxed structure for the highest-MAE "
                f"{'frozen' if explicit_case_panel else 'pilot'} case. This is "
                "retained for inspection, not presented as a representative crystal."
            ),
            "source_node": "phonon_pilot",
            "data": worst["structure"],
        },
    ]

    checkpoint_hash = results["checkpoint_sha256"]
    selected_cases = results["selected_cases"]
    return Output(
        metrics=metrics,
        data={
            "source": {
                "title": (
                    "Benchmarking universal machine learning interatomic potentials "
                    "for Real-Time Analysis of Inelastic Neutron Scattering Data"
                ),
                "authors": "Bowen Han and Yongqiang Cheng",
                "journal": "Machine Learning: Science and Technology 6, 030504 (2025)",
                "arxiv_id": "2506.01860v1",
                "url": "https://arxiv.org/abs/2506.01860",
                "code_url": "https://github.com/maplewen4/phonon_uMLIP",
                "data_url": "https://doi.org/10.5281/zenodo.15298436",
                "paper_global_mattersim_frequency_mae_meV": 1.430077,
            },
            "model_info": {
                "name": "MatterSim-v1.0.0-5M",
                "version": results["versions"]["mattersim"],
                "checkpoint": (f"{results['checkpoint_name']} sha256:{checkpoint_hash}"),
                "checkpoint_sha256": checkpoint_hash,
                "head": "MatterSim-v1.0.0-5M",
                "dtype": "float32",
                "hardware": results["gpu_name"],
                "device": results["device"],
            },
            "method_alignment": "same_model_partial_protocol",
            "dependency_versions": results["versions"],
            "dataset": {
                "archive_sha256": DATA_ARCHIVE_SHA256,
                "selected_cases": selected_cases,
                "selection_method": (
                    "Explicit released-paper crystal IDs"
                    if arguments.get("case_ids")
                    else "Deterministic equal-population quantile stratification by "
                    "unit-cell atom count"
                ),
                "selection_seed": results["selection_seed"],
                "population_sample_size": results["population_sample_size"],
                "shard_index": results["shard_index"],
                "shard_count": results["shard_count"],
                "selected_unit_cell_atom_counts": (results["selected_unit_cell_atom_counts"]),
                "archive_audit_material_count": results["archive_case_count"],
                "excluded_incompatible_cases": (results["excluded_incompatible_cases"]),
                "paper_reported_material_count": 4869,
                "cache_hit": results["dataset_cache_hit"],
            },
            "acceptance_contract": {
                "expected_case_count": expected_size,
                "relax_fmax_eV_per_A": force_threshold,
                "mean_frequency_mae_tolerance_meV": mean_threshold,
                "max_material_mae_tolerance_meV": worst_threshold,
                "significant_imaginary_frequency_threshold_meV": imaginary_threshold,
                "minimum_telemetry_samples": 5,
                "inference_batch_size": inference_batch_size,
                "batch_equivalence_tolerance_eV_per_A": (batch_equivalence_tolerance),
                "threshold_rationale": (
                    "Declared before GPU execution. Completion, numerical quality, and "
                    "usable telemetry are gates; the golden six-case DAG additionally "
                    "gates mean and worst-crystal frequency MAE. The imaginary-mode "
                    "count uses the explicit -1 meV significance threshold. The "
                    "frequency-error distribution is assessed without retuning a pass "
                    "line. Batched inference must reproduce the sequential force result "
                    "within the declared component-wise tolerance."
                ),
            },
            "resource_profile": profile,
            "timing_s": results["timing_s"],
            "optimization_assessment": {
                "dominant_phase": dominant_phase,
                "recommendation": optimization,
                "inference_batch_size": inference_batch_size,
                "batch_equivalence_max_force_delta_eV_per_A": (batch_equivalence_max_delta),
                "batch_equivalence_passed": batch_equivalence_passed,
            },
            "comparison_rows": table_rows,
            "scientific_decision": {
                "contract_version": "scientific-decision.v1",
                "outcome": "REVIEW",
                "calibration": {
                    "status": "INSUFFICIENT_EVIDENCE",
                    "accepted_case_count": 0,
                    "minimum_case_count": 30,
                },
                "scope": (
                    "Six deterministically selected released MatterSim phonon cases "
                    "used as a same-model protocol and throughput fixture."
                ),
                "headline": (
                    "Six-case same-model protocol check passed; this is a bounded "
                    "protocol fixture, not full-paper validation."
                    if operational_pass
                    else "The phonon protocol check needs infrastructure review."
                ),
                "quality_checks": [
                    {
                        "label": "Cases complete",
                        "status": "PASS" if completed else "FAILED",
                        "value": len(cases),
                        "unit": "count",
                        "criterion": f"exactly {expected_size} frozen cases",
                    },
                    {
                        "label": "Mean frequency MAE",
                        "status": "PASS" if mean_mae < mean_threshold else "FAILED",
                        "value": mean_mae,
                        "unit": "meV",
                        "criterion": f"< {mean_threshold:g} meV",
                    },
                    {
                        "label": "Worst crystal MAE",
                        "status": "PASS" if worst_mae < worst_threshold else "FAILED",
                        "value": worst_mae,
                        "unit": "meV",
                        "criterion": f"< {worst_threshold:g} meV",
                    },
                    {
                        "label": "Model imaginary-mode cases",
                        "status": "PASS" if imaginary_materials == 0 else "REVIEW",
                        "value": imaginary_materials,
                        "unit": "count",
                        "criterion": f"0 cases below {imaginary_threshold:g} meV",
                    },
                    {
                        "label": "DFT reference imaginary-mode cases",
                        "status": "PASS" if dft_imaginary_materials == 0 else "REVIEW",
                        "value": dft_imaginary_materials,
                        "unit": "count",
                        "criterion": f"0 cases below {imaginary_threshold:g} meV",
                    },
                    {
                        "label": "Residual force",
                        "status": "PASS" if numerical_quality else "FAILED",
                        "value": max_force,
                        "unit": "eV/Å",
                        "criterion": f"≤ {force_threshold:g} eV/Å",
                    },
                    {
                        "label": "Batch equivalence",
                        "status": "PASS" if batch_equivalence_passed else "FAILED",
                        "value": batch_equivalence_max_delta,
                        "unit": "eV/Å",
                        "criterion": f"≤ {batch_equivalence_tolerance:g} eV/Å",
                    },
                    {
                        "label": "Operational gate",
                        "status": "PASS" if operational_pass else "FAILED",
                        "value": 1 if operational_pass else 0,
                        "unit": "gate",
                        "criterion": (
                            "completion, numerical quality, telemetry, and batch checks pass"
                        ),
                    },
                ],
                "supported_claims": [
                    (
                        f"The exact MatterSim checkpoint completed {len(cases)} "
                        "deterministically selected released cases."
                    ),
                    (
                        f"Measured T4 utilization averaged {gpu_mean:.1f}% with "
                        f"{gpu_memory_fraction:.1f}% peak VRAM use."
                    ),
                    optimization,
                ],
                "limitations": [
                    (
                        f"{len(cases)} cases profile throughput but do not reproduce "
                        "the full paper distribution."
                    ),
                    (
                        "The six-case panel uses explicit frozen released-paper IDs; it is "
                        "chemistry-diverse but small and is not a random or "
                        "population-representative sample."
                        if arguments.get("case_ids")
                        else (
                            "Selection is stratified by unit-cell size, not yet "
                            "jointly stratified by chemistry."
                        )
                    ),
                    (
                        "Phonopy 4.3.1 replaces the paper's 2.28.0 because the latter "
                        "does not build in Python 3.12."
                    ),
                    "The released archive contains fewer cases than the paper reports.",
                ],
            },
        },
        visualizations=visuals,
    )


def main(input_path: Path, output_path: Path) -> None:
    payload = Input.model_validate_json(input_path.read_text(encoding="utf-8"))
    output = analyse(run_benchmark(payload.arguments), payload.arguments)
    output_path.write_text(output.model_dump_json(indent=2), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: mattersim_phonon_scale_pilot.py INPUT_JSON OUTPUT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
