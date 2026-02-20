# EX4: Second-Price Auction via Asynchronous MPC

**RDS 2026 — System Project 1**

A secure second-price auction implemented using asynchronous Multi-Party Computation (MPC) with omission failure tolerance. Four parties submit secret bids, and the protocol determines the winner and the second-highest price — without revealing any bid to other parties.

## System Model

| Parameter | Value |
|-----------|-------|
| Parties (n) | 4 |
| Fault threshold (f) | 1 (n = 3f+1) |
| Bid range | [0, 32) — 5-bit integers |
| Adversary | Adaptive, computationally unbounded |
| Failure model | Omission only (no malformed messages) |
| Network | Asynchronous (no synchrony assumptions) |
| Field | F_p, p = 2^127 - 1 (Mersenne prime) |

## Quick Start

```bash
# Run the auction with 3 demo scenarios
python3 main.py

# Run all tests (47 tests)
python3 -m pytest tests/ -v
```

### Example Output

```
=== Second-Price Auction ===
Bids: {1: 5, 2: 20, 3: 13, 4: 7}

--- Results ---
  Party 1: not the winner (output=0)
  Party 2: WINNER, pays 13
  Party 3: not the winner (output=0)
  Party 4: not the winner (output=0)

--- Metrics ---
  Messages sent: 2124
  Time: 3.316s
```

## Architecture

All 4 parties run as `asyncio` coroutines in a single Python process. Communication happens through in-memory `asyncio.Queue` channels. Omission failures are simulated by dropping messages on designated channels.

```
                    +-----------+
                    |  main.py  |  Entry point, runs scenarios
                    +-----+-----+
                          |
                    +-----+-----+
                    |  party.py |  Event-driven message dispatch
                    +-----+-----+
                          |
          +---------------+---------------+
          |               |               |
    +-----+-----+  +-----+-----+  +------+------+
    |  css.py   |  |  acs.py   |  | mpc_arith.  |
    |  Secret   |  | Agreement |  | Addition &  |
    |  Sharing  |  | on Common |  | Multiply    |
    +-----------+  |   Set     |  | (BGW)       |
                   +-----------+  +------+------+
                                         |
                              +----------+----------+
                              |                     |
                      +-------+-------+   +---------+---------+
                      | bit_decomp.py |   |  comparison.py    |
                      | Value -> Bits |   |  Greater-than     |
                      +-------+-------+   +---------+---------+
                              |                     |
                      +-------+---------------------+-------+
                      |            auction.py               |
                      |  Second-price auction circuit       |
                      +-------------------------------------+
```

## Protocol Flow

```
Phase 1: CSS Share     Each party secret-shares its bid
Phase 2: CSS Accept    Wait for n-f=3 sharings to be accepted
Phase 3: ACS           Agree on which parties' bids to include
Phase 4: Auction       Bit decompose -> Compare -> Find winner -> Mask output
Phase 5: Reveal        Winner learns second price; others learn nothing
```

## File Descriptions

### Core Primitives

#### `field.py` (102 lines)
Finite field arithmetic over F_p where p = 2^127 - 1.

- **`FieldElement`** — Supports `+`, `-`, `*`, `/`, `**`, negation, comparison
- `inverse()` — Via Fermat's little theorem: a^(p-2) mod p
- `random()` — Cryptographic randomness via `secrets.randbelow`
- `zero()`, `one()`, `to_int()` — Utility methods

#### `polynomial.py` (74 lines)
Polynomial operations and Lagrange interpolation.

- **`Polynomial`** — Coefficients list (index 0 = constant term)
- `evaluate(x)` — Horner's method
- `random(degree, constant)` — Random polynomial with fixed p(0)
- `interpolate_at_zero(points)` — Lagrange interpolation at x=0 (used for secret reconstruction)
- `lagrange_coefficients_at_zero(x_values)` — Precompute coefficients for degree reduction

#### `network.py` (104 lines)
Async communication layer with omission failure simulation.

- **`Message`** — Tagged with `msg_type`, `sender`, `payload`, `session_id`
- **`MessageChannel`** — Wraps `asyncio.Queue` with configurable delay and `dropped` flag
- **`Network`** — Creates n*(n-1) unidirectional channels
  - `send()`, `broadcast()` — Async message delivery
  - `set_omission(party_id)` — Silently drop all messages to/from a party
- **`NetworkMetrics`** — Counts messages sent/dropped

#### `beacon.py` (37 lines)
Randomness beacon — provides random field elements when f+1 parties request.

- **`RandomnessBeacon`** — `request(beacon_index, party_id)` blocks until threshold (f+1=2) parties request the same index, then releases a random `FieldElement`

#### `metrics.py` (25 lines)
Simple execution timing tracker.

- **`Metrics`** — `start()`, `stop()`, `elapsed` property

### Protocol Layer

#### `css.py` (246 lines)
Complete Secret Sharing for the omission failure model. Simplified because parties never lie — any f+1 shares are guaranteed correct.

