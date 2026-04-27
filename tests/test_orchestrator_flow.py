from __future__ import annotations

from atomforge.orchestrator import BaseExecutor, CoreOrchestrator
from atomforge.schemas import AtomsData, DagNode, ExperimentSpec, Hypothesis, PKAResult, SimulationResult


class FakeExecutor(BaseExecutor):
    async def fetch(self, element: str) -> AtomsData:
        return AtomsData(
            symbols=["W", "W"],
            positions=[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
            cell=[[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]],
        )

    async def alloy(
        self, parent: AtomsData, supercell: list[int], dopants: dict[str, float]
    ) -> AtomsData:
        return parent

    async def simulate(
        self, atoms_data: AtomsData, mode: str, params: dict, seed: int = 0
    ) -> SimulationResult:
        return PKAResult(seed=seed, n_defects=seed + 1, energy=-3.0)


async def test_orchestrator_happy_path_with_mock_executor():
    spec = ExperimentSpec(
        experiment_id="mock-e2e",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(id="a1", type="ALLOY", depends_on="f1", params={"supercell": [1, 1, 1]}),
            DagNode(
                id="s1",
                type="SIMULATE",
                depends_on="a1",
                params={"mode": "pka", "trials": 2, "energy_ev": 1000.0},
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

    core = CoreOrchestrator(executor=FakeExecutor())
    result, _, _ = await core.execute(spec)

    assert result.status == "SUCCESS"
    assert result.hypotheses[0].status == "PROVEN"
    assert 0.0 <= result.hypotheses[0].confidence <= 1.0
