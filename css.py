"""Complete Secret Sharing (CSS) for omission failure model.

Uses direct echo/ready dissemination (sufficient for omission-only faults).
Includes explicit finalization states and VID binding.
RBC is used separately by ACS for proposals, not inside CSS.
"""

import asyncio
import hashlib
from enum import Enum
from field import FieldElement
from polynomial import Polynomial, lagrange_coefficients_at_zero
from network import Network, Message


class CSSStatus(Enum):
    PENDING = "pending"
    FINALIZED = "finalized"
    INVALID = "invalid"


class CSSProtocol:
    """CSS protocol with echo/ready dissemination + finalization states."""

    def __init__(self, party_id: int, n: int, f: int, network: Network):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network

        # Per-session state
        self._shares: dict[str, FieldElement] = {}
        self._status: dict[str, CSSStatus] = {}
        self._vids: dict[str, str] = {}
        self._echoes: dict[str, dict[int, FieldElement]] = {}
        self._ready_counts: dict[str, set] = {}
        self._ready_sent: set[str] = set()
        self._finalized: dict[str, asyncio.Event] = {}

        # Recovery state
        self._recover_shares: dict[str, dict[int, FieldElement]] = {}

    def _ensure_session(self, session_id: str):
        if session_id not in self._status:
            self._status[session_id] = CSSStatus.PENDING
        if session_id not in self._echoes:
            self._echoes[session_id] = {}
        if session_id not in self._ready_counts:
            self._ready_counts[session_id] = set()
        if session_id not in self._finalized:
            self._finalized[session_id] = asyncio.Event()
        if session_id not in self._recover_shares:
            self._recover_shares[session_id] = {}

    async def share(self, secret: FieldElement, session_id: str):
        """Dealer shares a secret."""
        self._ensure_session(session_id)
        poly = Polynomial.random(degree=self.f, constant=secret)

        for i in range(1, self.n + 1):
            share_val = poly.evaluate(FieldElement(i))
            if i == self.party_id:
                self._shares[session_id] = share_val
                await self._send_echo(session_id, share_val)
            else:
                await self.network.send(
                    self.party_id, i,
                    Message("CSS_SHARE", self.party_id, {
                        "session_id": session_id,
                        "share_value": share_val.value,
                    }, session_id))

    async def _send_echo(self, session_id: str, share_val: FieldElement):
        msg = Message("CSS_ECHO", self.party_id, {
            "session_id": session_id,
            "point": self.party_id,
            "share_value": share_val.value,
        }, session_id)
        await self.network.broadcast(self.party_id, msg)
        self._echoes[session_id][self.party_id] = share_val
        await self._check_echoes(session_id)

    async def handle_share(self, msg: Message):
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        share_val = FieldElement(msg.payload["share_value"])
        self._shares[sid] = share_val
        await self._send_echo(sid, share_val)

    async def handle_echo(self, msg: Message):
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        point = msg.payload["point"]
        share_val = FieldElement(msg.payload["share_value"])
        self._echoes[sid][point] = share_val
        await self._check_echoes(sid)

    async def _check_echoes(self, session_id: str):
        if session_id in self._ready_sent:
            return
        if len(self._echoes[session_id]) >= self.f + 1:
            self._ready_sent.add(session_id)
            msg = Message("CSS_READY", self.party_id,
                          {"session_id": session_id}, session_id)
            await self.network.broadcast(self.party_id, msg)
            self._ready_counts[session_id].add(self.party_id)
            self._check_finalization(session_id)

    async def handle_ready(self, msg: Message):
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        self._ready_counts[sid].add(msg.sender)
        self._check_finalization(sid)

    def _check_finalization(self, session_id: str):
        """Finalize when n-f READYs received."""
        if self._status[session_id] != CSSStatus.PENDING:
            return
        if len(self._ready_counts[session_id]) < self.n - self.f:
            return

        # Finalize: compute VID from echoes
        self._status[session_id] = CSSStatus.FINALIZED

        echoes_sorted = sorted(
            (pt, sv.value) for pt, sv in self._echoes[session_id].items())
        vid_input = f"{session_id}:{echoes_sorted}"
        self._vids[session_id] = hashlib.sha256(vid_input.encode()).hexdigest()[:16]

        # Derive share from echoes if not received directly
        if session_id not in self._shares:
            self._derive_share_from_echoes(session_id)

        self._finalized[session_id].set()

    def _derive_share_from_echoes(self, session_id: str):
        """Compute our share via Lagrange interpolation from echoes."""
        echoes = self._echoes[session_id]
        points = [(FieldElement(pt), sv)
                  for pt, sv in list(echoes.items())[:self.f + 1]]
        x_eval = FieldElement(self.party_id)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        result = FieldElement.zero()
        for i in range(len(points)):
            num = FieldElement.one()
            den = FieldElement.one()
            for j in range(len(points)):
                if i == j:
                    continue
                num = num * (x_eval - xs[j])
                den = den * (xs[i] - xs[j])
            result = result + ys[i] * (num / den)
        self._shares[session_id] = result

    async def wait_accepted(self, session_id: str):
        self._ensure_session(session_id)
        await self._finalized[session_id].wait()

    def is_accepted(self, session_id: str) -> bool:
        return self._status.get(session_id) == CSSStatus.FINALIZED

    def get_status(self, session_id: str) -> CSSStatus:
        return self._status.get(session_id, CSSStatus.PENDING)

    def get_vid(self, session_id: str) -> str | None:
        return self._vids.get(session_id)

    def get_share(self, session_id: str) -> FieldElement:
        if session_id in self._shares:
            return self._shares[session_id]
        if session_id in self._echoes and len(self._echoes[session_id]) >= self.f + 1:
            self._derive_share_from_echoes(session_id)
            return self._shares[session_id]
        raise KeyError(f"No share available for session {session_id}")

    async def recover(self, session_id: str) -> FieldElement:
        self._ensure_session(session_id)
        my_share = self._shares[session_id]
        msg = Message("CSS_RECOVER", self.party_id, {
            "session_id": session_id,
            "point": self.party_id,
            "share_value": my_share.value,
        }, session_id)
        await self.network.broadcast(self.party_id, msg)
        self._recover_shares[session_id][self.party_id] = my_share
        while len(self._recover_shares[session_id]) < self.f + 1:
            await asyncio.sleep(0.001)
        points = [
            (FieldElement(pid), share)
            for pid, share in self._recover_shares[session_id].items()
        ]
        return Polynomial.interpolate_at_zero(points[:self.f + 1])

    async def recover_to_party(self, session_id: str, target_party: int) -> FieldElement | None:
        self._ensure_session(session_id)
        my_share = self._shares[session_id]
        reveal_key = f"reveal_{session_id}"
        if reveal_key not in self._recover_shares:
            self._recover_shares[reveal_key] = {}
        if self.party_id == target_party:
            self._recover_shares[reveal_key][self.party_id] = my_share
        else:
            msg = Message("CSS_REVEAL", self.party_id, {
                "session_id": session_id,
                "point": self.party_id,
                "share_value": my_share.value,
            }, session_id)
            await self.network.send(self.party_id, target_party, msg)
        if self.party_id == target_party:
            while len(self._recover_shares[reveal_key]) < self.f + 1:
                await asyncio.sleep(0.001)
            points = [
                (FieldElement(pid), share)
                for pid, share in self._recover_shares[reveal_key].items()
            ]
            return Polynomial.interpolate_at_zero(points[:self.f + 1])
        return None

    async def handle_recover(self, msg: Message):
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        point = msg.payload["point"]
        share_val = FieldElement(msg.payload["share_value"])
        self._recover_shares[sid][point] = share_val

    async def handle_reveal(self, msg: Message):
        sid = msg.payload["session_id"]
        reveal_key = f"reveal_{sid}"
        if reveal_key not in self._recover_shares:
            self._recover_shares[reveal_key] = {}
        point = msg.payload["point"]
        share_val = FieldElement(msg.payload["share_value"])
        self._recover_shares[reveal_key][point] = share_val
