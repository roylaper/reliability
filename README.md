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
# Run the auction with demo scenarios
python3 main.py

# Run with specific seed for reproducibility
python3 main.py 42

# Run all tests (77 tests)
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
  Messages sent: 2355
  By type:
    BA_DECIDE: 48
    BA_VOTE: 48
    CSS_ECHO: 36
    CSS_READY: 36
    CSS_SHARE: 12
    MASK_SHARE: 12
    MPC_OPEN: 168
    MUL_RESHARE: 918
    RBC_ECHO: 144
    RBC_INIT: 48
    RBC_READY: 144
```

## Project Structure

```
relabilty/
├── main.py                     # Entry point — runs auction scenarios
├── party.py                    # Party state machine (event-driven dispatch)
├── CLAUDE.md                   # Exercise specification
├── README.md
│
├── core/                       # Shared primitives
│   ├── __init__.py
│   ├── field.py                # Finite field arithmetic (F_p, p=2^127-1)
│   ├── polynomial.py           # Polynomial operations, Lagrange interpolation
│   └── rng.py                  # Deterministic PRNG for reproducible tests
│
├── sim/                        # Simulation infrastructure
│   ├── __init__.py
│   ├── network.py              # Async channels, delay models, omission policies
│   ├── beacon.py               # Randomness beacon (threshold f+1)
│   └── metrics.py              # Execution timing metrics
│
├── protocols/                  # Distributed protocol modules
│   ├── __init__.py
│   ├── rbc.py                  # Bracha Reliable Broadcast (INIT/ECHO/READY)
│   ├── ba.py                   # Binary Agreement with beacon coin (Ben-Or)
│   ├── acs.py                  # Agreement on Common Set (RBC + BA)
│   ├── css.py                  # Complete Secret Sharing (echo/ready + VID)
│   ├── mpc_arithmetic.py       # BGW multiplication with degree reduction
│   └── output_privacy.py       # Mask-and-open + private unmask
│
├── circuits/                   # Auction-specific computation
│   ├── __init__.py
│   ├── bit_decomposition.py    # Secret-shared value -> secret-shared bits
│   ├── comparison.py           # Greater-than on shared bit vectors
│   └── auction.py              # Second-price auction circuit
│
├── tests/                      # Test suite (77 tests)
│   ├── __init__.py
│   ├── utils.py                # Reference oracle, assertion helpers
│   ├── test_field.py           # Field arithmetic (15 tests)
│   ├── test_polynomial.py      # Lagrange interpolation (8 tests)
│   ├── test_rbc.py             # Reliable broadcast (4 tests)
│   ├── test_ba.py              # Binary agreement (5 tests)
│   ├── test_acs.py             # Agreement on common set (3 tests)
│   ├── test_css.py             # Secret sharing + finalization (5 tests)
│   ├── test_mpc.py             # MPC arithmetic (8 tests)
│   ├── test_comparison.py      # Bit decomposition + comparison (6 tests)
│   ├── test_auction.py         # Full auction integration (6 tests)
│   ├── test_honest.py          # Multiple configs x seeds (5 tests)
│   ├── test_one_omitter.py     # Each party as omitter (6 tests)
│   ├── test_random_delays.py   # Exponential/uniform delay stress (3 tests)
│   └── test_adversarial.py     # Adversarial scheduling (2 tests)
│
└── maor_suggestions/           # Design guidance documents
    ├── README_Project1_Detailed_Design_Plan.md
    └── README_Project1_Design_Rationale.md
```

## Architecture

```
                    +-----------+
                    |  main.py  |  Entry point
                    +-----+-----+
                          |
                    +-----+-----+
                    | party.py  |  Event-driven dispatch
                    +-----+-----+
                          |
     +--------------------+--------------------+
     |                    |                    |
+----+----+       +-------+-------+    +-------+-------+
|  core/  |       | protocols/    |    | circuits/     |
| field   |       | rbc  (Bracha) |    | bit_decomp    |
| poly    |       | ba   (Ben-Or) |    | comparison    |
| rng     |       | acs  (RBC+BA) |    | auction       |
+---------+       | css  (share)  |    +---------------+
                  | mpc  (BGW)    |
     +----+       | output_priv   |
     |sim/|       +---------------+
     |net |
     |bcn |
     +----+
