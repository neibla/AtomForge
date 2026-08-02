"""Internal structure record shared by data providers and transforms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ase import Atoms


@dataclass
class StructureRecord:
    material_id: str
    formula: str
    atoms: Atoms
    dft_energy_per_atom: float | None
    dft_forces: list[list[float]]
    metadata: dict[str, Any] = field(default_factory=dict)
