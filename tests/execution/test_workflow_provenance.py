from atomforge.execution.result_assembly import workflow_model_metadata
from atomforge.schemas import ModelMetadata


def _metadata(name: str, version: str, checkpoint: str) -> ModelMetadata:
    return ModelMetadata(
        name=name,
        version=version,
        checkpoint=checkpoint,
        head="default",
        dtype="float32",
        device="cuda",
    )


def test_single_component_preserves_exact_model_identity():
    mace = _metadata("MACE-MP-0", "0.3.15", "mace sha256:" + "c" * 64)

    summary = workflow_model_metadata(
        ModelMetadata(name="executor-default"),
        {"reproduce_mace": mace},
    )

    assert summary == mace


def test_multi_component_workflow_does_not_masquerade_as_executor_default():
    executor = ModelMetadata(
        name="MACE-MH-1",
        version="mace_mh_1",
        checkpoint="mace-mh-1.model",
        device="auto",
    )
    nodes = {
        "reproduce_mace": _metadata("MACE-MP-0", "0.3.15", "mace sha256:" + "c" * 64),
        "evaluate_mattersim": _metadata("MatterSim", "1.0.0rc9", "mattersim sha256:" + "d" * 64),
    }

    summary = workflow_model_metadata(executor, nodes)

    assert summary.name.startswith("Multi-component workflow:")
    assert "MACE-MP-0@0.3.15" in summary.name
    assert "MatterSim@1.0.0rc9" in summary.name
    assert summary.name != executor.name
    assert summary.version == "workflow-provenance.v1"
    assert summary.checkpoint is None
    assert summary.head == "per-node"
