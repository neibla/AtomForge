from __future__ import annotations

import math
import os
import time
from typing import Any

import numpy as np
from ase import Atoms, units
from ase.geometry import find_mic, get_distances
from ase.md.langevin import Langevin
from ase.optimize import FIRE, LBFGS

from atomforge.contracts import SimulationMode
from atomforge.schemas import (
    AtomsData,
    NVTParams,
    NVTResult,
    PKAFrameMetric,
    PKAParams,
    PKAResult,
    RelaxParams,
    RelaxResult,
    SimulationResult,
    SinglePointParams,
    SinglePointResult,
)


def electronic_stopping_friction(
    kinetic_energies: list[float] | np.ndarray,
    stopping_power: float,
    base_friction: float,
) -> np.ndarray:
    energies = np.asarray(kinetic_energies, dtype=float)
    return np.where(energies > 10.0, stopping_power, base_friction).reshape(-1, 1)


def locate_wigner_seitz_defect_details(
    initial_positions: list[list[float]] | np.ndarray,
    final_positions: list[list[float]] | np.ndarray,
    cell: list[list[float]] | np.ndarray,
    pbc: bool | list[bool] | tuple[bool, bool, bool] = True,
) -> tuple[int, int, list[list[float]], list[list[float]]]:
    initial = np.asarray(initial_positions, dtype=float)
    final = np.asarray(final_positions, dtype=float)
    _, distances = get_distances(final, initial, cell=np.asarray(cell), pbc=pbc)
    nearest_sites = np.argmin(distances, axis=1)
    occupancy = np.bincount(nearest_sites, minlength=len(initial))
    vacancy_positions = initial[occupancy == 0].tolist()
    interstitial_positions: list[list[float]] = []
    for site in np.flatnonzero(occupancy > 1):
        candidates = np.flatnonzero(nearest_sites == site)
        representative = candidates[np.argmax(distances[candidates, site])]
        interstitial_positions.append(final[representative].tolist())
    return (
        int(np.sum(occupancy == 0)),
        int(np.sum(occupancy > 1)),
        vacancy_positions,
        interstitial_positions,
    )


def locate_wigner_seitz_defects(
    initial_positions: list[list[float]] | np.ndarray,
    final_positions: list[list[float]] | np.ndarray,
    cell: list[list[float]] | np.ndarray,
    pbc: bool | list[bool] | tuple[bool, bool, bool] = True,
) -> tuple[int, int, list[list[float]]]:
    vacancies, interstitials, vacancy_positions, _ = locate_wigner_seitz_defect_details(
        initial_positions, final_positions, cell, pbc
    )
    return vacancies, interstitials, vacancy_positions


def count_wigner_seitz_defects(
    initial_positions: list[list[float]] | np.ndarray,
    final_positions: list[list[float]] | np.ndarray,
    cell: list[list[float]] | np.ndarray,
    pbc: bool | list[bool] | tuple[bool, bool, bool] = True,
) -> tuple[int, int]:
    vacancies, interstitials, _ = locate_wigner_seitz_defects(
        initial_positions, final_positions, cell, pbc
    )
    return vacancies, interstitials


def force_metrics(forces: np.ndarray) -> tuple[float, float]:
    """Return maximum per-atom vector norm and the global L2 force norm."""
    array = np.asarray(forces, dtype=float)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError("forces must have shape (n_atoms, 3)")
    per_atom = np.linalg.norm(array, axis=1)
    return float(per_atom.max(initial=0.0)), float(np.linalg.norm(array))


class FreeEnergyWrapper:
    """Mirror calculator energy into ASE's optional free_energy property."""

    def __init__(self, calculator):
        self.calc = calculator

    def __getattr__(self, name):
        return getattr(self.calc, name)

    def calculate(self, atoms=None, properties=None, system_changes=None):
        self.calc.calculate(atoms, properties, system_changes)
        if "energy" in self.calc.results:
            self.calc.results["free_energy"] = self.calc.results["energy"]


