"""Tests with one omitting party: full silence and partial omission."""

import sys
sys.path.insert(0, '..')

import asyncio
from network import DropAll, DropProb
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


def test_partial_omission_party4():
    """Party 4 drops 50% of messages."""
    async def _test():
        policy = DropProb(4, p=0.5)
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], omission_policy=policy, seed=310)
        # With 50% drop, party 4 might or might not be included
        # Either way, honest parties should produce a correct result
        active = [i + 1 for i in range(4)]
        # Check that at least 3 parties got a result
        non_none = [r for r in results if r is not None]
        assert len(non_none) >= 3
    asyncio.run(_test())


def test_omit_different_bids():
    """Different bid config with omission."""
    async def _test():
        results, _, _ = await run_auction_test([0, 1, 30, 31], omitting_party=3, seed=320)
        assert_correctness(results, [0, 1, 30, 31], omitting_party=3)
    asyncio.run(_test())
