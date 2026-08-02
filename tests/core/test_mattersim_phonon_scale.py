from __future__ import annotations

import pytest

from atomforge.compute_scaling import partition_selection, run_with_batch_backoff


def test_partition_selection_is_complete_and_non_overlapping() -> None:
    selection = [{"mp_id": f"mp-{index}"} for index in range(1000)]

    shards = [
        partition_selection(
            selection,
            shard_index=index,
            shard_count=4,
            expected_size=250,
        )
        for index in range(4)
    ]

    assert all(len(shard) == 250 for shard in shards)
    assert len({case["mp_id"] for shard in shards for case in shard}) == 1000
    assert [case["mp_id"] for case in shards[0][:3]] == ["mp-0", "mp-4", "mp-8"]


def test_batch_backoff_retries_only_memory_errors() -> None:
    attempted: list[int] = []
    backoffs: list[tuple[int, int]] = []

    def run_batch(batch_size: int) -> str:
        attempted.append(batch_size)
        if batch_size > 2:
            raise MemoryError("synthetic GPU OOM")
        return "forces"

    result, effective_size, retries = run_with_batch_backoff(
        16,
        run_batch,
        is_memory_error=lambda exc: isinstance(exc, MemoryError),
        on_backoff=lambda previous, current: backoffs.append((previous, current)),
    )

    assert result == "forces"
    assert effective_size == 2
    assert retries == 3
    assert attempted == [16, 8, 4, 2]
    assert backoffs == [(16, 8), (8, 4), (4, 2)]


def test_batch_backoff_does_not_hide_other_failures() -> None:
    with pytest.raises(ValueError, match="physics error"):
        run_with_batch_backoff(
            16,
            lambda _: (_ for _ in ()).throw(ValueError("physics error")),
            is_memory_error=lambda exc: isinstance(exc, MemoryError),
        )
