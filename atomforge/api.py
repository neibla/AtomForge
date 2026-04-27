from __future__ import annotations

import json
import os
from typing import Any

import modal
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atomforge.manifest import build_run_manifest, write_run_manifest
from atomforge.orchestrator import BaseExecutor, CoreOrchestrator
from atomforge.schemas import (
    AtomsData,
    DagNode,
    ExperimentSpec,
    ResultsGraph,
    SimulationResult,
)
from atomforge.validators import validate_experiment_spec

results_volume = modal.NetworkFileSystem.from_name("atomforge-results-v1", create_if_missing=True)

# MINIMAL API IMAGE
API_IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .add_local_file("pyproject.toml", remote_path="/root/pyproject.toml", copy=True)
    .add_local_file("uv.lock", remote_path="/root/uv.lock", copy=True)
    .uv_sync(extras=["physics"])  # Needs ase for orchestrator logic
    .add_local_dir(
        os.path.dirname(os.path.abspath(__file__)), remote_path="/root/atomforge", copy=True
    )
)

# HEAVY PHYSICS IMAGE
PHYSICS_IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("wget", "git")
    .add_local_file("pyproject.toml", remote_path="/root/pyproject.toml", copy=True)
    .add_local_file("uv.lock", remote_path="/root/uv.lock", copy=True)
    .uv_sync(extras=["physics"]) 
    .run_commands(
        "mkdir -p /root/.cache/mace",
        "wget https://github.com/ACEsuit/mace-foundations/releases/download/"
        "mace_mh_1/mace-mh-1.model -O /root/.cache/mace/mace-mh-1.model",
    )
    .add_local_dir(
        os.path.dirname(os.path.abspath(__file__)), remote_path="/root/atomforge", copy=True
    )
)

app = modal.App("atomforge-unified")
node_cache = modal.Dict.from_name("atomforge-node-cache-v02", create_if_missing=True)
mp_secret = modal.Secret.from_dict({"MP_API_KEY": os.environ.get("MP_API_KEY", "")})


def _metric_val(metrics: dict[str, Any], key: str) -> float | None:
    item = metrics.get(key)
    if isinstance(item, dict):
        val = item.get("val")
        return float(val) if isinstance(val, (int, float)) else None
    if hasattr(item, "val"):
        val = getattr(item, "val")
        return float(val) if isinstance(val, (int, float)) else None
    return None


def build_analysis_payload(
    spec: ExperimentSpec,
    results: ResultsGraph,
    trial_metrics_by_node: dict[str, list[dict[str, float]]],
) -> dict[str, Any]:
    pka_conditions: list[dict[str, Any]] = []
    for node in spec.dag:
        if node.type != "SIMULATE" or node.params.get("mode", "pka") != "pka":
            continue

        node_trials = trial_metrics_by_node.get(node.id, [])
        trial_defects = [
            float(trial["n_defects"])
            for trial in node_trials
            if isinstance(trial, dict) and isinstance(trial.get("n_defects"), (int, float))
        ]
        trial_energies = [
            float(trial["energy"])
            for trial in node_trials
            if isinstance(trial, dict) and isinstance(trial.get("energy"), (int, float))
        ]

        pka_conditions.append(
            {
                "node_id": node.id,
                "energy_ev": float(node.params.get("energy_ev", 0.0)),
                "temperature_K": float(node.params.get("temperature_K", 0.0)),
                "mean_defects": _metric_val(results.metrics, f"{node.id}_n_defects"),
                "std_defects": _metric_val(results.metrics, f"{node.id}_std_defects"),
                "mean_energy": _metric_val(results.metrics, f"{node.id}_energy"),
                "runtime_ms": _metric_val(results.metrics, f"{node.id}_runtime_ms"),
                "trial_defects": trial_defects,
                "trial_energies": trial_energies,
            }
        )

    energy_trend = [
        c
        for c in sorted(pka_conditions, key=lambda x: (x["temperature_K"], x["energy_ev"]))
        if c["mean_defects"] is not None
    ]
    temperature_trend = [
        c
        for c in sorted(pka_conditions, key=lambda x: (x["energy_ev"], x["temperature_K"]))
        if c["mean_defects"] is not None
    ]

    return {
        "pka_conditions": pka_conditions,
        "energy_trend": energy_trend,
        "temperature_trend": temperature_trend,
    }


