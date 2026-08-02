# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "ase==3.23.0",
#   "mattersim==1.0.0rc9",
#   "numpy==1.26.4",
#   "pydantic==2.9.2",
#   "setuptools<81",
#   "torch==2.2.0",
# ]
# ///

"""Evaluate the same frozen vacancy geometries with an independent MatterSim model."""

from __future__ import annotations

import importlib.metadata
import json
import math
import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from atomforge.node_scripts.berger_vacancy_protocol import (
    atoms_from_payload,
    file_digest,
    self_consistent_formation_energy,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["v1"]
    inputs: dict[str, Any]
    arguments: dict[str, Any]


def _source_cases(
    inputs: dict[str, Any], source_node: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    upstream = inputs.get(source_node)
    if not isinstance(upstream, dict) or not isinstance(upstream.get("data"), dict):
        raise ValueError(f"source node {source_node!r} is missing SCRIPT data")
    data = upstream["data"]
    cases = data.get("cases")
    source = data.get("source")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"source node {source_node!r} must include non-empty cases")
    if not isinstance(source, dict):
        raise ValueError(f"source node {source_node!r} must include source provenance")
    return cases, source


def _checkpoint_path() -> Path:
    path = Path.home() / ".local" / "mattersim" / "pretrained_models" / "mattersim-v1.0.0-5M.pth"
    if not path.is_file():
        raise FileNotFoundError(f"MatterSim checkpoint not found after load: {path}")
    return path


def build_output(inputs: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    import torch
    from mattersim.forcefield.potential import MatterSimCalculator

    source_node = str(arguments.get("source_node", "prepare_paper_subset"))
    cases, source = _source_cases(inputs, source_node)
    device = str(arguments.get("device", "cuda"))
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("MatterSim vacancy evaluation requires an available CUDA GPU")

    calculator = MatterSimCalculator(
        load_path="MatterSim-v1.0.0-5M.pth",
        device=device,
    )
    checkpoint = _checkpoint_path()
    rows: list[dict[str, Any]] = []

    for case in cases:
        pristine = atoms_from_payload(case["pristine_structure"])
        defect = atoms_from_payload(case["defect_structure"])
        pristine.calc = calculator
        defect.calc = calculator
        pristine_total = float(pristine.get_potential_energy())
        defect_total = float(defect.get_potential_energy())
        pristine_forces = np.asarray(pristine.get_forces(), dtype=float)
        defect_forces = np.asarray(defect.get_forces(), dtype=float)
        max_force = float(
            max(
                np.linalg.norm(pristine_forces, axis=1).max(initial=0.0),
                np.linalg.norm(defect_forces, axis=1).max(initial=0.0),
            )
        )
        vacancy_eV = self_consistent_formation_energy(
            defect_total,
            pristine_total,
            len(pristine),
        )
        torch.cuda.synchronize()
        finite = all(
            math.isfinite(value) for value in (pristine_total, defect_total, max_force, vacancy_eV)
        )
        rows.append(
            {
                "case_id": str(case["case_id"]),
                "mp_id": str(case["mp_id"]),
                "element": str(case["expected_element"]),
                "geometry_fingerprint": str(case["geometry_fingerprint"]),
                "mattersim_self_consistent_vacancy_eV": vacancy_eV,
                "max_single_point_force_eV_per_A": max_force,
                "finite": finite,
                "status": "PASS" if finite else "REVIEW",
            }
        )

    finite_rows = [row for row in rows if row["finite"]]
    max_force = max(float(row["max_single_point_force_eV_per_A"]) for row in rows)
    model_info = {
        "name": "MatterSim",
        "version": importlib.metadata.version("mattersim"),
        "checkpoint": f"{checkpoint.name} sha256:{file_digest(checkpoint, 'sha256')}",
        "head": "default",
        "dtype": "model-default",
        "device": device,
    }
    return {
        "contract_version": "v1",
        "metrics": {
            "case_count": {"val": float(len(rows)), "unit": "count"},
            "finite_case_count": {"val": float(len(finite_rows)), "unit": "count"},
            "max_single_point_force": {"val": max_force, "unit": "eV/Å"},
            "numerical_gate_passed": {
                "val": 1.0 if len(finite_rows) == len(rows) else 0.0,
                "unit": "dimensionless",
            },
        },
        "data": {
            "source": source,
            "model_info": model_info,
            "protocol": {
                "model": "MatterSim-v1.0.0-5M",
                "structures": (
                    "exact structures and vacancy sites emitted by prepare_paper_subset"
                ),
                "vacancies": "unrelaxed single-point calculations",
                "chemical_potential": "self-consistent pristine energy per atom",
            },
            "comparison_rows": rows,
            "scientific_decision": {
                "contract_version": "scientific-decision.v1",
                "outcome": "REVIEW",
                "calibration": {
                    "status": "INSUFFICIENT_EVIDENCE",
                    "accepted_case_count": 0,
                    "minimum_case_count": 30,
                },
                "scope": (
                    "Independent MatterSim single-point evaluation of the same five "
                    "frozen elemental-bcc vacancy geometries."
                ),
                "headline": (
                    f"MatterSim returned finite results for {len(finite_rows)} of "
                    f"{len(rows)} frozen geometries."
                ),
                "quality_checks": [
                    {
                        "label": "Finite model outputs",
                        "status": "PASS" if len(finite_rows) == len(rows) else "FAILED",
                        "value": f"{len(finite_rows)}/{len(rows)}",
                        "unit": "records",
                        "criterion": "all frozen geometries return finite energies and forces",
                    }
                ],
                "supported_claims": ["An independent model evaluated the exact frozen geometries."],
                "limitations": [
                    ("MatterSim is an extension and is not part of the Berger paper reproduction."),
                    (
                        "Cross-model disagreement is a prioritisation heuristic, not "
                        "calibrated uncertainty."
                    ),
                ],
            },
        },
        "visualizations": [
            {
                "id": "berger-mattersim-extension",
                "kind": "table.v1",
                "title": "Independent MatterSim vacancy evaluation",
                "columns": [
                    {"field": "element", "label": "Element"},
                    {"field": "mp_id", "label": "Materials Project ID"},
                    {
                        "field": "mattersim_self_consistent_vacancy_eV",
                        "label": "MatterSim vacancy energy",
                        "unit": "eV",
                    },
                    {
                        "field": "max_single_point_force_eV_per_A",
                        "label": "Maximum force",
                        "unit": "eV/Å",
                    },
                    {"field": "status", "label": "Status"},
                ],
                "rows": rows,
            }
        ],
    }


def main(input_path: Path, output_path: Path) -> None:
    payload = Input.model_validate_json(input_path.read_text(encoding="utf-8"))
    output_path.write_text(
        json.dumps(
            build_output(payload.inputs, payload.arguments),
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: berger_vacancy_mattersim.py INPUT_JSON OUTPUT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
