import numpy as np
import pytest
from ase import Atoms
from ase.calculators.calculator import Calculator, all_changes
from ase.calculators.lj import LennardJones

from atomforge.schemas import AtomsData, NVTParams, PKAParams, RelaxParams
from atomforge.simulator import (
    SimulationEngine,
    count_wigner_seitz_defects,
    electronic_stopping_friction,
    force_metrics,
)


def _argon_data(count: int = 2) -> AtomsData:
    positions = [[0.0, 0.0, 1.2 * index] for index in range(count)]
    atoms = Atoms(f"Ar{count}", positions=positions)
    atoms.set_cell([[8, 0, 0], [0, 8, 0], [0, 0, 8]])
    atoms.set_pbc([True, True, False])
    return AtomsData(
        symbols=atoms.get_chemical_symbols(),
        positions=atoms.get_positions().tolist(),
        cell=atoms.get_cell().tolist(),
        pbc=atoms.get_pbc().tolist(),
    )


def test_electronic_stopping_is_computed_per_atom():
    friction = electronic_stopping_friction(
        kinetic_energies=[5.0, 20.0],
        stopping_power=0.05,
        base_friction=0.002,
    )
    assert friction.tolist() == [[0.002], [0.05]]


def test_wigner_seitz_count_respects_periodic_boundaries():
    vacancies, interstitials = count_wigner_seitz_defects(
        initial_positions=[[0.1, 0.0, 0.0], [5.0, 0.0, 0.0]],
        final_positions=[[9.9, 0.0, 0.0], [5.0, 0.0, 0.0]],
        cell=[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]],
        pbc=[True, False, False],
    )
    assert vacancies == 0
    assert interstitials == 0


def test_atoms_data_preserves_partial_periodicity():
    assert _argon_data().pbc == (True, True, False)


def test_force_metrics_use_per_atom_vector_norm():
    maximum, global_norm = force_metrics(np.array([[3.0, 4.0, 0.0], [0.0, 0.0, 2.0]]))
    assert maximum == pytest.approx(5.0)
    assert global_norm == pytest.approx(np.sqrt(29.0))


def test_engine_initialization_and_relax():
    data = _argon_data()
    engine = SimulationEngine(device="cpu", calculator=LennardJones())
    params = RelaxParams(fmax=0.5)
    result = engine.run(data, mode="relax", params=params.model_dump())
    assert result.potential_energy < 0
    assert len(result.positions) == 2
    assert result.max_force <= params.fmax
    assert result.force_norm >= result.max_force
    assert result.final_positions == result.positions
    assert result.runtime_ms > 0


def test_engine_validation_error_for_single_atom():
    data = AtomsData(
        symbols=["H"],
        positions=[[0, 0, 0]],
        cell=[[5, 0, 0], [0, 5, 0], [0, 0, 5]],
    )
    with pytest.raises(ValueError, match="requires a supercell"):
        SimulationEngine(device="cpu", calculator=LennardJones()).run(
            data, mode="relax", params={"fmax": 0.5}
        )


class FailingCalculator(Calculator):
    implemented_properties = ["energy", "forces"]

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        raise RuntimeError("calculator unavailable")


def test_engine_stops_when_calculator_preflight_fails():
    with pytest.raises(RuntimeError, match="Calculator preflight failed"):
        SimulationEngine(device="cpu", calculator=FailingCalculator()).run(
            _argon_data(), mode="relax", params={"fmax": 0.5}
        )


def test_single_point_uses_same_force_definition_as_relaxation():
    result = SimulationEngine(device="cpu", calculator=LennardJones()).run(
        _argon_data(),
        mode="single_point",
        params={"displacement": [0.2, 0.0, 0.0]},
    )
    expected = np.linalg.norm(np.asarray(result.forces), axis=1).max()
    assert result.max_force == pytest.approx(expected)


def test_nvt_bounds_trajectory_and_does_not_claim_unconfigured_analysis():
    result = SimulationEngine(device="cpu", calculator=LennardJones()).run(
        _argon_data(),
        mode="nvt",
        params=NVTParams(
            n_steps=20,
            analysis_frames=5,
            frame_stride=1,
            max_recorded_frames=4,
        ).model_dump(),
        seed=7,
    )
    assert result.seed == 7
    assert result.n_frames <= 4
    assert result.trajectory_stride >= 5
    assert result.trajectory_total_steps == 20
    assert result.trajectory_truncated is True
    assert result.analysis_applicable is False
    assert result.trajectory_quality_passed is True
    assert result.stable is False
    assert result.bond_distance_stats == {}


def test_nvt_runs_declared_pair_analysis_only_when_applicable():
    result = SimulationEngine(device="cpu", calculator=LennardJones()).run(
        _argon_data(),
        mode="nvt",
        params=NVTParams(
            n_steps=2,
            frame_stride=1,
            max_recorded_frames=2,
            analysis_pairs={"Ar-Ar": 3.0},
        ).model_dump(),
        seed=8,
    )
    assert result.analysis_applicable is True
    assert "Ar-Ar" in result.bond_distance_stats


def test_pka_is_blocked_without_explicit_unsafe_demo_flag():
    engine = SimulationEngine(device="cpu", calculator=LennardJones())
    with pytest.raises(ValueError, match="blocked without a validated short-range hybrid"):
        engine.run(
            _argon_data(4),
            mode="pka",
            params=PKAParams(
                energy_ev=1.0,
                timestep_fs=0.01,
                n_blocks=1,
                steps_per_block=1,
            ).model_dump(),
        )


def test_pka_explicit_infrastructure_demo_emits_linked_evidence():
    result = SimulationEngine(device="cpu", calculator=LennardJones()).run(
        _argon_data(4),
        mode="pka",
        params=PKAParams(
            energy_ev=1.0,
            temperature_K=300.0,
            timestep_fs=0.01,
            n_blocks=2,
            steps_per_block=1,
            allow_unvalidated_short_range=True,
        ).model_dump(),
        seed=11,
    )
    assert result.seed == 11
    assert len(result.trajectory) == 2
    assert len(result.frame_metrics) == 2
    assert result.scientific_status == "EXPERIMENTAL_UNVALIDATED"
    assert result.frame_metrics[1].time_fs == pytest.approx(0.02)
    assert result.frame_metrics[1].vacancy_positions == result.vacancy_positions


def test_pka_local_rng_is_repeatable():
    engine = SimulationEngine(device="cpu", calculator=LennardJones())
    params = PKAParams(
        energy_ev=1.0,
        timestep_fs=0.01,
        n_blocks=1,
        steps_per_block=1,
        allow_unvalidated_short_range=True,
    ).model_dump()
    first = engine.run(_argon_data(4), mode="pka", params=params, seed=19)
    second = engine.run(_argon_data(4), mode="pka", params=params, seed=19)
    np.testing.assert_allclose(first.final_positions, second.final_positions)
