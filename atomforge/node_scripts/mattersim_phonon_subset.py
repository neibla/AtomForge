# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "ase==3.23.0",
#   "mattersim==1.0.0rc9",
#   "numpy==1.26.4",
#   "phonopy==4.3.1",
#   "pydantic==2.9.2",
#   "pymatgen==2024.4.13",
#   "setuptools<81",
#   "torch==2.2.0",
# ]
# ///

"""Reproduce a released subset of the 2025 uMLIP phonon benchmark.

The paper-wide leaderboard is context, not an output of this bounded run. This script
uses six entries from the authors' Zenodo DFT force-set archive and the exact
MatterSim-v1.0.0-5M checkpoint named in their environment and Supplementary Table S7.
"""

from __future__ import annotations

import hashlib
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from atomforge.compute_scaling import run_with_batch_backoff

DATA_URL = "https://zenodo.org/records/15298436/files/phonon_benchmark_database.tar.gz?download=1"
DATA_ARCHIVE_SHA256 = "fb3b98eb98c6c36e13aa2abde21c43435d2d8503c6ce86f76eb0dfc8c963e70e"
THZ_TO_MEV = 4.135667696
CASES = {
    "Al": "mp-134-Cheng23",
    "Cu": "mp-30-Cheng23",
    "Si": "mp-149-Cheng23",
    "GaAs": "mp-2534-Cheng23",
    "MgO": "mp-1265-Cheng23",
    "NaCl": "mp-22862-Cheng23",
}


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_database(destination: Path) -> Path:
    archive = destination / "phonon_benchmark_database.tar.gz"
    urllib.request.urlretrieve(DATA_URL, archive)
    actual = sha256(archive)
    if actual != DATA_ARCHIVE_SHA256:
        raise ValueError(
            f"Zenodo archive checksum mismatch: expected {DATA_ARCHIVE_SHA256}, got {actual}"
        )
    selected = {f"phonon_benchmark_database/{name}/" for name in CASES.values()}
    with tarfile.open(archive, "r:gz") as source:
        members = [
            member
            for member in source.getmembers()
            if any(member.name.startswith(prefix) for prefix in selected)
        ]
        for member in members:
            if member.islnk() or member.issym() or ".." in Path(member.name).parts:
                raise ValueError(f"Unsafe member in benchmark archive: {member.name}")
        source.extractall(destination, members=members, filter="data")
    root = destination / "phonon_benchmark_database"
    missing = [name for name in CASES.values() if not (root / name).is_dir()]
    if missing:
        raise ValueError(f"Selected benchmark cases missing from Zenodo archive: {missing}")
    return root


def parse_supercell_matrix(mesh_path: Path) -> list[int]:
    for line in mesh_path.read_text().splitlines():
        if line.strip().upper().startswith("DIM"):
            values = line.split("=", 1)[1].split()
            matrix = [int(value) for value in values]
            if len(matrix) == 3 and all(value > 0 for value in matrix):
                return matrix
    raise ValueError(f"No valid DIM entry in {mesh_path}")


def parse_mesh_matrix(mesh_path: Path, key: str) -> list[int]:
    """Read a three-integer Phonopy mesh setting such as ``MP``."""
    prefix = key.strip().upper()
    for line in mesh_path.read_text(encoding="utf-8").splitlines():
        if line.strip().upper().startswith(prefix):
            values = line.split("=", 1)[1].split()
            matrix = [int(value) for value in values]
            if len(matrix) == 3 and all(value > 0 for value in matrix):
                return matrix
    raise ValueError(f"No valid {prefix} entry in {mesh_path}")


def paper_model_supercell(atoms) -> list[int]:
    """Match the released script: make every model cell at least 12 Å wide."""
    lengths = np.asarray(atoms.cell.lengths(), dtype=float)
    return [max(1, int(np.ceil(12.0 / length))) for length in lengths]


