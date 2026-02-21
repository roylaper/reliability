"""MPC arithmetic: addition (local) and multiplication (BGW with degree reduction).

Multiplication uses CSS for resharing + per-gate ACS to agree on T:
1. Local product d_i = a_i * b_i
2. Each party CSS-shares d_i (robust against selective omission)
3. Per-gate ACS selects common T of size >= n-f = 2f+1
4. Lagrange recombination over T reduces degree back to f

No timeouts. Terminates with probability 1 via beacon-driven BA in ACS.
"""

import asyncio
from core.field import FieldElement
from core.polynomial import Polynomial, lagrange_coefficients_at_zero
from sim.network import Network, Message


class MPCArithmetic:
    """Arithmetic operations on secret-shared values."""

    def __init__(self, party_id: int, n: int, f: int, network: Network,
                 css=None, rbc=None, acs_factory=None):
        """
        css: CSSProtocol instance (shared with party)
        rbc: RBCProtocol instance (shared with party)
        acs_factory: callable() that returns a fresh ACSProtocol for per-gate use
        """
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network
        self.css = css
        self.rbc = rbc
        self.acs_factory = acs_factory

        self._active_set: list[int] | None = None

        # For open_value only (simple broadcast + reconstruct)
        self._open_shares: dict[str, dict[int, FieldElement]] = {}
        self._open_events: dict[str, asyncio.Event] = {}

    def set_active_set(self, active_set: set[int]):
        """Set the active set T determined by the initial ACS."""
        self._active_set = sorted(active_set)

    def add(self, share_a: FieldElement, share_b: FieldElement) -> FieldElement:
        return share_a + share_b

    def sub(self, share_a: FieldElement, share_b: FieldElement) -> FieldElement:
        return share_a - share_b

    def scalar_mul(self, constant: FieldElement, share: FieldElement) -> FieldElement:
        return constant * share

    async def multiply(self, share_a: FieldElement, share_b: FieldElement,
                       session_id: str) -> FieldElement:
        """Multiply two secret-shared values. Theory-aligned:

        1. Local product (degree 2f)
        2. CSS-share the local product (robust against selective omission)
        3. Per-gate ACS to agree on T (which CSS reshares to use)
        4. Lagrange recombination over T (degree reduction to f)
        """
        assert self._active_set is not None

        # Step 1: Local product
        d_i = share_a * share_b

        # Step 2: CSS-share d_i (each active party acts as dealer)
        css_sid = f"mul:{session_id}:d:{self.party_id}"
        if self.party_id in self._active_set:
            await self.css.share(d_i, css_sid)

        # Wait for CSS acceptance of each active party's resharing
        accepted_dealers = set()

        async def wait_css(pid):
            sid = f"mul:{session_id}:d:{pid}"
            await self.css.wait_accepted(sid)
            accepted_dealers.add(pid)

        # Watch all active parties' CSS sharings
        css_tasks = [asyncio.create_task(wait_css(pid))
                     for pid in self._active_set]

        # Wait until n-f CSS sharings are accepted (enough for T)
        enough_event = asyncio.Event()

        async def monitor_accepted():
            while len(accepted_dealers) < self.n - self.f:
                await asyncio.sleep(0.001)
            enough_event.set()

        monitor = asyncio.create_task(monitor_accepted())
        await enough_event.wait()
        monitor.cancel()

        # Step 3: Per-gate ACS to agree on T
        acs = self.acs_factory()
        gate_t = await acs.run(accepted_dealers, instance_id=f"mul:{session_id}")

        # Deterministic truncation to exactly n-f = 2f+1 parties
        gate_t_list = sorted(gate_t)[:self.n - self.f]

        # Cancel remaining CSS watchers
        for t in css_tasks:
            t.cancel()

        # Step 4: Lagrange recombination
        x_values = [FieldElement(pid) for pid in gate_t_list]
        lambdas = lagrange_coefficients_at_zero(x_values)

        result = FieldElement.zero()
        for idx, pid in enumerate(gate_t_list):
            css_share_sid = f"mul:{session_id}:d:{pid}"
            d_pid_share = self.css.get_share(css_share_sid)
            result = result + lambdas[idx] * d_pid_share

        return result

    # --- open_value: simple broadcast + reconstruct (no CSS needed) ---

    async def open_value(self, share: FieldElement, session_id: str) -> FieldElement:
        """Public reconstruction: broadcast shares, reconstruct from f+1."""
        open_key = f"open_{session_id}"
        if open_key not in self._open_shares:
            self._open_shares[open_key] = {}
        if open_key not in self._open_events:
            self._open_events[open_key] = asyncio.Event()

        await self.network.broadcast(self.party_id, Message(
            "MPC_OPEN", self.party_id, {
                "session_id": session_id,
                "share_value": share.value,
            }, session_id))

        self._open_shares[open_key][self.party_id] = share
        if len(self._open_shares[open_key]) >= self.f + 1:
            self._open_events[open_key].set()

        await self._open_events[open_key].wait()

        points = [(FieldElement(pid), s)
                  for pid, s in self._open_shares[open_key].items()]
        return Polynomial.interpolate_at_zero(points[:self.f + 1])

    async def handle_open(self, msg: Message):
        sid = msg.payload["session_id"]
        open_key = f"open_{sid}"
        if open_key not in self._open_shares:
            self._open_shares[open_key] = {}
        if open_key not in self._open_events:
            self._open_events[open_key] = asyncio.Event()
        self._open_shares[open_key][msg.sender] = FieldElement(msg.payload["share_value"])
        if len(self._open_shares[open_key]) >= self.f + 1:
            self._open_events[open_key].set()
