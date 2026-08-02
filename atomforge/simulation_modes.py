from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from atomforge.contracts import SimulationMode
from atomforge.schemas import (
    NVTParams,
    NVTResult,
    PKAParams,
    PKAResult,
    RelaxParams,
    RelaxResult,
    SimulationResult,
    SinglePointParams,
    SinglePointResult,
)


@dataclass(frozen=True, slots=True)
class SimulationModeDefinition:
    """Declarative contract facts shared by validation and cached execution."""

    params_model: type[BaseModel]
    result_model: type[SimulationResult]
    metrics: frozenset[str]
    boolean_metrics: frozenset[str] = frozenset()


MODE_CONTRACTS: dict[SimulationMode, SimulationModeDefinition] = {
    "pka": SimulationModeDefinition(
        params_model=PKAParams,
        result_model=PKAResult,
        metrics=frozenset({"n_defects", "interstitials", "energy", "runtime_ms"}),
    ),
    "relax": SimulationModeDefinition(
        params_model=RelaxParams,
        result_model=RelaxResult,
        metrics=frozenset({"potential_energy", "max_force", "force_norm", "runtime_ms"}),
    ),
    "single_point": SimulationModeDefinition(
        params_model=SinglePointParams,
        result_model=SinglePointResult,
        metrics=frozenset({"potential_energy", "max_force", "force_norm", "runtime_ms"}),
    ),
    "nvt": SimulationModeDefinition(
        params_model=NVTParams,
        result_model=NVTResult,
        metrics=frozenset(
            {
                "potential_energy",
                "mean_temperature_K",
                "std_temperature_K",
                "max_force",
                "n_frames",
                "stable",
                "analysis_applicable",
                "trajectory_quality_passed",
                "runtime_ms",
            }
        ),
        boolean_metrics=frozenset({"stable", "analysis_applicable", "trajectory_quality_passed"}),
    ),
}


def validate_mode_params(mode: str, params: dict[str, Any]) -> BaseModel:
    """Validate mode-specific parameters and preserve the PKA safety gate."""

    definition = MODE_CONTRACTS[mode]  # Validation already checked the mode name.
    mode_params = {key: value for key, value in params.items() if key not in {"mode", "trials"}}
    validated = definition.params_model.model_validate(mode_params)
    if mode == "pka" and not validated.allow_unvalidated_short_range:
        raise ValueError(
            "PKA is blocked for pure MLIP execution. Set "
            "allow_unvalidated_short_range=true only for an explicitly labelled "
            "infrastructure demonstration."
        )
    return validated
