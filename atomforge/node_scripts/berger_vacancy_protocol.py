"""Shared helpers for the bounded Berger vacancy-paper reproduction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MP_ID_PATTERN = re.compile(r"\bmp-\d+\b", re.IGNORECASE)


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(
    url: str,
    destination: Path,
    *,
    expected_md5: str,
) -> tuple[Path, bool]:
    """Download atomically and verify the published Zenodo checksum."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and file_digest(destination, "md5") == expected_md5:
        return destination, True

    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.",
        dir=destination.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "AtomForge-paper-reproduction/1.0"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            with temporary_path.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        actual_md5 = file_digest(temporary_path, "md5")
        if actual_md5 != expected_md5:
            raise ValueError(
                f"Dataset checksum mismatch: expected {expected_md5}, got {actual_md5}"
            )
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination, False


def repeat_factors_over_minimum(cell_lengths: Iterable[float], minimum_A: float) -> list[int]:
    """Return the smallest integer repeats making every lattice length > minimum_A."""
    if not math.isfinite(minimum_A) or minimum_A <= 0:
        raise ValueError("minimum_A must be finite and positive")
    factors = []
    for length in cell_lengths:
        length = float(length)
        if not math.isfinite(length) or length <= 0:
            raise ValueError("cell lengths must be finite and positive")
        factors.append(math.floor(minimum_A / length) + 1)
    if len(factors) != 3:
        raise ValueError("exactly three cell lengths are required")
    return factors


def formation_energy(
    defect_total_eV: float,
    pristine_total_eV: float,
    chemical_potential_eV: float,
) -> float:
    value = float(defect_total_eV) + float(chemical_potential_eV) - float(pristine_total_eV)
    if not math.isfinite(value):
        raise ValueError("vacancy formation energy must be finite")
    return value


def self_consistent_formation_energy(
    defect_total_eV: float,
    pristine_total_eV: float,
    pristine_atoms: int,
) -> float:
    if pristine_atoms < 2:
        raise ValueError("pristine structure must contain at least two atoms")
    chemical_potential = float(pristine_total_eV) / pristine_atoms
    return formation_energy(defect_total_eV, pristine_total_eV, chemical_potential)


def structure_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def atoms_payload(atoms: Any) -> dict[str, Any]:
    return {
        "numbers": [int(value) for value in atoms.get_atomic_numbers().tolist()],
        "symbols": list(atoms.get_chemical_symbols()),
        "positions": [[float(value) for value in row] for row in atoms.get_positions().tolist()],
        "cell": [[float(value) for value in row] for row in atoms.get_cell().array.tolist()],
        "pbc": [bool(value) for value in atoms.get_pbc().tolist()],
    }


def atoms_from_payload(payload: dict[str, Any]) -> Any:
    from ase import Atoms

    return Atoms(
        numbers=payload["numbers"],
        positions=payload["positions"],
        cell=payload["cell"],
        pbc=payload["pbc"],
    )


def _walk(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, (*path, str(key)))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            yield from _walk(item, (*path, str(index)))
    else:
        yield path, value


def find_mp_ids(*values: Any) -> set[str]:
    found: set[str] = set()
    for value in values:
        for _, item in _walk(value):
            if isinstance(item, str):
                found.update(match.lower() for match in MP_ID_PATTERN.findall(item))
    return found


def _vacancy_reference_candidates(
    metadata: dict[str, Any],
) -> list[tuple[int, str, float]]:
    candidates: list[tuple[int, str, float]] = []
    for path, value in _walk(metadata):
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        number = float(value)
        if not math.isfinite(number):
            continue
        label = ".".join(path)
        normalized = re.sub(r"[^a-z0-9]+", "", label.lower())
        score = 0
        if "vac" in normalized:
            score += 8
        if "formation" in normalized or "formenergy" in normalized:
            score += 8
        if "energy" in normalized or normalized.endswith("ev"):
            score += 3
        if "chemicalpotential" in normalized or normalized.endswith("mu"):
            score -= 8
        if "host" in normalized or "pristine" in normalized:
            score -= 4
        if -5.0 <= number <= 15.0:
            score += 1
        if score > 0:
            candidates.append((score, label, number))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates


