import asyncio
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from atomforge.contracts import ScriptExecutionProfile, SimulationMode
from atomforge.execution.result_assembly import assemble_results
from atomforge.execution.script_runner import script_source_sha256
from atomforge.execution.simulation_trials import SimulationTrialRunner
from atomforge.execution.sweep_runner import SweepRunner
from atomforge.manifest import runtime_fingerprint
from atomforge.schemas import (
    AtomsData,
    DagNode,
    ExperimentSpec,
    ModelMetadata,
    ResultsGraph,
    ScriptResult,
    SimulationResult,
    SweepResult,
)

ExecutionResult = tuple[ResultsGraph, dict[str, Any], dict[str, Any]]
logger = logging.getLogger(__name__)


def _rehydrate_cached_output(node: DagNode, value: Any) -> Any:
    """Restore node contract models after caches that serialize through JSON."""

    if node.type in {"FETCH", "ALLOY"}:
        return value if isinstance(value, AtomsData) else AtomsData.model_validate(value)
    if node.type == "SCRIPT":
        return value if isinstance(value, ScriptResult) else ScriptResult.model_validate(value)
    if node.type == "SWEEP":
        return value if isinstance(value, SweepResult) else SweepResult.model_validate(value)
    if node.type == "SIMULATE" and isinstance(value, dict):
        from atomforge.simulation_modes import MODE_CONTRACTS

        model = MODE_CONTRACTS[node.params["mode"]].result_model
        return {
            "ensemble": [
                item if isinstance(item, model) else model.model_validate(item)
                for item in value.get("ensemble", [])
            ]
        }
    return value


class BaseExecutor(ABC):
    """Abstract interface for executing physics nodes."""

    @abstractmethod
    async def fetch(
        self,
        element: str | None = None,
        structure_path: str | None = None,
    ) -> AtomsData:
        pass

    @abstractmethod
    async def alloy(
        self,
        parent: AtomsData,
        supercell: list[int],
        dopants: dict[str, float],
        seed: int = 0,
        vacancy: bool = False,
    ) -> AtomsData:
        pass

    @abstractmethod
    async def simulate(
        self,
        atoms_data: AtomsData,
        mode: SimulationMode,
        params: dict,
        seed: int = 0,
    ) -> SimulationResult:
        pass

    @abstractmethod
    async def script(
        self,
        inputs: dict[str, Any],
        script: str,
        arguments: dict[str, Any],
        output_metrics: dict[str, str],
        timeout_seconds: int,
        execution_profile: ScriptExecutionProfile,
    ) -> ScriptResult:
        pass

    def model_metadata(self) -> ModelMetadata:
        return ModelMetadata(name=self.__class__.__name__)


