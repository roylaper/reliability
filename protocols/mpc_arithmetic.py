"""MPC arithmetic: addition (local) and multiplication (BGW with degree reduction).

Fully event-driven, no timeouts in protocol logic:
- Multiplication waits for ALL reshares from the active set.
- open_value waits for f+1 shares (sufficient for reconstruction).
- No wall-clock timeouts affect protocol decisions.

For active sets where all members are honest (guaranteed when the omitter is
excluded by ACS), all reshares arrive and the protocol completes. If a selective
omitter enters the active set, per-gate BA would be needed to agree on the
reshare subset — this is noted as a known theoretical limitation of the fixed-T
optimization (see design docs).
"""

import asyncio
from core.field import FieldElement
from core.polynomial import Polynomial, lagrange_coefficients_at_zero
from sim.network import Network, Message


class MPCArithmetic:
    """Arithmetic operations on secret-shared values for a single party."""

    def __init__(self, party_id: int, n: int, f: int, network: Network):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network

        self._active_set: list[int] | None = None
        self._lagrange_coeffs: list[FieldElement] | None = None

        # Reshare state: session_id -> {sender_party: share_for_me}
        self._reshares: dict[str, dict[int, FieldElement]] = {}
        self._reshare_all_event: dict[str, asyncio.Event] = {}  # all active set
        self._reshare_enough_event: dict[str, asyncio.Event] = {}  # f+1 for open

    def set_active_set(self, active_set: set[int]):
        """Set the active set T determined by ACS. Precompute Lagrange coefficients."""
        self._active_set = sorted(active_set)
        x_values = [FieldElement(pid) for pid in self._active_set]
        self._lagrange_coeffs = lagrange_coefficients_at_zero(x_values)

    def add(self, share_a: FieldElement, share_b: FieldElement) -> FieldElement:
        return share_a + share_b

    def sub(self, share_a: FieldElement, share_b: FieldElement) -> FieldElement:
        return share_a - share_b

    def scalar_mul(self, constant: FieldElement, share: FieldElement) -> FieldElement:
        return constant * share

    async def multiply(self, share_a: FieldElement, share_b: FieldElement,
                       session_id: str) -> FieldElement:
        """Multiply two secret-shared values using BGW degree reduction.

        Waits for reshares from ALL parties in the active set (no timeout).
        All honest parties' reshares are guaranteed to arrive.
        """
        assert self._active_set is not None, "Must call set_active_set first"

        # Step 1: Local multiply
        h_i = share_a * share_b

        # Step 2: Reshare h_i with degree-f polynomial
        self._ensure_session(session_id)
        if self.party_id in self._active_set:
            poly = Polynomial.random(degree=self.f, constant=h_i)
            for j in range(1, self.n + 1):
                share_val = poly.evaluate(FieldElement(j))
                if j == self.party_id:
                    self._reshares[session_id][self.party_id] = share_val
                    self._check_reshare_all(session_id)
                else:
                    await self.network.send(
                        self.party_id, j,
                        Message("MUL_RESHARE", self.party_id, {
                            "session_id": session_id,
                            "share_value": share_val.value,
                        }, session_id))

        # Step 3: Wait for ALL reshares from active set (event-driven, no timeout)
        await self._reshare_all_event[session_id].wait()

        # Step 4: Recombine using precomputed Lagrange coefficients
        result = FieldElement.zero()
        for idx, pid in enumerate(self._active_set):
            lambda_i = self._lagrange_coeffs[idx]
            q_i_of_me = self._reshares[session_id][pid]
            result = result + lambda_i * q_i_of_me

        return result

    def _ensure_session(self, session_id: str):
        if session_id not in self._reshares:
            self._reshares[session_id] = {}
        if session_id not in self._reshare_all_event:
            self._reshare_all_event[session_id] = asyncio.Event()
        if session_id not in self._reshare_enough_event:
            self._reshare_enough_event[session_id] = asyncio.Event()

    def _check_reshare_all(self, session_id: str):
        """Check if ALL active set reshares arrived."""
        if self._active_set is None:
            return
        received = set(self._reshares[session_id].keys())
        if all(pid in received for pid in self._active_set):
            self._reshare_all_event[session_id].set()

    def _check_open_enough(self, open_key: str):
        """For open_value, f+1 shares suffice."""
        if len(self._reshares.get(open_key, {})) >= self.f + 1:
            self._reshare_enough_event[open_key].set()

    async def handle_reshare(self, msg: Message):
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        share_val = FieldElement(msg.payload["share_value"])
        self._reshares[sid][msg.sender] = share_val
        self._check_reshare_all(sid)

    async def open_value(self, share: FieldElement, session_id: str) -> FieldElement:
        """Open (reveal) a secret-shared value to all parties."""
        open_key = f"open_{session_id}"
        self._ensure_session(open_key)

        msg = Message("MPC_OPEN", self.party_id, {
            "session_id": session_id,
            "share_value": share.value,
        }, session_id)
        await self.network.broadcast(self.party_id, msg)

        self._reshares[open_key][self.party_id] = share
        self._check_open_enough(open_key)

        await self._reshare_enough_event[open_key].wait()

        points = [
            (FieldElement(pid), s)
            for pid, s in self._reshares[open_key].items()
        ]
        return Polynomial.interpolate_at_zero(points[:self.f + 1])

    async def handle_open(self, msg: Message):
        sid = msg.payload["session_id"]
        open_key = f"open_{sid}"
        self._ensure_session(open_key)
        share_val = FieldElement(msg.payload["share_value"])
        self._reshares[open_key][msg.sender] = share_val
        self._check_open_enough(open_key)
