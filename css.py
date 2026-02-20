"""Complete Secret Sharing for omission failure model.

Simplified: parties never send incorrect values, only omit messages.
So any f+1 shares are guaranteed correct and consistent.
"""

import asyncio
from field import FieldElement
from polynomial import Polynomial, lagrange_coefficients_at_zero
from network import Network, Message


class CSSProtocol:
    """CSS protocol instance for a single party."""

    def __init__(self, party_id: int, n: int, f: int, network: Network):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network

        # State per session
        self._shares: dict[str, FieldElement] = {}  # session -> my share
        self._echoes: dict[str, dict[int, FieldElement]] = {}  # session -> {party: share}
        self._ready_counts: dict[str, set] = {}  # session -> set of parties that sent READY
        self._ready_sent: set[str] = set()  # sessions for which we sent READY

        # Recovery state
        self._recover_shares: dict[str, dict[int, FieldElement]] = {}  # session -> {party: share}

        # Events
        self._accepted: dict[str, asyncio.Event] = {}  # session -> accepted event
        self._recovered: dict[str, asyncio.Event] = {}  # session -> recovery complete event
        self._recovered_values: dict[str, FieldElement] = {}

    def _ensure_session(self, session_id: str):
        if session_id not in self._echoes:
            self._echoes[session_id] = {}
        if session_id not in self._ready_counts:
            self._ready_counts[session_id] = set()
        if session_id not in self._accepted:
            self._accepted[session_id] = asyncio.Event()
        if session_id not in self._recover_shares:
            self._recover_shares[session_id] = {}
        if session_id not in self._recovered:
            self._recovered[session_id] = asyncio.Event()

    async def share(self, secret: FieldElement, session_id: str):
        """Dealer shares a secret. Called only by the dealing party."""
        self._ensure_session(session_id)
        poly = Polynomial.random(degree=self.f, constant=secret)

        # Send share p(i) to each party (including self)
        for i in range(1, self.n + 1):
            share_val = poly.evaluate(FieldElement(i))
            if i == self.party_id:
                # Deliver to self directly
                self._shares[session_id] = share_val
                # Echo own share
                await self._send_echo(session_id, share_val)
            else:
                await self.network.send(
                    self.party_id, i,
                    Message("CSS_SHARE", self.party_id,
                            {"session_id": session_id, "share_value": share_val.value},
                            session_id)
                )

    async def _send_echo(self, session_id: str, share_val: FieldElement):
        """Broadcast echo of our share."""
        msg = Message("CSS_ECHO", self.party_id, {
            "session_id": session_id,
            "point": self.party_id,
            "share_value": share_val.value,
        }, session_id)
        await self.network.broadcast(self.party_id, msg)
        # Also record own echo
        self._echoes[session_id][self.party_id] = share_val
        await self._check_echoes(session_id)

    async def handle_share(self, msg: Message):
        """Handle incoming CSS_SHARE message."""
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        share_val = FieldElement(msg.payload["share_value"])
        self._shares[sid] = share_val
        # Echo to all
        await self._send_echo(sid, share_val)

    async def handle_echo(self, msg: Message):
        """Handle incoming CSS_ECHO message."""
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        point = msg.payload["point"]
        share_val = FieldElement(msg.payload["share_value"])
        self._echoes[sid][point] = share_val
        await self._check_echoes(sid)

    async def _check_echoes(self, session_id: str):
        """Check if we have enough echoes to send READY."""
        if session_id in self._ready_sent:
            return
        if len(self._echoes[session_id]) >= self.f + 1:
            self._ready_sent.add(session_id)
            msg = Message("CSS_READY", self.party_id,
                          {"session_id": session_id}, session_id)
            await self.network.broadcast(self.party_id, msg)
            # Count own ready
            self._ready_counts[session_id].add(self.party_id)
            self._check_accepted(session_id)

    async def handle_ready(self, msg: Message):
        """Handle incoming CSS_READY message."""
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        self._ready_counts[sid].add(msg.sender)
        self._check_accepted(sid)

    def _check_accepted(self, session_id: str):
        """Check if enough READY messages to accept the sharing."""
        if len(self._ready_counts[session_id]) >= self.n - self.f:
            self._accepted[session_id].set()

    async def wait_accepted(self, session_id: str):
        """Wait until this sharing is accepted."""
        self._ensure_session(session_id)
        await self._accepted[session_id].wait()

    def is_accepted(self, session_id: str) -> bool:
        return session_id in self._accepted and self._accepted[session_id].is_set()

    def get_share(self, session_id: str) -> FieldElement:
        """Get our share for this session.

        If the direct dealer share hasn't arrived, derive it from echoes
        via Lagrange interpolation.
        """
        if session_id in self._shares:
            return self._shares[session_id]
        # Derive from echoes: interpolate polynomial at our party_id
        echoes = self._echoes.get(session_id, {})
        if len(echoes) >= self.f + 1:
            points = [
                (FieldElement(pid), share)
                for pid, share in list(echoes.items())[:self.f + 1]
            ]
            # Interpolate the full polynomial and evaluate at our point
            # For degree-1: p(x) from 2 points, then p(party_id)
            from polynomial import Polynomial
            # Build full interpolating polynomial
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            # Lagrange interpolation at our party_id
            x_eval = FieldElement(self.party_id)
            result = FieldElement.zero()
            n_pts = len(points)
            for i in range(n_pts):
                num = FieldElement.one()
                den = FieldElement.one()
                for j in range(n_pts):
                    if i == j:
                        continue
                    num = num * (x_eval - xs[j])
                    den = den * (xs[i] - xs[j])
                result = result + ys[i] * (num / den)
            self._shares[session_id] = result
            return result
        raise KeyError(f"No share available for session {session_id}")

    async def recover(self, session_id: str) -> FieldElement:
        """Reconstruct the secret from shares (all parties participate)."""
        self._ensure_session(session_id)
        my_share = self._shares[session_id]

        # Send our share to all
        msg = Message("CSS_RECOVER", self.party_id, {
            "session_id": session_id,
            "point": self.party_id,
            "share_value": my_share.value,
        }, session_id)
        await self.network.broadcast(self.party_id, msg)

        # Record own share
        self._recover_shares[session_id][self.party_id] = my_share

        # Wait for f+1 total shares (including own)
        while len(self._recover_shares[session_id]) < self.f + 1:
            await asyncio.sleep(0.001)

        # Interpolate at zero
        points = [
            (FieldElement(pid), share)
            for pid, share in self._recover_shares[session_id].items()
        ]
        return Polynomial.interpolate_at_zero(points[:self.f + 1])

    async def recover_to_party(self, session_id: str, target_party: int) -> FieldElement | None:
        """Reveal a shared value only to the target party."""
        self._ensure_session(session_id)
        my_share = self._shares[session_id]
        reveal_key = f"reveal_{session_id}"
        if reveal_key not in self._recover_shares:
            self._recover_shares[reveal_key] = {}

        if self.party_id == target_party:
            # Record own share directly (no self-send)
            self._recover_shares[reveal_key][self.party_id] = my_share
        else:
            # Send share to target
            msg = Message("CSS_REVEAL", self.party_id, {
                "session_id": session_id,
                "point": self.party_id,
                "share_value": my_share.value,
            }, session_id)
            await self.network.send(self.party_id, target_party, msg)

        if self.party_id == target_party:
            # Wait for enough shares to reconstruct
            while len(self._recover_shares[reveal_key]) < self.f + 1:
                await asyncio.sleep(0.001)

            points = [
                (FieldElement(pid), share)
                for pid, share in self._recover_shares[reveal_key].items()
            ]
            return Polynomial.interpolate_at_zero(points[:self.f + 1])
        return None

    async def handle_recover(self, msg: Message):
        """Handle incoming CSS_RECOVER message."""
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        point = msg.payload["point"]
        share_val = FieldElement(msg.payload["share_value"])
        self._recover_shares[sid][point] = share_val

    async def handle_reveal(self, msg: Message):
        """Handle incoming CSS_REVEAL message (selective reveal)."""
        sid = msg.payload["session_id"]
        reveal_key = f"reveal_{sid}"
        if reveal_key not in self._recover_shares:
            self._recover_shares[reveal_key] = {}
        point = msg.payload["point"]
        share_val = FieldElement(msg.payload["share_value"])
        self._recover_shares[reveal_key][point] = share_val
