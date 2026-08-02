from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from atomforge.execution.orchestrator import BaseExecutor, CoreOrchestrator
from atomforge.execution.script_runner import run_script_node
from atomforge.schemas import (
    AtomsData,
    DagNode,
    ExperimentSpec,
    Hypothesis,
    ModelMetadata,
    PKAResult,
    ScriptResult,
    SinglePointResult,
    SweepResult,
)
from atomforge.serialization import to_jsonable


class FakeExecutor(BaseExecutor):
    def model_metadata(self) -> ModelMetadata:
        return ModelMetadata(
            name="FakePotential",
            version="test",
            checkpoint_sha256="a" * 64,
            device="cpu",
        )

    async def fetch(
        self,
        element: str | None = None,
        structure_path: str | None = None,
    ) -> AtomsData:
        symbol = element or "W"
        return AtomsData(
            symbols=[symbol, symbol],
            positions=[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
            cell=[[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]],
            pbc=[True, True, False],
        )

    async def alloy(
        self,
        parent: AtomsData,
        supercell: list[int],
        dopants: dict[str, float],
        seed: int = 0,
        vacancy: bool = False,
    ) -> AtomsData:
        return parent

    async def simulate(self, atoms_data, mode, params, seed=0):
        if mode == "single_point":
            return SinglePointResult(
                seed=seed,
                potential_energy=-3.0,
                max_force=0.0,
                force_norm=0.0,
                forces=[[0.0, 0.0, 0.0] for _ in atoms_data.symbols],
                positions=atoms_data.positions,
                final_positions=atoms_data.positions,
                atomic_numbers=[74 for _ in atoms_data.symbols],
                cell=atoms_data.cell,
            )
        return PKAResult(seed=seed, n_defects=seed + 1, energy=-3.0)

    async def script(
        self,
        inputs,
        script,
        arguments,
        output_metrics,
        timeout_seconds,
        execution_profile,
    ) -> ScriptResult:
        return run_script_node(
            script=script,
            inputs=inputs,
            arguments=arguments,
            output_metrics=output_metrics,
            timeout_seconds=timeout_seconds,
            execution_profile=execution_profile,
        )


class FailingExecutor(FakeExecutor):
    async def simulate(self, atoms_data, mode, params, seed=0):
        raise RuntimeError("worker unavailable")


class SelectiveFailExecutor(FakeExecutor):
    async def simulate(self, atoms_data, mode, params, seed=0):
        if params.get("fail"):
            raise RuntimeError("selected worker failure")
        return await super().simulate(atoms_data, mode, params, seed)


class ConcurrentExecutor(FakeExecutor):
    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def simulate(self, atoms_data, mode, params, seed=0):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return PKAResult(seed=seed, n_defects=0, energy=-3.0)


class CountingExecutor(FakeExecutor):
    def __init__(self):
        self.calls = 0

    async def simulate(self, atoms_data, mode, params, seed=0):
        self.calls += 1
        return await super().simulate(atoms_data, mode, params, seed)


class SweepRecordingExecutor(FakeExecutor):
    def __init__(self):
        self.scales: list[float] = []
        self.params: list[dict] = []

    async def simulate(self, atoms_data, mode, params, seed=0):
        self.scales.append(params["cell_scale"])
        self.params.append(dict(params))
        return await super().simulate(atoms_data, mode, params, seed)


class PartiallyFailingSweepExecutor(FakeExecutor):
    def __init__(self, *, fail_all: bool = False):
        self.fail_all = fail_all

    async def simulate(self, atoms_data, mode, params, seed=0):
        if self.fail_all or params["cell_scale"] > 1:
            raise RuntimeError("point failed")
        return await super().simulate(atoms_data, mode, params, seed)


class LongErrorSweepExecutor(FakeExecutor):
    async def simulate(self, atoms_data, mode, params, seed=0):
        raise RuntimeError("worker context: " + "x" * 3_000)


class CancellingTrialExecutor(FakeExecutor):
    def __init__(self):
        self.cancelled = False

    async def simulate(self, atoms_data, mode, params, seed=0):
        if seed == 0:
            raise RuntimeError("first trial failed")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return await super().simulate(atoms_data, mode, params, seed)


class OtherModelExecutor(CountingExecutor):
    def model_metadata(self) -> ModelMetadata:
        return ModelMetadata(
            name="OtherPotential",
            version="test",
            checkpoint_sha256="b" * 64,
            device="cpu",
        )


class AsyncOperation:
    def __init__(self, callback):
        self.callback = callback

    async def aio(self, *args):
        return self.callback(*args)


class InMemoryCache:
    def __init__(self):
        self.values = {}
        self.contains = AsyncOperation(lambda key: key in self.values)
        self.get = AsyncOperation(self.values.__getitem__)
        self.put = AsyncOperation(self.values.__setitem__)


class JsonRoundTripCache(InMemoryCache):
    def __init__(self):
        super().__init__()
        self.get = AsyncOperation(lambda key: json.loads(json.dumps(to_jsonable(self.values[key]))))


class UnavailableCache:
    def __init__(self):
        self.contains = AsyncOperation(self._unavailable)
        self.get = AsyncOperation(self._unavailable)
        self.put = AsyncOperation(self._unavailable)

    @staticmethod
    def _unavailable(*_args):
        raise ConnectionError("cache service unavailable")


async def test_happy_path_aggregates_trials_and_records_node_provenance():
    spec = ExperimentSpec(
        experiment_id="mock-e2e",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="s1",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "pka", "trials": 2},
            ),
        ],
        hypotheses=[
            Hypothesis(
                id="h1",
                target_node="s1",
                metric="n_defects",
                assertion="target.n_defects >= 1",
            )
        ],
    )
    result, trial_bundle, _ = await CoreOrchestrator(FakeExecutor()).execute(spec)
    assert result.status == "SUCCESS"
    assert result.hypotheses[0].status == "PASSED"
    assert result.hypotheses[0].target_node == "s1"
    assert result.hypotheses[0].sample_size == 2
    assert result.node_statuses == {"f1": "COMPLETE", "s1": "COMPLETE"}
    assert result.node_model_info["s1"].checkpoint_sha256 == "a" * 64
    assert "s1" not in trial_bundle["trial_data"]
    assert len(trial_bundle["trial_metrics_by_node"]["s1"]) == 2


