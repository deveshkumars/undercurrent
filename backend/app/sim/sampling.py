"""Seeded random helpers. Everything stochastic in the simulator draws from these so runs are reproducible."""

from __future__ import annotations

import bisect
import hashlib
import math
import random
from typing import Sequence, TypeVar

T = TypeVar("T")


def rng_for(*parts: object) -> random.Random:
    """A Random seeded from any mix of values, stable across processes (unlike hash())."""
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def normalize(probs: Sequence[float]) -> list[float]:
    total = sum(probs)
    if total <= 0:
        return [1 / len(probs)] * len(probs)
    return [p / total for p in probs]


def pick(levels: Sequence[T], probs: Sequence[float], u: float) -> T:
    """Inverse-CDF draw with a supplied uniform, so the same u gives a stable choice as probs shift."""
    cum, acc = [], 0.0
    for p in normalize(probs):
        acc += p
        cum.append(acc)
    i = bisect.bisect_left(cum, u * cum[-1])
    return levels[min(i, len(levels) - 1)]


def largest_remainder(n: int, shares: dict[str, float]) -> dict[str, int]:
    """Integer counts summing to n that are as close as possible to n * share."""
    total = sum(shares.values()) or 1.0
    exact = {k: n * v / total for k, v in shares.items()}
    counts = {k: int(math.floor(x)) for k, x in exact.items()}
    short = n - sum(counts.values())
    for k in sorted(exact, key=lambda k: exact[k] - counts[k], reverse=True)[:short]:
        counts[k] += 1
    return counts


def weighted_sample(items: Sequence[T], weights: Sequence[float], k: int, rng: random.Random) -> list[T]:
    """k items without replacement, P(selected) increasing in weight (Efraimidis-Spirakis A-Res)."""
    keyed = []
    for item, w in zip(items, weights):
        if w <= 0:
            continue
        keyed.append((rng.random() ** (1.0 / w), item))
    keyed.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in keyed[:k]]


def poisson(lam: float, rng: random.Random) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    threshold, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1
