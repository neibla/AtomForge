from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from atomforge.contracts import MAX_SWEEP_POINT_ERROR_LENGTH
from atomforge.execution.simulation_trials import SimulationTrialRunner
from atomforge.schemas import (
    AtomsData,
    SweepParams,
    SweepPointResult,
    SweepResult,
)
from atomforge.sweeps import bind_sweep_point, sweep_point_id


@dataclass(frozen=True, slots=True)
class SweepExecution:
    """The aggregate evidence and any node-level failure it implies."""

    result: SweepResult
    error: ValueError | None = None


class SweepRunner:
    """Execute one parameter sweep while keeping its points internal to the DAG."""

    def __init__(
        self,
        trial_runner: SimulationTrialRunner,
    ) -> None:
        self._trial_runner = trial_runner

    async def execute(
        self,
        *,
        node_id: str,
        parent: AtomsData,
        params: dict[str, Any] | SweepParams,
    ) -> SweepExecution:
        sweep = params if isinstance(params, SweepParams) else SweepParams.model_validate(params)
        point_semaphore = asyncio.Semaphore(sweep.max_concurrency)

        async def run_point(index: int, value: float) -> SweepPointResult:
            binding = bind_sweep_point(
                operation_params=sweep.operation.params,
                target=sweep.apply.target,
                value=value,
                apply_value=sweep.apply.apply,
                mode=sweep.operation.mode,
                trials=sweep.operation.trials,
            )
            try:
                async with point_semaphore:
                    ensemble = await self._trial_runner.run(
                        parent=parent,
                        mode=sweep.operation.mode,
                        params=binding.simulation_params,
                        trials=sweep.operation.trials,
                    )
                return SweepPointResult(
                    id=sweep_point_id(node_id, index),
                    index=index,
                    value=binding.value,
                    applied_value=binding.applied_value,
                    simulation_params=binding.simulation_params,
                    status="COMPLETED",
                    ensemble=ensemble,
                )
            except Exception as exc:  # noqa: BLE001
                return SweepPointResult(
                    id=sweep_point_id(node_id, index),
                    index=index,
                    value=binding.value,
                    applied_value=binding.applied_value,
                    simulation_params=binding.simulation_params,
                    status="FAILED",
                    error=_point_error(exc),
                )

        result = SweepResult(
            coordinate=sweep.coordinate,
            apply=sweep.apply,
            points=await asyncio.gather(
                *(
                    run_point(index, value)
                    for index, value in enumerate(sweep.coordinate.grid.materialize())
                )
            ),
        )
        return SweepExecution(
            result=result,
            error=self._failure(node_id=node_id, sweep=sweep, result=result),
        )

    @staticmethod
    def _failure(
        *,
        node_id: str,
        sweep: SweepParams,
        result: SweepResult,
    ) -> ValueError | None:
        if result.completed_count == 0:
            return ValueError(f"SWEEP node '{node_id}' failed every point")
        if sweep.failure_policy == "require_all" and result.failed_count:
            return ValueError(
                f"SWEEP node '{node_id}' failed {result.failed_count} of "
                f"{len(result.points)} points"
            )
        return None


def _point_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    if len(message) <= MAX_SWEEP_POINT_ERROR_LENGTH:
        return message
    suffix = "… [truncated]"
    return f"{message[: MAX_SWEEP_POINT_ERROR_LENGTH - len(suffix)]}{suffix}"
