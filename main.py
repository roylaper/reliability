"""Second-Price Auction via Asynchronous MPC — Entry Point.

EX4 System Project 1: n=4 parties, f=1, bids in [0, 32).
"""

import asyncio
import time
from network import Network
from beacon import RandomnessBeacon
from party import Party
from bit_decomposition import preprocess_random_bit_sharings


# Each bid needs 5 random bits for decomposition.
# Max active bids = n = 4, so we need up to 4 * 5 = 20 random bit sharings.
NUM_RANDOM_BITS = 20


async def run_auction(bids: list[int], omitting_party: int | None = None):
    """Run a second-price auction with the given bids.

    Args:
        bids: List of 4 integers in [0, 32), one per party (index 0 = party 1).
        omitting_party: Party ID (1-4) that will omit messages, or None.
    """
    n, f = 4, 1
    assert len(bids) == n, f"Need exactly {n} bids"
    assert all(0 <= b < 32 for b in bids), "Bids must be in [0, 32)"
    assert len(set(bids)) == len(bids), "Bids must be unique"

    print(f"=== Second-Price Auction ===")
    print(f"Bids: {dict(enumerate(bids, 1))}")
    if omitting_party:
        print(f"Omitting party: {omitting_party}")
    print()

    # Preprocessing: generate random bit sharings (simulates offline phase via beacon + CSS)
    random_bits = preprocess_random_bit_sharings(n, f, NUM_RANDOM_BITS)

    # Setup
    network = Network(n)
    beacon = RandomnessBeacon(threshold=f + 1)

    if omitting_party is not None:
        network.set_omission(omitting_party)

    # Create parties with preprocessed random bits
    parties = []
    for i in range(1, n + 1):
        party = Party(i, n, f, bids[i - 1], network, beacon, random_bits)
        parties.append(party)

    # Run all parties concurrently
    start = time.time()
    network.metrics.start()
    results = await asyncio.gather(*[p.run() for p in parties])
    elapsed = time.time() - start

    # Report results
    print("--- Results ---")
    for i, result in enumerate(results, 1):
        if result is not None and result.to_int() > 0:
            print(f"  Party {i}: WINNER, pays {result.to_int()}")
        elif result is not None:
            print(f"  Party {i}: not the winner (output=0)")
        else:
            print(f"  Party {i}: no output (omitted/excluded)")

    # Compute expected results for verification
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
    print()

    return results, expected_winner, expected_second_price


async def main():
    # Scenario 1: All honest
    print("=" * 50)
    print("SCENARIO 1: All parties honest")
    print("=" * 50)
    await run_auction([5, 20, 13, 7])

    # Scenario 2: Party 4 (non-winner) omitting
    print("=" * 50)
    print("SCENARIO 2: Party 4 (bid=7) omitting")
    print("=" * 50)
    await run_auction([5, 20, 13, 7], omitting_party=4)

    # Scenario 3: Party 2 (would-be winner) omitting
    print("=" * 50)
    print("SCENARIO 3: Party 2 (bid=20) omitting")
    print("=" * 50)
    await run_auction([5, 20, 13, 7], omitting_party=2)


if __name__ == "__main__":
    asyncio.run(main())
