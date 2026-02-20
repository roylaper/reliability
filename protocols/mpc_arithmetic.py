"""MPC arithmetic: addition (local) and multiplication (BGW with degree reduction).

Handles partial omission: if not all reshares arrive within a timeout,
falls back to using the n-f reshares that did arrive. All honest parties
converge on the same subset because honest parties' reshares always arrive.
"""

import asyncio
from core.field import FieldElement
from core.polynomial import Polynomial, lagrange_coefficients_at_zero
from sim.network import Network, Message


class MPCArithmetic:
    """Arithmetic operations on secret-shared values for a single party."""

    # Timeout per multiplication gate for collecting reshares.
    # If not all active set reshares arrive within this, fall back to n-f subset.
    RESHARE_TIMEOUT = 0.3

    def __init__(self, party_id: int, n: int, f: int, network: Network):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network

        self._active_set: list[int] | None = None

        # Reshare state: session_id -> {sender_party: share_for_me}
        self._reshares: dict[str, dict[int, FieldElement]] = {}
        self._reshare_events: dict[str, asyncio.Event] = {}  # fires when ALL arrive
        self._reshare_enough_events: dict[str, asyncio.Event] = {}  # fires at n-f

    def set_active_set(self, active_set: set[int]):
        """Set the active set T determined by ACS."""
        self._active_set = sorted(active_set)

    def add(self, share_a: FieldElement, share_b: FieldElement) -> FieldElement:
        return share_a + share_b

    def sub(self, share_a: FieldElement, share_b: FieldElement) -> FieldElement:
        return share_a - share_b

    def scalar_mul(self, constant: FieldElement, share: FieldElement) -> FieldElement:
        return constant * share

    async def multiply(self, share_a: FieldElement, share_b: FieldElement,
                       session_id: str) -> FieldElement:
        """Multiply two secret-shared values using BGW degree reduction.

        Waits for all reshares from the active set. If a partial omitter
        causes some reshares to not arrive, falls back to using the n-f
        reshares that did arrive (sufficient for degree reduction from 2f to f).
        """
        assert self._active_set is not None, "Must call set_active_set first"

        # Step 1: Local multiply
        h_i = share_a * share_b

        # Step 2: Reshare h_i with degree-f polynomial
        self._ensure_reshare_session(session_id)
        if self.party_id in self._active_set:
            poly = Polynomial.random(degree=self.f, constant=h_i)
            for j in range(1, self.n + 1):
                share_val = poly.evaluate(FieldElement(j))
                if j == self.party_id:
                    self._reshares[session_id][self.party_id] = share_val
                    self._check_reshare_progress(session_id)
                else:
                    await self.network.send(
                        self.party_id, j,
                        Message("MUL_RESHARE", self.party_id, {
                            "session_id": session_id,
                            "share_value": share_val.value,
                        }, session_id)
                    )

        # Step 3: Wait for reshares — optimistic (all) with timeout fallback (n-f)
        try:
            await asyncio.wait_for(
                self._reshare_events[session_id].wait(),
                timeout=self.RESHARE_TIMEOUT)
            # All reshares arrived — use the full active set
            used_set = list(self._active_set)
        except asyncio.TimeoutError:
            # Not all arrived — wait for at least n-f (guaranteed to arrive)
            await self._reshare_enough_events[session_id].wait()
            # Use whichever active set members' reshares arrived
            used_set = sorted(
                pid for pid in self._active_set
                if pid in self._reshares[session_id]
            )

        # Step 4: Recombine using Lagrange coefficients for the used set
        x_values = [FieldElement(pid) for pid in used_set]
        lambdas = lagrange_coefficients_at_zero(x_values)

        result = FieldElement.zero()
        for idx, pid in enumerate(used_set):
            result = result + lambdas[idx] * self._reshares[session_id][pid]

        return result

    def _ensure_reshare_session(self, session_id: str):
        if session_id not in self._reshares:
            self._reshares[session_id] = {}
        if session_id not in self._reshare_events:
            self._reshare_events[session_id] = asyncio.Event()
        if session_id not in self._reshare_enough_events:
            self._reshare_enough_events[session_id] = asyncio.Event()

    def _check_reshare_progress(self, session_id: str):
        """Check reshare collection progress."""
        if self._active_set is None:
            return
        received = set(self._reshares[session_id].keys())
        active_received = received & set(self._active_set)

        # Check if n-f arrived (enough for fallback)
        if len(active_received) >= self.n - self.f:
            if session_id in self._reshare_enough_events:
                self._reshare_enough_events[session_id].set()

        # Check if ALL arrived (optimal path)
        if all(pid in received for pid in self._active_set):
            self._reshare_events[session_id].set()

    async def handle_reshare(self, msg: Message):
        sid = msg.payload["session_id"]
        self._ensure_reshare_session(sid)
        share_val = FieldElement(msg.payload["share_value"])
        self._reshares[sid][msg.sender] = share_val
        self._check_reshare_progress(sid)

    async def open_value(self, share: FieldElement, session_id: str) -> FieldElement:
        """Open (reveal) a secret-shared value to all parties."""
        open_key = f"open_{session_id}"
        self._ensure_reshare_session(open_key)

        msg = Message("MPC_OPEN", self.party_id, {
            "session_id": session_id,
            "share_value": share.value,
        }, session_id)
        await self.network.broadcast(self.party_id, msg)

        self._reshares[open_key][self.party_id] = share
        self._check_open_complete(open_key)

        await self._reshare_events[open_key].wait()

        points = [
            (FieldElement(pid), s)
            for pid, s in self._reshares[open_key].items()
        ]
        return Polynomial.interpolate_at_zero(points[:self.f + 1])

    def _check_open_complete(self, open_key: str):
        if len(self._reshares.get(open_key, {})) >= self.f + 1:
            if open_key not in self._reshare_events:
                self._reshare_events[open_key] = asyncio.Event()
            self._reshare_events[open_key].set()

    async def handle_open(self, msg: Message):
        sid = msg.payload["session_id"]
        open_key = f"open_{sid}"
        self._ensure_reshare_session(open_key)
        share_val = FieldElement(msg.payload["share_value"])
        self._reshares[open_key][msg.sender] = share_val
        self._check_open_complete(open_key)
