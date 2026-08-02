from collections.abc import Mapping
from typing import Any

from atomforge.schemas import ScriptResult


def select_report_contexts(script_results: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Keep aggregate dataset evidence when present, otherwise return all entries."""
    entries = [
        (str(node_id), result.data if isinstance(result, ScriptResult) else result["data"])
        for node_id, result in script_results.items()
        if isinstance(result, ScriptResult)
        or (isinstance(result, Mapping) and isinstance(result.get("data"), dict))
    ]
    aggregate = [
        entry
        for entry in entries
        if isinstance(entry[1].get("dataset"), dict)
        and isinstance(entry[1]["dataset"].get("shard_count"), int | float)
        and any(
            isinstance(entry[1]["dataset"].get(key), int | float)
            for key in ("unique_case_count", "selected_case_count", "population_sample_size")
        )
    ]
    return aggregate or entries