```

## Protocol Flow

```
Phase 1: CSS Share       Each party secret-shares its bid (echo/ready)
Phase 2: CSS Finalize    Wait for n-f=3 sharings to be finalized (VID binding)
Phase 3: ACS             RBC-broadcast proposals, run BA per dealer, agree on active set
Phase 4: MPC Compute     Bit decompose -> Compare -> Find winner -> Mask output
Phase 5: Output Privacy  Mask-and-open: public open masked value, private unmask
```

## Directory Descriptions

### `core/` — Shared Primitives

#### `field.py`
Finite field arithmetic over F_p where p = 2^127 - 1 (Mersenne prime). `FieldElement` class with `+`, `-`, `*`, `/`, `**`, `inverse()`, `random()`.

#### `polynomial.py`
Polynomial operations: `evaluate()` (Horner's), `random(degree, constant)`, `interpolate_at_zero(points)` (Lagrange), `lagrange_coefficients_at_zero()`.

#### `rng.py`
Deterministic PRNG wrapper. Call `rng.set_seed(n)` for reproducible tests. Default uses `os.urandom` for cryptographic randomness.

### `sim/` — Simulation Infrastructure

#### `network.py`
Async message-passing layer with configurable:
- **Delay models**: `UniformDelay`, `ExponentialDelay`, `FixedDelay`, `AdversarialDelay`
- **Omission policies**: `DropAll`, `DropProb(p)`, `DropTypes(types)`, `BurstDrop(intervals)`
- **Metrics**: per-message-type counts, total sent/dropped

#### `beacon.py`
Randomness beacon — releases random `FieldElement` when f+1=2 parties request the same index. Used by BA for common coin.

#### `metrics.py`
Simple wall-clock timing tracker.

### `protocols/` — Distributed Protocol Modules

#### `rbc.py` — Bracha Reliable Broadcast
Per-instance protocol keyed by (sender, tag):
- INIT -> ECHO -> READY -> DELIVER
- Thresholds: n-f=3 echoes, f+1=2 readys (amplification), n-f=3 readys (deliver)
- Guarantees: if one honest party delivers, all honest parties deliver the same value

#### `ba.py` — Binary Agreement
Ben-Or style with beacon as common coin:
- Each round: broadcast vote, collect n-f votes
- Supermajority -> decide; simple majority -> adopt; no majority -> beacon coin
- Guarantees: all honest parties decide the same value

#### `acs.py` — Agreement on Common Set
Theory-faithful construction using RBC + BA:
1. Each party RBC-broadcasts which CSS sharings it accepted
2. For each dealer j, run BA_j to decide inclusion
3. Output set = {j : BA_j decided 1}, size >= n-f=3

#### `css.py` — Complete Secret Sharing
Echo/ready dissemination with explicit finalization:
- `CSSStatus`: PENDING / FINALIZED / INVALID
- VID (value ID) computation via SHA-256 for binding
- `share()`, `recover()`, `recover_to_party()`, `get_share()`, `wait_accepted()`

#### `mpc_arithmetic.py` — BGW Multiplication
- `add()`, `sub()`, `scalar_mul()` — local (no communication)
- `multiply()` — BGW: local product -> reshare with degree-f poly -> Lagrange recombination
- `open_value()` — public reconstruction from f+1 shares

#### `output_privacy.py` — Mask-and-Open
- Compute [y] = [output] + [mask] (local)
- Public open y (all reconstruct)
- Send mask shares privately to owner
- Owner computes output = y - mask

### `circuits/` — Auction-Specific Computation

#### `bit_decomposition.py`
Convert secret-shared value to secret-shared bits using pre-generated random bit sharings + ripple-borrow subtraction circuit. `preprocess_random_bit_sharings()` for offline phase.

#### `comparison.py`
Greater-than on secret-shared bit vectors via MSB-to-LSB prefix scan. 3 multiplications per bit, 15 total for 5-bit values.

#### `auction.py`
Second-price auction circuit:
1. Bit decompose all active bids
2. Pairwise comparisons
3. Winner = beats all others; second = 1 - max - min
4. Second price = sum(bid_i * is_second_i)
5. Output mask = is_max * second_price
6. Reveal via output_privacy (mask-and-open)

### `party.py` — Orchestration

Event-driven state machine wiring all protocol instances. Spawns one asyncio reader per incoming channel. Dispatches messages to RBC/BA/CSS/MPC/output_privacy handlers.

### `main.py` — Entry Point

Runs demo scenarios with configurable seed. Reports results and per-message-type metrics.

## Tests

Run with `python3 -m pytest tests/ -v` (77 tests total).

| Test File | Tests | Category |
|-----------|-------|----------|
| `test_field.py` | 15 | Field arithmetic |
| `test_polynomial.py` | 8 | Lagrange interpolation |
| `test_rbc.py` | 4 | Reliable broadcast: honest, sender omits, non-sender omits, agreement |
| `test_ba.py` | 5 | Binary agreement: unanimous, majority, split, omission |
| `test_acs.py` | 3 | ACS: all honest, one omitter, agreement |
| `test_css.py` | 5 | Secret sharing: honest, omission, finalization status, VID |
| `test_mpc.py` | 8 | MPC: add, sub, scalar, multiply, open |
| `test_comparison.py` | 6 | Bit decomposition + comparison |
| `test_auction.py` | 6 | Full integration: honest, omission, edge bids, metrics |
| `test_honest.py` | 5 | Multiple bid configs x seeds |
| `test_one_omitter.py` | 6 | Each party as omitter, partial drop |
| `test_random_delays.py` | 3 | Exponential/uniform delay stress |
| `test_adversarial.py` | 2 | Adversarial scheduling |
| **Total** | **77** | |

## Dependencies

- **Python 3.11+**
- **Standard library only**: `asyncio`, `hashlib`, `os`, `random`, `time`, `json`, `dataclasses`, `collections`, `enum`
- **Testing**: `pytest`, `pytest-asyncio` (`pip3 install pytest pytest-asyncio`)