class CoreOrchestrator:
    """Pure Python DAG orchestrator decoupled from infrastructure."""

    def __init__(
        self,
        executor: BaseExecutor,
        node_cache: Any = None,
        *,
        script_source_root: Path | None = None,
        max_simulation_concurrency: int = 4,
    ):
        self.executor = executor
        self.node_cache = node_cache
        self.script_source_root = script_source_root
        self.trial_runner = SimulationTrialRunner(
            executor.simulate,
            max_concurrency=max_simulation_concurrency,
        )
        self.sweep_runner = SweepRunner(self.trial_runner)
        self.runtime_fingerprint = runtime_fingerprint()

    def _executor_metadata(self) -> ModelMetadata:
        return self.executor.model_metadata()

    def _node_hash(
        self,
        node: DagNode,
        deps: list[str],
        hashes: dict[str, str],
    ) -> str:
        cache_identity = {
            "cache_contract": "v2",
            "node_type": node.type,
            "params": node.params,
            "dependency_hashes": [hashes.get(dep) for dep in deps],
            "model": self._executor_metadata().model_dump(mode="json"),
            "runtime": self.runtime_fingerprint,
        }
        if node.type == "SCRIPT":
            cache_identity["script_sha256"] = script_source_sha256(
                node.params["script"],
                source_root=self.script_source_root,
            )
            cache_identity["execution_profile"] = node.params.get("execution_profile", "analysis")
        canonical_identity = json.dumps(cache_identity, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_identity.encode()).hexdigest()

    async def _execute_node_operation(
        self,
        node: DagNode,
        deps: list[str],
        *,
        results: dict[str, Any],
        structures: dict[str, AtomsData],
    ) -> tuple[Any, ValueError | None]:
        if node.type == "FETCH":
            return (
                await self.executor.fetch(
                    structure_path=node.params.get("structure_path"),
                    element=node.params.get("element"),
                ),
                None,
            )
        if node.type == "ALLOY":
            return (
                await self.executor.alloy(
                    results[deps[0]],
                    node.params.get("supercell", [3, 3, 3]),
                    node.params.get("dopants", {}),
                    node.params.get("seed", 0),
                    vacancy=node.params.get("vacancy", False),
                ),
                None,
            )
        if node.type == "SIMULATE":
            parent_input = structures[deps[0]]
            return (
                {
                    "ensemble": await self.trial_runner.run(
                        parent=parent_input,
                        mode=node.params.get("mode", "pka"),
                        params=node.params,
                        trials=node.params.get("trials", 1),
                    )
                },
                None,
            )
        if node.type == "SWEEP":
            execution = await self.sweep_runner.execute(
                node_id=node.id,
                parent=structures[deps[0]],
                params=node.params,
            )
            return execution.result, execution.error
        if node.type == "SCRIPT":
            return (
                await self.executor.script(
                    inputs={dep: results[dep] for dep in deps},
                    script=node.params["script"],
                    arguments=node.params.get("arguments", {}),
                    output_metrics=node.params["output_metrics"],
                    timeout_seconds=node.params.get("timeout_seconds", 300),
                    execution_profile=node.params.get("execution_profile", "analysis"),
                ),
                None,
            )
        raise ValueError(f"Unsupported node type: {node.type}")

    def _record_provenance(
        self,
        node: DagNode,
        node_output: Any,
        node_model_info: dict[str, ModelMetadata],
    ) -> None:
        if node.type in {"SIMULATE", "SWEEP"}:
            node_model_info[node.id] = self._executor_metadata()
            return
        if not isinstance(node_output, ScriptResult):
            return
        model_info = node_output.data.get("model_info")
        if not isinstance(model_info, dict):
            return
        metadata = ModelMetadata.model_validate(model_info)
        node_model_info[node.id] = metadata

    def _record_structure(
        self,
        node: DagNode,
        deps: list[str],
        node_output: Any,
        structures: dict[str, AtomsData],
    ) -> None:
        if isinstance(node_output, AtomsData):
            structures[node.id] = node_output
            return
        if node.type != "SIMULATE" or not isinstance(node_output, dict):
            return
        ensemble = node_output.get("ensemble", [])
        if not ensemble or len(ensemble) != 1:
            return

        from ase.data import chemical_symbols

        parent = structures[deps[0]]
        result = ensemble[0]
        positions = getattr(result, "positions", None) or getattr(result, "final_positions", None)
        if positions is None:
            structures[node.id] = parent
            return
        atomic_numbers = getattr(result, "atomic_numbers", None)
        symbols = (
            [chemical_symbols[number] for number in atomic_numbers]
            if atomic_numbers
            else parent.symbols
        )
        if len(symbols) != len(positions):
            raise ValueError(
                f"Symbol/position mismatch in node '{node.id}': "
                f"{len(symbols)} symbols for {len(positions)} positions."
            )
        structures[node.id] = AtomsData(
            symbols=symbols,
            positions=positions,
            cell=getattr(result, "cell", None) or parent.cell,
            pbc=parent.pbc,
        )

    async def execute(self, spec: ExperimentSpec) -> ExecutionResult:
        results: dict[str, Any] = {}
        hashes: dict[str, str] = {}
        errors: dict[str, str] = {}
        structures: dict[str, AtomsData] = {}
        node_model_info: dict[str, ModelMetadata] = {}
        events = {node.id: asyncio.Event() for node in spec.dag}

        async def execute_node(node: DagNode) -> None:
            deps = node.dependencies
            for dep in deps:
                await events[dep].wait()

            failed_dependencies = [dep for dep in deps if dep in errors]
            if failed_dependencies:
                errors[node.id] = f"Dependency failed: {', '.join(failed_dependencies)}"
                events[node.id].set()
                return

            try:
                await execute_node_body(node, deps)
            except Exception as exc:  # noqa: BLE001
                errors[node.id] = str(exc)
            finally:
                events[node.id].set()

        async def execute_node_body(node: DagNode, deps: list[str]) -> None:
            node_hash = self._node_hash(node, deps, hashes)
            hashes[node.id] = node_hash

            if self.node_cache is not None and not spec.force_recompute:
                try:
                    cache_hit = await self.node_cache.contains.aio(node_hash)
                    if cache_hit:
                        node_output = _rehydrate_cached_output(
                            node,
                            await self.node_cache.get.aio(node_hash),
                        )
                        results[node.id] = node_output
                        self._record_structure(node, deps, node_output, structures)
                        self._record_provenance(node, node_output, node_model_info)
                        return
                except Exception as exc:  # noqa: BLE001
                    # The cache is derived acceleration state. A read outage or
                    # stale/corrupt entry must never turn valid computation into
                    # a failed scientific run.
                    logger.warning(
                        "Ignoring node cache read failure; recomputing node",
                        extra={"node_id": node.id, "error": str(exc)},
                    )

            node_output, deferred_error = await self._execute_node_operation(
                node,
                deps,
                results=results,
                structures=structures,
            )

            results[node.id] = node_output
            self._record_structure(node, deps, node_output, structures)
            self._record_provenance(node, node_output, node_model_info)
            if deferred_error is not None:
                raise deferred_error
            if self.node_cache is not None:
                try:
                    await self.node_cache.put.aio(node_hash, node_output)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Ignoring node cache write failure after successful execution",
                        extra={"node_id": node.id, "error": str(exc)},
                    )

        await asyncio.gather(*(asyncio.create_task(execute_node(node)) for node in spec.dag))

        ordered_results = {node.id: results[node.id] for node in spec.dag if node.id in results}
        ordered_errors = {node.id: errors[node.id] for node in spec.dag if node.id in errors}
        ordered_model_info = {
            node.id: node_model_info[node.id] for node in spec.dag if node.id in node_model_info
        }
        result_graph, trial_bundle = assemble_results(
            spec,
            ordered_results,
            ordered_errors,
            executor_metadata=self._executor_metadata(),
            node_model_info=ordered_model_info,
        )
        return result_graph, trial_bundle, ordered_results
