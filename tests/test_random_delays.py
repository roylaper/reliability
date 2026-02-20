"""Stress tests with random delays."""

import sys
sys.path.insert(0, '..')

import asyncio
from network import ExponentialDelay, UniformDelay
from tests.utils import run_auction_test, assert_correctness


def test_exponential_delays():
    """Exponential delays with mean=0.02, all honest."""
    async def _test():
        delay = ExponentialDelay(mean=0.02)
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], delay_model=delay, seed=400,
            protocol_timeout=60.0)
        assert_correctness(results, [5, 20, 13, 7])
    asyncio.run(_test())


def test_wide_uniform_delays():
    """Uniform delays [0, 0.05]."""
    async def _test():
        delay = UniformDelay(0.0, 0.05)
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], delay_model=delay, seed=410,
            protocol_timeout=60.0)
        assert_correctness(results, [5, 20, 13, 7])
    asyncio.run(_test())


def test_delays_with_omission():
    """Exponential delays + one omitting party."""
    async def _test():
        delay = ExponentialDelay(mean=0.01)
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], omitting_party=4, delay_model=delay, seed=420,
            protocol_timeout=60.0)
        assert_correctness(results, [5, 20, 13, 7], omitting_party=4)
    asyncio.run(_test())
