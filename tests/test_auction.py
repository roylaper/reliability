"""Integration tests for the full second-price auction."""

import sys
sys.path.insert(0, '..')

import asyncio
from tests.utils import run_auction_test, assert_correctness


def test_all_honest():
    async def _test():
        results, net, beacon = await run_auction_test([5, 20, 13, 7])
        assert_correctness(results, [5, 20, 13, 7])
    asyncio.run(_test())


def test_omitting_non_winner():
    async def _test():
        results, _, _ = await run_auction_test([5, 20, 13, 7], omitting_party=4)
        assert_correctness(results, [5, 20, 13, 7], omitting_party=4)
    asyncio.run(_test())


def test_omitting_would_be_winner():
    async def _test():
        results, _, _ = await run_auction_test([5, 20, 13, 7], omitting_party=2)
        assert_correctness(results, [5, 20, 13, 7], omitting_party=2)
    asyncio.run(_test())


def test_edge_bids():
    async def _test():
        results, _, _ = await run_auction_test([0, 1, 30, 31], seed=100)
        assert_correctness(results, [0, 1, 30, 31])
    asyncio.run(_test())


def test_close_bids():
    async def _test():
        results, _, _ = await run_auction_test([10, 11, 12, 13], seed=101)
        assert_correctness(results, [10, 11, 12, 13])
    asyncio.run(_test())


def test_metrics_nonzero():
    async def _test():
        _, net, _ = await run_auction_test([5, 20, 13, 7])
        assert net.metrics.messages_sent > 100
        assert len(net.metrics.by_type) > 0
    asyncio.run(_test())
