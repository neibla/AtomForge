from __future__ import annotations

import hashlib
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from atomforge.contracts import SimulationMode

_MISSING = object()


@dataclass(frozen=True, slots=True)
class SweepPointBinding:
    """Canonical parameters for one coordinate value in a parameter sweep."""

    value: float
    applied_value: float | list[float]
    simulation_params: dict[str, Any]


def get_parameter(params: dict[str, Any], target: str, *, default: Any = None) -> Any:
    """Read a dotted dict/list path, returning ``default`` when it is absent."""

    current: Any = params
    for segment in target.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
        else:
            return default
    return current


def parameter_is_set(params: dict[str, Any], target: str) -> bool:
    return get_parameter(params, target, default=_MISSING) is not _MISSING


def bind_sweep_point(
    *,
    operation_params: dict[str, Any],
    target: str,
    value: float,
    apply_value: Callable[[float], float | list[float]],
    mode: SimulationMode,
    trials: int,
) -> SweepPointBinding:
    """Apply one coordinate value and assemble the canonical simulation contract."""

    applied_value = apply_value(value)
    simulation_params = with_parameter(operation_params, target, applied_value)
    simulation_params.update(mode=mode, trials=trials)
    return SweepPointBinding(
        value=value,
        applied_value=applied_value,
        simulation_params=simulation_params,
    )


def with_parameter(params: dict[str, Any], target: str, value: Any) -> dict[str, Any]:
    """Return a copy of params with a dotted object path assigned."""

    updated = deepcopy(params)
    current: Any = updated
    segments = target.split(".")
    for segment in segments[:-1]:
        if isinstance(current, dict):
            existing = current.get(segment)
            if existing is None:
                existing = {}
                current[segment] = existing
            if not isinstance(existing, dict | list):
                raise ValueError(f"sweep target '{target}' crosses scalar field '{segment}'")
            current = existing
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                raise ValueError(f"sweep target '{target}' has out-of-range index {index}")
            current = current[index]
        else:
            raise ValueError(f"sweep target '{target}' cannot traverse '{segment}'")
    final = segments[-1]
    if isinstance(current, dict):
        current[final] = value
    elif isinstance(current, list) and final.isdigit():
        index = int(final)
        if index >= len(current):
            raise ValueError(f"sweep target '{target}' has out-of-range index {index}")
        current[index] = value
    else:
        raise ValueError(f"sweep target '{target}' cannot assign '{final}'")
    return updated


def sweep_point_id(node_id: str, index: int) -> str:
    suffix = f"-point-{index:04d}"
    if len(node_id) + len(suffix) <= 100:
        return f"{node_id}{suffix}"
    digest = hashlib.sha256(node_id.encode()).hexdigest()[:10]
    return f"{node_id[: 100 - len(suffix) - 11]}-{digest}{suffix}"
