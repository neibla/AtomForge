from __future__ import annotations

import random

import numpy as np


def mean_and_bootstrap_ci(values: list[float], confidence: float = 0.95) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    if len(values) == 1:
        v = float(values[0])
        return v, v, v

    alpha = 1.0 - confidence
    arr = np.array(values, dtype=float)
    mean = float(arr.mean())

    rng = random.Random(42)
    boots = []
    n = len(arr)
    for _ in range(400):
        sample = [arr[rng.randrange(n)] for _ in range(n)]
        boots.append(float(np.mean(sample)))
    boots.sort()
    low = float(np.quantile(boots, alpha / 2.0))
    high = float(np.quantile(boots, 1.0 - alpha / 2.0))
    return mean, low, high


def confidence_from_ci(mean: float, ci_low: float, ci_high: float) -> float:
    """Map CI tightness to a bounded confidence score for UI compatibility."""
    denom = abs(mean) + 1e-9
    rel_half_width = ((ci_high - ci_low) / 2.0) / denom
    score = 1.0 - rel_half_width
    return float(max(0.0, min(1.0, score)))