@app.cls(image=PHYSICS_IMAGE, secrets=[mp_secret], timeout=3600, max_containers=10)
class PhysicsWorker:
    @modal.enter()
    def setup(self):
        import torch
        from mace.calculators import MACECalculator

        from atomforge.simulator import FreeEnergyWrapper, SimulationEngine

        m_path = "/root/.cache/mace/mace-mh-1.model"
        device = "cuda" if torch.cuda.is_available() else "cpu"
        calc = MACECalculator(
            model_paths=m_path,
            device=device,
            default_dtype="float64",
            compute_stress=True,
            head="matpes_r2scan",
        )
        engine = SimulationEngine(model=m_path, device=device)
        engine.calc = FreeEnergyWrapper(calc)
        self.engine = engine

    @modal.method()
    async def simulate(
        self, atoms_data: AtomsData, mode: str, params: dict, seed: int = 0
    ) -> SimulationResult:
        return self.engine.run(atoms_data, mode, params, seed)

    @modal.method()
    async def fetch(self, element: str) -> AtomsData:
        from atomforge.fetch import fetch_structure

        res = fetch_structure(element)
        return AtomsData(
            symbols=res.atoms.get_chemical_symbols(),
            positions=res.atoms.get_positions().tolist(),
            cell=res.atoms.get_cell().tolist(),
            dft_energy=float(res.dft_energy_per_atom),
        )

    @modal.method()
    async def alloy(
        self, parent: AtomsData, supercell: list[int], dopants: dict[str, float]
    ) -> AtomsData:
        from ase import Atoms

        from atomforge.fetch import StructureRecord, make_alloy_supercell

        at = Atoms(symbols=parent.symbols, positions=parent.positions, cell=parent.cell, pbc=True)
        alloyed = make_alloy_supercell(
            StructureRecord(
                material_id="tmp", formula="Tmp", atoms=at, dft_energy_per_atom=0, dft_forces=[]
            ),
            supercell=tuple(supercell),
            dopants=dopants,
        )
        return AtomsData(
            symbols=alloyed.atoms.get_chemical_symbols(),
            positions=alloyed.atoms.get_positions().tolist(),
            cell=alloyed.atoms.get_cell().tolist(),
        )


class HardwareRouter:
    @staticmethod
    def get_spec(n_atoms: int) -> dict[str, Any]:
        if n_atoms < 50:
            return {"gpu": None, "cpu": 8, "memory": 16384}
        elif n_atoms < 500:
            return {"gpu": "T4", "cpu": 4, "memory": 8192}
        elif n_atoms < 10000:
            return {"gpu": "A100-40GB", "cpu": 8, "memory": 32768}
        else:
            return {"gpu": "A100-80GB", "cpu": 12, "memory": 65536}


class ModalExecutor(BaseExecutor):
    """Modal implementation of the physics executor."""

    async def fetch(self, element: str) -> AtomsData:
        return await PhysicsWorker().fetch.remote.aio(element)

    async def alloy(
        self, parent: AtomsData, supercell: list[int], dopants: dict[str, float]
    ) -> AtomsData:
        return await PhysicsWorker().alloy.remote.aio(parent, supercell, dopants)

    async def simulate(
        self, atoms_data: AtomsData, mode: str, params: dict, seed: int = 0
    ) -> SimulationResult:
        spec = HardwareRouter.get_spec(len(atoms_data.symbols))
        Worker = PhysicsWorker.with_options(gpu=spec["gpu"], cpu=spec["cpu"], memory=spec["memory"])
        return await Worker().simulate.remote.aio(atoms_data, mode, params, seed)


