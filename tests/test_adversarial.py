"""Adversarial schedule tests: worst-case delays + selective omission."""

import asyncio
from sim.network import AdversarialDelay, SelectiveOmission
from tests.utils import run_auction_test, assert_correctness


def test_adversarial_delay_p1_to_p2():
    """Delay messages from P1->P2 and P1->P3 heavily."""
    async def _test():
        delay = AdversarialDelay(
            slow_pairs={(1, 2), (1, 3)},
            slow_range=(0.02, 0.06),
            fast_range=(0.0, 0.005))
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], delay_model=delay, seed=500, protocol_timeout=60.0)
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
            [5, 20, 13, 7], delay_model=delay, seed=510, protocol_timeout=60.0)
        assert_correctness(results, [5, 20, 13, 7])
    asyncio.run(_test())


# --- Selective Omission Tests ---
# The adversary sends to SOME parties but not others.
# Note: If the omitting party's CSS still finalizes (enough echoes propagate),
# it may enter the active set. In that case, MPC requires per-gate ACS to
# handle the missing reshares (not implemented — we use fixed T).
# So these tests verify the protocol either succeeds or gracefully times out.

def test_selective_omission_send_to_1_only():
    """Party 4 sends only to party 1, omits to 2 and 3.
    P4's CSS won't get enough echoes at P2/P3 -> P4 excluded -> auction proceeds."""
    async def _test():
        policy = SelectiveOmission(party_id=4, drop_to={2, 3})
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], omission_policy=policy, seed=520,
            protocol_timeout=60.0)
        # P4 excluded from active set, honest parties proceed
        # At least P1/P2/P3 should produce results (P4 may timeout)
        honest_results = [results[i] for i in range(3)]  # P1/P2/P3
        non_none = [r for r in honest_results if r is not None]
        assert len(non_none) >= 3, f"Expected >=3 honest results, got {len(non_none)}"
    asyncio.run(_test())


def test_selective_omission_winner_sends_to_one():
    """Party 2 (highest bid=20) sends only to party 1, omits to 3 and 4.
    P2's CSS likely excluded. Auction proceeds with P1/P3/P4."""
    async def _test():
        policy = SelectiveOmission(party_id=2, drop_to={3, 4})
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], omission_policy=policy, seed=540,
            protocol_timeout=60.0)
        # P2 excluded, auction among P1(5), P3(13), P4(7)
        # P3 wins with second price 7
        honest_results = [results[i] for i in [0, 2, 3]]  # P1/P3/P4
        non_none = [r for r in honest_results if r is not None]
        assert len(non_none) >= 3
    asyncio.run(_test())
