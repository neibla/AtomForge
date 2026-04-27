"""
fetch.py — Pull crystal structures and DFT reference data from the Materials Project API.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ase import Atoms
from mp_api.client import MPRester
from pymatgen.io.ase import AseAtomsAdaptor

MP_API_KEY = os.environ.get("MP_API_KEY", "")

BENCHMARK_MATERIALS: dict[str, str] = {
    "W": "mp-91",
    "Cu": "mp-30",
    "Fe": "mp-13",
}


@dataclass
class StructureRecord:
    material_id: str
    formula: str
    atoms: Atoms
    dft_energy_per_atom: float
    dft_forces: list[list[float]]
    metadata: dict[str, Any] = field(default_factory=dict)


def fetch_structure(material_id: str, *, api_key: str | None = None) -> StructureRecord:
    key = api_key or MP_API_KEY
    if not key:
        raise OSError("Set MP_API_KEY environment variable.")

    with MPRester(key) as mpr:
        # Detect if input is a chemical formula/element (W, Cu, Fe) or an MP ID (mp-91)
        if "-" not in material_id:
            print(f"  Searching for stable benchmark of formula: {material_id}...")
            docs = mpr.materials.summary.search(
                formula=[material_id],
                is_stable=True,
                fields=[
                    "material_id",
                    "formula_pretty",
                    "energy_per_atom",
                    "structure",
                    "last_updated",
                ],
            )
        else:
            print(f"  Fetching specific Material ID: {material_id}...")
            docs = mpr.materials.summary.search(
                material_ids=[material_id],
                fields=[
                    "material_id",
                    "formula_pretty",
                    "energy_per_atom",
                    "structure",
                    "last_updated",
                ],
            )

        if not docs:
            raise ValueError(f"No stable structure found for '{material_id}' in Materials Project.")

        # Sort by energy_above_hull (stability) then by date (most recent)
        doc = sorted(
            docs,
            key=lambda x: (
                getattr(x, "energy_above_hull", 0) or 0,
                -getattr(x, "last_updated", 0).timestamp()
                if getattr(x, "last_updated", None)
                else 0,
            ),
        )[0]

        dft_epa = doc.energy_per_atom

        # Fetch forces using the specific Task ID if available
        forces: list[list[float]] = []
        try:
            # Get the primary task ID associated with this summary doc
            task_id = mpr.materials.summary.get_data_by_id(material_id).last_updated_task_id
            task_doc = mpr.tasks.get_data_by_id(task_id)
            if task_doc and task_doc.output and task_doc.output.ionic_steps:
                forces = task_doc.output.ionic_steps[-1].forces or []
        except Exception:
            # Fallback to general task search if specific ID fails
            try:
                tasks = mpr.tasks.search(chemsys=doc.chemsys, fields=["output"])
                if tasks and tasks[0].output and tasks[0].output.ionic_steps:
                    forces = tasks[0].output.ionic_steps[-1].forces or []
            except Exception:
                forces = []

    adaptor = AseAtomsAdaptor()
    atoms = adaptor.get_atoms(doc.structure)

    return StructureRecord(
        material_id=doc.material_id,
        formula=doc.formula_pretty,
        atoms=atoms,
        dft_energy_per_atom=dft_epa,
        dft_forces=forces,
        metadata={"mp_id": doc.material_id},
    )


def fetch_benchmark_set(
    elements: list[str] | None = None, *, api_key: str | None = None
) -> list[StructureRecord]:
    targets = elements or list(BENCHMARK_MATERIALS.keys())
    records: list[StructureRecord] = []
    for elem in targets:
        mid = BENCHMARK_MATERIALS[elem]
        print(f"  Fetching {elem} ({mid})…")
        try:
            records.append(fetch_structure(mid, api_key=api_key))
        except Exception as e:
            print(f"  Failed to fetch {elem}: {e}")
    return records


def make_vacancy_supercell(
    record: StructureRecord, supercell: tuple[int, int, int] = (3, 3, 3)
) -> StructureRecord:
    import numpy as np
    from ase.build import make_supercell

    sc_atoms = make_supercell(record.atoms, np.diag(supercell))
    if len(sc_atoms) > 1:
        del sc_atoms[0]  # Create vacancy

    return StructureRecord(
        material_id=record.material_id + "_vac",
        formula=record.formula + "_vacancy",
        atoms=sc_atoms,
        dft_energy_per_atom=record.dft_energy_per_atom,
        dft_forces=[],
        metadata={**record.metadata, "supercell": supercell, "defect": "vacancy"},
    )


def make_alloy_supercell(
    record: StructureRecord,
    supercell: tuple[int, int, int] = (3, 3, 3),
    dopants: dict[str, float] | None = None,
) -> StructureRecord:
    """
    Creates a supercell and replaces atoms with multiple dopant elements based on concentrations.
    """
    import numpy as np
    from pymatgen.core import Element

    # 1. Build host supercell
    atoms = record.atoms.copy()
    atoms = atoms * supercell
    n_total = len(atoms)

    # 2. Multi-Doping logic
    if dopants:
        # Get all numbers and available indices
        numbers = atoms.get_atomic_numbers()
        available_indices = np.arange(n_total)
        np.random.shuffle(available_indices)

        current_start = 0
        for element_sym, concentration in dopants.items():
            n_dopant = int(n_total * concentration)
            if n_dopant > 0 and current_start + n_dopant <= n_total:
                # Find dopant atomic number
                dopant_num = Element(element_sym).Z

                # Pick unique indices for this element
                target_indices = available_indices[current_start : current_start + n_dopant]
                numbers[target_indices] = dopant_num
                current_start += n_dopant

        atoms.set_atomic_numbers(numbers)

    return StructureRecord(
        material_id=f"{record.material_id}_alloy_{'_'.join(dopants.keys()) if dopants else 'none'}",
        formula=atoms.get_chemical_formula(),
        atoms=atoms,
        dft_energy_per_atom=record.dft_energy_per_atom,
        dft_forces=[],
        metadata={**record.metadata, "supercell": supercell, "dopants": dopants},
    )
