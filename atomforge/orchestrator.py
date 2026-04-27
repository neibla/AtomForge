from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from typing import Any

import numpy as np
from simpleeval import simple_eval

from atomforge.schemas import (
    AtomsData,
    ExperimentSpec,
    HypothesisEval,
    MetricResult,
    ResultsGraph,
    SimulationResult,
)
from atomforge.stats import confidence_from_ci, mean_and_bootstrap_ci


class BaseExecutor(ABC):
    """Abstract interface for executing physics nodes."""

    @abstractmethod
    async def fetch(self, element: str) -> AtomsData:
        pass

    @abstractmethod
    async def alloy(
        self, parent: AtomsData, supercell: list[int], dopants: dict[str, float]
    ) -> AtomsData:
        pass

    @abstractmethod
    async def simulate(
        self, atoms_data: AtomsData, mode: str, params: dict, seed: int = 0
    ) -> SimulationResult:
        pass


class CoreOrchestrator:
    """Pure Python DAG Orchestrator decoupled from infrastructure."""

    def __init__(self, executor: BaseExecutor, node_cache: Any = None):
        self.executor = executor
        self.node_cache = node_cache
        self.worker_semaphore = asyncio.Semaphore(4)

    async def execute(self, spec: ExperimentSpec) -> ResultsGraph:
        results = {}
        hashes = {}
        events = {node.id: asyncio.Event() for node in spec.dag}

        async def execute_node(node):
            # 1. Wait for dependencies
            deps = (
                node.depends_on
                if isinstance(node.depends_on, list)
                else ([node.depends_on] if node.depends_on else [])
            )
            for dep in deps:
                await events[dep].wait()

            # 2. Content-addressable hashing
            dep_hashes = [hashes.get(d) for d in deps]
            node_h = hashlib.sha256(f"{node.type}{node.params}{dep_hashes}".encode()).hexdigest()
            hashes[node.id] = node_h

            # 3. Cache lookup
            if self.node_cache and await self.node_cache.contains.aio(node_h):
                results[node.id] = await self.node_cache.get.aio(node_h)
                events[node.id].set()
                return

            # 4. Infrastructure-agnostic execution
            if node.type == "FETCH":
                node_out = await self.executor.fetch(node.params["element"])

            elif node.type == "ALLOY":
                parent_data = results[deps[0]]
                node_out = await self.executor.alloy(
                    parent_data,
                    node.params.get("supercell", [3, 3, 3]),
                    node.params.get("dopants", {}),
                )

            elif node.type == "SIMULATE" or node.type == "SOLVE_QUANTUM":
                # Position and Symbol Extraction Logic
                parent_atoms = results[spec.dag[0].id]
                input_data = results[deps[0]]

                if isinstance(input_data, dict) and "ensemble" in input_data:
                    from ase.data import chemical_symbols
                    last_res = input_data["ensemble"][0]
                    
                    # RelaxResult uses 'positions', others use 'final_positions'
                    pos = (
                        last_res.positions
                        if hasattr(last_res, "positions") and last_res.positions
                        else last_res.final_positions
                    )
                    cell = (
                        last_res.cell
                        if hasattr(last_res, "cell") and last_res.cell
                        else parent_atoms.cell
                    )
                    
                    # Ensure symbols match the count of positions (crucial for PKA/Relax downstream)
                    if hasattr(last_res, "atomic_numbers") and last_res.atomic_numbers:
                        symbols = [chemical_symbols[z] for z in last_res.atomic_numbers]
                    else:
                        # Fallback to parent symbols if they match the count, otherwise raise
                        if len(parent_atoms.symbols) == len(pos):
                            symbols = parent_atoms.symbols
                        else:
                            raise ValueError(
                                f"Symbol/Position mismatch: {len(parent_atoms.symbols)} symbols "
                                f"but {len(pos)} positions in node {deps[0]}"
                            )

                    parent_input = AtomsData(
                        symbols=symbols,
                        positions=pos,
                        cell=cell,
                    )
                else:
                    parent_input = input_data

                trials = node.params.get("trials", 1)
                mode = node.params.get("mode", "pka") if node.type == "SIMULATE" else "solve_quantum"

                async with self.worker_semaphore:
                    tasks = [
                        self.executor.simulate(parent_input, mode, node.params, seed=i)
                        for i in range(trials)
                    ]
                    node_out = {"ensemble": await asyncio.gather(*tasks)}
            else:
                events[node.id].set()
                return

            results[node.id] = node_out
            if self.node_cache:
                await self.node_cache.put.aio(node_h, node_out)
            events[node.id].set()

        # Run DAG
        tasks = [asyncio.create_task(execute_node(node)) for node in spec.dag]
        await asyncio.gather(*tasks)

        # 5. Hypothesis Evaluation
        context = {}
        trial_data = {}
        trial_metric_samples: dict[str, list[float]] = {}
        trial_metrics_by_node: dict[str, list[dict[str, float]]] = {}
        for nid, res in results.items():
            if isinstance(res, dict) and "ensemble" in res:
                ensemble = res["ensemble"]
                if ensemble:
                    trial_data[nid] = ensemble[0]
                    node_trials: list[dict[str, float]] = []
                    for key in ensemble[0].__class__.model_fields:
                        vals = [
                            getattr(r, key)
                            for r in ensemble
                            if isinstance(getattr(r, key), (int, float, bool))
                        ]
                        if vals:
                            metric_key = f"{nid}_{key}"
                            context[metric_key] = float(np.mean(vals))
                            trial_metric_samples[metric_key] = [float(v) for v in vals]
                            trial_metrics_by_node.setdefault(nid, [])
                            if len(trial_metrics_by_node[nid]) < len(vals):
                                trial_metrics_by_node[nid] = [{} for _ in range(len(vals))]
                            for i, v in enumerate(vals):
                                trial_metrics_by_node[nid][i][key] = float(v)
                    if nid in trial_metrics_by_node:
                        node_trials = trial_metrics_by_node[nid]
                    else:
                        node_trials = [{} for _ in range(len(ensemble))]
                    trial_metrics_by_node[nid] = node_trials
            elif isinstance(res, AtomsData):
                if res.dft_energy is not None:
                    context[f"{nid}_energy"] = res.dft_energy

        evals = []
        import re
        for hypo in spec.hypotheses:
            # Replace target prefix
            expr = hypo.assertion.replace("target.", f"{hypo.target_node}.")
            # Replace dots in variables (e.g., node.metric) but NOT in floats (e.g., 5.0)
            # We ensure we only match valid Python identifiers (start with letter/underscore)
            eval_expr = re.sub(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b', r'\1_\2', expr)
            
            try:
                status = "PROVEN" if simple_eval(eval_expr, names=context) else "DISPROVEN"
                metric_key = f"{hypo.target_node}_{hypo.metric}"
                samples = trial_metric_samples.get(metric_key, [])
                if samples:
                    mean_v, ci_low, ci_high = mean_and_bootstrap_ci(samples)
                    value = f"{mean_v:.6g} (95% CI [{ci_low:.6g}, {ci_high:.6g}], n={len(samples)})"
                    confidence = confidence_from_ci(mean_v, ci_low, ci_high)
                else:
                    value = str(context.get(metric_key, "0"))
                    confidence = 0.5
                evals.append(
                    HypothesisEval(
                        id=hypo.id,
                        status=status,
                        metric=hypo.metric,
                        value=value,
                        confidence=confidence,
                    )
                )
            except Exception:
                evals.append(
                    HypothesisEval(
                        id=hypo.id, status="REVIEW", metric=hypo.metric, value="Error", confidence=0
                    )
                )

        return (
            ResultsGraph(
                experiment_id=spec.experiment_id,
                metrics={k: MetricResult(val=v, unit="val") for k, v in context.items()},
                hypotheses=evals,
                summary="Completed.",
            ),
            {
                "trial_data": trial_data,
                "trial_metrics_by_node": trial_metrics_by_node,
            },
            results,
        )
