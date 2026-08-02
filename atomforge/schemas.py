from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atomforge.contracts import (
    MAX_SIMULATION_TRIALS,
    MAX_SWEEP_POINT_ERROR_LENGTH,
    MAX_VISUALIZATION_CATALOG_ITEMS,
    NodeType,
    ScriptExecutionProfile,
    SimulationMode,
)
from atomforge.sweeps import get_parameter


class DagNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    type: NodeType
    depends_on: str | list[str] | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @property
    def dependencies(self) -> list[str]:
        if self.depends_on is None:
            return []
        return [self.depends_on] if isinstance(self.depends_on, str) else list(self.depends_on)


# --- SIMULATION DATA SCHEMAS ---


class AtomsData(BaseModel):
    symbols: list[str]
    positions: list[list[float]]
    cell: list[list[float]]
    pbc: tuple[bool, bool, bool] = (True, True, True)
    dft_energy: float | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("pbc", mode="before")
    @classmethod
    def normalize_pbc(cls, value: Any) -> tuple[bool, bool, bool]:
        if isinstance(value, bool):
            return (value, value, value)
        if (
            isinstance(value, list | tuple)
            and len(value) == 3
            and all(isinstance(item, bool) for item in value)
        ):
            return tuple(value)
        raise ValueError("pbc must be a bool or three booleans")


class SimulationResult(BaseModel):
    """Base class for all simulation outputs."""

    seed: int
    runtime_ms: float | None = None
    initial_positions: list[list[float]] | None = None
    final_positions: list[list[float]] | None = None
    atomic_numbers: list[int] | None = None
    energies: list[float] | None = None
    trajectory: list[list[list[float]]] | None = None
    trajectory_stride: int | None = Field(default=None, ge=1)
    trajectory_total_steps: int | None = Field(default=None, ge=0)
    trajectory_truncated: bool = False
    cell: list[list[float]] | None = None
    pbc: list[bool] | tuple[bool, bool, bool] | None = None


# --- SIMULATION PARAMETERS ---


class PKAParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    energy_ev: float = Field(default=1000.0, gt=0, le=2_000_000)
    temperature_K: float = Field(default=300.0, gt=0, le=5_000)
    timestep_fs: float = Field(default=0.2, gt=0, le=2)
    n_blocks: int = Field(default=20, ge=1, le=1_000)
    steps_per_block: int = Field(default=20, ge=1, le=1_000)
    stopping_power: float = Field(default=0.05, ge=0, le=10)
    base_friction: float = Field(default=0.002, ge=0, le=10)
    allow_unvalidated_short_range: bool = False

    @model_validator(mode="after")
    def bound_total_steps(self) -> PKAParams:
        if self.n_blocks * self.steps_per_block > 100_000:
            raise ValueError("n_blocks * steps_per_block must be <= 100000")
        return self


class RelaxParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fmax: float = Field(default=0.05, gt=0, le=10)
    optimizer: Literal["lbfgs", "fire"] = "lbfgs"
    max_steps: int = Field(default=1_000, ge=1, le=100_000)


class SinglePointParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_index: int = Field(default=0, ge=0)
    displacement: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3
    )
    cell_scale: float = Field(default=1.0, gt=0.8, lt=1.2)

    @model_validator(mode="after")
    def validate_displacement(self) -> SinglePointParams:
        if any(not math.isfinite(value) for value in self.displacement):
            raise ValueError("displacement values must be finite")
        if math.sqrt(sum(value * value for value in self.displacement)) > 10:
            raise ValueError("displacement magnitude must be <= 10 Å")
        return self


