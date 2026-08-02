import json
import math

import pytest

from atomforge.node_scripts.berger_vacancy_protocol import (
    extract_published_vacancy_value,
    formation_energy,
    repeat_factors_over_minimum,
    select_database_rows,
    self_consistent_formation_energy,
    structure_fingerprint,
)


def test_repeat_factors_make_every_length_strictly_greater_than_ten_angstrom():
    factors = repeat_factors_over_minimum([3.2, 5.1, 10.0], 10.0)

    assert factors == [4, 2, 2]
    assert all(length * factor > 10.0 for length, factor in zip([3.2, 5.1, 10.0], factors))


def test_vacancy_formation_energy_contract():
    pristine_total = -100.0
    defect_total = -88.0

    assert formation_energy(defect_total, pristine_total, -10.0) == pytest.approx(2.0)
    assert self_consistent_formation_energy(defect_total, pristine_total, 10) == pytest.approx(2.0)


def test_reference_extraction_prefers_vacancy_formation_energy_over_other_energies():
    value, path = extract_published_vacancy_value(
        {
            "energy_per_atom": -8.0,
            "chemical_potential": -9.0,
            "results": {"vacancy_formation_energies_eV": [1.75, 2.1]},
        },
        value_index=1,
    )

    assert value == pytest.approx(2.1)
    assert "vacancy_formation_energies" in path


def test_structure_fingerprint_is_order_stable_and_rejects_nan():
    left = structure_fingerprint({"cell": [[1.0]], "numbers": [1]})
    right = structure_fingerprint({"numbers": [1], "cell": [[1.0]]})

    assert left == right
    with pytest.raises(ValueError):
        structure_fingerprint({"value": math.nan})


def test_select_database_rows_reads_the_released_mp_keyed_json_shape(tmp_path):
    source = tmp_path / "Vacancies.json"
    source.write_text(
        json.dumps(
            {
                "mp-91": {
                    "Symbols": ["W", "W"],
                    "Vacancy": [3.61, 3.61],
                    "Cell": [[3.17, 0, 0], [0, 3.17, 0], [0, 0, 3.17]],
                    "Positions": [[0, 0, 0], [1.585, 1.585, 1.585]],
                }
            }
        ),
        encoding="utf-8",
    )

    rows = select_database_rows(
        source,
        [
            {
                "case_id": "bcc-w",
                "mp_id": "mp-91",
                "expected_element": "W",
                "vacancy_value_index": 0,
            }
        ],
    )

    assert rows[0]["published_vacancy_formation_energy_eV"] == pytest.approx(3.61)
    assert rows[0]["published_reference_path"] == "Vacancy.0"
    assert rows[0]["minimum_supercell_length_A"] > 10.0
    assert rows[0]["pristine_atoms"] == 128
    assert rows[0]["defect_atoms"] == 127
