import pytest
from pydantic import ValidationError

from atomforge.schemas import (
    ChartVisualization,
    DagNode,
    ExperimentSpec,
    MetricResult,
    PKAFrameMetric,
    PKAResult,
    ScriptResult,
    SinglePointResult,
    SweepResult,
    VisualizationCatalog,
)
from atomforge.visualizations import build_visualization_catalog


def test_catalog_collects_simulation_and_script_visualizations():
    spec = ExperimentSpec(
        experiment_id="visualization-catalog",
        dag=[
            DagNode(
                id="energy",
                type="SIMULATE",
                depends_on="fetch",
                params={"mode": "single_point"},
            ),
            DagNode(
                id="analysis",
                type="SCRIPT",
                depends_on="energy",
                params={
                    "script": "vacancy_disagreement_rank.py",
                    "output_metrics": {"value": "eV"},
                },
            ),
        ],
    )
    trial = SinglePointResult(
        seed=0,
        potential_energy=-10.0,
        max_force=0.0,
        force_norm=0.0,
        forces=[[0.0, 0.0, 0.0]],
        positions=[[0.0, 0.0, 0.0]],
        cell=[[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
        atomic_numbers=[74],
    )
    script_result = ScriptResult(
        metrics={"value": MetricResult(val=1.0, unit="eV")},
        visualizations=[
            ChartVisualization(
                id="comparison",
                title="Comparison",
                mark="bar",
                rows=[{"source": "Paper", "value": 1.0}],
                x={"field": "source", "type": "nominal"},
                y={"field": "value", "type": "quantitative", "unit": "eV"},
            )
        ],
    )

    catalog = build_visualization_catalog(
        spec,
        trial_data={"energy": trial},
        node_results={"analysis": script_result},
    )

    assert [visualization.kind for visualization in catalog.visualizations] == [
        "atomistic.v1",
        "chart.v1",
    ]
    assert catalog.visualizations[1].id == "analysis-comparison"
    assert catalog.visualizations[1].source_node == "analysis"


def test_chart_contract_rejects_non_numeric_y_values():
    with pytest.raises(ValidationError, match="chart y values must be numeric"):
        ChartVisualization(
            id="bad-chart",
            title="Bad chart",
            mark="bar",
            rows=[{"source": "Paper", "value": "unknown"}],
            x={"field": "source", "type": "nominal"},
            y={"field": "value", "type": "quantitative"},
        )


def test_atomistic_contract_accepts_lattice_metadata():
    from atomforge.schemas import AtomisticVisualization

    visualization = AtomisticVisualization(
        id="bcc-lattice",
        title="bcc tungsten lattice",
        data={
            "positions": [[0.0, 0.0, 0.0], [1.5, 1.5, 1.5]],
            "numbers": [74, 74],
            "symbols": ["W", "W"],
            "cell": [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
            "pbc": [True, True, True],
            "metadata": {"structure": "bcc", "lattice_parameter_A": 3.0},
        },
    )
    assert visualization.data.metadata["structure"] == "bcc"
    assert visualization.data.pbc == [True, True, True]


def test_catalog_preserves_simulation_visualization_metadata():
    spec = ExperimentSpec(
        experiment_id="visualization-metadata",
        dag=[
            DagNode(
                id="eos_a300",
                type="SIMULATE",
                depends_on="fetch",
                params={"mode": "single_point"},
            ),
        ],
    )
    trial = {
        "positions": [[0.0, 0.0, 0.0]],
        "atomic_numbers": [74],
        "cell": [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
        "pbc": [True, True, True],
        "metadata": {"structure": "bcc", "lattice_parameter_A": 3.0},
    }

    catalog = build_visualization_catalog(
        spec,
        trial_data={"eos_a300": trial},
        node_results={},
    )

    atomistic = catalog.visualizations[0]
    assert atomistic.data.metadata == {
        "structure": "bcc",
        "lattice_parameter_A": 3.0,
    }


def test_catalog_authors_scan_parameter_metadata_from_script_contract():
    spec = ExperimentSpec(
        experiment_id="coordinate-scan-metadata",
        dag=[
            DagNode(
                id="scan_m010",
                type="SIMULATE",
                depends_on="fetch",
                params={"mode": "single_point"},
            ),
            DagNode(
                id="scan_p010",
                type="SIMULATE",
                depends_on="fetch",
                params={"mode": "single_point"},
            ),
            DagNode(
                id="analyze_scan",
                type="SCRIPT",
                depends_on=["scan_m010", "scan_p010"],
                params={
                    "script": "vacancy_disagreement_rank.py",
                    "output_metrics": {"scan_points": "count"},
                    "arguments": {
                        "coordinate_label": "W atom [111] displacement",
                        "scan_nodes": [
                            {"node_id": "scan_m010", "displacement_A": -0.1},
                            {"node_id": "scan_p010", "displacement_A": 0.1},
                        ],
                    },
                },
            ),
        ],
    )
    trial = {
        "positions": [[0.0, 0.0, 0.0]],
        "atomic_numbers": [74],
        "cell": [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
        "pbc": [True, True, True],
    }

    catalog = build_visualization_catalog(
        spec,
        trial_data={"scan_m010": trial, "scan_p010": trial},
        node_results={},
    )

    assert catalog.visualizations[0].data.metadata == {
        "scan_parameter_series": "analyze_scan",
        "scan_parameter_label": "W atom [111] displacement",
        "scan_parameter_value": -0.1,
        "scan_parameter_unit": "Å",
        "scan_parameter_signed": True,
    }


def test_catalog_expands_sweep_result_into_slider_ready_visualizations():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "sweep-visualizations",
            "dag": [
                {
                    "id": "eos",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "lattice_constant_A",
                            "label": "Lattice parameter",
                            "unit": "Å",
                            "grid": {"start": 5.4, "stop": 5.5, "step": 0.1},
                        },
                        "apply": {"target": "cell_scale"},
                    },
                }
            ],
        }
    )
    trial = SinglePointResult(
        seed=0,
        potential_energy=-3,
        max_force=0,
        force_norm=0,
        forces=[[0, 0, 0]],
        positions=[[0, 0, 0]],
        atomic_numbers=[14],
        cell=[[3, 0, 0], [0, 3, 0], [0, 0, 3]],
    )
    sweep = SweepResult.model_validate(
        {
            "coordinate": spec.dag[0].params["coordinate"],
            "apply": spec.dag[0].params["apply"],
            "points": [
                {
                    "id": "eos-point-0000",
                    "index": 0,
                    "value": 5.4,
                    "applied_value": 5.4,
                    "simulation_params": {"cell_scale": 5.4},
                    "status": "COMPLETED",
                    "ensemble": [trial],
                },
                {
                    "id": "eos-point-0001",
                    "index": 1,
                    "value": 5.5,
                    "applied_value": 5.5,
                    "simulation_params": {"cell_scale": 5.5},
                    "status": "COMPLETED",
                    "ensemble": [trial],
                },
            ],
        }
    )

    catalog = build_visualization_catalog(spec, trial_data={}, node_results={"eos": sweep})

    assert len(catalog.visualizations) == 2
    assert catalog.visualizations[1].data.metadata["scan_parameter_series"] == "eos"
    assert catalog.visualizations[1].data.metadata["scan_parameter_value"] == 5.5
    assert catalog.visualizations[1].data.metadata["scan_parameter_unit"] == "Å"


def test_catalog_rejects_duplicate_visualization_ids():
    chart = ChartVisualization(
        id="same",
        title="Chart",
        mark="bar",
        rows=[{"x": "A", "y": 1.0}],
        x={"field": "x", "type": "nominal"},
        y={"field": "y", "type": "quantitative"},
    )

    with pytest.raises(ValidationError, match="visualization ids must be unique"):
        VisualizationCatalog(
            experiment_id="duplicates",
            visualizations=[chart, chart],
        )


def test_catalog_can_hold_every_point_in_a_thousand_point_sweep():
    visualizations = [
        ChartVisualization(
            id=f"sweep-point-{index:04d}",
            title=f"Sweep point {index}",
            mark="scatter",
            rows=[{"x": index, "y": float(index)}],
            x={"field": "x", "type": "quantitative"},
            y={"field": "y", "type": "quantitative"},
        )
        for index in range(1_000)
    ]

    catalog = VisualizationCatalog(
        experiment_id="large-sweep",
        visualizations=visualizations,
    )

    assert len(catalog.visualizations) == 1_000


def test_pka_catalog_preserves_linked_explorer_evidence():
    spec = ExperimentSpec(
        experiment_id="pka-explorer",
        dag=[
            DagNode(
                id="cascade",
                type="SIMULATE",
                params={"mode": "pka"},
            )
        ],
    )
    metric = PKAFrameMetric(
        frame=0,
        step=10,
        time_fs=1.0,
        kinetic_energy_ev=25.0,
        potential_energy_ev=-200.0,
        temperature_K=850.0,
        n_defects=1,
        interstitials=1,
        displaced_atoms=3,
        max_displacement_angstrom=1.5,
        vacancy_positions=[[0.0, 0.0, 0.0]],
        interstitial_positions=[[1.0, 1.0, 1.0]],
    )
    trial = PKAResult(
        seed=7,
        n_defects=1,
        interstitials=1,
        energy=-5.0,
        initial_positions=[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
        final_positions=[[0.1, 0.0, 0.0], [1.2, 1.0, 1.0]],
        atomic_numbers=[74, 74],
        trajectory=[[[0.1, 0.0, 0.0], [1.2, 1.0, 1.0]]],
        cell=[[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
        vacancy_positions=metric.vacancy_positions,
        interstitial_positions=metric.interstitial_positions,
        pka_index=1,
        frame_metrics=[metric],
    )

    catalog = build_visualization_catalog(
        spec,
        trial_data={"cascade": trial},
        node_results={},
    )

    visualization = catalog.visualizations[0]
    assert visualization.kind == "atomistic.v1"
    assert visualization.data.simulation_mode == "pka"
    assert visualization.data.cell == trial.cell
    assert visualization.data.n_defects == 1
    assert visualization.data.frame_metrics[0].temperature_K == 850.0
    assert visualization.data.frame_metrics[0].interstitial_positions == [[1.0, 1.0, 1.0]]