class SweepGrid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float | None = None
    stop: float | None = None
    step: float | None = Field(default=None, gt=0)
    values: list[float] | None = Field(default=None, min_length=2, max_length=1_000)

    @model_validator(mode="after")
    def validate_grid(self) -> SweepGrid:
        range_values = (self.start, self.stop, self.step)
        range_field_count = sum(value is not None for value in range_values)
        if self.values is not None and range_field_count:
            raise ValueError("explicit sweep values cannot include range fields")
        if self.values is None and range_field_count != 3:
            raise ValueError("sweep grid requires exactly one of start/stop/step or values")
        if self.values is not None:
            if any(not math.isfinite(value) for value in self.values):
                raise ValueError("sweep grid values must be finite")
            if any(right <= left for left, right in zip(self.values, self.values[1:])):
                raise ValueError("explicit sweep grid values must be strictly increasing")
            return self
        assert self.start is not None and self.stop is not None and self.step is not None
        if not all(math.isfinite(value) for value in (self.start, self.stop, self.step)):
            raise ValueError("sweep grid values must be finite")
        if self.stop < self.start:
            raise ValueError("sweep grid stop must be >= start")
        point_count = len(self.materialize())
        if point_count < 2:
            raise ValueError("sweep grid must contain at least two points")
        if point_count > 1_000:
            raise ValueError("sweep grid must contain at most 1000 points")
        return self

    def materialize(self) -> list[float]:
        if self.values is not None:
            return list(self.values)
        assert self.start is not None and self.stop is not None and self.step is not None
        start = Decimal(str(self.start))
        stop = Decimal(str(self.stop))
        step = Decimal(str(self.step))
        count = int((stop - start) // step) + 1
        values = [start + step * index for index in range(count)]
        if values and values[-1] < stop and stop - values[-1] <= step * Decimal("1e-9"):
            values[-1] = stop
        return [float(value) for value in values]


class SweepCoordinate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    label: str = Field(min_length=1, max_length=160)
    unit: str = Field(default="", max_length=30)
    grid: SweepGrid


class SweepApply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*(?:\.(?:[A-Za-z][A-Za-z0-9_]*|\d+))*$",
    )
    transform: Literal[
        "identity", "ratio_to_reference", "cubic_ratio_to_reference", "scale_vector"
    ] = "identity"
    reference: float | None = None
    vector: list[float] | None = Field(default=None, min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_transform(self) -> SweepApply:
        if self.transform in {"ratio_to_reference", "cubic_ratio_to_reference"}:
            if self.reference is None or not math.isfinite(self.reference) or self.reference <= 0:
                raise ValueError("ratio_to_reference requires a positive finite reference")
            if self.vector is not None:
                raise ValueError("reference transforms do not accept vector")
        elif self.transform == "scale_vector":
            if self.reference is not None:
                raise ValueError("scale_vector does not accept reference")
            if (
                self.vector is None
                or any(not math.isfinite(component) for component in self.vector)
                or not any(component != 0 for component in self.vector)
            ):
                raise ValueError("scale_vector requires a finite non-zero vector")
        elif self.reference is not None:
            raise ValueError("reference is only valid with a reference transform")
        elif self.vector is not None:
            raise ValueError("vector is only valid with scale_vector")
        return self

    def apply(self, value: float) -> float | list[float]:
        if self.transform in {"ratio_to_reference", "cubic_ratio_to_reference"}:
            assert self.reference is not None
            ratio = value / self.reference
            return ratio**3 if self.transform == "cubic_ratio_to_reference" else ratio
        if self.transform == "scale_vector":
            assert self.vector is not None
            return [value * component for component in self.vector]
        return value


class SweepOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["SIMULATE"] = "SIMULATE"
    mode: SimulationMode
    params: dict[str, Any] = Field(default_factory=dict)
    trials: int = Field(default=1, ge=1, le=MAX_SIMULATION_TRIALS)

    @model_validator(mode="after")
    def reject_reserved_params(self) -> SweepOperation:
        reserved = {"mode", "trials"}.intersection(self.params)
        if reserved:
            raise ValueError(
                f"operation.params cannot redefine reserved fields: {sorted(reserved)}"
            )
        return self


class SweepParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: SweepOperation
    coordinate: SweepCoordinate
    apply: SweepApply
    max_concurrency: int = Field(default=4, ge=1, le=64)
    failure_policy: Literal["require_all", "allow_partial"] = "require_all"
    visualization_trial: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_visualization_trial(self) -> SweepParams:
        if self.visualization_trial >= self.operation.trials:
            raise ValueError("visualization_trial must be lower than operation.trials")
        return self


class NVTParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature_K: float = Field(default=300.0, gt=0, le=5_000)
    timestep_fs: float = Field(default=1.0, gt=0, le=2)
    n_steps: int = Field(default=1_000, ge=1, le=100_000)
    friction_per_fs: float = Field(default=0.01, gt=0, le=10)
    analysis_frames: int = Field(default=500, ge=1, le=10_000)
    frame_stride: int = Field(default=10, ge=1, le=100_000)
    max_recorded_frames: int = Field(default=2_000, ge=1, le=10_000)
    minimum_distance_A: float = Field(default=0.4, gt=0, le=10)
    analysis_pairs: dict[str, float] = Field(default_factory=dict)

    @field_validator("analysis_pairs")
    @classmethod
    def validate_analysis_pairs(cls, value: dict[str, float]) -> dict[str, float]:
        for label, cutoff in value.items():
            parts = label.split("-")
            if len(parts) != 2 or any(not part for part in parts):
                raise ValueError("analysis pair keys must look like 'Si-O'")
            if not math.isfinite(cutoff) or cutoff <= 0:
                raise ValueError("analysis pair cutoffs must be positive")
        return value


# --- SIMULATION RESULTS ---


class PKAFrameMetric(BaseModel):
    frame: int = Field(ge=0)
    step: int = Field(ge=0)
    time_fs: float = Field(ge=0)
    kinetic_energy_ev: float = Field(ge=0)
    potential_energy_ev: float
    temperature_K: float = Field(ge=0)
    n_defects: int = Field(ge=0)
    interstitials: int = Field(ge=0)
    displaced_atoms: int = Field(ge=0)
    max_displacement_angstrom: float = Field(ge=0)
    vacancy_positions: list[list[float]] = Field(default_factory=list)
    interstitial_positions: list[list[float]] = Field(default_factory=list)


class PKAResult(SimulationResult):
    n_defects: int
    interstitials: int | None = None
    vacancy_positions: list[list[float]] | None = None
    interstitial_positions: list[list[float]] | None = None
    pka_index: int | None = None
    frame_metrics: list[PKAFrameMetric] | None = None
    energy: float
    scientific_status: Literal["EXPERIMENTAL_UNVALIDATED"] = "EXPERIMENTAL_UNVALIDATED"


class RelaxResult(SimulationResult):
    potential_energy: float
    max_force: float
    force_norm: float
    positions: list[list[float]]
    cell: list[list[float]]


class SinglePointResult(SimulationResult):
    potential_energy: float
    max_force: float
    force_norm: float
    forces: list[list[float]]
    positions: list[list[float]]
    cell: list[list[float]]


class NVTResult(SimulationResult):
    potential_energy: float
    mean_temperature_K: float
    std_temperature_K: float
    max_force: float
    n_frames: int
    stable: bool
    analysis_applicable: bool = False
    trajectory_quality_passed: bool = False
    bond_distance_stats: dict[str, dict[str, float]]
    bond_angle_stats: dict[str, dict[str, float]]
    rdf_stats: dict[str, dict[str, Any]]
    positions: list[list[float]]
    cell: list[list[float]]


SimulationOutput = PKAResult | RelaxResult | SinglePointResult | NVTResult


class SweepPointResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    index: int = Field(ge=0)
    value: float
    applied_value: float | list[float]
    simulation_params: dict[str, Any]
    status: Literal["COMPLETED", "FAILED"]
    ensemble: list[SimulationOutput] = Field(
        default_factory=list,
        max_length=MAX_SIMULATION_TRIALS,
    )
    error: str | None = Field(default=None, max_length=MAX_SWEEP_POINT_ERROR_LENGTH)

    @model_validator(mode="after")
    def validate_status(self) -> SweepPointResult:
        if self.status == "COMPLETED" and not self.ensemble:
            raise ValueError("completed sweep points require at least one result")
        if self.status == "COMPLETED" and self.error is not None:
            raise ValueError("completed sweep points cannot contain an error")
        if self.status == "FAILED" and not self.error:
            raise ValueError("failed sweep points require an error")
        if self.status == "FAILED" and self.ensemble:
            raise ValueError("failed sweep points cannot contain results")
        return self


class SweepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["sweep-result.v1"] = "sweep-result.v1"
    coordinate: SweepCoordinate
    apply: SweepApply
    points: list[SweepPointResult] = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_points_match_contract(self) -> SweepResult:
        grid_values = self.coordinate.grid.materialize()
        if len(self.points) != len(grid_values):
            raise ValueError("sweep result points must exactly match the declared grid")
        if [point.index for point in self.points] != list(range(len(grid_values))):
            raise ValueError("sweep result point indices must be ordered and contiguous")
        if len({point.id for point in self.points}) != len(self.points):
            raise ValueError("sweep result point ids must be unique")

        for point, grid_value in zip(self.points, grid_values, strict=True):
            if not math.isclose(point.value, grid_value, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("sweep result point values must match the declared grid")
            expected_applied = self.apply.apply(grid_value)
            if not _numeric_values_close(point.applied_value, expected_applied):
                raise ValueError("sweep result applied values must match the apply contract")
            actual_applied = get_parameter(point.simulation_params, self.apply.target)
            if not _numeric_values_close(actual_applied, expected_applied):
                raise ValueError(
                    "sweep result simulation params must contain the applied parameter"
                )
        return self

    @property
    def completed_count(self) -> int:
        return sum(point.status == "COMPLETED" for point in self.points)

    @property
    def failed_count(self) -> int:
        return len(self.points) - self.completed_count


def _numeric_values_close(left: Any, right: Any) -> bool:
    if isinstance(left, list) or isinstance(right, list):
        if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
            return False
        return all(_numeric_values_close(a, b) for a, b in zip(left, right, strict=True))
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if not isinstance(left, int | float) or not isinstance(right, int | float):
        return False
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    target_node: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    metric: str = "n_defects"
    assertion: str = Field(default="target.n_defects < 50", min_length=1, max_length=1000)


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    dag: list[DagNode] = Field(min_length=1, max_length=128)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    decision_node_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    parent_experiment_id: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    revision: int = Field(default=0, ge=0, le=1_000)
    change_summary: str | None = Field(default=None, max_length=2_000)
    force_recompute: bool = False
    script_snapshot_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class MetricResult(BaseModel):
    val: float
    unit: str


VisualizationValue = str | int | float | bool | None


class VisualizationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    source_node: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )


class AtomisticVisualizationData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positions: list[list[float]]
    numbers: list[int]
    symbols: list[str] | None = None
    pbc: list[bool] | tuple[bool, bool, bool] | None = None
    metadata: dict[str, Any] | None = None
    initial_positions: list[list[float]] | None = None
    final_positions: list[list[float]] | None = None
    energies: list[float] | None = None
    cell: list[list[float]] | None = None
    trajectory: list[list[list[float]]] | None = None
    vacancy_positions: list[list[float]] | None = None
    interstitial_positions: list[list[float]] | None = None
    n_defects: int | None = Field(default=None, ge=0)
    interstitials: int | None = Field(default=None, ge=0)
    pka_index: int | None = Field(default=None, ge=0)
    frame_metrics: list[PKAFrameMetric] | None = None
    simulation_mode: SimulationMode | None = None

    @model_validator(mode="after")
    def validate_atom_counts(self) -> AtomisticVisualizationData:
        if not self.positions or len(self.positions) != len(self.numbers):
            raise ValueError("atomistic positions and numbers must have the same non-zero length")
        return self


class AtomisticVisualization(VisualizationBase):
    kind: Literal["atomistic.v1"] = "atomistic.v1"
    data: AtomisticVisualizationData


class ChartEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=100)
    type: Literal["quantitative", "nominal", "ordinal"]
    unit: str | None = Field(default=None, max_length=30)


