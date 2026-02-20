# README — Detailed Project Plan (Theory-Aligned) — System Project 1, n=4, f=1

Great — below is a **much more detailed, “build-this-repo” project plan** that matches the **theory-aligned design** (CSS/RBC/ACS + BGW-style evaluation with degree reduction), and includes **exactly how to simulate** the async network + omissions and how to build a **proper test suite**.

I’ll keep the “comparison / bit-decomposition” as a **weak black box**, but everything around it (privacy, sharing, ACS, multiplication/degree-reduction, output privacy) is implemented in the system.

---

## 1) Repository layout

```text
src/
  core/
    types.py                  # PartyId, Epoch, FieldElement, Message base
    field.py                  # mod prime arithmetic
    rng.py                    # deterministic PRNG wrapper with per-test seeds
  sim/
    event_loop.py             # discrete-event simulator (priority queue)
    network.py                # async network with delays + omission rules
    scheduler.py              # helper to schedule timeouts & periodic checks
    metrics.py                # message counts, beacon invocations, latency stats
  crypto/
    shamir.py                 # degree-1 Shamir share/reconstruct/lagrange
    css.py                    # Complete Secret Sharing (CSS-like) instance logic
  protocols/
    rbc.py                    # Bracha RBC module (INIT/ECHO/READY)
    beacon.py                 # common coin beacon (threshold f+1 requests)
    ba.py                     # binary agreement using beacon coin
    acs.py                    # ACS built from RBC+BA
    mpc_engine.py             # BGW evaluation: add/mul + degree reduction
    auction_circuit.py        # second-price circuit wiring using black-box GT/MUX
    output_privacy.py         # mask-and-open + private unmask
  party.py                    # Party state machine (event-driven)
tests/
  test_honest.py
  test_one_omitter.py
  test_random_delays.py
  test_adversarial_schedules.py
  test_regressions.py
  utils.py                    # reference auction, asserts, log inspectors
```

If you’re coding in another language (Go/TS/Java), the structure maps 1:1.

---

## 2) Simulation model (how you “run the distributed system”)

### 2.1 Discrete-event event loop
You simulate time as integers (ticks). The core data structure:

- `PriorityQueue<Event>` sorted by `(time, tie_breaker_counter)`
- `Event` holds: `time`, `target_party_id OR network/beacon`, `callback`, `payload`

#### Why this is important
- Asynchrony is modeled by random (or adversarial) delay between send and delivery.
- “No rounds” is enforced because parties only progress on message delivery or scheduled local timeouts.

### 2.2 Network simulator
`Network.send(from, to, msg)` does:

1) Apply omission policy:
   - if `from == faulty_party` and message type is droppable → drop with probability `p` (or always drop)
2) Otherwise compute delay:
   - `d = delay_model.sample()` (random or adversarial)
3) Schedule delivery:
   - `event_loop.schedule(now + d, target=to, callback=Party.on_message, payload=msg)`
4) Increment metrics:
   - `metrics.msg_total += 1`
   - `metrics.by_type[msg.type] += 1`

#### Delay models you should implement
- `UniformDelay(min,max)`
- `ExponentialDelay(lambda)`
- `AdversarialDelay` (deterministic): e.g., delay messages from certain parties more
- `ReplayDelay` (for debugging): a recorded list of delays per message-id

### 2.3 Omission fault model (one omitter)
Provide **policies**:
- `DropAllFrom(faulty_id)`
- `DropProbFrom(faulty_id, p)`
- `DropOnlyTypes(faulty_id, types, p=1.0)`
- `BurstDrop(faulty_id, bursts=[(t0,t1),...])`

This is crucial for tests.

---

## 3) Field and Shamir primitives

### 3.1 Choose the field
Pick a prime `p` comfortably above all computations. You can use a 61-bit prime (safe in 64-bit ops) or Python big ints.

Implement:
- `add, sub, mul, inv`
- convert bid 0..31 to field element

### 3.2 Degree-1 Shamir (f=1)
A secret `s` is represented by `p(t) = s + r*t`.

- Share for party j: `share[j] = p(j)`
- Reconstruct from any 2 points `(j, share[j])`:
  - `s = L0*share[j1] + L1*share[j2]` where Lagrange coefficients interpolate at 0.
- For robustness in simulation, **prefer reconstruct from 3 shares when possible** (since 3 honest exist), but degree-1 only needs 2.

---