async def test_failure_and_partial_results_are_explicit():
    failed = ExperimentSpec(
        experiment_id="failed",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(id="s1", type="SIMULATE", depends_on="f1", params={"mode": "pka"}),
        ],
    )
    result, _, _ = await CoreOrchestrator(FailingExecutor()).execute(failed)
    assert result.status == "PARTIAL"
    assert result.errors == {"s1": "worker unavailable"}

    mixed = ExperimentSpec(
        experiment_id="partial",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(id="ok", type="SIMULATE", depends_on="f1", params={"mode": "pka"}),
            DagNode(
                id="bad",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "pka", "fail": True},
            ),
        ],
    )
    result, _, _ = await CoreOrchestrator(SelectiveFailExecutor()).execute(mixed)
    assert result.status == "PARTIAL"
    assert result.errors == {"bad": "selected worker failure"}
    assert result.node_statuses == {"f1": "COMPLETE", "ok": "COMPLETE", "bad": "FAILED"}


async def test_concurrent_trials_are_bounded():
    executor = ConcurrentExecutor()
    spec = ExperimentSpec(
        experiment_id="bounded",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="s1",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "pka", "trials": 10},
            ),
        ],
    )
    result, _, _ = await CoreOrchestrator(executor).execute(spec)
    assert result.status == "SUCCESS"
    assert executor.max_active == 4


