"""Tests with one omitting party: full omission scenarios.

Full omission (DropAll) is the primary adversary model for the exercise.
The omitter's CSS never finalizes, so it is excluded from the active set,
and all multiplications complete correctly.
"""

import asyncio
from sim.network import DropAll
from tests.utils import run_auction_test, assert_correctness


def test_omit_party1():
    async def _test():
        results, _, _ = await run_auction_test([5, 20, 13, 7], omitting_party=1, seed=300)
        assert_correctness(results, [5, 20, 13, 7], omitting_party=1)
    asyncio.run(_test())

def test_omit_party2():
    async def _test():
        results, _, _ = await run_auction_test([5, 20, 13, 7], omitting_party=2, seed=301)
        assert_correctness(results, [5, 20, 13, 7], omitting_party=2)
    asyncio.run(_test())

def test_omit_party3():
    async def _test():
        results, _, _ = await run_auction_test([5, 20, 13, 7], omitting_party=3, seed=302)
        assert_correctness(results, [5, 20, 13, 7], omitting_party=3)
    asyncio.run(_test())

def test_omit_party4():
    async def _test():
        results, _, _ = await run_auction_test([5, 20, 13, 7], omitting_party=4, seed=303)
        assert_correctness(results, [5, 20, 13, 7], omitting_party=4)
    asyncio.run(_test())

def test_omit_different_bids():
    async def _test():
        results, _, _ = await run_auction_test([0, 1, 30, 31], omitting_party=3, seed=320)
        assert_correctness(results, [0, 1, 30, 31], omitting_party=3)
    asyncio.run(_test())