def to_phonopy_atoms(atoms):
    from phonopy.structure.atoms import PhonopyAtoms

    return PhonopyAtoms(
        symbols=atoms.get_chemical_symbols(),
        cell=np.asarray(atoms.cell.array, dtype=float),
        scaled_positions=np.asarray(atoms.get_scaled_positions(), dtype=float),
    )


def to_ase_atoms(atoms):
    from ase import Atoms

    return Atoms(
        symbols=atoms.symbols,
        scaled_positions=np.asarray(atoms.scaled_positions, dtype=float),
        cell=np.asarray(atoms.cell, dtype=float),
        pbc=True,
    )


def calculate_case(
    *,
    label: str,
    case_dir: Path,
    calculator,
    fmax: float,
    max_steps: int,
    displacement_A: float,
    inference_batch_size: int = 1,
    validate_batch_equivalence: bool = False,
) -> dict[str, Any]:
    import phonopy
    from ase.io import read
    from ase.optimize import FIRE
    from phonopy import Phonopy

    case_started = time.perf_counter()
    poscar = case_dir / "POSCAR-unitcell"
    force_sets = case_dir / "FORCE_SETS"
    mesh_conf = case_dir / "mesh.conf"
    for required in (poscar, force_sets, mesh_conf):
        if not required.is_file():
            raise FileNotFoundError(required)

    initial = read(poscar, format="vasp")
    relaxed = initial.copy()
    relaxed.calc = calculator
    optimiser = FIRE(relaxed, logfile=None)
    converged = bool(optimiser.run(fmax=fmax, steps=max_steps))
    forces = np.asarray(relaxed.get_forces(), dtype=float)
    max_force = float(np.linalg.norm(forces, axis=1).max(initial=0.0))
    displacements = np.asarray(relaxed.positions - initial.positions, dtype=float)
    mean_coordinate_shift = float(np.linalg.norm(displacements, axis=1).mean())
    relaxation_finished = time.perf_counter()

    dft_supercell_matrix = parse_supercell_matrix(mesh_conf)
    model_supercell_matrix = paper_model_supercell(initial)
    q_mesh = parse_mesh_matrix(mesh_conf, "MP")
    dft_phonon = phonopy.load(
        unitcell_filename=str(poscar),
        supercell_matrix=dft_supercell_matrix,
        primitive_matrix=np.eye(3),
        force_sets_filename=str(force_sets),
        is_nac=False,
        produce_fc=True,
    )
    dft_force_constants_finished = time.perf_counter()
    model_phonon = Phonopy(
        to_phonopy_atoms(relaxed),
        supercell_matrix=model_supercell_matrix,
        primitive_matrix=np.eye(3),
    )
    model_phonon.generate_displacements(distance=displacement_A)
    displaced_atoms = [
        to_ase_atoms(supercell) for supercell in model_phonon.supercells_with_displacements
    ]
    batch_equivalence_max_force_delta = None
    requested_inference_batch_size = min(inference_batch_size, len(displaced_atoms))
    effective_inference_batch_size = requested_inference_batch_size
    batch_oom_retries = 0
    if inference_batch_size > 1:
        import gc

        import torch
        from mattersim.datasets.utils.build import build_dataloader

        def predict_forces(batch_size: int):
            inference_args = dict(calculator.args_dict)
            inference_args.update(batch_size=batch_size, only_inference=True)
            dataloader = build_dataloader(
                displaced_atoms,
                model_type=calculator.potential.model_name,
                **inference_args,
            )
            return calculator.potential.predict_properties(
                dataloader,
                include_forces=True,
                include_stresses=False,
            )

        def clear_cuda_and_log(previous: int, current: int) -> None:
            gc.collect()
            torch.cuda.empty_cache()
            print(
                f"MatterSim batch OOM for {label}: reducing displacement batch "
                f"{previous} -> {current}",
                flush=True,
            )

        prediction, effective_inference_batch_size, batch_oom_retries = run_with_batch_backoff(
            requested_inference_batch_size,
            predict_forces,
            is_memory_error=lambda exc: isinstance(exc, torch.cuda.OutOfMemoryError),
            on_backoff=clear_cuda_and_log,
        )
        _, predicted_forces, _ = prediction
        model_forces = [np.asarray(force, dtype=float) for force in predicted_forces]
        if len(model_forces) != len(displaced_atoms):
            raise RuntimeError(
                f"MatterSim returned {len(model_forces)} force arrays for "
                f"{len(displaced_atoms)} displaced structures"
            )
        if validate_batch_equivalence and displaced_atoms:
            reference = displaced_atoms[0].copy()
            reference.calc = calculator
            reference_forces = np.asarray(reference.get_forces(), dtype=float)
            batch_equivalence_max_force_delta = float(
                np.max(np.abs(reference_forces - model_forces[0]), initial=0.0)
            )
    else:
        model_forces = []
        for atoms in displaced_atoms:
            atoms.calc = calculator
            model_forces.append(np.asarray(atoms.get_forces(), dtype=float))
    model_phonon.forces = model_forces
    model_phonon.produce_force_constants()
    model_force_constants_finished = time.perf_counter()

    mesh_options = {
        "is_mesh_symmetry": False,
        "is_gamma_center": True,
    }
    dft_phonon.run_mesh(q_mesh, **mesh_options)
    model_phonon.run_mesh(q_mesh, **mesh_options)
    dft_frequencies = np.asarray(dft_phonon.mesh.frequencies, dtype=float) * THZ_TO_MEV
    model_frequencies = np.asarray(model_phonon.mesh.frequencies, dtype=float) * THZ_TO_MEV
    if dft_frequencies.shape != model_frequencies.shape:
        raise ValueError(
            f"Frequency-grid mismatch for {label}: "
            f"DFT={dft_frequencies.shape}, MatterSim={model_frequencies.shape}"
        )
    absolute_errors = np.abs(model_frequencies - dft_frequencies)
    frequency_mae = float(np.mean(absolute_errors))
    # Keep reference instability separate from model instability.  An imaginary
    # DFT mode is a property of the released reference force set, not evidence
    # that MatterSim failed.  Conflating the two made the old report label a
    # scientifically mixed population as a single model defect.
    dft_significant_imaginary = int(np.count_nonzero(dft_frequencies < -1.0))
    significant_imaginary = int(np.count_nonzero(model_frequencies < -1.0))
    mesh_finished = time.perf_counter()

    flat_dft = dft_frequencies.ravel()
    flat_model = model_frequencies.ravel()
    if flat_dft.size > 4000:
        sample_indices = np.linspace(0, flat_dft.size - 1, 4000, dtype=int)
    else:
        sample_indices = np.arange(flat_dft.size)
    scatter_rows = [
        {
            "dft_frequency_meV": float(flat_dft[index]),
            "mattersim_frequency_meV": float(flat_model[index]),
        }
        for index in sample_indices
    ]
    return {
        "material": label,
        "materials_project_id": case_dir.name.split("-Cheng23", 1)[0],
        "n_atoms_unit_cell": len(initial),
        "supercell": "x".join(str(value) for value in model_supercell_matrix),
        "dft_supercell": "x".join(str(value) for value in dft_supercell_matrix),
        "n_atoms_supercell": len(initial) * int(np.prod(model_supercell_matrix)),
        "n_displacements": len(model_forces),
        "requested_inference_batch_size": requested_inference_batch_size,
        "inference_batch_size": effective_inference_batch_size,
        "batch_oom_retries": batch_oom_retries,
        "batch_equivalence_max_force_delta_eV_per_A": (batch_equivalence_max_force_delta),
        "q_mesh": "x".join(str(value) for value in q_mesh),
        "n_frequency_values": int(flat_dft.size),
        "frequency_mae_meV": frequency_mae,
        "frequency_p95_error_meV": float(np.percentile(absolute_errors, 95)),
        "max_force_eV_per_A": max_force,
        "mean_coordinate_shift_A": mean_coordinate_shift,
        "significant_imaginary_modes": significant_imaginary,
        "dft_significant_imaginary_modes": dft_significant_imaginary,
        "optimizer_converged": converged,
        "optimizer_steps": int(optimiser.nsteps),
        "timing_s": {
            "relaxation": relaxation_finished - case_started,
            "dft_force_constants": (dft_force_constants_finished - relaxation_finished),
            "model_force_constants": (
                model_force_constants_finished - dft_force_constants_finished
            ),
            "mesh_and_comparison": mesh_finished - model_force_constants_finished,
            "total": mesh_finished - case_started,
        },
        "scatter_rows": scatter_rows,
        "structure": {
            "numbers": relaxed.get_atomic_numbers().tolist(),
            "symbols": relaxed.get_chemical_symbols(),
            "positions": relaxed.get_positions().tolist(),
            "initial_positions": initial.get_positions().tolist(),
            "final_positions": relaxed.get_positions().tolist(),
            "cell": relaxed.cell.array.tolist(),
            "pbc": [True, True, True],
            "metadata": {
                "material": label,
                "materials_project_id": case_dir.name.split("-Cheng23", 1)[0],
                "display_replicas_recommended": "2x2x2",
            },
        },
    }


