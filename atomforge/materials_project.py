"""Materials Project structure and reference-data Adapter."""

from __future__ import annotations

import os

from mp_api.client import MPRester
from pymatgen.io.ase import AseAtomsAdaptor

from atomforge.structures import StructureRecord

MP_API_KEY = os.environ.get("MP_API_KEY", "")


def fetch_structure(material_id: str, *, api_key: str | None = None) -> StructureRecord:
    key = api_key or MP_API_KEY
    if not key:
        raise OSError("Set MP_API_KEY environment variable.")

    with MPRester(key) as mpr:
        # Accept either a chemical formula/element (W, Cu, Fe) or an MP ID (mp-91).
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

        doc = sorted(
            docs,
            key=lambda item: (
                getattr(item, "energy_above_hull", 0) or 0,
                -getattr(item, "last_updated", 0).timestamp()
                if getattr(item, "last_updated", None)
                else 0,
            ),
        )[0]

        dft_epa = doc.energy_per_atom
        forces: list[list[float]] = []
        try:
            summary = mpr.materials.summary.get_data_by_id(str(doc.material_id))
            task_id = getattr(summary, "last_updated_task_id", None)
            task_doc = mpr.tasks.get_data_by_id(task_id) if task_id else None
            if task_doc and task_doc.output and task_doc.output.ionic_steps:
                forces = task_doc.output.ionic_steps[-1].forces or []
        except Exception:
            forces = []

    atoms = AseAtomsAdaptor().get_atoms(doc.structure)
    return StructureRecord(
        material_id=doc.material_id,
        formula=doc.formula_pretty,
        atoms=atoms,
        dft_energy_per_atom=dft_epa,
        dft_forces=forces,
        metadata={
            "source": "Materials Project",
            "mp_id": str(doc.material_id),
            "dft_energy_per_atom": dft_epa,
            "forces_available": bool(forces),
        },
    )
