"""Second-Price Auction via Asynchronous MPC — Entry Point.

EX4 System Project 1: n=4 parties, f=1, bids in [0, 32).
Uses theory-faithful protocols: RBC, BA, ACS, CSS with finalization.
"""

import asyncio
import sys
import time
import rng
from network import Network, DropAll, DropProb, UniformDelay, ExponentialDelay
from beacon import RandomnessBeacon
from party import Party
from bit_decomposition import preprocess_random_bit_sharings
from polynomial import Polynomial
from field import FieldElement


NUM_RANDOM_BITS = 20  # 4 bids × 5 bits each
NUM_MASK_SHARINGS = 4  # one mask per party output


def preprocess_mask_sharings(n: int, f: int, count: int) -> list[dict[int, FieldElement]]:
    """Generate random mask sharings for output privacy."""
    result = []
    for _ in range(count):
        mask = FieldElement.random()
        poly = Polynomial.random(degree=f, constant=mask)
        shares = {i: poly.evaluate(FieldElement(i)) for i in range(1, n + 1)}
        result.append(shares)
    return result


async def run_auction(bids: list[int], omitting_party: int | None = None,
                      seed: int | None = None, omission_prob: float | None = None):
    """Run a second-price auction with the given bids."""
    n, f = 4, 1
    assert len(bids) == n
    assert all(0 <= b < 32 for b in bids)
    assert len(set(bids)) == len(bids), "Bids must be unique"

    if seed is not None:
        rng.set_seed(seed)

    print(f"=== Second-Price Auction ===")
    print(f"Bids: {dict(enumerate(bids, 1))}")
    if omitting_party:
        prob_str = f" (prob={omission_prob})" if omission_prob else ""
        print(f"Omitting party: {omitting_party}{prob_str}")
    if seed is not None:
        print(f"Seed: {seed}")
    print()

    # Preprocessing
    random_bits = preprocess_random_bit_sharings(n, f, NUM_RANDOM_BITS)
    mask_shares = preprocess_mask_sharings(n, f, NUM_MASK_SHARINGS)

    # Setup network with omission policy
    omission_policy = None
    if omitting_party is not None:
        if omission_prob is not None:
            omission_policy = DropProb(omitting_party, omission_prob)
        else:
            omission_policy = DropAll(omitting_party)

    network = Network(n, delay_model=UniformDelay(0.0, 0.01),
                      omission_policy=omission_policy)
    beacon = RandomnessBeacon(threshold=f + 1)

    # Create parties
    parties = []
    for i in range(1, n + 1):
        party = Party(i, n, f, bids[i - 1], network, beacon,
                      random_bits, mask_shares)
        parties.append(party)

    # Run
    start = time.time()
    network.metrics.start()
    results = await asyncio.gather(*[p.run() for p in parties])
    elapsed = time.time() - start

    # Results
    print("--- Results ---")
    for i, result in enumerate(results, 1):
        if result is not None and result.to_int() > 0:
            print(f"  Party {i}: WINNER, pays {result.to_int()}")
        elif result is not None:
            print(f"  Party {i}: not the winner (output=0)")
        else:
            print(f"  Party {i}: no output (omitted/excluded)")

    # Expected
    active_bids = [
        (i + 1, bids[i]) for i in range(n)
        if omitting_party is None or i + 1 != omitting_party
    ]
    active_bids.sort(key=lambda x: x[1], reverse=True)
    expected_winner = active_bids[0][0]
    expected_second_price = active_bids[1][1]
    print(f"\n  Expected: Party {expected_winner} wins, pays {expected_second_price}")

    # Metrics
    print(f"\n--- Metrics ---")
    print(f"  Messages sent: {network.metrics.messages_sent}")
    print(f"  Messages dropped: {network.metrics.messages_dropped}")
    print(f"  Beacon invocations: {beacon.invocations}")
    print(f"  Time: {elapsed:.3f}s")
    if network.metrics.by_type:
        print(f"  By type:")
        for msg_type, count in sorted(network.metrics.by_type.items()):
            print(f"    {msg_type}: {count}")
    print()

    return results, expected_winner, expected_second_price


async def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42

    print("=" * 50)
    print("SCENARIO 1: All parties honest")
    print("=" * 50)
    await run_auction([5, 20, 13, 7], seed=seed)

    print("=" * 50)
    print("SCENARIO 2: Party 4 (bid=7) omitting")
    print("=" * 50)
    await run_auction([5, 20, 13, 7], omitting_party=4, seed=seed + 1)

    print("=" * 50)
    print("SCENARIO 3: Party 2 (bid=20, winner) omitting")
    print("=" * 50)
    await run_auction([5, 20, 13, 7], omitting_party=2, seed=seed + 2)

    print("=" * 50)
    print("SCENARIO 4: Edge bids [0, 1, 30, 31]")
    print("=" * 50)
    await run_auction([0, 1, 30, 31], seed=seed + 3)


if __name__ == "__main__":
    asyncio.run(main())
