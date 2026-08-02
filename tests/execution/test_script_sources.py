import pytest
from modal.exception import AlreadyExistsError

from atomforge.execution.script_sources import (
    script_snapshot_id,
    sync_script_sources,
)


class _Batch:
    def __init__(self):
        self.calls = []

    def put_file(self, local_path, remote_path):
        self.calls.append((local_path, remote_path))


class _Volume:
    def __init__(self, *, mutate=None, fail_first=False, error_type=AlreadyExistsError):
        self.batch = _Batch()
        self.forces = []
        self.mutate = mutate
        self.fail_first = fail_first
        self.error_type = error_type

    def batch_upload(self, *, force):
        self.forces.append(force)
        if self.mutate:
            self.mutate()
        volume = self

        class Context:
            async def __aenter__(self):
                return volume.batch

            async def __aexit__(self, *_):
                if volume.fail_first and not force:
                    raise volume.error_type("already published")
                return None

        return Context()


def test_script_snapshot_id_ignores_bytecode_and_tracks_relative_content(tmp_path):
    source_root = tmp_path / "node_scripts"
    source_root.mkdir()
    (source_root / "new_method.py").write_text("value = 1\n", encoding="utf-8")
    cache_dir = source_root / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "new_method.cpython-312.pyc").write_bytes(b"not portable")

    first = script_snapshot_id(source_root)
    (cache_dir / "new_method.cpython-313.pyc").write_bytes(b"also ignored")
    second = script_snapshot_id(source_root)
    (source_root / "new_method.py").write_text("value = 2\n", encoding="utf-8")
    third = script_snapshot_id(source_root)

    assert first == second
    assert third != first


@pytest.mark.asyncio
async def test_snapshot_upload_uses_captured_bytes_when_source_changes(tmp_path):
    source_root = tmp_path / "node_scripts"
    source_root.mkdir()
    source = source_root / "new_method.py"
    source.write_text("value = 1\n", encoding="utf-8")

    volume = _Volume(mutate=lambda: source.write_text("value = 2\n", encoding="utf-8"))
    snapshot_id = await sync_script_sources(volume, source_root=source_root)

    assert snapshot_id != script_snapshot_id(source_root)
    assert volume.forces == [False]
    assert volume.batch.calls[0][1] == f"snapshots/{snapshot_id}/new_method.py"
    assert volume.batch.calls[0][0].read() == b"value = 1\n"
    assert len(volume.batch.calls) == 1


@pytest.mark.asyncio
async def test_existing_snapshot_is_repaired_only_with_same_captured_bytes(tmp_path):
    source_root = tmp_path / "node_scripts"
    source_root.mkdir()
    (source_root / "new_method.py").write_text("value = 1\n", encoding="utf-8")

    volume = _Volume(fail_first=True)
    await sync_script_sources(volume, source_root=source_root)
    assert volume.forces == [False, True]


@pytest.mark.asyncio
async def test_filesystem_exists_race_is_repaired(tmp_path):
    source_root = tmp_path / "node_scripts"
    source_root.mkdir()
    (source_root / "new_method.py").write_text("value = 1\n", encoding="utf-8")

    volume = _Volume(fail_first=True, error_type=FileExistsError)
    await sync_script_sources(volume, source_root=source_root)
    assert volume.forces == [False, True]
