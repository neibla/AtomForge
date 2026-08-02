from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, Protocol

from atomforge.contracts import SimulationMode
from atomforge.schemas import AtomsData, SimulationResult


class Simulate(Protocol):
    def __call__(
        self,
        atoms_data: AtomsData,
        mode: SimulationMode,
        params: dict[str, Any],
        seed: int = 0,
    ) -> Awaitable[SimulationResult]: ...


class SimulationTrialRunner:
    """Run seeded simulation trials under one workflow-wide concurrency limit."""

    def __init__(self, simulate: Simulate, *, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._simulate = simulate
        self._worker_semaphore = asyncio.Semaphore(max_concurrency)

    async def run(
        self,
        *,
        parent: AtomsData,
        mode: SimulationMode,
        params: dict[str, Any],
        trials: int,
    ) -> list[SimulationResult]:
        tasks = [
            asyncio.create_task(self._run_trial(parent, mode, params, seed))
            for seed in range(trials)
        ]
        try:
            return await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _run_trial(
        self,
        parent: AtomsData,
        mode: SimulationMode,
        params: dict[str, Any],
        seed: int,
    ) -> SimulationResult:
        async with self._worker_semaphore:
            return await self._simulate(parent, mode, params, seed=seed)
