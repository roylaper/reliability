"""Adversarial schedule tests: worst-case delays.

Under adversarial delays, ACS may legitimately exclude a slow honest party
(its RBC proposal arrives after n-f BAs already decided). This is correct
per the ACS spec: output has >= n-f parties, >= n-2f honest.
Tests assert at least n-f correct results, not all n.
"""

import asyncio
from sim.network import AdversarialDelay, SelectiveOmission
from tests.utils import run_auction_test, reference_auction


def test_adversarial_delay_p1_to_p2():
    """Delay messages from P1->P2 and P1->P3 heavily."""
    async def _test():
        delay = AdversarialDelay(
            slow_pairs={(1, 2), (1, 3)},
            slow_range=(0.02, 0.06),
            fast_range=(0.0, 0.005))
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], delay_model=delay, seed=500, protocol_timeout=120.0)
        # At least n-f=3 parties should produce results
        non_none = [r for r in results if r is not None]
        assert len(non_none) >= 3, f"Expected >=3 results, got {len(non_none)}"
        # Exactly 1 winner
        winners = [r for r in non_none if r.to_int() > 0]
        assert len(winners) == 1
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
            [5, 20, 13, 7], delay_model=delay, seed=510, protocol_timeout=120.0)
        non_none = [r for r in results if r is not None]
        assert len(non_none) >= 3
        winners = [r for r in non_none if r.to_int() > 0]
        assert len(winners) == 1
    asyncio.run(_test())


def test_selective_omission_send_to_1_only():
    """Party 4 sends only to P1, omits to P2/P3.
    With per-gate CSS+ACS, this is correctly handled but slow (~130 gates
    each running full ACS with RBC+BA). Requires long harness timeout."""
    async def _test():
        policy = SelectiveOmission(party_id=4, drop_to={2, 3})
        results, _, _ = await run_auction_test(
            [5, 20, 13, 7], omission_policy=policy, seed=520,
            protocol_timeout=600.0)
        non_none = [r for r in results if r is not None]
        assert len(non_none) >= 3
        winners = [r for r in non_none if r.to_int() > 0]
        assert len(winners) == 1
    asyncio.run(_test())