class SimulationEngine:
    """Pure physics engine; model identity and execution infrastructure live elsewhere."""

    def __init__(
        self,
        model: str = "medium",
        device: str = "cpu",
        calculator=None,
        *,
        model_head: str | None = None,
    ):
        self.device = device
        if calculator is not None:
            self.calc = FreeEnergyWrapper(calculator)
            return

        dtype = "float32" if device == "mps" else "float64"
        if os.path.exists(model):
            if not model_head:
                raise ValueError(
                    "model_head is required when loading an explicit multi-head checkpoint"
                )
            from mace.calculators import MACECalculator

            calculator = MACECalculator(
                model_paths=model,
                device=device,
                default_dtype=dtype,
                compute_stress=True,
                head=model_head,
            )
        else:
            if model_head is not None:
                raise ValueError("model_head is only valid for an explicit checkpoint")
            from mace.calculators import mace_mp

            calculator = mace_mp(model=model, device=device, default_dtype=dtype)
        self.calc = FreeEnergyWrapper(calculator)

    def run(
        self,
        atoms_input: AtomsData,
        mode: SimulationMode,
        params: dict[str, Any],
        seed: int = 0,
    ) -> SimulationResult:
        rng = np.random.default_rng(seed)
        atoms = Atoms(
            symbols=atoms_input.symbols,
            positions=atoms_input.positions,
            cell=atoms_input.cell,
            pbc=atoms_input.pbc,
        )
        if len(atoms) <= 1:
            raise ValueError(
                "Simulation requires a supercell with more than 1 atom. "
                "Use an ALLOY node to expand the cell."
            )
        atoms.calc = self.calc
        try:
            atoms.get_potential_energy()
            atoms.get_forces()
        except Exception as exc:
            raise RuntimeError("Calculator preflight failed") from exc

        mode_params = {key: value for key, value in params.items() if key not in {"mode", "trials"}}
        started = time.perf_counter()
        if mode == "pka":
            result = self._run_pka(atoms, mode_params, rng)
        elif mode == "relax":
            result = self._run_relax(atoms, mode_params)
        elif mode == "single_point":
            result = self._run_single_point(atoms, mode_params)
        elif mode == "nvt":
            result = self._run_nvt(atoms, mode_params, rng)
        else:
            raise ValueError(f"Unknown simulation mode: {mode}")
        result.seed = seed
        result.runtime_ms = (time.perf_counter() - started) * 1000
        return result

    def _run_pka(
        self,
        atoms: Atoms,
        params_dict: dict[str, Any],
        rng: np.random.Generator,
    ) -> PKAResult:
        params = PKAParams.model_validate(params_dict)
        if not params.allow_unvalidated_short_range:
            raise ValueError(
                "PKA execution is blocked without a validated short-range hybrid. "
                "Set allow_unvalidated_short_range=true only for an explicitly "
                "labelled infrastructure demonstration."
            )
        initial = atoms.get_positions().copy()
        pka_index = len(atoms) // 2
        speed = np.sqrt(2 * params.energy_ev / atoms[pka_index].mass)
        direction = np.array([2.3, 1.1, 4.7]) + rng.normal(0, 0.3, 3)
        velocities = np.zeros_like(initial)
        velocities[pka_index] = direction / np.linalg.norm(direction) * speed
        atoms.set_velocities(velocities)
        dynamics = Langevin(
            atoms,
            timestep=params.timestep_fs * units.fs,
            temperature_K=params.temperature_K,
            friction=params.base_friction,
            rng=rng,
        )
        trajectory: list[list[list[float]]] = []
        frame_metrics: list[PKAFrameMetric] = []
        vacancies = interstitials = 0
        vacancy_positions: list[list[float]] = []
        interstitial_positions: list[list[float]] = []
        for block in range(params.n_blocks):
            kinetic = 0.5 * atoms.get_masses() * np.sum(atoms.get_velocities() ** 2, axis=1)
            dynamics.set_friction(
                electronic_stopping_friction(kinetic, params.stopping_power, params.base_friction)
            )
            dynamics.run(params.steps_per_block)
            positions = atoms.get_positions().copy()
            trajectory.append(positions.tolist())
            (
                vacancies,
                interstitials,
                vacancy_positions,
                interstitial_positions,
            ) = locate_wigner_seitz_defect_details(
                initial, positions, atoms.get_cell(), atoms.get_pbc()
            )
            _, displacements = find_mic(
                positions - initial, cell=atoms.get_cell(), pbc=atoms.get_pbc()
            )
            frame_metrics.append(
                PKAFrameMetric(
                    frame=block,
                    step=(block + 1) * params.steps_per_block,
                    time_fs=(block + 1) * params.steps_per_block * params.timestep_fs,
                    kinetic_energy_ev=float(atoms.get_kinetic_energy()),
                    potential_energy_ev=float(atoms.get_potential_energy()),
                    temperature_K=float(atoms.get_temperature()),
                    n_defects=vacancies,
                    interstitials=interstitials,
                    displaced_atoms=int(np.sum(displacements > 0.5)),
                    max_displacement_angstrom=float(np.max(displacements)),
                    vacancy_positions=vacancy_positions,
                    interstitial_positions=interstitial_positions,
                )
            )
        final = atoms.get_positions()
        return PKAResult(
            seed=0,
            n_defects=vacancies,
            interstitials=interstitials,
            vacancy_positions=vacancy_positions,
            interstitial_positions=interstitial_positions,
            pka_index=pka_index,
            frame_metrics=frame_metrics,
            energy=float(atoms.get_potential_energy() / len(atoms)),
            energies=atoms.get_potential_energies().tolist(),
            trajectory=trajectory,
            trajectory_stride=params.steps_per_block,
            trajectory_total_steps=params.n_blocks * params.steps_per_block,
            final_positions=final.tolist(),
            initial_positions=initial.tolist(),
            atomic_numbers=atoms.get_atomic_numbers().tolist(),
            cell=atoms.get_cell().tolist(),
            pbc=atoms.get_pbc().tolist(),
        )

    def _run_relax(self, atoms: Atoms, params_dict: dict[str, Any]) -> RelaxResult:
        params = RelaxParams.model_validate(params_dict)
        initial = atoms.get_positions().copy()
        optimizer = FIRE if params.optimizer == "fire" else LBFGS
        optimizer(atoms, logfile=None).run(fmax=params.fmax, steps=params.max_steps)
        forces = np.asarray(atoms.get_forces())
        max_force, force_norm = force_metrics(forces)
        return RelaxResult(
            seed=0,
            potential_energy=float(atoms.get_potential_energy() / len(atoms)),
            max_force=max_force,
            force_norm=force_norm,
            energies=atoms.get_potential_energies().tolist(),
            positions=atoms.get_positions().tolist(),
            initial_positions=initial.tolist(),
            final_positions=atoms.get_positions().tolist(),
            cell=atoms.get_cell().tolist(),
            atomic_numbers=atoms.get_atomic_numbers().tolist(),
            pbc=atoms.get_pbc().tolist(),
        )

    def _run_single_point(self, atoms: Atoms, params_dict: dict[str, Any]) -> SinglePointResult:
        params = SinglePointParams.model_validate(params_dict)
        if params.atom_index >= len(atoms):
            raise ValueError(f"atom_index {params.atom_index} is outside the structure")
        if params.cell_scale != 1.0:
            atoms.set_cell(atoms.get_cell() * params.cell_scale, scale_atoms=True)
        initial = atoms.get_positions().copy()
        atoms.positions[params.atom_index] += np.asarray(params.displacement)
        forces = np.asarray(atoms.get_forces())
        max_force, force_norm = force_metrics(forces)
        return SinglePointResult(
            seed=0,
            potential_energy=float(atoms.get_potential_energy() / len(atoms)),
            max_force=max_force,
            force_norm=force_norm,
            forces=forces.tolist(),
            positions=atoms.get_positions().tolist(),
            initial_positions=initial.tolist(),
            final_positions=atoms.get_positions().tolist(),
            cell=atoms.get_cell().tolist(),
            atomic_numbers=atoms.get_atomic_numbers().tolist(),
            pbc=atoms.get_pbc().tolist(),
        )

    def _run_nvt(
        self,
        atoms: Atoms,
        params_dict: dict[str, Any],
        rng: np.random.Generator,
    ) -> NVTResult:
        params = NVTParams.model_validate(params_dict)
        initial = atoms.get_positions().copy()
        stride = max(
            params.frame_stride,
            math.ceil((params.n_steps + 1) / params.max_recorded_frames),
        )
        trajectory: list[list[list[float]]] = []
        temperatures: list[float] = []
        dynamics = Langevin(
            atoms,
            timestep=params.timestep_fs * units.fs,
            temperature_K=params.temperature_K,
            friction=params.friction_per_fs / units.fs,
            rng=rng,
        )

        def record() -> None:
            trajectory.append(atoms.get_positions().tolist())
            temperatures.append(float(atoms.get_temperature()))

        dynamics.attach(record, interval=stride)
        dynamics.run(params.n_steps)
        if not trajectory:
            record()
        sample = trajectory[-min(params.analysis_frames, len(trajectory)) :]
        (
            bond_stats,
            angle_stats,
            rdf_stats,
            analysis_applicable,
            quality_passed,
        ) = self._analyze_trajectory(
            atoms,
            sample,
            pair_rules=params.analysis_pairs,
            minimum_distance_A=params.minimum_distance_A,
        )
        max_force, _ = force_metrics(np.asarray(atoms.get_forces()))
        return NVTResult(
            seed=0,
            potential_energy=float(atoms.get_potential_energy() / len(atoms)),
            mean_temperature_K=float(np.mean(temperatures)),
            std_temperature_K=float(np.std(temperatures)),
            max_force=max_force,
            n_frames=len(trajectory),
            stable=analysis_applicable and quality_passed,
            analysis_applicable=analysis_applicable,
            trajectory_quality_passed=quality_passed,
            bond_distance_stats=bond_stats,
            bond_angle_stats=angle_stats,
            rdf_stats=rdf_stats,
            trajectory=trajectory,
            trajectory_stride=stride,
            trajectory_total_steps=params.n_steps,
            trajectory_truncated=stride > 1,
            initial_positions=initial.tolist(),
            final_positions=atoms.get_positions().tolist(),
            positions=atoms.get_positions().tolist(),
            cell=atoms.get_cell().tolist(),
            atomic_numbers=atoms.get_atomic_numbers().tolist(),
            pbc=atoms.get_pbc().tolist(),
            energies=atoms.get_potential_energies().tolist(),
        )

    def _analyze_trajectory(
        self,
        atoms: Atoms,
        trajectory: list[list[list[float]]],
        *,
        pair_rules: dict[str, float],
        minimum_distance_A: float,
    ) -> tuple[
        dict[str, dict[str, float]],
        dict[str, dict[str, float]],
        dict[str, dict[str, Any]],
        bool,
        bool,
    ]:
        symbols = np.asarray(atoms.get_chemical_symbols())
        applicable_rules: dict[str, tuple[str, str, float]] = {}
        for label, cutoff in pair_rules.items():
            first, second = label.split("-", maxsplit=1)
            if first in symbols and second in symbols:
                applicable_rules[label] = (first, second, cutoff)
        distances_by_pair = {label: [] for label in applicable_rules}
        angles_by_pair: dict[str, list[float]] = {}
        rdf_bins = np.arange(0.0, 5.02, 0.02)
        rdf_counts = {label: np.zeros(len(rdf_bins) - 1) for label in applicable_rules}
        upper_i, upper_j = np.triu_indices(len(atoms), k=1)
        quality_passed = True
        for positions in trajectory:
            frame = atoms.copy()
            frame.set_positions(positions)
            distances = frame.get_all_distances(mic=True)
            if not np.isfinite(distances).all():
                quality_passed = False
                continue
            pair_distances = distances[upper_i, upper_j]
            if len(pair_distances) and float(pair_distances.min()) < minimum_distance_A:
                quality_passed = False
            for label, (center_symbol, neighbor_symbol, cutoff) in applicable_rules.items():
                if center_symbol == neighbor_symbol:
                    mask = (symbols[upper_i] == center_symbol) & (
                        symbols[upper_j] == neighbor_symbol
                    )
                else:
                    mask = (
                        (symbols[upper_i] == center_symbol) & (symbols[upper_j] == neighbor_symbol)
                    ) | (
                        (symbols[upper_i] == neighbor_symbol) & (symbols[upper_j] == center_symbol)
                    )
                values = distances[upper_i[mask], upper_j[mask]]
                distances_by_pair[label].extend(values[values <= cutoff].tolist())
                rdf_counts[label] += np.histogram(values, bins=rdf_bins)[0]
                centers = np.flatnonzero(symbols == center_symbol)
                neighbors = np.flatnonzero(symbols == neighbor_symbol)
                angle_label = f"{neighbor_symbol}-{center_symbol}-{neighbor_symbol}"
                for center in centers:
                    near = neighbors[distances[center, neighbors] <= cutoff]
                    near = near[near != center]
                    for left in range(len(near)):
                        for right in range(left + 1, len(near)):
                            first_vector = frame.get_distance(
                                center, near[left], mic=True, vector=True
                            )
                            second_vector = frame.get_distance(
                                center, near[right], mic=True, vector=True
                            )
                            denominator = np.linalg.norm(first_vector) * np.linalg.norm(
                                second_vector
                            )
                            if denominator == 0:
                                quality_passed = False
                                continue
                            cosine = np.clip(
                                np.dot(first_vector, second_vector) / denominator,
                                -1.0,
                                1.0,
                            )
                            angles_by_pair.setdefault(angle_label, []).append(
                                float(np.degrees(np.arccos(cosine)))
                            )

        def summarize(values: list[float]) -> dict[str, float]:
            array = np.asarray(values, dtype=float)
            if not len(array):
                return {"count": 0.0}
            return {
                "mean": float(np.mean(array)),
                "std": float(np.std(array)),
                "min": float(np.min(array)),
                "max": float(np.max(array)),
                "count": float(len(array)),
            }

        rdf_stats: dict[str, dict[str, Any]] = {}
        cell_volume = abs(float(np.linalg.det(atoms.get_cell())))
        shell_volume = (4.0 / 3.0) * np.pi * (rdf_bins[1:] ** 3 - rdf_bins[:-1] ** 3)
        for label, (first, second, _) in applicable_rules.items():
            expected = (
                int(np.sum(symbols == first))
                * int(np.sum(symbols == second))
                / cell_volume
                * shell_volume
                * max(len(trajectory), 1)
                if cell_volume > 0
                else np.zeros_like(shell_volume)
            )
            normalized = np.divide(
                rdf_counts[label],
                expected,
                out=np.zeros_like(rdf_counts[label]),
                where=expected > 0,
            )
            rdf_stats[label] = {
                "bin_width_A": 0.02,
                "r_max_A": 5.0,
                "r_A": ((rdf_bins[:-1] + rdf_bins[1:]) / 2.0).tolist(),
                "g_r": np.nan_to_num(normalized).tolist(),
            }
        if not np.isfinite(atoms.get_positions()).all():
            quality_passed = False
        return (
            {label: summarize(values) for label, values in distances_by_pair.items()},
            {label: summarize(values) for label, values in angles_by_pair.items()},
            rdf_stats,
            bool(applicable_rules),
            quality_passed,
        )
