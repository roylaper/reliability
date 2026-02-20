"""MPC arithmetic: addition (local) and multiplication (BGW with degree reduction)."""

import asyncio
from field import FieldElement
from polynomial import Polynomial, lagrange_coefficients_at_zero
from network import Network, Message


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
        self._reshare_events: dict[str, asyncio.Event] = {}

    def set_active_set(self, active_set: set[int]):
        """Set the active set T determined by ACS. Precompute Lagrange coefficients."""
        self._active_set = sorted(active_set)
        x_values = [FieldElement(pid) for pid in self._active_set]
        self._lagrange_coeffs = lagrange_coefficients_at_zero(x_values)

    def add(self, share_a: FieldElement, share_b: FieldElement) -> FieldElement:
        """Add two secret-shared values (local, no communication)."""
        return share_a + share_b

    def sub(self, share_a: FieldElement, share_b: FieldElement) -> FieldElement:
        """Subtract two secret-shared values (local)."""
        return share_a - share_b

    def scalar_mul(self, constant: FieldElement, share: FieldElement) -> FieldElement:
        """Multiply a share by a public constant (local)."""
        return constant * share

    async def multiply(self, share_a: FieldElement, share_b: FieldElement,
                       session_id: str) -> FieldElement:
        """Multiply two secret-shared values using BGW degree reduction.

        1. Local multiply: h_i = a_i * b_i (degree 2f sharing)
        2. Reshare: each party in T creates degree-f poly with constant = h_i
        3. Recombine using Lagrange coefficients for T
        """
        assert self._active_set is not None, "Must call set_active_set first"

        # Step 1: Local multiply
        h_i = share_a * share_b

        # Step 2: Reshare h_i with degree-f polynomial
        if self.party_id in self._active_set:
            poly = Polynomial.random(degree=self.f, constant=h_i)
            for j in range(1, self.n + 1):
                share_val = poly.evaluate(FieldElement(j))
                if j == self.party_id:
                    self._ensure_reshare_session(session_id)
                    self._reshares[session_id][self.party_id] = share_val
                    self._check_reshare_complete(session_id)
                else:
                    await self.network.send(
                        self.party_id, j,
                        Message("MUL_RESHARE", self.party_id, {
                            "session_id": session_id,
                            "share_value": share_val.value,
                        }, session_id)
                    )

        # Step 3: Wait for reshares from all parties in active set
        self._ensure_reshare_session(session_id)
        await self._reshare_events[session_id].wait()

        # Step 4: Recombine
        result = FieldElement.zero()
        for idx, pid in enumerate(self._active_set):
            lambda_i = self._lagrange_coeffs[idx]
            q_i_of_me = self._reshares[session_id][pid]
            result = result + lambda_i * q_i_of_me

        return result

    def _ensure_reshare_session(self, session_id: str):
        if session_id not in self._reshares:
            self._reshares[session_id] = {}
        if session_id not in self._reshare_events:
            self._reshare_events[session_id] = asyncio.Event()

    def _check_reshare_complete(self, session_id: str):
        """Check if we received reshares from all parties in active set."""
        if self._active_set is None:
            return
        received = set(self._reshares[session_id].keys())
        if all(pid in received for pid in self._active_set):
            self._reshare_events[session_id].set()

    async def handle_reshare(self, msg: Message):
        """Handle incoming MUL_RESHARE message."""
        sid = msg.payload["session_id"]
        self._ensure_reshare_session(sid)
        share_val = FieldElement(msg.payload["share_value"])
        self._reshares[sid][msg.sender] = share_val
        self._check_reshare_complete(sid)

    async def open_value(self, share: FieldElement, session_id: str) -> FieldElement:
        """Open (reveal) a secret-shared value to all parties.

        All parties broadcast their shares, then reconstruct.
        """
        open_key = f"open_{session_id}"
        self._ensure_reshare_session(open_key)

        # Broadcast own share
        msg = Message("MPC_OPEN", self.party_id, {
            "session_id": session_id,
            "share_value": share.value,
        }, session_id)
        await self.network.broadcast(self.party_id, msg)

        # Record own
        self._reshares[open_key][self.party_id] = share
        self._check_open_complete(open_key)

        # Wait for enough shares
        await self._reshare_events[open_key].wait()

        # Reconstruct
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
        """Handle incoming MPC_OPEN message."""
        sid = msg.payload["session_id"]
        open_key = f"open_{sid}"
        self._ensure_reshare_session(open_key)
        share_val = FieldElement(msg.payload["share_value"])
        self._reshares[open_key][msg.sender] = share_val
        self._check_open_complete(open_key)
