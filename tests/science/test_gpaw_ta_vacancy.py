from pathlib import Path

import numpy as np
import pytest

from atomforge.node_scripts.gpaw_ta_vacancy import (
    _formation_energy_eV,
    _max_force_norm,
    _scf_energy_change_eV,
)


def test_vacancy_formation_energy_uses_same_cell_bulk_chemical_potential():
    formation = _formation_energy_eV(
        -1261.0,
        -1271.0,
        defect_atoms=127,
        pristine_atoms=128,
    )

    assert formation == pytest.approx(0.0703125)


def test_vacancy_formation_energy_rejects_non_vacancy_atom_counts():
    with pytest.raises(ValueError, match="N-1"):
        _formation_energy_eV(
            -1261.0,
            -1271.0,
            defect_atoms=126,
            pristine_atoms=128,
        )


def test_max_force_uses_per_atom_vector_norm_not_largest_component():
    forces = np.array([[0.02, 0.02, 0.02], [0.01, 0.0, 0.0]])

    assert _max_force_norm(forces) == pytest.approx(0.02 * 3**0.5)


def test_final_scf_energy_change_is_parsed_from_new_gpaw_log(tmp_path: Path):
    log = tmp_path / "gpaw.txt"
    log.write_text(
        "|iter:  54| 01:46:02 |-1261.232919c| -7.23 | -6.33c|\n"
        "|iter:  55| 01:46:05 |-1261.232926c| -7.44c| -6.48c|\n",
        encoding="utf-8",
    )

    assert _scf_energy_change_eV(log) == pytest.approx(7e-6)


def test_final_scf_energy_change_fails_closed_without_two_energies(tmp_path: Path):
    log = tmp_path / "gpaw.txt"
    log.write_text(
        "|iter:   1| 01:45:00 |-1261.000000c| -2.00 | -1.00|\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="two parseable"):
        _scf_energy_change_eV(log)