## 4) CSS-like input sharing (binding + hiding)

Even with omission faults, aligning to the theory means you want each input-sharing instance to produce a **well-defined “value id” (vid)** and finalized shares that honest parties agree are consistent.

### Practical CSS-like approach (implementable, theory-faithful)
For each dealer `d`:

1) Dealer sends `SS_SHARE(d -> j, shareValue)` to all.
2) Each receiver `j` broadcasts an **RBC** message containing what it received (or a commitment to it):
   - RBC tag: `CSS_EVIDENCE(d)`
   - payload: `(j, shareValue)` or `(j, H(shareValue))`  
   For simplicity and since this is a simulation, you can send `(j, shareValue)`.

3) Once a party collects **RBC-delivered evidence** from enough parties (≥3) that implies a **unique degree-1 polynomial**, it “finalizes” the CSS instance:
   - pick any 2 consistent points among delivered evidence → define polynomial
   - verify other delivered points match
   - if matches, finalize:
     - `vid_d = H(d || epoch || polynomial_coeffs)` (or H of the 2 defining points)
     - store its own finalized share `x_d(j)`.

If evidence is inconsistent (shouldn’t happen under pure omission, but could if your model allows arbitrary faults):
- finalize as “invalid” and vote it out in ACS.

**Output of CSS for dealer d at party j:**
- `CSSStatus[d] ∈ {FINALIZED(vid, share), INVALID, PENDING}`

---

## 5) RBC module (Bracha) — explicit

For each `(sender s, tag)` instance:
- State: `echoCount[payload]`, `readyCount[payload]`, flags `sentEcho/sentReady/delivered`
- Thresholds (n=4, f=1): `3` for `n-f` and `2` for `f+1`.

Rules (as you already have):
- INIT → ECHO
- 3 ECHOs → READY
- 2 READY → READY
- 3 READY → DELIVER

**Important simulation detail:** RBC messages themselves go through the same network delays/omissions.

---

## 6) Beacon (common coin)

Implement a module that handles `BEACON_REQUEST(t)`:

- Maintain `requests[t] = set(parties)`
- When `len(requests[t]) >= 2` (f+1):
  - generate `rho_t = random_field_element()`
  - broadcast `BEACON_VALUE(t, rho_t)` to all parties
  - metrics.beacon_invocations += 1

This is used by BA.

---

## 7) BA (Binary Agreement) — per index

For ACS you run **BA_i** for i=1..4.

### Minimal BA suitable for simulation (n=4,f=1)
Use a Ben-Or–style common-coin BA. Keep it event-driven:

State per BA instance:
- `estimate ∈ {0,1}`
- `round r = 1,2,...`
- sets `votes[r][value] = set(parties)`
- `decided?`

Messages:
- `BA_VOTE(i, r, value)`

Rules:
1) Broadcast your current `estimate` as `BA_VOTE(i, r, estimate)`.
2) When you see **≥3 votes** for the same value `v` in round r:
   - decide `v`
3) Else if you see **≥2 votes** for some value `v`:
   - set `estimate = v` for next round
4) Else:
   - request beacon `rho_r` and set `estimate = rho_r mod 2` for next round

Progress:
- In async, you might need a local timeout trigger: if you’re not receiving enough votes to progress, request the beacon for that round.

---

## 8) ACS construction (RBC + BA)

**Goal:** output a common set `I` of size 3.

### 8.1 What value is proposed to ACS?
For each party i, propose via RBC:
- tag: `ACS_PROPOSE(i)`
- payload: `vid_i` (the CSS finalized value id for dealer i), or `⊥` if invalid.

RBC ensures consistency of `vid_i` (if delivered).

### 8.2 BA inputs
For each i:
- `b_i = 1` iff RBC delivered a non-⊥ `vid_i`
- else `b_i = 0`

Run BA_i to decide inclusion.

### 8.3 Output set
Let `S = { i | BA_i decided 1 }`.
- If `|S| >= 3`: `I = smallest3(S)` (deterministic)
- If `|S| < 3`: continue BA rounds until enough are included (coin ensures eventual progress).

---

## 9) MPC evaluation engine (BGW-style)

You need to support:
- addition gates (local)
- multiplication gates (interactive + degree reduction)

### 9.1 Representation
Each wire is a “shared value” with:
- `shares[j]` at party j (degree-1)
- `wire_id` for debugging/metrics

