"""Test utilities: reference oracle, assertion helpers."""

import asyncio
from core import rng
from core.field import FieldElement
from core.polynomial import Polynomial
from sim.network import (Network, UniformDelay, ExponentialDelay,
                         DropAll, DropProb, AdversarialDelay)
from sim.beacon import RandomnessBeacon
from party import Party
from circuits.bit_decomposition import preprocess_random_bit_sharings


def preprocess_mask_sharings(n, f, count):
    result = []
    for _ in range(count):
        mask = FieldElement.random()
        poly = Polynomial.random(degree=f, constant=mask)
        shares = {i: poly.evaluate(FieldElement(i)) for i in range(1, n + 1)}
        result.append(shares)
    return result


def reference_auction(bids, active_parties):
    """Cleartext oracle: returns (winner_id, second_price)."""
    active_bids = [(pid, bids[pid - 1]) for pid in active_parties]
    active_bids.sort(key=lambda x: x[1], reverse=True)
    winner_id = active_bids[0][0]
    second_price = active_bids[1][1]
    return winner_id, second_price


async def run_auction_test(bids, omitting_party=None, seed=42,
                           delay_model=None, omission_policy=None,
                           protocol_timeout=30.0):
    """Run a full auction and return (results, net, beacon)."""
    rng.set_seed(seed)
    n, f = 4, 1
    rbs = preprocess_random_bit_sharings(n, f, 20)
    masks = preprocess_mask_sharings(n, f, 4)

    if omission_policy is None and omitting_party is not None:
        omission_policy = DropAll(omitting_party)

    net = Network(n, delay_model=delay_model or UniformDelay(0.0, 0.005),
                  omission_policy=omission_policy)
    beacon = RandomnessBeacon(threshold=f + 1)

    parties = [Party(i, n, f, bids[i - 1], net, beacon, rbs, masks,
                     protocol_timeout=protocol_timeout)
               for i in range(1, n + 1)]
    results = await asyncio.gather(*[p.run() for p in parties])
    return results, net, beacon


def assert_correctness(results, bids, omitting_party=None):
    """Assert auction correctness: winner gets second price, others get 0."""
    n = len(bids)
    active = [i + 1 for i in range(n)
              if omitting_party is None or i + 1 != omitting_party]
    winner_id, second_price = reference_auction(bids, active)

    winner_result = results[winner_id - 1]
    assert winner_result is not None, f"Winner P{winner_id} got None"
    assert winner_result.to_int() == second_price, \
        f"Winner P{winner_id} got {winner_result.to_int()}, expected {second_price}"

    for pid in active:
        if pid != winner_id:
            r = results[pid - 1]
            assert r is not None, f"Active P{pid} got None"
            assert r.to_int() == 0, f"P{pid} got {r.to_int()}, expected 0"

    if omitting_party:
        assert results[omitting_party - 1] is None, \
            f"Omitting P{omitting_party} should get None"