async def test_sweep_executes_internal_points_and_returns_one_aggregate_result():
    executor = SweepRecordingExecutor()
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "sweep-execution",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "eos",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point", "trials": 1},
                        "coordinate": {
                            "name": "lattice_constant_A",
                            "label": "Lattice parameter",
                            "unit": "Å",
                            "grid": {"start": 4.9, "stop": 5.1, "step": 0.1},
                        },
                        "apply": {
                            "target": "cell_scale",
                            "transform": "ratio_to_reference",
                            "reference": 5.0,
                        },
                    },
                },
            ],
        }
    )

    results, _, node_results = await CoreOrchestrator(executor).execute(spec)

    sweep = node_results["eos"]
    assert isinstance(sweep, SweepResult)
    assert [point.value for point in sweep.points] == [4.9, 5.0, 5.1]
    assert sorted(executor.scales) == pytest.approx([0.98, 1.0, 1.02])
    observed_params = {params["cell_scale"]: params for params in executor.params}
    assert all(
        observed_params[point.applied_value] == point.simulation_params for point in sweep.points
    )
    assert results.metrics["eos_sample_count"].val == 3


async def test_cached_sweep_output_is_rehydrated_after_json_round_trip():
    cache = JsonRoundTripCache()
    executor = SweepRecordingExecutor()
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "cached-sweep",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "scan",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "scale",
                            "label": "Scale",
                            "grid": {"values": [0.99, 1.01]},
                        },
                        "apply": {"target": "cell_scale"},
                    },
                },
            ],
        }
    )

    await CoreOrchestrator(executor, cache).execute(spec)
    result, _, node_results = await CoreOrchestrator(executor, cache).execute(spec)

    assert isinstance(node_results["scan"], SweepResult)
    assert result.metrics["scan_completed_count"].val == 2
    assert len(executor.scales) == 2


async def test_allow_partial_sweep_marks_run_partial_and_preserves_evidence():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "partial-sweep",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "scan",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "scale",
                            "label": "Scale",
                            "grid": {"values": [0.99, 1.01]},
                        },
                        "apply": {"target": "cell_scale"},
                        "failure_policy": "allow_partial",
                    },
                },
            ],
        }
    )

    result, _, node_results = await CoreOrchestrator(PartiallyFailingSweepExecutor()).execute(spec)

    assert result.status == "PARTIAL"
    assert node_results["scan"].completed_count == 1
    assert node_results["scan"].failed_count == 1
    assert result.node_statuses["scan"] == "REVIEW"


async def test_require_all_sweep_retains_evidence_blocks_descendants_and_skips_cache():
    cache = InMemoryCache()
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "strict-partial-sweep",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "scan",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "scale",
                            "label": "Scale",
                            "grid": {"values": [0.99, 1.01]},
                        },
                        "apply": {"target": "cell_scale"},
                    },
                },
                {
                    "id": "analysis",
                    "type": "SCRIPT",
                    "depends_on": "scan",
                    "params": {
                        "script": "vacancy_disagreement_rank.py",
                        "output_metrics": {"scan_points": "count"},
                    },
                },
            ],
        }
    )

    result, _, node_results = await CoreOrchestrator(
        PartiallyFailingSweepExecutor(),
        cache,
    ).execute(spec)

    assert node_results["scan"].completed_count == 1
    assert node_results["scan"].failed_count == 1
    assert "analysis" not in node_results
    assert result.errors == {
        "scan": "SWEEP node 'scan' failed 1 of 2 points",
        "analysis": "Dependency failed: scan",
    }
    assert result.node_statuses == {
        "fetch": "COMPLETE",
        "scan": "FAILED",
        "analysis": "BLOCKED",
    }
    assert len(cache.values) == 1  # FETCH is cached; terminal SWEEP evidence is not.


async def test_all_failed_sweep_is_an_error_but_retains_point_evidence():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "failed-sweep",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "scan",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "scale",
                            "label": "Scale",
                            "grid": {"values": [0.99, 1.01]},
                        },
                        "apply": {"target": "cell_scale"},
                        "failure_policy": "allow_partial",
                    },
                },
            ],
        }
    )

    result, _, node_results = await CoreOrchestrator(
        PartiallyFailingSweepExecutor(fail_all=True)
    ).execute(spec)

    assert result.status == "PARTIAL"
    assert result.errors == {"scan": "SWEEP node 'scan' failed every point"}
    assert node_results["scan"].failed_count == 2


