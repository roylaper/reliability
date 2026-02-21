"""Complete Secret Sharing (CSS) for omission failure model.

Finalization is based on f+1 consistent ECHOs (enough to define the degree-f
polynomial), NOT on n-f READYs. This prevents self-deadlock when a party's
own outgoing messages are slow — finalization depends only on INCOMING evidence.
READY messages are still broadcast as an optimization.
"""

import asyncio
import hashlib
from enum import Enum
from core.field import FieldElement
from core.polynomial import Polynomial
from sim.network import Network, Message


class CSSStatus(Enum):
    PENDING = "pending"
    FINALIZED = "finalized"
    INVALID = "invalid"


class CSSProtocol:
    """CSS with echo-based finalization (f+1 echoes to finalize)."""

    def __init__(self, party_id: int, n: int, f: int, network: Network):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network

        self._shares: dict[str, FieldElement] = {}
        self._status: dict[str, CSSStatus] = {}
        self._vids: dict[str, str] = {}
        self._echoes: dict[str, dict[int, FieldElement]] = {}
        self._ready_sent: set[str] = set()
        self._finalized: dict[str, asyncio.Event] = {}
        self._recover_shares: dict[str, dict[int, FieldElement]] = {}

    def _ensure_session(self, session_id: str):
        if session_id not in self._status:
            self._status[session_id] = CSSStatus.PENDING
        if session_id not in self._echoes:
            self._echoes[session_id] = {}
        if session_id not in self._finalized:
            self._finalized[session_id] = asyncio.Event()
        if session_id not in self._recover_shares:
            self._recover_shares[session_id] = {}

    async def share(self, secret: FieldElement, session_id: str):
        """Dealer shares a secret via degree-f polynomial."""
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
        self._try_finalize(session_id)

    async def handle_share(self, msg: Message):
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        self._shares[sid] = FieldElement(msg.payload["share_value"])
        await self._send_echo(sid, self._shares[sid])

    async def handle_echo(self, msg: Message):
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        self._echoes[sid][msg.payload["point"]] = FieldElement(msg.payload["share_value"])
        self._try_finalize(sid)
        # Broadcast READY as optimization once f+1 echoes seen
        if sid not in self._ready_sent and len(self._echoes[sid]) >= self.f + 1:
            self._ready_sent.add(sid)
            await self.network.broadcast(self.party_id, Message(
                "CSS_READY", self.party_id, {"session_id": sid}, sid))

    async def handle_ready(self, msg: Message):
        """READY is an optimization only. Finalization is echo-based."""
        pass

    def _try_finalize(self, session_id: str):
        """Finalize when f+1 echoes arrive — enough to define the polynomial.
        Depends ONLY on incoming echoes, not on our own outgoing messages."""
        if self._status[session_id] != CSSStatus.PENDING:
            return
        if len(self._echoes[session_id]) < self.f + 1:
            return
        self._status[session_id] = CSSStatus.FINALIZED
        echoes_sorted = sorted(
            (pt, sv.value) for pt, sv in self._echoes[session_id].items())
        self._vids[session_id] = hashlib.sha256(
            f"{session_id}:{echoes_sorted}".encode()).hexdigest()[:16]
        if session_id not in self._shares:
            self._derive_share(session_id)
        self._finalized[session_id].set()

    def _derive_share(self, session_id: str):
        """Compute our share via Lagrange from f+1 echoes."""
        echoes = self._echoes[session_id]
        pts = [(FieldElement(pt), sv)
               for pt, sv in list(echoes.items())[:self.f + 1]]
        x_eval = FieldElement(self.party_id)
        result = FieldElement.zero()
        for i in range(len(pts)):
            num = den = FieldElement.one()
            for j in range(len(pts)):
                if i != j:
                    num = num * (x_eval - pts[j][0])
                    den = den * (pts[i][0] - pts[j][0])
            result = result + pts[i][1] * (num / den)
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
            self._derive_share(session_id)
            return self._shares[session_id]
        raise KeyError(f"No share for {session_id}")

    async def recover(self, session_id: str) -> FieldElement:
        self._ensure_session(session_id)
        my_share = self.get_share(session_id)
        await self.network.broadcast(self.party_id, Message(
            "CSS_RECOVER", self.party_id, {
                "session_id": session_id, "point": self.party_id,
                "share_value": my_share.value}, session_id))
        self._recover_shares[session_id][self.party_id] = my_share
        while len(self._recover_shares[session_id]) < self.f + 1:
            await asyncio.sleep(0.001)
        pts = [(FieldElement(p), s)
               for p, s in self._recover_shares[session_id].items()]
        return Polynomial.interpolate_at_zero(pts[:self.f + 1])

    async def recover_to_party(self, session_id: str, target: int) -> FieldElement | None:
        self._ensure_session(session_id)
        my_share = self.get_share(session_id)
        rk = f"reveal_{session_id}"
        if rk not in self._recover_shares:
            self._recover_shares[rk] = {}
        if self.party_id == target:
            self._recover_shares[rk][self.party_id] = my_share
        else:
            await self.network.send(self.party_id, target, Message(
                "CSS_REVEAL", self.party_id, {
                    "session_id": session_id, "point": self.party_id,
                    "share_value": my_share.value}, session_id))
        if self.party_id == target:
            while len(self._recover_shares[rk]) < self.f + 1:
                await asyncio.sleep(0.001)
            pts = [(FieldElement(p), s)
                   for p, s in self._recover_shares[rk].items()]
            return Polynomial.interpolate_at_zero(pts[:self.f + 1])
        return None

    async def handle_recover(self, msg: Message):
        sid = msg.payload["session_id"]
        self._ensure_session(sid)
        self._recover_shares[sid][msg.payload["point"]] = FieldElement(msg.payload["share_value"])

    async def handle_reveal(self, msg: Message):
        sid = msg.payload["session_id"]
        rk = f"reveal_{sid}"
        if rk not in self._recover_shares:
            self._recover_shares[rk] = {}
        self._recover_shares[rk][msg.payload["point"]] = FieldElement(msg.payload["share_value"])