def run_benchmark(arguments: dict[str, Any]) -> dict[str, Any]:
    import ase
    import mattersim
    import phonopy
    import torch
    from mattersim.forcefield.potential import MatterSimCalculator

    device = str(arguments.get("device", "cuda"))
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("MatterSim phonon reproduction requires an available CUDA GPU")
    fmax = float(arguments.get("relax_fmax_eV_per_A", 0.005))
    max_steps = int(arguments.get("relax_max_steps", 200))
    displacement_A = float(arguments.get("finite_displacement_A", 0.03))
    calculator = MatterSimCalculator(
        load_path="MatterSim-v1.0.0-5M.pth",
        device=device,
    )
    checkpoint = (
        Path.home() / ".local" / "mattersim" / "pretrained_models" / "mattersim-v1.0.0-5M.pth"
    )
    if not checkpoint.is_file():
        raise FileNotFoundError(f"MatterSim checkpoint not found after load: {checkpoint}")

    with tempfile.TemporaryDirectory(prefix="atomforge-phonon-benchmark-") as temp:
        database = download_database(Path(temp))
        results = [
            calculate_case(
                label=label,
                case_dir=database / directory,
                calculator=calculator,
                fmax=fmax,
                max_steps=max_steps,
                displacement_A=displacement_A,
            )
            for label, directory in CASES.items()
        ]
    return {
        "cases": results,
        "checkpoint_sha256": sha256(checkpoint),
        "checkpoint_name": checkpoint.name,
        "device": device,
        "versions": {
            "mattersim": mattersim.__version__,
            "ase": ase.__version__,
            "phonopy": phonopy.__version__,
            "torch": torch.__version__,
        },
    }