def extract_published_vacancy_value(
    metadata: dict[str, Any],
    *,
    value_index: int,
) -> tuple[float, str]:
    """Select a site-resolved released value by a checked-in, explicit index."""
    candidates = _vacancy_reference_candidates(metadata)
    if not candidates:
        available = sorted(
            ".".join(path)
            for path, value in _walk(metadata)
            if isinstance(value, int | float) and not isinstance(value, bool)
        )
        raise ValueError(
            "No vacancy-formation-energy field found. Numeric fields: " + ", ".join(available[:40])
        )

    best_score = candidates[0][0]
    best = [item for item in candidates if item[0] == best_score]
    if not isinstance(value_index, int) or isinstance(value_index, bool) or value_index < 0:
        raise ValueError("vacancy_value_index must be a non-negative integer")
    if value_index >= len(best):
        raise ValueError(f"vacancy_value_index={value_index} exceeds {len(best)} best candidates")
    _, path, value = best[value_index]
    return value, path


def row_metadata(row: Any) -> dict[str, Any]:
    key_values = dict(getattr(row, "key_value_pairs", {}) or {})
    data = dict(getattr(row, "data", {}) or {})
    return {
        "row_id": getattr(row, "id", None),
        "key_value_pairs": key_values,
        "data": data,
    }


def select_database_rows(database_path: Path, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select frozen records from the released raw JSON and build vacancy geometries."""
    from ase import Atoms

    wanted = {str(case["mp_id"]).lower(): case for case in cases}
    if len(wanted) != len(cases):
        raise ValueError("manifest cases must use unique Materials Project IDs")
    try:
        released = json.loads(database_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("released vacancy source is not valid JSON") from exc
    if not isinstance(released, dict):
        raise ValueError("released vacancy source must be a mapping keyed by MP ID")

    missing = sorted(set(wanted) - {str(key).lower() for key in released})
    if missing:
        raise ValueError(f"Frozen Materials Project records not found in dataset: {missing}")

    selected: list[dict[str, Any]] = []
    for case in cases:
        mp_id = str(case["mp_id"]).lower()
        record = released[mp_id]
        if not isinstance(record, dict):
            raise ValueError(f"{mp_id} released record must be an object")
        symbols = record.get("Symbols")
        positions = record.get("Positions")
        cell = record.get("Cell")
        vacancy_values = record.get("Vacancy")
        if not isinstance(symbols, list) or not all(
            isinstance(symbol, str) and symbol for symbol in symbols
        ):
            raise ValueError(f"{mp_id} released record has invalid Symbols")
        if not isinstance(positions, list) or not isinstance(cell, list):
            raise ValueError(f"{mp_id} released record is missing Positions or Cell")
        if not isinstance(vacancy_values, list) or not vacancy_values:
            raise ValueError(f"{mp_id} released record has no Vacancy values")
        value_index = case.get("vacancy_value_index")
        if not isinstance(value_index, int) or isinstance(value_index, bool) or value_index < 0:
            raise ValueError(f"{mp_id} must freeze a non-negative vacancy_value_index")
        if value_index >= len(vacancy_values):
            raise ValueError(
                f"{mp_id} vacancy_value_index={value_index} exceeds "
                f"{len(vacancy_values)} released values"
            )
        published_eV = float(vacancy_values[value_index])
        if not math.isfinite(published_eV):
            raise ValueError(f"{mp_id} released Vacancy value must be finite")
        try:
            atoms = Atoms(symbols=symbols, positions=positions, cell=cell, pbc=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{mp_id} released structure is not ASE-compatible") from exc
        expected_element = str(case["expected_element"])
        found_symbols = set(atoms.get_chemical_symbols())
        if found_symbols != {expected_element}:
            raise ValueError(
                f"{mp_id} expected pure {expected_element}, found {sorted(found_symbols)}"
            )
        repeats = repeat_factors_over_minimum(atoms.cell.lengths(), 10.0)
        pristine = atoms.repeat(repeats)
        defect = pristine.copy()
        del defect[0]
        pristine_payload = atoms_payload(pristine)
        defect_payload = atoms_payload(defect)
        geometry_contract = {
            "mp_id": mp_id,
            "repeat_factors": repeats,
            "vacancy_atom_index": 0,
            "pristine": pristine_payload,
            "defect": defect_payload,
        }
        selected.append(
            {
                **case,
                "mp_id": mp_id,
                "published_vacancy_formation_energy_eV": published_eV,
                "published_reference_path": f"Vacancy.{value_index}",
                "repeat_factors": repeats,
                "minimum_supercell_length_A": min(
                    float(value) for value in pristine.cell.lengths()
                ),
                "pristine_atoms": len(pristine),
                "defect_atoms": len(defect),
                "pristine_structure": pristine_payload,
                "defect_structure": defect_payload,
                "geometry_fingerprint": structure_fingerprint(geometry_contract),
            }
        )
    return selected
