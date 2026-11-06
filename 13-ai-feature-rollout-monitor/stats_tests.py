"""Small, dependency-free statistics for rollout decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass


def norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


@dataclass
class PropTest:
    p_control: float
    p_treatment: float
    diff: float
    z: float
    p_value: float  # one-sided: treatment worse than control
    n_control: int
    n_treatment: int


def worse_proportion(bad_c: int, n_c: int, bad_t: int, n_t: int) -> PropTest:
    """One-sided two-proportion z-test that the treatment's *bad* rate is higher than control's."""
    pc, pt = bad_c / max(1, n_c), bad_t / max(1, n_t)
    pooled = (bad_c + bad_t) / max(1, n_c + n_t)
    se = math.sqrt(max(pooled * (1 - pooled) * (1 / max(1, n_c) + 1 / max(1, n_t)), 1e-12))
    z = (pt - pc) / se
    return PropTest(pc, pt, pt - pc, z, 1 - norm_cdf(z), n_c, n_t)


def min_samples_per_arm(base_rate: float, mde: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Samples per arm to detect an absolute increase of `mde` in a bad-outcome rate."""
    za, zb = 1.645, 0.842 if power == 0.8 else 1.282
    p1, p2 = base_rate, base_rate + mde
    pbar = (p1 + p2) / 2
    n = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / mde ** 2
    return math.ceil(n)
