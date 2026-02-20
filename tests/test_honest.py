"""Multiple honest execution tests with different configs and seeds."""

import asyncio
from tests.utils import run_auction_test, assert_correctness


def test_honest_config1_seed1():
    async def _test():
        results, _, _ = await run_auction_test([3, 17, 29, 11], seed=200)
        assert_correctness(results, [3, 17, 29, 11])
    asyncio.run(_test())

def test_honest_config1_seed2():
    async def _test():
        results, _, _ = await run_auction_test([3, 17, 29, 11], seed=201)
        assert_correctness(results, [3, 17, 29, 11])
    asyncio.run(_test())

def test_honest_config2():
    async def _test():
        results, _, _ = await run_auction_test([1, 2, 3, 4], seed=210)
        assert_correctness(results, [1, 2, 3, 4])
    asyncio.run(_test())

def test_honest_config3():
    async def _test():
        results, _, _ = await run_auction_test([28, 15, 7, 22], seed=220)
        assert_correctness(results, [28, 15, 7, 22])
    asyncio.run(_test())

def test_honest_extreme_bids():
    async def _test():
        results, _, _ = await run_auction_test([0, 31, 16, 8], seed=230)
        assert_correctness(results, [0, 31, 16, 8])
    asyncio.run(_test())
