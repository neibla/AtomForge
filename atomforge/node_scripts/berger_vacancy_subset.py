# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "ase==3.28.0",
#   "pydantic==2.9.2",
# ]
# ///

"""Prepare a frozen five-record subset from Berger et al.'s released vacancy database."""

from __future__ import annotations

import importlib.metadata
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from atomforge.node_scripts.berger_vacancy_protocol import (
    download_verified,
    file_digest,
    select_database_rows,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["v1"]
    inputs: dict[str, Any]
    arguments: dict[str, Any]


def _manifest_path(arguments: dict[str, Any]) -> Path:
    configured = Path(
        arguments.get(
            "manifest_path",
            "atomforge/data/berger_vacancy_subset.json",
        )
    )
    if configured.is_absolute():
        return configured
    # SCRIPT files execute from an immutable volume snapshot on Modal, while
    # checked-in package data is mounted at /root/atomforge. Keep local and
    # worker resolution equivalent by preferring the package mount when it
    # exists and falling back to the repository containing this script.
    mounted = Path("/root") / configured
    if mounted.is_file():
        return mounted
    repository_root = Path(__file__).resolve().parents[2]
    return repository_root / configured


def build_output(arguments: dict[str, Any]) -> dict[str, Any]:
    manifest_path = _manifest_path(arguments)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paper = manifest["paper"]
    cache_dir = Path(arguments.get("dataset_cache_dir", tempfile.gettempdir())) / "atomforge-berger"
    dataset_path, cache_hit = download_verified(
        paper["dataset_download_url"],
        cache_dir / paper["dataset_file"],
        expected_md5=paper["dataset_md5"],
    )
    dataset_sha256 = file_digest(dataset_path, "sha256")
    selected = select_database_rows(dataset_path, manifest["cases"])
    minimum_length = min(float(case["minimum_supercell_length_A"]) for case in selected)
    rows = [
        {
            "case_id": case["case_id"],
            "mp_id": case["mp_id"],
            "element": case["expected_element"],
            "paper_vacancy_eV": case["published_vacancy_formation_energy_eV"],
            "supercell_atoms": case["pristine_atoms"],
            "minimum_length_A": case["minimum_supercell_length_A"],
        }
        for case in selected
    ]
    return {
        "contract_version": "v1",
        "metrics": {
            "selected_case_count": {"val": float(len(selected)), "unit": "count"},
            "dataset_checksum_passed": {
                "val": 1.0,
                "unit": "dimensionless",
            },
            "minimum_supercell_length": {"val": minimum_length, "unit": "Å"},
            "dataset_cache_hit": {
                "val": 1.0 if cache_hit else 0.0,
                "unit": "dimensionless",
            },
        },
        "data": {
            "model_info": {
                "name": "ASE vacancy dataset preparation",
                "version": importlib.metadata.version("ase"),
                "checkpoint": f"Vacancies.json sha256:{dataset_sha256}",
                "head": "not-applicable",
                "dtype": "float64",
                "device": "cpu",
            },
            "source": {
                "title": paper["title"],
                "arxiv": paper["arxiv"],
                "dataset": paper["dataset"],
                "dataset_file": paper["dataset_file"],
                "dataset_md5": paper["dataset_md5"],
                "dataset_sha256": dataset_sha256,
                "materials_project_release": paper["materials_project_release"],
            },
            "selection_rule": manifest["selection_rule"],
            "protocol": {
                "structure_source": "paper-released ASE database",
                "supercell_rule": (
                    "repeat conventional cells until all lattice lengths are > 10 Å"
                ),
                "vacancy_rule": "remove atom index 0 without relaxation",
                "case_count": len(selected),
            },
            "cases": selected,
        },
        "visualizations": [
            {
                "id": "berger-frozen-subset",
                "kind": "table.v1",
                "title": "Frozen Berger vacancy-reproduction subset",
                "description": ("Five elemental bcc records selected before either model is run."),
                "columns": [
                    {"field": "case_id", "label": "Case"},
                    {"field": "mp_id", "label": "Materials Project ID"},
                    {"field": "element", "label": "Element"},
                    {
                        "field": "paper_vacancy_eV",
                        "label": "Published vacancy energy",
                        "unit": "eV",
                    },
                    {
                        "field": "supercell_atoms",
                        "label": "Pristine atoms",
                        "unit": "count",
                    },
                    {
                        "field": "minimum_length_A",
                        "label": "Minimum cell length",
                        "unit": "Å",
                    },
                ],
                "rows": rows,
            }
        ],
    }


def main(input_path: Path, output_path: Path) -> None:
    payload = Input.model_validate_json(input_path.read_text(encoding="utf-8"))
    output_path.write_text(
        json.dumps(build_output(payload.arguments), indent=2, allow_nan=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: berger_vacancy_subset.py INPUT_JSON OUTPUT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
