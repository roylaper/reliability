# README — Project Purpose & Design Rationale (Python)

## Project goal (Python implementation)

The goal of **System Project 1** is to implement a **theory-faithful asynchronous MPC-style second-price auction** for **n=4 parties** with **f=1 omission fault**, in a **fully asynchronous, event-driven** setting.

Each party \(P_i\) holds a private 5-bit bid \(x_i \in \{0,\dots,31\}\) (all bids are unique). The system must:

- **Agree on a common subset** \(I\) of size \(|I| = n-f = 3\) (the subset used to define the auction outcome).
- **Compute the second-price auction** on bids in \(I\) without revealing bids:
  - winner = argmax bid in \(I\)
  - price = second-highest bid in \(I\)
- **Deliver per-party outputs** \(o_1,\dots,o_4\) such that:
  - only the winner learns `price`
  - all others learn `0`
- Remain correct and terminating for honest parties under:
  - arbitrary message delays (asynchrony)
  - one party that may omit sending any subset of messages
- Provide **measurements**:
  - total messages sent (optionally by message type)
  - number of beacon invocations (common-coin usage)

To match the theoretical part, the design explicitly includes:
- **Secret sharing** for input privacy,
- **RBC + ACS** for agreement in asynchrony,
- **BGW-style arithmetic-circuit evaluation** with **degree reduction** for multiplication gates,
- **Output privacy** via mask-and-open and private unmasking.

---

## Why the folder/file split looks like this (Python)

The structure is designed to separate four concerns that otherwise get tangled and become untestable:

1) **Simulation infrastructure** (asynchrony + faults)  
2) **Cryptographic/data primitives** (field arithmetic, Shamir, Lagrange)  
3) **Distributed protocol components** (RBC/BA/ACS, beacon, MPC engine)  
4) **Application logic** (auction circuit + output delivery)  

This separation lets you:
- unit-test each protocol module in isolation,
- swap delay/fault models without touching protocol logic,
- keep “math correctness” (Shamir/Lagrange) isolated and heavily tested,
- keep the Party state machine thin: it orchestrates modules rather than re-implementing them.

---

## Proposed Python repo layout and rationale

### `src/core/` — shared building blocks used everywhere
- `types.py`  
  Central type definitions: `PartyId`, `Epoch`, message base classes, enums for message types.  
  Keeps the whole codebase consistent and prevents circular imports.

- `field.py`  
  Implements arithmetic in \( \mathbb{Z}_p \): `add/sub/mul/inv`, plus encoding bids into field elements.  
  Field operations must be correct and fast; isolating them reduces mistakes.

- `rng.py`  
  Deterministic PRNG wrappers (seeded per test run).  
  Critical for reproducible simulations (same seed → same delays → same execution).

---

### `src/sim/` — the distributed systems “world”
- `event_loop.py`  
  A discrete-event simulator with a priority queue of scheduled events.  
  This is what enforces “fully asynchronous, event-driven”: no round loops.

- `network.py`  
  Message passing abstraction:
  - schedules deliveries with delay,
  - applies omission policies,
  - increments message counters.  
  Protocol modules call `network.send()`; they never manipulate time directly.

- `scheduler.py`  
  Utilities for timeouts / periodic progress triggers (useful for BA/ACS liveness).  
  Keeps “timing logic” out of protocol code.

- `metrics.py`  
  Collects global metrics:
  - total messages/by type
  - beacon invocations
  - completion times  
  Centralizing metrics avoids accidental double-counting.

---

### `src/crypto/` — theory math primitives
- `shamir.py`  
  Degree-1 Shamir share generation and reconstruction; Lagrange coefficient computation.  
  This is a core correctness component: used by input sharing, masks, degree reduction.

- `css.py`  
  A CSS-like input-sharing instance manager (finalization/binding logic).  
  This is where you implement the “sharing instance” abstraction expected by the theory:
  - finalization,
  - value IDs (`vid`),
  - handling incomplete/invalid dealers under omission.

---

### `src/protocols/` — reusable distributed protocol modules
- `rbc.py`  
  Bracha RBC (INIT/ECHO/READY) with deliver callbacks.  
  RBC is a general primitive used by ACS and by CSS evidence dissemination.

- `beacon.py`  
  Threshold beacon (release once ≥ f+1 requests).  
  A standalone component to keep the common coin logic consistent and measurable.

- `ba.py`  
  Binary Agreement using the beacon as common coin.  
  Implemented as an instance-per-index module, heavily testable in isolation.

- `acs.py`  
  Asynchronous Common Subset built from RBC + BA.  
  ACS is the “agree on I / agree on T” engine:
  - used once for choosing auction subset \(I\),
  - and repeatedly for degree-reduction subsets \(T\) inside multiplications.

- `mpc_engine.py`  
  BGW-style evaluation of arithmetic circuits on shares:
  - local add,
  - multiply via reshare + ACS(T) + Lagrange recombination (degree reduction).  
  This keeps “circuit evaluation” separate from “auction wiring”.

- `auction_circuit.py`  
  The application-specific circuit wiring for second-price on three inputs:
  - top1/top2 tournament logic,
  - uses weak black-box compare primitives (`GT`, `MUX`, etc.),
  - outputs shared values `[o_i]`.

- `output_privacy.py`  
  Implements mask-and-open + private unmask:
  - public reconstruction of `y_i = o_i + r_i`,
  - private reconstruction of `r_i` only by owner.  
  This is logically separate from auction correctness.

---

### `src/party.py` — orchestration / glue
The `Party` class is an event-driven state machine that:
- starts its own CSS input sharing,
- participates in RBC/ACS/BA instances,
- runs MPC evaluation tasks,
- produces its final private output.

**Importantly**: `party.py` should not contain cryptographic math or protocol logic—only coordination and state.

---

### `tests/` — tests mirror the architecture
- `test_honest.py`  
  End-to-end correctness with random delays, no faults.

- `test_one_omitter.py`  
  End-to-end with each party as the omitter; drop-all and partial drop.

- `test_random_delays.py`  
  Stress with large delays; ensures termination and agreement.

- `test_adversarial_schedules.py`  
  Deterministic adversarial delay models to trigger tricky interleavings.

- `test_regressions.py`  
  Frozen seeds/configs that reproduce previous bugs.

- `utils.py`  
  Reference auction function, assertions (agreement on I, correctness), log inspectors (privacy sanity).