### 9.2 Addition gate
Local:
- `c_share = a_share + b_share`

No messages.

### 9.3 Multiplication gate (core theory alignment)
Given `[a]` and `[b]` as degree-1 sharings.

#### Step 1: local product (degree becomes 2)
Party j computes:
- `d_j = a_j * b_j`

Now the set `{d_j}` corresponds to a degree-2 sharing of the product (in theory).

#### Step 2: “reshare” each d_j as degree-1
Each party j acts as a dealer and runs **CSS** on secret `d_j` to produce a fresh degree-1 sharing `[d_j]^{reshared}`.

This spawns 4 CSS instances (one per j) per multiplication gate.

#### Step 3: agree on subset T of size 3 (2f+1) for reduction
Run **ACS** (or ACS-lite but theory-aligned: reuse ACS module) to obtain:
- `T ⊆ {1,2,3,4}`, `|T|=3`
- The selection must be consistent across honest parties.

#### Step 4: Lagrange recombination to reduce degree
Compute Lagrange coefficients \(\lambda_j\) for interpolation at 0 using points `T` (party indices as x-coordinates).

Each party i sets its share of `[c]`:
\[
c_i = \sum_{j\in T} \lambda_j \cdot \left(d_j^{reshared}ight)_i
\]
Result is a fresh degree-1 sharing of `ab`.

✅ This is the exact “agree on T + Lagrange sum” reduction from the theory.

---

## 10) Auction circuit (second-price) using weak black box

Once ACS outputs `I={a,b,c}`, you have shared bids `[x_a],[x_b],[x_c]`.

You may treat comparisons as black boxes, but they must **input shared values and output shared bits**:
- `GT([u],[v]) -> [bit]`
- `MUX([bit],[u],[v]) -> [w]`

Then compute:
- `maxVal`, `secondVal` via tournament logic
- `isWinner_i = EQ([x_i], maxVal)` (or derive from comparisons)
- `[o_i] = isWinner_i * secondVal` using your multiplication gate

---

## 11) Output privacy (mask-and-open + private unmask)

For each i:

1) Create random shared mask `[r_i]`:
   - each party j samples random `r_i^(j)` and shares it (Shamir)
   - everyone sums to get `[r_i]`

2) Publicly open `y_i = o_i + r_i`:
   - parties broadcast their share of `[y_i]`
   - reconstruct `y_i` from 3 shares

3) Send mask shares privately to owner i:
   - each party sends its share of `[r_i]` to i
   - i reconstructs `r_i` and computes `o_i = y_i - r_i`

No one else can unmask.

---

## 12) Party state machine (very explicit)

Each party maintains a set of concurrent “subprotocol instances” keyed by IDs:
- CSS instances: `CSS(dealer, context)`
- RBC instances: `(sender, tag)`
- BA instances: `(index i)`
- ACS instances: `(context)`
- MPC gates: `(gate_id)` (each multiplication gate triggers its own internal ACS+CSS instances)

**Top-level states:**
1) Start: initiate CSS for own bid
2) When own CSS finalized: RBC-broadcast its `vid`
3) Run ACS to decide `I`
4) Run MPC auction circuit:
   - triggers multiple multiplications (depending on circuit wiring)
   - each multiplication runs internal ACS for T
5) Output privacy stage
6) Done

You will likely need a “progress engine” method called after every event:
- `try_advance()` checks if enough conditions have been met to start next steps.

---

## 13) Test Suite Plan (what to test, how to simulate, what to assert)

### 13.1 Test harness structure
Each test does:

1) Choose:
   - bids (unique)
   - faulty party (or none)
   - omission policy
   - delay model + RNG seed
2) Create simulator:
   - event loop
   - network
   - beacon
   - parties
3) Start all parties (schedule `onStart` at time 0)
4) Run event loop until:
   - all honest parties reach DONE, or
   - max steps / max simulated time reached (fail)
5) Assertions + metrics collection

#### Key outputs to record per party
- decided set `I`
- final output `o_i` (only its own)
- transcript logs (for debugging)
- time-to-done

#### Global metrics
- total messages + by type
- beacon invocations
- number of ACS rounds used
- number of multiplication gates executed

---

### 13.2 Core correctness assertions

#### A) Agreement on I
For all honest parties:
- `I_p == I_q`
- `|I| == 3`

