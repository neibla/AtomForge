# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "ase==3.28.0",
#   "mace-torch==0.3.15",
#   "numpy>=2.0",
#   "pydantic==2.12.5",
#   "torch==2.3.1",
# ]
# ///

"""Reproduce a frozen subset of Berger et al. with the paper's MACE-MP-0 setup."""

from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import math
import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from atomforge.node_scripts.berger_vacancy_protocol import (
    atoms_from_payload,
    formation_energy,
    self_consistent_formation_energy,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["v1"]
    inputs: dict[str, Any]
    arguments: dict[str, Any]


def _model_state_sha256(calculator: Any) -> str:
    import torch

    models = getattr(calculator, "models", None)
    model = (
        models[0]
        if isinstance(models, list | tuple) and models
        else getattr(calculator, "model", None)
    )
    if model is None or not hasattr(model, "state_dict"):
        raise RuntimeError("Unable to locate the loaded MACE model state for provenance")
    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)
    return hashlib.sha256(buffer.getvalue()).hexdigest()


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


def run_cases(
    cases: list[dict[str, Any]], *, device: str, tolerance_eV: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import torch
    from mace.calculators import mace_mp

    calculator = mace_mp(
        model="small",
        dispersion=False,
        default_dtype="float32",
        device=device,
    )
    checkpoint_sha = _model_state_sha256(calculator)
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
        if device.startswith("cuda"):
            torch.cuda.synchronize()

        paper_protocol_eV = formation_energy(
            defect_total,
            pristine_total,
            float(case["paper_mace_chemical_potential_eV"]),
        )
        self_consistent_eV = self_consistent_formation_energy(
            defect_total,
            pristine_total,
            len(pristine),
        )
        published_eV = float(case["published_vacancy_formation_energy_eV"])
        error_eV = abs(paper_protocol_eV - published_eV)
        finite = all(
            math.isfinite(value)
            for value in (
                pristine_total,
                defect_total,
                max_force,
                paper_protocol_eV,
                self_consistent_eV,
                error_eV,
            )
        )
        rows.append(
            {
                "case_id": str(case["case_id"]),
                "mp_id": str(case["mp_id"]),
                "element": str(case["expected_element"]),
                "geometry_fingerprint": str(case["geometry_fingerprint"]),
                "published_vacancy_eV": published_eV,
                "mace_paper_protocol_vacancy_eV": paper_protocol_eV,
                "mace_self_consistent_vacancy_eV": self_consistent_eV,
                "absolute_reproduction_error_eV": error_eV,
                "max_single_point_force_eV_per_A": max_force,
                "finite": finite,
                "reproduction_status": (
                    "PASS" if finite and error_eV <= tolerance_eV else "REVIEW"
                ),
                "published_reference_path": str(case["published_reference_path"]),
            }
        )

    return rows, {
        "name": "MACE-MP-0",
        "version": importlib.metadata.version("mace-torch"),
        "checkpoint": f"MACE-MP-0 small state_dict sha256:{checkpoint_sha}",
        "head": "default",
        "dtype": "float32",
        "device": device,
    }


def build_output(inputs: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    source_node = str(arguments.get("source_node", "prepare_paper_subset"))
    cases, source = _source_cases(inputs, source_node)
    tolerance_eV = float(arguments.get("reproduction_tolerance_eV", 0.10))
    device = str(arguments.get("device", "cuda"))
    rows, model_info = run_cases(cases, device=device, tolerance_eV=tolerance_eV)
    errors = [float(row["absolute_reproduction_error_eV"]) for row in rows]
    passed = [row for row in rows if row["reproduction_status"] == "PASS"]
    numerical_passed = all(bool(row["finite"]) for row in rows)

    return {
        "contract_version": "v1",
        "metrics": {
            "case_count": {"val": float(len(rows)), "unit": "count"},
            "reproduction_pass_count": {
                "val": float(len(passed)),
                "unit": "count",
            },
            "mean_absolute_reproduction_error": {
                "val": float(np.mean(errors)),
                "unit": "eV",
            },
            "max_absolute_reproduction_error": {
                "val": float(max(errors)),
                "unit": "eV",
            },
            "numerical_gate_passed": {
                "val": 1.0 if numerical_passed else 0.0,
                "unit": "dimensionless",
            },
        },
        "data": {
            "source": source,
            "model_info": model_info,
            "protocol": {
                "model": "MACE-MP-0 small",
                "dispersion": False,
                "dtype": "float32",
                "structures": (
                    "paper-released conventional cells repeated until every lattice length > 10 Å"
                ),
                "vacancies": "one unrelaxed vacancy at the frozen site",
                "paper_chemical_potentials": True,
                "reproduction_tolerance_eV": tolerance_eV,
            },
            "comparison_rows": rows,
            "scientific_decision": {
                "contract_version": "scientific-decision.v1",
                "outcome": (
                    "VALIDATED" if len(passed) == len(rows) and numerical_passed else "REVIEW"
                ),
                "calibration": {
                    "status": "INSUFFICIENT_EVIDENCE",
                    "accepted_case_count": 0,
                    "minimum_case_count": 30,
                },
                "scope": (
                    "Five frozen elemental-bcc vacancy records evaluated with the "
                    "declared MACE-MP-0 paper protocol."
                ),
                "headline": (
                    f"{len(passed)} of {len(rows)} frozen records matched the "
                    "released vacancy-energy benchmark."
                ),
                "quality_checks": [
                    {
                        "label": "Released-record reproduction",
                        "status": "PASS"
                        if len(passed) == len(rows) and numerical_passed
                        else "FAILED",
                        "value": f"{len(passed)}/{len(rows)}",
                        "unit": "records",
                        "criterion": (f"all frozen records within {tolerance_eV:g} eV and finite"),
                    }
                ],
                "supported_claims": [
                    (
                        f"{len(passed)} of {len(rows)} frozen records matched the released "
                        f"vacancy energies within {tolerance_eV:g} eV."
                    )
                ],
                "limitations": [
                    ("This is a five-record subset, not the paper-wide 86,259-material campaign."),
                    (
                        "Single-point force magnitude is diagnostic; the published "
                        "high-throughput vacancies were intentionally unrelaxed."
                    ),
                ],
            },
        },
        "visualizations": [
            {
                "id": "berger-mace-reproduction",
                "kind": "table.v1",
                "title": "Berger vacancy subset: MACE reproduction",
                "description": (
                    "Published and rerun vacancy formation energies for the frozen subset."
                ),
                "columns": [
                    {"field": "element", "label": "Element"},
                    {"field": "mp_id", "label": "Materials Project ID"},
                    {
                        "field": "published_vacancy_eV",
                        "label": "Published",
                        "unit": "eV",
                    },
                    {
                        "field": "mace_paper_protocol_vacancy_eV",
                        "label": "AtomForge MACE",
                        "unit": "eV",
                    },
                    {
                        "field": "absolute_reproduction_error_eV",
                        "label": "Absolute error",
                        "unit": "eV",
                    },
                    {"field": "reproduction_status", "label": "Status"},
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
        raise SystemExit("usage: berger_vacancy_mace.py INPUT_JSON OUTPUT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
