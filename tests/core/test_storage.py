import json

from atomforge.storage import create_json_exclusive, read_json, write_json_atomic, write_text_atomic


def test_atomic_writers_replace_complete_files(tmp_path):
    json_path = tmp_path / "result.json"
    text_path = tmp_path / "report.md"

    write_json_atomic(json_path, {"status": "QUEUED"})
    write_json_atomic(json_path, {"status": "COMPLETED"})
    write_text_atomic(text_path, "complete report\n")

    assert read_json(json_path) == {"status": "COMPLETED"}
    assert json.loads(json_path.read_text()) == {"status": "COMPLETED"}
    assert text_path.read_text() == "complete report\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_exclusive_json_creation_rejects_duplicate_submission(tmp_path):
    path = tmp_path / "run.json"

    create_json_exclusive(path, {"state": "QUEUED"})

    import pytest

    with pytest.raises(FileExistsError):
        create_json_exclusive(path, {"state": "QUEUED"})
