from __future__ import annotations

from collections.abc import Callable
from typing import Any


def partition_selection(
    selection: list[dict[str, Any]],
    *,
    shard_index: int,
    shard_count: int,
    expected_size: int,
) -> list[dict[str, Any]]:
    """Return one deterministic, non-overlapping strided partition."""
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError(f"shard_index must be between 0 and {shard_count - 1}, got {shard_index}")
    partition = selection[shard_index::shard_count]
    if len(partition) != expected_size:
        raise ValueError(
            f"Shard {shard_index}/{shard_count} selected {len(partition)} cases; "
            f"expected {expected_size}. Ensure population_sample_size equals "
            "sample_size * shard_count."
        )
    return partition


def run_with_batch_backoff[T](
    requested_batch_size: int,
    run_batch: Callable[[int], T],
    *,
    is_memory_error: Callable[[BaseException], bool],
    on_backoff: Callable[[int, int], None] | None = None,
) -> tuple[T, int, int]:
    """Retry one operation at descending powers of two after memory errors."""
    if requested_batch_size < 1:
        raise ValueError("requested_batch_size must be at least 1")
    effective_batch_size = requested_batch_size
    retries = 0
    while True:
        try:
            return (
                run_batch(effective_batch_size),
                effective_batch_size,
                retries,
            )
        except BaseException as exc:
            if not is_memory_error(exc) or effective_batch_size <= 1:
                raise
            previous_batch_size = effective_batch_size
            effective_batch_size = max(1, effective_batch_size // 2)
            retries += 1
            if on_backoff is not None:
                on_backoff(previous_batch_size, effective_batch_size)
