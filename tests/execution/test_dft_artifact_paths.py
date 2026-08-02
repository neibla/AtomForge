import pytest

from atomforge.execution import artifact_paths
from atomforge.execution.artifact_paths import resolve_dft_artifact_dir
from atomforge.execution.script_runner import _claim_dft_attempt


@pytest.fixture
def artifact_root(tmp_path, monkeypatch):
    root = tmp_path / "dft-artifacts"
    root.mkdir()
    monkeypatch.setattr(artifact_paths, "DFT_ARTIFACT_ROOT", root)
    return root


@pytest.mark.parametrize(
    "value",
    [
        "relative/run",
        "/tmp/dft-artifacts-copy/run",
    ],
)
def test_artifact_paths_must_be_absolute_children(value, artifact_root):
    with pytest.raises(ValueError, match="absolute|child"):
        resolve_dft_artifact_dir(value)


def test_artifact_paths_resolve_dotdot_and_reject_escape(artifact_root):
    valid = resolve_dft_artifact_dir(str(artifact_root / "run" / ".." / "run-1"))
    assert valid == artifact_root / "run-1"

    with pytest.raises(ValueError, match="child"):
        resolve_dft_artifact_dir(str(artifact_root / "run" / ".." / ".." / "escape"))


def test_artifact_root_itself_is_not_a_run_destination(artifact_root):
    with pytest.raises(ValueError, match="child"):
        resolve_dft_artifact_dir(str(artifact_root))


def test_dft_attempt_claim_is_exclusive_after_canonicalization(artifact_root):
    arguments = {"artifact_dir": str(artifact_root / "run" / ".." / "run-1")}
    _claim_dft_attempt("dft.py", arguments)

    assert (artifact_root / "run-1" / "attempt.json").is_file()
    with pytest.raises(RuntimeError, match="Refusing to replay"):
        _claim_dft_attempt("dft.py", arguments)


def test_symlinked_artifact_parent_cannot_escape(artifact_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (artifact_root / "alias").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="child"):
        resolve_dft_artifact_dir(str(artifact_root / "alias" / "run"))
