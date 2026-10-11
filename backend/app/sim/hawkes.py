"""Hawkes-process activity engine (POSIM).

    λ(t) = μ·c(t) + Σ_exo α_ext·importance·e^{-β_ext (t - t_e)} + Σ_endo α'·w·e^{-β_int (t - t_a)}

Time is in minutes; λ is activations per agent-hour, so a tick of Δ minutes activates
N_t ~ Poisson(λ(t_mid) · M · Δ / 60) agents. POSIM calibrated μ=0.01, α_ext=0.08, β_ext=0.005,
α_int=0.005, β_int=0.16 at N_s=2000. For a small simulated population (M agents) we keep the
exogenous terms as fractions of the population and rescale the endogenous jump so its branching
ratio n* = α'·M/(60·β_int) stays fixed (POSIM's values imply n ≈ 1.04; we default to 0.9 so a
cascade dies out unless events keep feeding it).
"""

from __future__ import annotations

import math
import random

DEFAULTS = {"mu": 0.01, "alpha_ext": 0.08, "beta_ext": 0.005, "beta_int": 0.16, "circadian_amp": 0.3, "branching": 0.9}


def params(overrides: dict | None) -> dict[str, float]:
    p = dict(DEFAULTS)
    for k, v in (overrides or {}).items():
        if k in p and v is not None:
            p[k] = float(v)
    return p


def circadian(minute_of_day: float, amp: float) -> float:
    """24-hour modulation peaking at 20:00 and bottoming out around 08:00."""
    hour = (minute_of_day / 60.0) % 24
    return max(0.1, 1 + amp * math.sin(2 * math.pi * (hour - 14) / 24))


def endo_jump(p: dict[str, float], m: int) -> float:
    return p["branching"] * p["beta_int"] * 60.0 / max(1, m)


def intensity(t: float, clock_offset_min: float, p: dict[str, float], m: int, exo: list, endo: list) -> float:
    lam = p["mu"] * circadian(clock_offset_min + t, p["circadian_amp"])
    for te, alpha in exo:
        if te <= t:
            lam += alpha * math.exp(-p["beta_ext"] * (t - te))
    jump = endo_jump(p, m)
    for ta, w in endo:
        if ta <= t:
            lam += jump * w * math.exp(-p["beta_int"] * (t - ta))
    return lam


def expected_activations(lam: float, m: int, tick_minutes: float) -> float:
    return lam * m * tick_minutes / 60.0


def prune(kernels: list, t: float, beta: float, scale: float, floor: float = 1e-6) -> list:
    return [k for k in kernels if scale * k[1] * math.exp(-beta * (t - k[0])) > floor]


def pick_active(candidates: list[tuple[str, float]], n: int, rng: random.Random) -> list[str]:
    """Weighted sampling without replacement (Efraimidis-Spirakis)."""
    keyed = sorted(((rng.random() ** (1.0 / w), aid) for aid, w in candidates if w > 0), reverse=True)
    return [aid for _, aid in keyed[:n]]
