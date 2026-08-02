"""Pure structure transforms used by ALLOY DAG nodes."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any

from atomforge.structures import StructureRecord


def _structure_sha256(atoms: Any) -> str:
    """Hash the structural inputs that affect a transform's scientific identity."""

    import numpy as np

    payload = {
        "symbols": list(atoms.get_chemical_symbols()),
        "positions": np.asarray(atoms.get_positions(), dtype=float).tolist(),
        "cell": np.asarray(atoms.get_cell(), dtype=float).tolist(),
        "pbc": [bool(value) for value in atoms.get_pbc()],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _composition_metadata(atoms: Any) -> dict[str, Any]:
    counts = Counter(atoms.get_chemical_symbols())
    total = len(atoms)
    return {
        "realized_element_counts": dict(sorted(counts.items())),
        "realized_element_fractions": {
            symbol: count / total for symbol, count in sorted(counts.items())
        },
    }


def make_vacancy_supercell(
    record: StructureRecord, supercell: tuple[int, int, int] = (3, 3, 3)
) -> StructureRecord:
    import numpy as np
    from ase.build import make_supercell

    sc_atoms = make_supercell(record.atoms, np.diag(supercell))
    input_count = len(sc_atoms)
    input_structure_sha256 = _structure_sha256(record.atoms)
    if input_count < 2:
        raise ValueError("A vacancy transform requires at least two atoms")
    removed_indices: list[int] = []
    del sc_atoms[0]
    removed_indices.append(0)

    metadata = {
        **record.metadata,
        "supercell": supercell,
        "defect": "vacancy",
        "reference_energy": "pristine structure only; recompute for defect",
        "transformation": {
            "kind": "vacancy",
            "implementation_version": "vacancy.v2",
            "input_atom_count": input_count,
            "output_atom_count": len(sc_atoms),
            "supercell": list(supercell),
            "removed_atom_indices": removed_indices,
            "input_structure_sha256": input_structure_sha256,
            "output_structure_sha256": _structure_sha256(sc_atoms),
        },
        **_composition_metadata(sc_atoms),
    }

    return StructureRecord(
        material_id=record.material_id + "_vac",
        formula=record.formula + "_vacancy",
        atoms=sc_atoms,
        dft_energy_per_atom=None,
        dft_forces=[],
        metadata=metadata,
    )


def _dopant_counts(
    n_total: int,
    dopants: dict[str, float],
) -> dict[str, int]:
    """Allocate a deterministic integer composition without silently dropping species."""

    if sum(dopants.values()) > 1:
        raise ValueError("Dopant concentrations must sum to at most 1")
    positive = [symbol for symbol, concentration in dopants.items() if concentration > 0]
    if len(positive) > n_total:
        raise ValueError(
            "Cannot represent every positive dopant concentration in a structure "
            f"with only {n_total} atoms."
        )

    raw = {symbol: n_total * concentration for symbol, concentration in dopants.items()}
    counts = {
        symbol: (max(1, math.floor(value)) if dopants[symbol] > 0 else 0)
        for symbol, value in raw.items()
    }
    target = max(int(round(sum(raw.values()))), sum(counts.values()))
    target = min(target, n_total)
    remaining = target - sum(counts.values())
    ranked = sorted(
        raw,
        key=lambda symbol: (-(raw[symbol] - math.floor(raw[symbol])), symbol),
    )
    for index in range(max(0, remaining)):
        counts[ranked[index % len(ranked)]] += 1
    return counts


def make_alloy_supercell(
    record: StructureRecord,
    supercell: tuple[int, int, int] = (3, 3, 3),
    dopants: dict[str, float] | None = None,
    seed: int = 0,
) -> StructureRecord:
    """Create a supercell and replace atoms using seeded concentrations."""

    import numpy as np
    from pymatgen.core import Element

    atoms = record.atoms.copy() * supercell
    n_total = len(atoms)
    input_structure_sha256 = _structure_sha256(record.atoms)

    requested_dopants = {
        str(symbol): float(concentration) for symbol, concentration in (dopants or {}).items()
    }
    selected_indices: dict[str, list[int]] = {}
    if requested_dopants:
        from ase.data import atomic_numbers

        for element_sym, concentration in requested_dopants.items():
            if element_sym not in atomic_numbers or atomic_numbers[element_sym] <= 0:
                raise ValueError(f"Unknown chemical symbol: {element_sym}")
            if not math.isfinite(concentration) or not 0 <= concentration <= 1:
                raise ValueError(f"Dopant concentration must be between 0 and 1: {element_sym}")

        numbers = atoms.get_atomic_numbers()
        available_indices = np.random.default_rng(seed).permutation(n_total)
        current_start = 0
        allocated_counts = _dopant_counts(n_total, requested_dopants)
        for element_sym in sorted(requested_dopants):
            n_dopant = allocated_counts[element_sym]
            target_indices = available_indices[current_start : current_start + n_dopant]
            numbers[target_indices] = Element(element_sym).Z
            selected_indices[element_sym] = [int(index) for index in target_indices]
            current_start += n_dopant

        atoms.set_atomic_numbers(numbers)

    realized_dopants = {
        symbol: len(indices) for symbol, indices in sorted(selected_indices.items())
    }
    metadata = {
        **record.metadata,
        "supercell": supercell,
        "dopants": requested_dopants,
        "requested_dopants": requested_dopants,
        "realized_dopants": realized_dopants,
        "selected_atom_indices": selected_indices,
        "seed": seed,
        "transformation": {
            "kind": "alloy",
            "implementation_version": "alloy.v2",
            "input_atom_count": len(record.atoms),
            "output_atom_count": n_total,
            "supercell": list(supercell),
            "requested_dopants": requested_dopants,
            "realized_dopants": realized_dopants,
            "selected_atom_indices": selected_indices,
            "seed": seed,
            "input_structure_sha256": input_structure_sha256,
            "output_structure_sha256": _structure_sha256(atoms),
        },
        **_composition_metadata(atoms),
    }

    return StructureRecord(
        material_id=f"{record.material_id}_alloy_{'_'.join(dopants.keys()) if dopants else 'none'}",
        formula=atoms.get_chemical_formula(),
        atoms=atoms,
        dft_energy_per_atom=None,
        dft_forces=[],
        metadata=metadata,
    )