class ChartVisualization(VisualizationBase):
    kind: Literal["chart.v1"] = "chart.v1"
    mark: Literal["bar", "line", "scatter"]
    rows: list[dict[str, VisualizationValue]] = Field(min_length=1, max_length=10_000)
    x: ChartEncoding
    y: ChartEncoding

    @model_validator(mode="after")
    def validate_chart_fields(self) -> ChartVisualization:
        for row in self.rows:
            if self.x.field not in row or self.y.field not in row:
                raise ValueError("chart rows must contain the declared x and y fields")
            value = row[self.y.field]
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise ValueError("chart y values must be numeric")
        return self


class TableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    unit: str | None = Field(default=None, max_length=30)


class TableVisualization(VisualizationBase):
    kind: Literal["table.v1"] = "table.v1"
    columns: list[TableColumn] = Field(min_length=1, max_length=50)
    rows: list[dict[str, VisualizationValue]] = Field(max_length=10_000)

    @model_validator(mode="after")
    def validate_table_fields(self) -> TableVisualization:
        fields = [column.field for column in self.columns]
        if len(fields) != len(set(fields)):
            raise ValueError("table column fields must be unique")
        if any(field not in row for row in self.rows for field in fields):
            raise ValueError("table rows must contain every declared column field")
        return self


