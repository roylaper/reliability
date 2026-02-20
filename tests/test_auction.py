"""Integration tests for the full second-price auction."""

import sys
sys.path.insert(0, '..')

import asyncio
from field import FieldElement
from network import Network
from beacon import RandomnessBeacon
from party import Party
from bit_decomposition import preprocess_random_bit_sharings


async def run_auction_test(bids, omitting_party=None):
    """Run auction and return (results, active_bids_sorted)."""
    n, f = 4, 1
    rbs = preprocess_random_bit_sharings(n, f, 20)
    net = Network(n)
    beacon = RandomnessBeacon(threshold=f + 1)
    if omitting_party:
        net.set_omission(omitting_party)

    parties = [Party(i, n, f, bids[i - 1], net, beacon, rbs) for i in range(1, n + 1)]
    results = await asyncio.gather(*[p.run() for p in parties])

    # Compute expected
    active_bids = [
        (i + 1, bids[i]) for i in range(n)
        if omitting_party is None or i + 1 != omitting_party
    ]
    active_bids.sort(key=lambda x: x[1], reverse=True)

    return results, active_bids, net.metrics.messages_sent


def test_all_honest():
    """Bids: 5, 20, 13, 7. Winner=P2(20), second_price=13."""
    async def _test():
        results, active_bids, msgs = await run_auction_test([5, 20, 13, 7])
        expected_winner = active_bids[0][0]  # Party 2
        expected_price = active_bids[1][1]   # 13

        # Winner should get second price
        winner_result = results[expected_winner - 1]
        assert winner_result is not None
        assert winner_result.to_int() == expected_price, \
            f"Winner got {winner_result.to_int()}, expected {expected_price}"

        # Non-winners should get 0
        for i, r in enumerate(results, 1):
            if i != expected_winner and r is not None:
                assert r.to_int() == 0, f"Party {i} got {r.to_int()}, expected 0"

        assert msgs > 0
    asyncio.run(_test())


def test_omitting_non_winner():
    """Party 4 (bid=7) omits. Winner=P2(20), second_price=13."""
    async def _test():
        results, active_bids, _ = await run_auction_test(
            [5, 20, 13, 7], omitting_party=4)
        expected_winner = active_bids[0][0]
        expected_price = active_bids[1][1]

        # Winner correct
        winner_result = results[expected_winner - 1]
        assert winner_result is not None
        assert winner_result.to_int() == expected_price

        # Omitting party gets None
        assert results[3] is None  # Party 4

        # Other non-winners get 0
        for i, r in enumerate(results, 1):
            if i != expected_winner and i != 4 and r is not None:
                assert r.to_int() == 0
    asyncio.run(_test())


def test_omitting_would_be_winner():
    """Party 2 (bid=20) omits. New winner=P3(13), second_price=7."""
    async def _test():
        results, active_bids, _ = await run_auction_test(
            [5, 20, 13, 7], omitting_party=2)
        # Active bids: P1=5, P3=13, P4=7 -> winner=P3, price=7
        expected_winner = active_bids[0][0]
        expected_price = active_bids[1][1]

        assert expected_winner == 3
        assert expected_price == 7

        winner_result = results[expected_winner - 1]
        assert winner_result is not None
        assert winner_result.to_int() == expected_price

        assert results[1] is None  # Party 2 omitted
    asyncio.run(_test())


def test_edge_bids():
    """Bids at extremes: 0, 1, 30, 31."""
    async def _test():
        results, active_bids, _ = await run_auction_test([0, 1, 30, 31])
        # Winner=P4(31), second_price=30
        expected_winner = active_bids[0][0]
        expected_price = active_bids[1][1]

        assert expected_winner == 4
        assert expected_price == 30

        winner_result = results[expected_winner - 1]
        assert winner_result is not None
        assert winner_result.to_int() == expected_price
    asyncio.run(_test())


def test_close_bids():
    """Bids close together: 10, 11, 12, 13."""
    async def _test():
        results, active_bids, _ = await run_auction_test([10, 11, 12, 13])
        # Winner=P4(13), second_price=12
        assert active_bids[0][0] == 4
        assert active_bids[1][1] == 12

        assert results[3].to_int() == 12
        for i in range(3):
            assert results[i] is not None
            assert results[i].to_int() == 0
    asyncio.run(_test())


def test_metrics_nonzero():
    """Check that metrics are tracked."""
    async def _test():
        _, _, msgs = await run_auction_test([5, 20, 13, 7])
        assert msgs > 100  # Should have many messages
    asyncio.run(_test())
