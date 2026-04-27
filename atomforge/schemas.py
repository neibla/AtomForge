from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class DagNode(BaseModel):
    id: str
    type: Literal["FETCH", "ALLOY", "SIMULATE", "ANALYZE", "GENERATE", "SOLVE_QUANTUM"]
    depends_on: str | list[str] | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    # Default to None to allow HardwareRouter to pick automatically
    gpu: Literal["T4", "A100-40GB", "A100-80GB"] | None = None


# --- SIMULATION DATA SCHEMAS ---


class AtomsData(BaseModel):
    symbols: list[str]
    positions: list[list[float]]
    cell: list[list[float]]
    pbc: bool = True
    dft_energy: float | None = None
    metadata: dict[str, Any] | None = None


class SimulationResult(BaseModel):
    """Base class for all simulation outputs."""

    seed: int
    runtime_ms: float | None = None
    initial_positions: list[list[float]] | None = None
    final_positions: list[list[float]] | None = None
    atomic_numbers: list[int] | None = None
    energies: list[float] | None = None
    trajectory: list[list[list[float]]] | None = None


# --- SIMULATION PARAMETERS ---


class PKAParams(BaseModel):
    energy_ev: float = 1000.0
    temperature_K: float = 300.0
    timestep_fs: float = 0.2
    n_blocks: int = 20
    steps_per_block: int = 20
    stopping_power: float = 0.05
    base_friction: float = 0.002

    @field_validator("energy_ev", "temperature_K", "timestep_fs")
    @classmethod
    def must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Value {v} must be greater than zero")
        return v


class MeltParams(BaseModel):
    temperature: float = 1121.0
    steps: int = 1000

    @field_validator("temperature")
    @classmethod
    def valid_temp(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Temperature cannot be negative")
        return v


class RelaxParams(BaseModel):
    fmax: float = 0.05


class CompressionParams(BaseModel):
    strain_rate: float = 1e-5  # fs^-1
    total_strain: float = 0.1
    temperature_K: float = 300.0
    timestep_fs: float = 1.0


class QuantumParams(BaseModel):
    property: Literal["tc", "dos", "bandgap"] = "tc"
    method: str = "ml-regression"


# --- SIMULATION RESULTS ---


class PKAResult(SimulationResult):
    n_defects: int
    interstitials: int | None = None
    energy: float


class MeltResult(SimulationResult):
    temperature: float
    msd: float
    is_liquid: bool


class RelaxResult(SimulationResult):
    potential_energy: float
    positions: list[list[float]]
    cell: list[list[float]]


class CompressionResult(SimulationResult):
    youngs_modulus_gpa: float
    max_stress_gpa: float
    strains: list[float]
    stresses: list[float]
    energy_absorption: float


class QuantumResult(SimulationResult):
    tc_k: float | None = None
    bandgap_ev: float | None = None
    dos_at_fermi: float | None = None


class Hypothesis(BaseModel):
    id: str
    target_node: str
    metric: str = "n_defects"
    assertion: str = "target.avg_defects < 50"


class ExperimentSpec(BaseModel):
    experiment_id: str
    dag: list[DagNode]
    hypotheses: list[Hypothesis] = Field(default_factory=list)


class MetricResult(BaseModel):
    val: float
    unit: str


class HypothesisEval(BaseModel):
    id: str
    status: Literal["PROVEN", "REVIEW", "DISPROVEN"]
    metric: str
    value: str
    confidence: float


class ModelMetadata(BaseModel):
    name: str = "MACE-MP-0"
    version: str = "2023-12-03"
    hardware: str | None = None
    device: str = "cuda"


class ResultsGraph(BaseModel):
    experiment_id: str
    status: Literal["SUCCESS", "FAILED", "PARTIAL"] = "SUCCESS"
    metrics: dict[str, MetricResult]
    hypotheses: list[HypothesisEval]
    model_info: ModelMetadata = Field(default_factory=ModelMetadata)
    summary: str
