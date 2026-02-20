"""Deterministic PRNG for reproducible simulations.

Use set_seed(n) at test start for reproducibility.
Default (no seed) uses os.urandom for cryptographic randomness.
"""

import os
import random as _random


class DeterministicRNG:
    """Seeded PRNG wrapper. When seed is None, uses os.urandom."""

    def __init__(self, seed=None):
        self._seed = seed
        if seed is not None:
            self._rng = _random.Random(seed)
        else:
            self._rng = None  # Use os-level randomness

    def randbelow(self, n: int) -> int:
        if self._rng is not None:
            return self._rng.randrange(n)
        return int.from_bytes(os.urandom(16), 'big') % n

    def uniform(self, a: float, b: float) -> float:
        if self._rng is not None:
            return self._rng.uniform(a, b)
        return _random.uniform(a, b)

    def random(self) -> float:
        if self._rng is not None:
            return self._rng.random()
        return _random.random()

    def expovariate(self, lambd: float) -> float:
        if self._rng is not None:
            return self._rng.expovariate(lambd)
        return _random.expovariate(lambd)


# Global instance
_global_rng = DeterministicRNG(seed=None)


def set_seed(seed: int | None):
    """Set global seed for reproducibility. None = cryptographic randomness."""
    global _global_rng
    _global_rng = DeterministicRNG(seed=seed)


def randbelow(n: int) -> int:
    return _global_rng.randbelow(n)


def uniform(a: float, b: float) -> float:
    return _global_rng.uniform(a, b)


def random() -> float:
    return _global_rng.random()


def expovariate(lambd: float) -> float:
    return _global_rng.expovariate(lambd)