class ImageVisualization(VisualizationBase):
    kind: Literal["image.v1"] = "image.v1"
    artifact_path: str
    alt: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_artifact_path(self) -> ImageVisualization:
        path = PurePosixPath(self.artifact_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}
        ):
            raise ValueError("image artifact_path must be a safe relative raster image path")
        return self


VisualizationSpec = Annotated[
    AtomisticVisualization | ChartVisualization | TableVisualization | ImageVisualization,
    Field(discriminator="kind"),
]


class VisualizationCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    experiment_id: str
    visualizations: list[VisualizationSpec] = Field(
        default_factory=list,
        max_length=MAX_VISUALIZATION_CATALOG_ITEMS,
    )

    @model_validator(mode="after")
    def validate_unique_ids(self) -> VisualizationCatalog:
        ids = [visualization.id for visualization in self.visualizations]
        if len(ids) != len(set(ids)):
            raise ValueError("visualization ids must be unique")
        return self


class VisualizationCatalogReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["catalog-reference.v1"] = "catalog-reference.v1"
    artifact_path: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*_visualizations\.json$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    visualization_count: int = Field(ge=0, le=MAX_VISUALIZATION_CATALOG_ITEMS)


class SweepResultsArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["sweep-results.v1"] = "sweep-results.v1"
    experiment_id: str
    results: dict[str, SweepResult]


class SweepResultsReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["sweep-results-reference.v1"] = "sweep-results-reference.v1"
    artifact_path: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*_sweeps\.json$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sweep_count: int = Field(ge=1, le=128)


class ScriptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    metrics: dict[str, MetricResult]
    data: dict[str, Any] = Field(default_factory=dict)
    visualizations: list[VisualizationSpec] = Field(default_factory=list, max_length=32)


class ScriptResult(ScriptOutput):
    stdout: str = ""
    execution_profile: ScriptExecutionProfile = "analysis"


NodeExecutionStatus = Literal[
    "COMPLETE",
    "QUEUED",
    "RUNNING",
    "REVIEW",
    "FAILED",
    "BLOCKED",
    "NOT_RUN",
]

HypothesisReviewReason = Literal[
    "MISSING_METRIC",
    "INVALID_EXPRESSION",
    "NON_NUMERIC_VALUE",
    "INSUFFICIENT_SAMPLES",
    "EVALUATION_ERROR",
]


class HypothesisEval(BaseModel):
    id: str
    status: Literal["PASSED", "REVIEW", "FAILED"]
    metric: str
    value: str
    # Kept optional for result bundles produced before target-node attribution
    # was added. New assemblies always populate this field.
    target_node: str = ""
    sample_size: int = 0
    ci_low: float | None = None
    ci_high: float | None = None
    review_reason: HypothesisReviewReason | None = None
    detail: str | None = Field(default=None, max_length=500)


class ScientificQualityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=160)
    status: Literal["PASS", "REVIEW", "FAILED"]
    value: str | float
    unit: str = Field(min_length=1, max_length=80)
    criterion: str = Field(min_length=1, max_length=500)


class ScientificCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["CALIBRATED", "INSUFFICIENT_EVIDENCE"]
    accepted_case_count: int = Field(default=0, ge=0)
    minimum_case_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_calibration_count(self) -> ScientificCalibration:
        if self.status == "CALIBRATED" and (
            self.minimum_case_count <= 0 or self.accepted_case_count < self.minimum_case_count
        ):
            raise ValueError("CALIBRATED requires accepted_case_count >= minimum_case_count > 0")
        return self


class ScientificDecision(BaseModel):
    """Canonical decision surface shared by scripts, reports, and the UI."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["scientific-decision.v1"] = "scientific-decision.v1"
    outcome: Literal["VALIDATED", "REVIEW", "BLOCKED"]
    calibration: ScientificCalibration
    scope: str = Field(min_length=1, max_length=1000)
    headline: str = Field(min_length=1, max_length=1000)
    supported_claims: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(min_length=1, max_length=64)
    quality_checks: list[ScientificQualityCheck] = Field(default_factory=list, max_length=64)


class ModelMetadata(BaseModel):
    name: str = "unknown"
    version: str = "unknown"
    checkpoint: str | None = None
    checkpoint_sha256: str | None = None
    head: str | None = None
    dtype: str | None = None
    hardware: str | None = None
    device: str = "unknown"


class ResultsGraph(BaseModel):
    experiment_id: str
    status: Literal["SUCCESS", "FAILED", "PARTIAL"] = "SUCCESS"
    metrics: dict[str, MetricResult]
    hypotheses: list[HypothesisEval]
    node_statuses: dict[str, NodeExecutionStatus] = Field(default_factory=dict)
    model_info: ModelMetadata = Field(default_factory=ModelMetadata)
    node_model_info: dict[str, ModelMetadata] = Field(default_factory=dict)
    summary: str
    errors: dict[str, str] = Field(default_factory=dict)


class ExperimentResultsResponse(BaseModel):
    """Stable, permissive result shape for the experiment bundle endpoint."""

    experiment_id: str
    status: Literal["SUCCESS", "FAILED", "PARTIAL"]
    metrics: dict[str, MetricResult]
    hypotheses: list[HypothesisEval]
    node_statuses: dict[str, NodeExecutionStatus] = Field(default_factory=dict)
    model_info: ModelMetadata
    node_model_info: dict[str, ModelMetadata]
    summary: str
    errors: dict[str, str]


class ExperimentBundleResponse(BaseModel):
    results: ExperimentResultsResponse
    spec: ExperimentSpec
    scientific_decision: ScientificDecision
    analysis: Any | None = None
    visualization_catalog_ref: VisualizationCatalogReference | None = None
    sweep_results_ref: SweepResultsReference | None = None
    script_results: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]


class RunRecord(BaseModel):
    experiment_id: str
    state: Literal["QUEUED", "RUNNING", "COMPLETED", "PARTIAL", "FAILED"]
    call_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
    parent_experiment_id: str | None = Field(default=None, max_length=100)
    revision: int = Field(default=0, ge=0, le=1_000)
    script_snapshot_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RunRecordResponse(RunRecord):
    """Stable API representation with no omitted defaulted fields."""

    call_id: str | None
    created_at: datetime
    updated_at: datetime
    error: str | None
    parent_experiment_id: str | None = Field(max_length=100)
    revision: int = Field(ge=0, le=1_000)
    script_snapshot_id: str | None


class DeleteExperimentResponse(BaseModel):
    deleted: str


class ReportResponse(BaseModel):
    content: str