@app.cls(
    image=API_IMAGE,
    secrets=[mp_secret],
    network_file_systems={"/results": results_volume},
    timeout=3600,
    max_containers=1,
)
class Orchestrator:
    @modal.method()
    async def execute(self, spec: ExperimentSpec) -> ResultsGraph:
        validate_experiment_spec(spec)
        executor = ModalExecutor()
        core = CoreOrchestrator(executor, node_cache=node_cache)
        final_res, trial_bundle, results = await core.execute(spec)
        trial_data = trial_bundle.get("trial_data", {})
        trial_metrics_by_node = trial_bundle.get("trial_metrics_by_node", {})
        analysis = build_analysis_payload(spec, final_res, trial_metrics_by_node)

        # PERSIST TO CLOUD VOLUME
        os.makedirs("/results", exist_ok=True)
        bundle = {
            "results": final_res.model_dump(),
            "spec": spec.model_dump(),
            "analysis": analysis,
        }
        with open(f"/results/{spec.experiment_id}.json", "w") as f:
            json.dump(bundle, f, indent=2)
        manifest = build_run_manifest(spec, final_res)
        write_run_manifest(f"/results/{spec.experiment_id}_manifest.json", manifest)

        # Enhanced Markdown Report Generation
        md_report = f"# Research Report: {spec.experiment_id}\n\n"
        md_report += "## Executive Summary\n"
        md_report += f"This experiment targeted the validation of material properties for **{spec.experiment_id}**. "
        md_report += f"The DAG execution involved {len(spec.dag)} nodes across the distributed infrastructure.\n\n"
        
        md_report += "## Hypotheses & Validation\n"
        hypo_map = {h.id: h.assertion for h in spec.hypotheses}
        for h in final_res.hypotheses:
            status_emoji = "✅" if h.status == "PROVEN" else "❌" if h.status == "DISPROVEN" else "⚠️"
            md_report += f"- {status_emoji} **{h.id}**: {h.status}\n"
            md_report += f"  - Metric: `{h.metric}`\n"
            md_report += f"  - Value: `{h.value}`\n"
            md_report += f"  - Assertion: `{hypo_map.get(h.id, 'N/A')}`\n"
            md_report += f"  - Confidence: `{h.confidence*100:.1f}%`\n\n"

        md_report += "## Simulation Methodology\n"
        md_report += "The structures were simulated using the following DAG sequence:\n"
        for node in spec.dag:
            md_report += f"### Node: {node.id} ({node.type})\n"
            md_report += f"- **Parameters**: `{node.params}`\n"
            if node.depends_on:
                md_report += f"- **Dependencies**: `{node.depends_on}`\n"
            md_report += "\n"

        md_report += "## Results Discussion\n"
        md_report += "### Key Metrics\n"
        for k, v in final_res.metrics.items():
            md_report += f"- **{k}**: {v.val:.4f} {v.unit}\n"
        
        md_report += "\n---\n*Generated by AtomForge Orchestrator v0.4.0*"

        with open(f"/results/{spec.experiment_id}.md", "w") as f:
            f.write(md_report)

        last_sim = next((nid for nid in reversed(trial_data.keys())), None)
        if last_sim:
            trial = trial_data[last_sim]
            viz_payload = {
                "positions": trial.final_positions,
                "numbers": results[spec.dag[0].id].symbols,
                "trajectory": trial.trajectory,
            }
            viz_payload.update(trial.model_dump())
            with open(f"/results/{spec.experiment_id}_viz.json", "w") as f:
                json.dump(viz_payload, f)

        return final_res


web_app = FastAPI()
web_app.add_middleware(CORSMiddleware, allow_origins=["*"])