async def test_sweep_normalizes_long_worker_errors_without_losing_point_evidence():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "long-worker-error",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "scan",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "scale",
                            "label": "Scale",
                            "grid": {"values": [0.99, 1.01]},
                        },
                        "apply": {"target": "cell_scale"},
                    },
                },
            ],
        }
    )

    result, _, node_results = await CoreOrchestrator(LongErrorSweepExecutor()).execute(spec)

    sweep = node_results["scan"]
    assert result.errors == {"scan": "SWEEP node 'scan' failed every point"}
    assert sweep.failed_count == 2
    assert all(len(point.error) == 2_000 for point in sweep.points)
    assert all(point.error.endswith("… [truncated]") for point in sweep.points)


async def test_failed_trial_cancels_and_drains_sibling_trials():
    executor = CancellingTrialExecutor()
    spec = ExperimentSpec(
        experiment_id="cancel-trials",
        dag=[
            DagNode(id="fetch", type="FETCH", params={"element": "W"}),
            DagNode(
                id="simulation",
                type="SIMULATE",
                depends_on="fetch",
                params={"mode": "single_point", "trials": 2},
            ),
        ],
    )

    result, _, _ = await CoreOrchestrator(executor).execute(spec)

    assert result.status == "PARTIAL"
    assert executor.cancelled is True


async def test_cache_key_is_stable_and_separates_exact_model_identity():
    cache = InMemoryCache()
    first = CountingExecutor()
    spec = ExperimentSpec(
        experiment_id="cache",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="s1",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "pka", "trials": 1, "energy_ev": 1000.0},
            ),
        ],
    )
    await CoreOrchestrator(first, cache).execute(spec)
    await CoreOrchestrator(first, cache).execute(spec)
    assert first.calls == 1

    force_spec = spec.model_copy(update={"experiment_id": "cache-rerun", "force_recompute": True})
    await CoreOrchestrator(first, cache).execute(force_spec)
    assert first.calls == 2

    other = OtherModelExecutor()
    await CoreOrchestrator(other, cache).execute(spec)
    assert other.calls == 1


async def test_cache_outage_degrades_to_recomputation_without_failing_the_run():
    executor = CountingExecutor()
    spec = ExperimentSpec(
        experiment_id="cache-outage",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="s1",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "pka", "trials": 1, "energy_ev": 1000.0},
            ),
        ],
    )

    result, _, _ = await CoreOrchestrator(executor, UnavailableCache()).execute(spec)

    assert result.status == "SUCCESS"
    assert executor.calls == 1


async def test_multi_trial_structure_is_not_silently_selected_when_validation_is_bypassed():
    spec = ExperimentSpec(
        experiment_id="no-trial-zero",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="ensemble",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "single_point", "trials": 2},
            ),
            DagNode(
                id="downstream",
                type="SIMULATE",
                depends_on="ensemble",
                params={"mode": "single_point", "trials": 1},
            ),
        ],
    )
    result, _, _ = await CoreOrchestrator(FakeExecutor()).execute(spec)
    assert result.status == "PARTIAL"
    assert "downstream" in result.errors


async def test_script_execution_profile_is_preserved():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "script-contract",
            "dag": [
                {"id": "p", "type": "FETCH", "params": {"element": "W"}},
                {"id": "d", "type": "FETCH", "params": {"element": "V"}},
                {
                    "id": "script",
                    "type": "SCRIPT",
                    "depends_on": ["p", "d"],
                    "params": {
                        "script": "vacancy_disagreement_rank.py",
                        "execution_profile": "analysis",
                        "arguments": {
                            "pristine_node": "p",
                            "defective_node": "d",
                            "paper_reference_ev": 3.0,
                        },
                        "output_metrics": {
                            "vacancy_formation_energy": "eV",
                            "absolute_error_to_paper": "eV",
                        },
                    },
                },
            ],
        }
    )
    executor = FakeExecutor()
    executor.script = AsyncMock(
        return_value=ScriptResult(
            metrics={},
            execution_profile="analysis",
        )
    )
    result, _, nodes = await CoreOrchestrator(executor).execute(spec)
    assert result.status == "SUCCESS"
    executor.script.assert_awaited_once()
    assert executor.script.await_args.kwargs["execution_profile"] == "analysis"
    assert nodes["script"].execution_profile == "analysis"