def analyse(results: dict[str, Any], arguments: dict[str, Any]) -> Output:
    mean_threshold = float(arguments.get("mean_frequency_mae_tolerance_meV", 2.0))
    worst_threshold = float(arguments.get("max_material_mae_tolerance_meV", 5.0))
    force_threshold = float(arguments.get("relax_fmax_eV_per_A", 0.005))
    cases = results["cases"]
    mean_mae = float(np.mean([case["frequency_mae_meV"] for case in cases]))
    worst_mae = float(max(case["frequency_mae_meV"] for case in cases))
    max_force = float(max(case["max_force_eV_per_A"] for case in cases))
    imaginary_materials = sum(case["significant_imaginary_modes"] > 0 for case in cases)
    numerical_quality = (
        all(case["optimizer_converged"] for case in cases) and max_force <= force_threshold * 1.001
    )
    subset_passed = (
        numerical_quality
        and mean_mae <= mean_threshold
        and worst_mae <= worst_threshold
        and imaginary_materials == 0
    )

    metrics: dict[str, Metric] = {
        "subset_mean_phonon_frequency_mae": Metric(val=mean_mae, unit="meV"),
        "subset_worst_material_phonon_frequency_mae": Metric(val=worst_mae, unit="meV"),
        "max_relaxation_force": Metric(val=max_force, unit="eV/Å"),
        "materials_with_significant_imaginary_modes": Metric(
            val=float(imaginary_materials), unit="count"
        ),
        "numerical_quality_gate_passed": Metric(
            val=1.0 if numerical_quality else 0.0, unit="dimensionless"
        ),
        "bounded_reproduction_gate_passed": Metric(
            val=1.0 if subset_passed else 0.0, unit="dimensionless"
        ),
    }
    for case in cases:
        metrics[f"{case['material'].lower()}_phonon_frequency_mae"] = Metric(
            val=case["frequency_mae_meV"], unit="meV"
        )

    table_rows = [
        {
            "material": case["material"],
            "mp_id": case["materials_project_id"],
            "unit_cell_atoms": case["n_atoms_unit_cell"],
            "supercell": case["supercell"],
            "supercell_atoms": case["n_atoms_supercell"],
            "q_mesh": case["q_mesh"],
            "frequency_mae_meV": case["frequency_mae_meV"],
            "p95_error_meV": case["frequency_p95_error_meV"],
            "max_force_eV_per_A": case["max_force_eV_per_A"],
            "imaginary_modes": case["significant_imaginary_modes"],
            "dft_imaginary_modes": case["dft_significant_imaginary_modes"],
            "status": (
                "PASS"
                if case["frequency_mae_meV"] <= worst_threshold
                and case["significant_imaginary_modes"] == 0
                else "REVIEW"
            ),
        }
        for case in cases
    ]
    visuals: list[dict[str, Any]] = [
        {
            "id": "phonon-subset-mae",
            "kind": "chart.v1",
            "title": "MatterSim-v1.0.0-5M phonon error across six released crystals",
            "description": (
                "Mean absolute phonon-frequency difference from the authors' released "
                "DFT force sets. Lower is better; the predeclared subset mean gate is "
                f"{mean_threshold:g} meV."
            ),
            "source_node": "phonons",
            "mark": "bar",
            "rows": [
                {
                    "material": case["material"],
                    "frequency_mae_meV": case["frequency_mae_meV"],
                }
                for case in cases
            ],
            "x": {"field": "material", "label": "Crystal", "type": "nominal"},
            "y": {
                "field": "frequency_mae_meV",
                "label": "Phonon-frequency MAE",
                "type": "quantitative",
                "unit": "meV",
            },
        },
        {
            "id": "phonon-subset-evidence",
            "kind": "table.v1",
            "title": "Per-crystal reproduction evidence",
            "description": (
                "Every row uses the paper's fixed-cell relaxation, 0.03 Å finite "
                "displacements, released DFT force sets, and reciprocal-space mesh density."
            ),
            "source_node": "phonons",
            "columns": [
                {"field": "material", "label": "Crystal"},
                {"field": "mp_id", "label": "Materials Project ID"},
                {"field": "unit_cell_atoms", "label": "Unit-cell atoms"},
                {"field": "supercell", "label": "Phonon supercell"},
                {"field": "supercell_atoms", "label": "Supercell atoms"},
                {"field": "q_mesh", "label": "q mesh"},
                {
                    "field": "frequency_mae_meV",
                    "label": "Frequency MAE",
                    "unit": "meV",
                },
                {"field": "p95_error_meV", "label": "95th pct error", "unit": "meV"},
                {
                    "field": "max_force_eV_per_A",
                    "label": "Residual force",
                    "unit": "eV/Å",
                },
                {"field": "imaginary_modes", "label": "Model imaginary modes"},
                {"field": "dft_imaginary_modes", "label": "DFT reference imaginary modes"},
                {"field": "status", "label": "Status"},
            ],
            "rows": table_rows,
        },
    ]
    nacl = next(case for case in cases if case["material"] == "NaCl")
    visuals.extend(
        [
            {
                "id": "nacl-frequency-agreement",
                "kind": "chart.v1",
                "title": "NaCl phonon frequencies: MatterSim versus DFT",
                "description": (
                    "Each point is one vibrational mode at one reciprocal-space point. "
                    "Perfect agreement lies on the implicit y=x diagonal."
                ),
                "source_node": "phonons",
                "mark": "scatter",
                "rows": nacl["scatter_rows"],
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
                "id": "nacl-relaxed-structure",
                "kind": "atomistic.v1",
                "title": "NaCl fixed-cell structure used for phonons",
                "description": (
                    "The conventional eight-atom unit cell after MatterSim coordinate "
                    "relaxation. The force calculation used a 3x3x3, 216-atom supercell."
                ),
                "source_node": "phonons",
                "data": nacl["structure"],
            },
        ]
    )

    checkpoint_hash = results["checkpoint_sha256"]
    return Output(
        metrics=metrics,
        data={
            "source": {
                "title": (
                    "Benchmarking universal machine learning interatomic potentials "
                    "for rapid analysis of inelastic neutron scattering data"
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
                "hardware": str(arguments.get("hardware", "Modal T4")),
                "device": results["device"],
            },
            "method_alignment": "same_model_partial_protocol",
            "dependency_versions": results["versions"],
            "dataset": {
                "archive_sha256": DATA_ARCHIVE_SHA256,
                "selected_cases": CASES,
                "archive_audit_material_count": 3009,
                "paper_reported_material_count": 4869,
            },
            "acceptance_contract": {
                "mean_frequency_mae_tolerance_meV": mean_threshold,
                "max_material_mae_tolerance_meV": worst_threshold,
                "relax_fmax_eV_per_A": force_threshold,
                "significant_imaginary_frequency_threshold_meV": -1.0,
                "threshold_rationale": (
                    "Declared before GPU execution. The mean gate is slightly above the "
                    "paper's 1.430077 meV global MatterSim mean, while the per-material "
                    "bound prevents a good average from hiding one poor chemistry."
                ),
            },
            "comparison_rows": table_rows,
            "scientific_decision": {
                "contract_version": "scientific-decision.v1",
                "outcome": "VALIDATED" if subset_passed else "REVIEW",
                "calibration": {
                    "status": "INSUFFICIENT_EVIDENCE",
                    "accepted_case_count": 0,
                    "minimum_case_count": 30,
                },
                "scope": (
                    "Six released crystals evaluated with the declared MatterSim "
                    "harmonic-phonon protocol and DFT force sets."
                ),
                "headline": (
                    "MatterSim reproduced the 2025 paper's low-error phonon behaviour "
                    "on AtomForge's six-crystal released-data subset."
                    if subset_passed
                    else "The bounded 2025 phonon reproduction needs scientific review."
                ),
                "quality_checks": [
                    {
                        "label": "Six-case phonon reproduction",
                        "status": "PASS" if subset_passed else "FAILED",
                        "value": 1 if subset_passed else 0,
                        "unit": "gate",
                        "criterion": "declared aggregate and per-material error gates pass",
                    }
                ],
                "supported_claims": [
                    "This exact MatterSim checkpoint can approximate DFT harmonic phonons "
                    "across the six tested metallic, covalent, semiconductor, and ionic crystals.",
                    "The released DFT force sets, fixed-cell relaxations, finite displacements, "
                    "and q-space comparison are independently inspectable.",
                ],
                "limitations": [
                    "This is a six-material subset, not a rerun of the 4,869-crystal leaderboard.",
                    "Phonopy 4.3.1 replaces the paper's 2.28.0 because the latter does not "
                    "build in AtomForge's Python 3.12 runtime.",
                    "The released archive contains 3,009 directories, fewer than "
                    "the paper reports.",
                    "The run compares harmonic phonons to DFT force sets; it does not reproduce "
                    "the paper's experimental neutron-scattering overlays.",
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
        raise SystemExit("usage: mattersim_phonon_subset.py INPUT_JSON OUTPUT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