@web_app.get("/experiments")
def list_experiments():
    if not os.path.exists("/results"):
        return []
    return [
        f.replace(".json", "")
        for f in os.listdir("/results")
        if f.endswith(".json") and not f.endswith("_viz.json") and not f.endswith("_manifest.json")
    ]


@web_app.get("/experiments/{id}")
def get_experiment(id: str):
    path = f"/results/{id}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"error": "Not found"}


@web_app.get("/experiments/{id}/report")
def get_report_md(id: str):
    path = f"/results/{id}.md"
    if os.path.exists(path):
        with open(path) as f:
            return {"content": f.read()}
    return {"error": "Not found"}


@web_app.get("/experiments/{id}/viz")
def get_viz(id: str):
    path = f"/results/{id}_viz.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"error": "Not found"}


@app.function(
    image=API_IMAGE, secrets=[mp_secret], network_file_systems={"/results": results_volume}
)
@modal.asgi_app()
def fastapi_app():
    return web_app


@app.local_entrypoint()
async def main(spec_path: str | None = None):
    if spec_path:
        with open(spec_path) as f:
            spec = ExperimentSpec.model_validate_json(f.read())
    else:
        spec = ExperimentSpec(
            experiment_id="refactor-test",
            dag=[DagNode(id="f1", type="FETCH", params={"element": "W"})],
        )

    print(f"🚀 Dispatching Experiment: {spec.experiment_id} (Cloud Pool)")
    validate_experiment_spec(spec)
    res = await Orchestrator().execute.remote.aio(spec=spec)

    # LOCAL PERSISTENCE RESTORED
    log_path = f"research/{spec.experiment_id}.md"
    json_path = f"research/{spec.experiment_id}.json"
    manifest_path = f"research/manifests/{spec.experiment_id}_manifest.json"
    os.makedirs("research", exist_ok=True)

    # Enhanced Markdown Report Generation (Matches Cloud version)
    md_report = f"# Research Report: {spec.experiment_id}\n\n"
    md_report += "## Executive Summary\n"
    md_report += f"This experiment targeted the validation of material properties for **{spec.experiment_id}**. "
    md_report += f"The DAG execution involved {len(spec.dag)} nodes across the distributed infrastructure.\n\n"
    
    md_report += "## Hypotheses & Validation\n"
    hypo_map = {h.id: h.assertion for h in spec.hypotheses}
    for h in res.hypotheses:
        status_emoji = "✅" if h.status == "PROVEN" else "❌" if h.status == "DISPROVEN" else "⚠️"
        md_report += f"- {status_emoji} **{h.id}**: {h.status}\n"
        md_report += f"  - Metric: `{h.metric}`\n"
        md_report += f"  - Value: `{h.value}`\n"
        md_report += f"  - Assertion: `{hypo_map.get(h.id, 'N/A')}`\n"
        md_report += f"  - Confidence: `{h.confidence*100:.1f}%`\n\n"

    md_report += "## Simulation Methodology\n"
    md_report += "The structures were simulated using the following DAG sequence:\n"
    for node in spec.dag:
        md_report += f"### Node: {node.id} ({node.type})\n"
        md_report += f"- **Parameters**: `{node.params}`\n"
        if node.depends_on:
            md_report += f"- **Dependencies**: `{node.depends_on}`\n"
        md_report += "\n"

    md_report += "## Results Discussion\n"
    md_report += "### Key Metrics\n"
    for k, v in res.metrics.items():
        md_report += f"- **{k}**: {v.val:.4f} {v.unit}\n"
    
    md_report += "\n---\n*Generated by AtomForge Orchestrator v0.4.0*"

    with open(log_path, "w") as f:
        f.write(md_report)
    with open(json_path, "w") as f:
        bundle = {"results": res.model_dump(), "spec": spec.model_dump()}
        json.dump(bundle, f, indent=2)
    manifest = build_run_manifest(spec, res)
    write_run_manifest(manifest_path, manifest)

    print("\n✅ Done. Results persisted locally and to Modal volume.")
