"""Agreement metrics between judges and humans, and pass-threshold tuning."""

from __future__ import annotations

from collections import Counter


def cohen_kappa(a: list, b: list) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def mae(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else 0.0


def agreement(judge_scores: list[int], human_scores: list[float], pass_at: int, judge_pass_at: int | None = None) -> dict:
    jp = judge_pass_at or pass_at
    return {
        "kappa_pass": round(cohen_kappa([s >= jp for s in judge_scores], [h >= pass_at for h in human_scores]), 3),
        "mae": round(mae(judge_scores, human_scores), 3),
        "spearman": round(spearman(judge_scores, human_scores), 3),
        "bias": round(sum(judge_scores) / len(judge_scores) - sum(human_scores) / len(human_scores), 3),
    }


def tune_threshold(judge_scores: list[int], human_scores: list[float], pass_at: int) -> tuple[int, float]:
    """Pick the judge pass cut-off that best reproduces human pass/fail (max kappa)."""
    human = [h >= pass_at for h in human_scores]
    best = max(range(2, 6), key=lambda t: cohen_kappa([s >= t for s in judge_scores], human))
    return best, round(cohen_kappa([s >= best for s in judge_scores], human), 3)