#### B) Auction correctness
Compute reference outcome using a “cleartext oracle” **only in the test harness**:
- Determine which parties are in `I`
- Take their true bids (test harness knows them)
- winner = max, price = second max
- expected outputs: winner gets price else 0

Then assert:
- honest parties’ **own** output equals expected for them
- (if your implementation outputs only to owner, check only local output)

#### C) Privacy sanity checks (system-level)
Even if you treat comparisons as black box, you can enforce:
- No message contains a plaintext bid (0..31) in a field where it shouldn’t.
Practical checks:
- ensure message types never carry raw bids
- ensure `SS_SHARE` payloads look random mod p (optional statistical sanity)

#### D) Termination / liveness
- honest parties terminate within a configured bound:
  - `max_events` (e.g., 200k events)
  - `max_sim_time` (e.g., 1e6 ticks)
If not, fail and dump schedule/log.

---

### 13.3 Required test categories (with concrete test cases)

#### 1) Honest execution tests
**Goal:** baseline correctness.

- Fixed bids, fixed seed
- Several random seeds

Assertions: agreement, correctness, zero/low beacon usage.

Example:
- bids: [3, 17, 29, 11]
- delay: Uniform(1,10)
- faulty: none

Expect:
- `I` usually includes all 4? No: must be size 3; ACS truncates deterministically.
- With no omitter, BA should include all, then truncate to smallest3.

#### 2) One omitting party — full silence
**Goal:** tolerate omission.

For each `faulty ∈ {1..4}`:
- drop all outgoing messages from faulty
- delays random
- run multiple seeds

Expect:
- honest parties decide `I` as the 3 honest parties (typically)
- beacon might be used depending on scheduling, but should terminate.

#### 3) One omitter — partial omission
**Goal:** robustness against flaky sender.

For each faulty:
- drop probability p ∈ {0.3, 0.5, 0.7}
- run multiple seeds

Expect:
- termination w.p.1 in practice (bounded by test time)
- agreement + correctness.

#### 4) Random delays stress
**Goal:** heavy asynchrony.

- Exponential delays with large mean, or Uniform(1,1000)
- no faulty, then with faulty
- many seeds

Track:
- beacon invocations should increase
- messages increase, but still terminates

#### 5) Adversarial schedule tests (deterministic worst-ish cases)
**Goal:** catch subtle race bugs.

Implement a delay model that:
- delays messages from P1→P2 a lot
- delivers P3’s messages early
- causes parties to see different evidence first

Then assert:
- they still converge on same `I`

#### 6) Regression tests
Whenever you find a bug:
- record the exact seed + omission config + delay model params
- add a regression test that reproduces it

---

## 14) How to simulate the weak black-box compare (without breaking “privacy spirit”)

You have two good options:

### Option A (recommended): “Ideal functionality in the harness”
- The “compare” black box does **not** exist inside parties.
- Instead, parties send a request to a simulated “IdealMPCCompare” component that:
  - has access to ground truth (stored privately in harness)
  - returns *shared outputs* consistent with the requested operation
- This is closest to “ideal functionality” and avoids accidentally leaking bids.

BUT: if you do this, make sure:
- compare results are returned as **Shamir shares**, not plaintext bits.

### Option B: symbolic handles
- represent shared values as DAG nodes
- `GT` returns a `SharedBitHandle`
- evaluation happens only at the end using harness truth
This is more work but avoids a “central oracle” flavor.

Either way, no party ever sees plaintext comparisons.

---

## 15) Metrics & reporting output

At the end of each test run, print a compact report:

- `seed`, `faulty`, `drop_policy`, `delay_model`
- `msg_total`, `msg_by_type`
- `beacon_invocations`
- `sim_time_to_decision` (max over honest parties)
- `acs_rounds_used` (max)
- `mul_gates_executed`

Also dump:
- decided I
- winner id (not necessarily revealed to all; keep it in harness)
- winner’s output

---

## 16) Implementation checkpoints (what to build first)

1) Event loop + network + omission + metrics
2) RBC module + tests (unit tests: one sender broadcasts, ensure agreement on delivered value)
3) Beacon module + tests
4) BA module + tests (force coin usage via adversarial delays)
5) ACS module + tests (output same set)
6) Shamir + CSS-like finalize logic + tests
7) MPC engine:
   - add gate test
   - mul gate test (degree reduction correctness against cleartext)
8) Auction circuit wiring + end-to-end tests
9) Output privacy stage tests

This ordering prevents “big bang debugging”.
