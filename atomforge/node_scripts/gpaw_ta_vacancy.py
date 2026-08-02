# /// script
# requires-python = ">=3.12"
# ///

"""Run the held-out Ta/mp-50 vacancy calculation on New GPAW's GPU path.

The node consumes the exact frozen geometry selected upstream, relaxes the
127-atom vacancy at fixed cell, and evaluates both the relaxed vacancy and its
128-atom pristine reference with the same tight PBE/PW/Gamma protocol.  It
writes an immutable, hashed evidence bundle for the fail-closed validator.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from atomforge.execution.artifact_paths import resolve_dft_artifact_dir

_SCF_ENERGY_RE = re.compile(
    r"^\|iter:\s*\d+\|[^|]*\|\s*([-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?)c?\|",
    re.MULTILINE,
)


def _node_data(inputs: dict[str, Any], node_id: str) -> dict[str, Any]:
    value = inputs.get(node_id)
    if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
        raise ValueError(f"source node {node_id!r} is missing SCRIPT data")
    return value["data"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _structure_fingerprint(case: dict[str, Any]) -> str:
    contract = {
        "mp_id": case["mp_id"],
        "repeat_factors": case["repeat_factors"],
        "vacancy_atom_index": 0,
        "pristine": case["pristine_structure"],
        "defect": case["defect_structure"],
    }
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scf_energy_change_eV(log_path: Path) -> float:
    energies = [
        float(value)
        for value in _SCF_ENERGY_RE.findall(log_path.read_text(encoding="utf-8", errors="replace"))
    ]
    if len(energies) < 2:
        raise RuntimeError(f"{log_path.name} does not contain two parseable New GPAW SCF energies")
    return abs(energies[-1] - energies[-2])


def _max_force_norm(forces: Any) -> float:
    if getattr(forces, "size", 0) == 0:
        return 0.0
    return float(((forces**2).sum(axis=1).max()) ** 0.5)


def _formation_energy_eV(
    defect_energy_eV: float,
    pristine_energy_eV: float,
    *,
    defect_atoms: int,
    pristine_atoms: int,
) -> float:
    if pristine_atoms <= 0 or defect_atoms != pristine_atoms - 1:
        raise ValueError("vacancy formation energy requires N-1 defect atoms")
    return defect_energy_eV - defect_atoms / pristine_atoms * pristine_energy_eV


def _sample_gpu(stop: threading.Event, samples: list[dict[str, float]]) -> None:
    while not stop.is_set():
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,power.draw",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            values = result.stdout.strip().splitlines()[0].split(",")
            samples.append(
                {
                    "time": time.time(),
                    "utilization_pct": float(values[0].strip()),
                    "memory_MiB": float(values[1].strip()),
                    "power_W": float(values[2].strip()),
                }
            )
        except (IndexError, OSError, ValueError, subprocess.SubprocessError):
            pass
        stop.wait(1.0)


def _atoms_from_payload(payload: dict[str, Any]) -> Any:
    from ase import Atoms

    return Atoms(
        numbers=payload["numbers"],
        positions=payload["positions"],
        cell=payload["cell"],
        pbc=payload["pbc"],
    )


def _write_atoms(path: Path, atoms: Any) -> None:
    payload = {
        "numbers": [int(value) for value in atoms.numbers],
        "symbols": atoms.get_chemical_symbols(),
        "positions": atoms.positions.tolist(),
        "cell": atoms.cell.array.tolist(),
        "pbc": [bool(value) for value in atoms.pbc],
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )


def build_output(inputs: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    import ase
    import gpaw
    import numpy as np
    from ase.optimize import LBFGS
    from gpaw import GPAW, PW, FermiDirac
    from gpaw.gpu import cupy, cupy_is_fake

    selection_node = str(arguments.get("selection_node", "select_dft_case"))
    geometry_node = str(arguments.get("geometry_node", "prepare_paper_subset"))
    decision = _node_data(inputs, selection_node).get("decision")
    if not isinstance(decision, dict) or not isinstance(decision.get("promoted_candidate"), dict):
        raise ValueError("selection node did not promote a candidate to DFT")
    promoted = decision["promoted_candidate"]
    if promoted.get("element") != "Ta" or promoted.get("mp_id") != "mp-50":
        raise ValueError("This bounded GPAW protocol is declared only for Ta mp-50")
    cases = _node_data(inputs, geometry_node).get("cases")
    matches = [
        case
        for case in cases or []
        if isinstance(case, dict) and case.get("case_id") == promoted.get("case_id")
    ]
    if len(matches) != 1:
        raise ValueError("frozen geometry data must contain the promoted case exactly once")
    case = matches[0]
    if not isinstance(case.get("pristine_structure"), dict) or not isinstance(
        case.get("defect_structure"), dict
    ):
        raise ValueError("promoted case is missing pristine or defect structure")
    geometry_fingerprint = _structure_fingerprint(case)
    if geometry_fingerprint != promoted.get("geometry_fingerprint"):
        raise ValueError("promoted geometry fingerprint does not match frozen input geometry")

    artifact_dir = resolve_dft_artifact_dir(
        arguments.get("artifact_dir", "/dft-artifacts/gpaw-ta-vacancy")
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)

    phase_path = artifact_dir / "phases.jsonl"
    step_path = artifact_dir / "relaxation_steps.jsonl"
    phases: list[dict[str, Any]] = []
    started = time.perf_counter()
    wall_limit_s = int(arguments.get("wall_time_limit_seconds", 1740))
    if wall_limit_s < 300 or wall_limit_s > 1800:
        raise ValueError("wall_time_limit_seconds must be between 300 and 1800")

    def mark(label: str, **extra: Any) -> None:
        event = {
            "label": label,
            "elapsed_s": time.perf_counter() - started,
            "time": time.time(),
            **extra,
        }
        phases.append(event)
        with phase_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        print(f"DFT_PHASE {label} {json.dumps(extra, sort_keys=True)}", flush=True)

    gpu_count = int(cupy.cuda.runtime.getDeviceCount())
    if bool(cupy_is_fake) or gpu_count != 1:
        raise RuntimeError(
            f"held-out DFT requires one real GPU, found fake={cupy_is_fake} count={gpu_count}"
        )
    calculator_module = type(
        GPAW(mode=PW(200), txt=None, parallel={"gpu": True}, legacy_gpaw=False)
    ).__module__
    if not calculator_module.startswith("gpaw.new."):
        raise RuntimeError(f"Expected New GPAW calculator, got {calculator_module}")
    mark(
        "runtime_verified",
        ase_version=ase.__version__,
        gpaw_version=gpaw.__version__,
        calculator_module=calculator_module,
        gpu_name=str(cupy.cuda.runtime.getDeviceProperties(0)["name"]),
    )

    cutoff_eV = float(arguments.get("plane_wave_cutoff_eV", 350.0))
    smearing_eV = float(arguments.get("electronic_temperature_eV", 0.2585))
    relaxation_energy_tolerance_eV = float(arguments.get("relaxation_energy_tolerance_eV", 1e-4))
    final_energy_tolerance_eV = float(arguments.get("final_energy_tolerance_eV", 1e-5))
    force_tolerance = float(arguments.get("force_tolerance_eV_per_A", 0.03))
    max_scf_iterations = int(arguments.get("max_scf_iterations", 80))
    extra_bands = int(arguments.get("extra_bands", -20))
    max_ionic_steps = int(arguments.get("max_ionic_steps", 30))
    max_displacement = float(arguments.get("max_displacement_A", 0.1))
    if (
        cutoff_eV <= 0
        or smearing_eV <= 0
        or relaxation_energy_tolerance_eV <= 0
        or final_energy_tolerance_eV <= 0
        or force_tolerance <= 0
        or max_scf_iterations < 1
        or max_ionic_steps < 1
    ):
        raise ValueError("GPAW protocol parameters must be positive")

    protocol = {
        "mode": "plane-wave",
        "plane_wave_cutoff_eV": cutoff_eV,
        "exchange_correlation_functional": "PBE",
        "kpoint_mesh": [1, 1, 1],
        "electronic_temperature_eV": smearing_eV,
        "spin_treatment": "spin-paired non-magnetic Ta with fractional occupations",
        "relaxation_energy_tolerance_eV": relaxation_energy_tolerance_eV,
        "final_energy_tolerance_eV": final_energy_tolerance_eV,
        "force_tolerance_eV_per_A": force_tolerance,
        "max_scf_iterations": max_scf_iterations,
        "extra_bands": extra_bands,
        "random_initial_wavefunctions": True,
        "optimizer": "ASE LBFGS",
        "max_ionic_steps": max_ionic_steps,
        "max_displacement_A": max_displacement,
        "cell_relaxation": False,
        "gpu_count": gpu_count,
    }
    (artifact_dir / "protocol.json").write_text(
        json.dumps(protocol, indent=2, sort_keys=True), encoding="utf-8"
    )
    (artifact_dir / "frozen_pristine_input.json").write_text(
        json.dumps(case["pristine_structure"], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (artifact_dir / "frozen_defect_input.json").write_text(
        json.dumps(case["defect_structure"], indent=2, sort_keys=True),
        encoding="utf-8",
    )

    def calculator(log_name: str, energy_tolerance_eV: float) -> Any:
        np.random.seed(0)
        return GPAW(
            mode=PW(cutoff_eV),
            xc="PBE",
            kpts=(1, 1, 1),
            occupations=FermiDirac(smearing_eV),
            spinpol=False,
            convergence={"energy": energy_tolerance_eV},
            maxiter=max_scf_iterations,
            nbands=extra_bands,
            random=True,
            parallel={"gpu": True},
            legacy_gpaw=False,
            txt=str(artifact_dir / log_name),
        )

    vacancy = _atoms_from_payload(case["defect_structure"])
    pristine = _atoms_from_payload(case["pristine_structure"])
    if len(vacancy) != len(pristine) - 1:
        raise ValueError("frozen defect is not a one-atom vacancy")
    vacancy.calc = calculator("relaxation_scf.txt", relaxation_energy_tolerance_eV)
    optimizer = LBFGS(
        vacancy,
        trajectory=str(artifact_dir / "relaxation.traj"),
        logfile=str(artifact_dir / "relaxation.log"),
        maxstep=max_displacement,
    )
    step_records: list[dict[str, float]] = []
    previous_step_time = time.perf_counter()

    def record_step() -> None:
        nonlocal previous_step_time
        now = time.perf_counter()
        forces = vacancy.get_forces()
        record = {
            "optimizer_step": float(optimizer.nsteps),
            "elapsed_s": now - started,
            "evaluation_s": now - previous_step_time,
            "energy_eV": float(vacancy.get_potential_energy()),
            "max_force_eV_per_A": _max_force_norm(forces),
        }
        previous_step_time = now
        step_records.append(record)
        with step_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        print(f"DFT_STEP {json.dumps(record, sort_keys=True)}", flush=True)
        if now - started > wall_limit_s:
            raise TimeoutError("GPAW DFT exceeded its declared wall-time limit")

    samples: list[dict[str, float]] = []
    stop = threading.Event()
    sampler = threading.Thread(target=_sample_gpu, args=(stop, samples), daemon=True)
    sampler.start()
    try:
        mark("vacancy_relaxation_started", atom_count=len(vacancy))
        optimizer.attach(record_step, interval=1)
        ionic_converged = bool(optimizer.run(fmax=force_tolerance, steps=max_ionic_steps))
        relaxed_force = _max_force_norm(vacancy.get_forces())
        ionic_converged = bool(ionic_converged and relaxed_force <= force_tolerance)
        mark(
            "vacancy_relaxation_finished",
            ionic_converged=ionic_converged,
            max_force_eV_per_A=relaxed_force,
            optimizer_steps=optimizer.nsteps,
        )
        if not ionic_converged:
            raise RuntimeError(
                f"vacancy relaxation stopped at {relaxed_force:.6g} eV/Å, "
                f"above {force_tolerance:.6g} eV/Å"
            )
        _write_atoms(artifact_dir / "relaxed_defect.json", vacancy)

        vacancy.calc = calculator("vacancy_final_scf.txt", final_energy_tolerance_eV)
        mark("vacancy_final_scf_started")
        vacancy_energy_eV = float(vacancy.get_potential_energy())
        vacancy_forces = vacancy.get_forces()
        max_force = _max_force_norm(vacancy_forces)
        (artifact_dir / "vacancy_final_forces.json").write_text(
            json.dumps(vacancy_forces.tolist(), indent=2), encoding="utf-8"
        )
        vacancy_energy_change_eV = _scf_energy_change_eV(artifact_dir / "vacancy_final_scf.txt")
        mark(
            "vacancy_final_scf_finished",
            energy_eV=vacancy_energy_eV,
            final_energy_change_eV=vacancy_energy_change_eV,
            max_force_eV_per_A=max_force,
        )

        pristine.calc = calculator("pristine_final_scf.txt", final_energy_tolerance_eV)
        mark("pristine_reference_scf_started", atom_count=len(pristine))
        pristine_energy_eV = float(pristine.get_potential_energy())
        pristine_forces = pristine.get_forces()
        (artifact_dir / "pristine_final_forces.json").write_text(
            json.dumps(pristine_forces.tolist(), indent=2), encoding="utf-8"
        )
        pristine_energy_change_eV = _scf_energy_change_eV(artifact_dir / "pristine_final_scf.txt")
        mark(
            "pristine_reference_scf_finished",
            energy_eV=pristine_energy_eV,
            final_energy_change_eV=pristine_energy_change_eV,
            max_force_eV_per_A=_max_force_norm(pristine_forces),
        )
    finally:
        stop.set()
        sampler.join(timeout=2)

    elapsed_s = time.perf_counter() - started
    if elapsed_s > wall_limit_s:
        raise TimeoutError(f"GPAW DFT took {elapsed_s:.1f}s, above {wall_limit_s}s limit")
    formation_energy_eV = _formation_energy_eV(
        vacancy_energy_eV,
        pristine_energy_eV,
        defect_atoms=len(vacancy),
        pristine_atoms=len(pristine),
    )
    final_energy_change_eV = max(vacancy_energy_change_eV, pristine_energy_change_eV)
    electronic_converged = final_energy_change_eV <= final_energy_tolerance_eV
    ionic_converged = bool(ionic_converged and max_force <= force_tolerance)
    peak_gpu = max((sample["utilization_pct"] for sample in samples), default=0.0)
    mean_gpu = statistics.mean(sample["utilization_pct"] for sample in samples) if samples else 0.0
    (artifact_dir / "gpu_samples.json").write_text(
        json.dumps(samples, indent=2, sort_keys=True), encoding="utf-8"
    )

    calculation = {
        "contract_version": "dft-artifact.v1",
        "case_id": promoted["case_id"],
        "element": promoted["element"],
        "mp_id": promoted["mp_id"],
        "initial_geometry_fingerprint": geometry_fingerprint,
        "code": "GPAW",
        "code_version": gpaw.__version__,
        "ase_version": ase.__version__,
        "calculator_module": calculator_module,
        "pseudopotential_set": "GPAW PAW setups 24.11.0",
        "protocol": protocol,
        "reference_convention": "self-consistent elemental bulk",
        "independent_of_selection_models": True,
        "pristine_atom_count": len(pristine),
        "defect_atom_count": len(vacancy),
        "pristine_total_energy_eV": pristine_energy_eV,
        "relaxed_defect_total_energy_eV": vacancy_energy_eV,
        "dft_vacancy_formation_energy_eV": formation_energy_eV,
        "max_force_eV_per_A": max_force,
        "vacancy_final_energy_change_eV": vacancy_energy_change_eV,
        "pristine_final_energy_change_eV": pristine_energy_change_eV,
        "electronic_converged": electronic_converged,
        "ionic_converged": ionic_converged,
        "optimizer_steps": optimizer.nsteps,
        "step_records": step_records,
        "wall_time_s": elapsed_s,
        "gpu_mean_utilization_pct": mean_gpu,
        "gpu_peak_utilization_pct": peak_gpu,
    }
    calculation_path = artifact_dir / "dft_calculation.json"
    calculation_path.write_text(
        json.dumps(calculation, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    tracked = sorted(
        path
        for path in artifact_dir.iterdir()
        if path.is_file() and path.name != "artifact_manifest.json"
    )
    manifest = {
        "contract_version": "dft-artifact-manifest.v1",
        "case_id": promoted["case_id"],
        "initial_geometry_fingerprint": geometry_fingerprint,
        "files": {path.name: _sha256(path) for path in tracked},
    }
    manifest_path = artifact_dir / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    source_artifact_sha256 = _sha256(manifest_path)
    cell_lengths = [float(value) for value in pristine.cell.lengths()]
    dft_result = {
        "case_id": promoted["case_id"],
        "element": promoted["element"],
        "mp_id": promoted["mp_id"],
        "initial_geometry_fingerprint": geometry_fingerprint,
        "code": "GPAW",
        "code_version": gpaw.__version__,
        "exchange_correlation_functional": "PBE",
        "pseudopotential_set": "GPAW PAW setups 24.11.0",
        "spin_treatment": protocol["spin_treatment"],
        "reference_convention": "self-consistent elemental bulk",
        "independent_of_selection_models": True,
        "electronic_converged": electronic_converged,
        "ionic_converged": ionic_converged,
        "dft_vacancy_formation_energy_eV": formation_energy_eV,
        "max_force_eV_per_A": max_force,
        "final_energy_change_eV": final_energy_change_eV,
        "plane_wave_cutoff_eV": cutoff_eV,
        "electronic_scf_tolerance_eV": final_energy_tolerance_eV,
        "electronic_temperature_eV": smearing_eV,
        "ionic_force_tolerance_eV_per_A": force_tolerance,
        "kpoint_mesh": [1, 1, 1],
        "kpoint_density_per_A": min(mesh / length for mesh, length in zip((1, 1, 1), cell_lengths)),
        "source_artifact_sha256": source_artifact_sha256,
        "artifact_uri": str(artifact_dir),
        "artifact_manifest": str(manifest_path),
        "wall_time_s": elapsed_s,
    }
    ready = electronic_converged and ionic_converged
    return {
        "contract_version": "v1",
        "metrics": {
            "dft_artifact_written": {"val": 1.0, "unit": "dimensionless"},
            "dft_electronic_converged": {
                "val": 1.0 if electronic_converged else 0.0,
                "unit": "dimensionless",
            },
            "dft_ionic_converged": {
                "val": 1.0 if ionic_converged else 0.0,
                "unit": "dimensionless",
            },
            "dft_max_force": {"val": max_force, "unit": "eV/Å"},
            "dft_final_energy_change": {
                "val": final_energy_change_eV,
                "unit": "eV",
            },
            "dft_vacancy_formation_energy": {
                "val": formation_energy_eV,
                "unit": "eV",
            },
            "dft_wall_time": {"val": elapsed_s, "unit": "s"},
            "dft_optimizer_steps": {
                "val": float(optimizer.nsteps),
                "unit": "count",
            },
            "dft_gpu_mean_utilization_pct": {"val": mean_gpu, "unit": "%"},
            "dft_gpu_peak_utilization_pct": {"val": peak_gpu, "unit": "%"},
            "dft_result_ready": {
                "val": 1.0 if ready else 0.0,
                "unit": "dimensionless",
            },
        },
        "data": {
            "dft_result": dft_result,
            "dft_calculation": calculation,
            "artifact_manifest": manifest,
        },
    }


def main(input_path: Path, output_path: Path) -> None:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    output = build_output(payload["inputs"], payload.get("arguments", {}))
    output_path.write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        raise SystemExit("usage: gpaw_ta_vacancy.py INPUT_JSON OUTPUT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