- **`CSSProtocol`** — Per-party CSS instance
  - `share(secret, session_id)` — Dealer creates degree-1 polynomial, distributes shares
  - Echo phase: parties forward received shares to all others
  - Ready phase: send READY after f+1 consistent echoes; accept after n-f READYs
  - `recover(session_id)` — All parties exchange shares, interpolate at zero
  - `recover_to_party(session_id, target)` — Selective reveal to one party only
  - `get_share(session_id)` — Returns share (derives from echoes if dealer's direct message delayed)

#### `acs.py` (69 lines)
Agreement on Common Set — determines which parties' inputs to use.

- **`ACSProtocol`** — Per-party ACS instance
  - `run(accepted_dealers)` — Broadcast which CSS sharings this party accepted
  - A dealer is confirmed if f+1 parties voted for it
  - Returns set of >= n-f confirmed dealers (the active set)

#### `mpc_arithmetic.py` (152 lines)
Secret-shared arithmetic operations.

- **`MPCArithmetic`** — Per-party arithmetic engine
  - `set_active_set(T)` — Set the ACS-determined active set, precompute Lagrange coefficients
  - `add()`, `sub()`, `scalar_mul()` — Local operations (no communication)
  - `multiply(share_a, share_b, session_id)` — BGW multiplication:
    1. Local multiply → degree-2f sharing
    2. Each party in T reshares with degree-f polynomial
    3. Recombine via Lagrange coefficients → degree-f sharing of product
  - `open_value(share, session_id)` — Broadcast shares, reconstruct from f+1

### Circuit Layer

#### `bit_decomposition.py` (126 lines)
Convert a secret-shared field element to secret-shared individual bits.

- `preprocess_random_bit_sharings(n, f, count)` — Offline: generate random bit sharings (simulates beacon + CSS preprocessing)
- **`BitDecomposition`** — Per-party bit decomposer
  - `load_random_bits(sharings)` — Load preprocessed random bit shares
  - `decompose(shared_value, num_bits, session_id)`:
    1. Consume pre-generated random shared bits [r_0..r_4]
    2. Compute [r] = sum(r_i * 2^i)
    3. Open y = x + r publicly (safe: both < 32, no field wraparound)
    4. Bit subtraction circuit: compute [x_i] from public y and shared r via ripple-borrow
  - Each borrow step: 2 multiplications (XOR with borrow + carry computation)

#### `comparison.py` (54 lines)
Greater-than comparison on secret-shared bit vectors.

- **`ComparisonCircuit`**
  - `greater_than(bits_a, bits_b, session_id)` — MSB-to-LSB prefix scan:
    - Per bit: compute [a_i * b_i], derive [gt_i] and [eq_i]
    - Accumulate: result += prefix_eq * gt_i, then prefix_eq *= eq_i
    - 3 multiplications per bit, 15 total for 5-bit values

#### `auction.py` (198 lines)
Second-price auction circuit — the main computation.

- **`SecondPriceAuction`**
  - `run(bid_shares, active_set)`:
    1. **Bit decompose** all active bids
    2. **Pairwise comparisons** — [a > b] for every pair
    3. **Winner detection** — is_max[i] = product of all gt[(i,j)]
    4. **Second-highest** — is_second[i] = 1 - is_max - is_min (m=3) or polynomial indicator (m=4)
    5. **Second price** — [sp] = sum(bid_i * is_second_i)
    6. **Output masking** — output_i = is_max_i * sp (winner gets price, others get 0)
    7. **Selective reveal** — each party learns only its own output

### Orchestration

#### `party.py` (144 lines)
Single MPC participant with event-driven message dispatch.

- **`Party`** — Aggregates all protocol instances
  - `run()` — Main coroutine (with 30s timeout for omitted parties):
    1. Share own bid via CSS
    2. Wait for n-f CSS acceptances (2s timeout per dealer)
    3. ACS to agree on active set
    4. Run auction computation
  - Message dispatcher: spawns one `asyncio` reader task per incoming channel, routes messages to appropriate protocol handler by `msg_type`

#### `main.py` (112 lines)
Entry point — runs three demo scenarios.

- `run_auction(bids, omitting_party)` — Full auction with metrics reporting
- Three scenarios: all honest, non-winner omitting, would-be winner omitting
- Preprocessing: generates 20 random bit sharings before each run

## Tests

Run with `python3 -m pytest tests/ -v` (47 tests total).

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `test_field.py` | 15 | Field arithmetic: add, sub, mul, div, inverse, edge cases |
| `test_polynomial.py` | 8 | Evaluation, Lagrange interpolation (degree 1 & 2), random polynomials |
| `test_css.py` | 3 | Share/recover all honest, with omission, multiple secret values |
| `test_mpc.py` | 8 | Addition, subtraction, scalar multiply, BGW multiplication, open |
| `test_comparison.py` | 6 | Bit decomposition (0, 13, 31), comparison (>, <, ==) |
| `test_auction.py` | 6 | Full integration: honest, omitting non-winner, omitting winner, edge bids, close bids, metrics |

## Complexity

| Phase | Multiplications | Messages (approx) |
|-------|----------------|--------------------|
| Bit decomposition (per bid) | ~10 | ~90 |
| Comparison (per pair) | 15 | ~135 |
| Winner/min detection | 6-9 | ~60 |
| Second price computation | 3 | ~27 |
| Output masking | 3 | ~27 |
| **Total (4 active bids)** | **~170** | **~2100** |
| **Total (3 active bids)** | **~120** | **~900** |

## Dependencies

- **Python 3.11+** (for `asyncio`, type hints)
- **Standard library only**: `asyncio`, `secrets`, `dataclasses`, `time`
- **Testing**: `pytest`, `pytest-asyncio` (`pip3 install pytest pytest-asyncio`)
