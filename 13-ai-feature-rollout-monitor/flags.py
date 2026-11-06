"""Sticky percentage rollout via consistent hashing: a user's bucket never changes between stages."""

from __future__ import annotations

import hashlib

BUCKETS = 10_000


def bucket(user_id: str, feature: str) -> int:
    return int(hashlib.sha256(f"{feature}:{user_id}".encode()).hexdigest()[:8], 16) % BUCKETS


def in_treatment(user_id: str, feature: str, percent: float) -> bool:
    """Raising percent only adds users; nobody flips back to control mid-rollout."""
    return bucket(user_id, feature) < percent / 100 * BUCKETS
