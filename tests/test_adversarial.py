"""Adversarial schedule tests: deterministic worst-case delays."""

import sys
sys.path.insert(0, '..')

import asyncio
from network import AdversarialDelay
from tests.utils import run_auction_test, assert_correctness


def test_adversarial_delay_p1_to_p2():
    """Delay messages from P1→P2 and P1→P3 heavily."""
    async def _test():
        delay = AdversarialDelay(
            slow_pairs={(1, 2), (1, 3)},
            slow_range=(0.02, 0.06),
            fast_range=(0.0, 0.005))
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], delay_model=delay, seed=500,
            protocol_timeout=60.0)
        assert_correctness(results, [5, 20, 13, 7])
    asyncio.run(_test())


def test_adversarial_delay_all_slow_from_p3():
    """All messages from P3 are slow."""
    async def _test():
        slow = {(3, j) for j in range(1, 5) if j != 3}
        delay = AdversarialDelay(
            slow_pairs=slow,
            slow_range=(0.02, 0.05),
            fast_range=(0.0, 0.005))
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], delay_model=delay, seed=510,
            protocol_timeout=60.0)
        assert_correctness(results, [5, 20, 13, 7])
    asyncio.run(_test())
