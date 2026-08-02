import pytest
from ase import Atoms

from atomforge.structure_transforms import make_alloy_supercell, make_vacancy_supercell
from atomforge.structures import StructureRecord


def test_alloy_substitution_is_reproducible_for_a_seed():
    atoms = Atoms(
        symbols=["W"] * 10,
        positions=[[float(index), 0.0, 0.0] for index in range(10)],
        cell=[[20.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]],
        pbc=True,
    )
    record = StructureRecord(
        material_id="fixture",
        formula="W10",
        atoms=atoms,
        dft_energy_per_atom=-1.0,
        dft_forces=[],
    )

    first = make_alloy_supercell(record, supercell=(1, 1, 1), dopants={"Ni": 0.2}, seed=7)
    second = make_alloy_supercell(record, supercell=(1, 1, 1), dopants={"Ni": 0.2}, seed=7)

    assert first.atoms.get_atomic_numbers().tolist() == second.atoms.get_atomic_numbers().tolist()
    assert first.metadata["requested_dopants"] == {"Ni": 0.2}
    assert first.metadata["realized_dopants"] == {"Ni": 2}
    assert first.metadata["realized_element_counts"]["Ni"] == 2
    assert (
        first.metadata["transformation"]["input_structure_sha256"]
        == second.metadata["transformation"]["input_structure_sha256"]
    )
    assert (
        first.metadata["transformation"]["output_structure_sha256"]
        == second.metadata["transformation"]["output_structure_sha256"]
    )

    different_seed = make_alloy_supercell(record, supercell=(1, 1, 1), dopants={"Ni": 0.2}, seed=8)
    assert (
        different_seed.metadata["transformation"]["output_structure_sha256"]
        != first.metadata["transformation"]["output_structure_sha256"]
    )


def test_vacancy_records_input_and_output_structure_hashes():
    atoms = Atoms(
        symbols=["W", "W"],
        positions=[[0.0, 0.0, 0.0], [1.5, 1.5, 1.5]],
        cell=[[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
        pbc=True,
    )
    record = StructureRecord(
        material_id="fixture",
        formula="W2",
        atoms=atoms,
        dft_energy_per_atom=None,
        dft_forces=[],
    )

    transformed = make_vacancy_supercell(record, supercell=(1, 1, 1))
    transformation = transformed.metadata["transformation"]

    assert transformation["input_atom_count"] == 2
    assert transformation["output_atom_count"] == 1
    assert len(transformation["input_structure_sha256"]) == 64
    assert len(transformation["output_structure_sha256"]) == 64
    assert transformation["input_structure_sha256"] != transformation["output_structure_sha256"]


def test_alloy_rejects_more_positive_species_than_atoms():
    atoms = Atoms(
        symbols=["W"] * 3,
        positions=[[float(index), 0.0, 0.0] for index in range(3)],
        cell=[[10.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]],
        pbc=True,
    )
    record = StructureRecord(
        material_id="fixture",
        formula="W3",
        atoms=atoms,
        dft_energy_per_atom=-1.0,
        dft_forces=[],
    )

    with pytest.raises(ValueError, match="every positive dopant"):
        make_alloy_supercell(
            record,
            supercell=(1, 1, 1),
            dopants={"Cr": 0.2, "Ni": 0.2, "Fe": 0.2, "Co": 0.2},
            seed=7,
        )
