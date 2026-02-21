"""Party: encapsulates a single MPC participant with event-driven message dispatch.

Fully asynchronous, no synchrony assumptions. Protocol proceeds on evidence
thresholds (n-f events), never on wall-clock timeouts. The only timeout is the
outer harness guard in run() which is NOT part of the protocol logic.
"""

import asyncio
from core.field import FieldElement
from sim.network import Network, Message
from sim.beacon import RandomnessBeacon
from protocols.rbc import RBCProtocol
from protocols.ba import BAProtocol
from protocols.css import CSSProtocol
from protocols.acs import ACSProtocol
from protocols.mpc_arithmetic import MPCArithmetic
from circuits.bit_decomposition import BitDecomposition
from circuits.comparison import ComparisonCircuit
from protocols.output_privacy import OutputPrivacy
from circuits.auction import SecondPriceAuction


class Party:
    """A single party in the MPC auction protocol."""

    def __init__(self, party_id: int, n: int, f: int, bid: int,
                 network: Network, beacon: RandomnessBeacon,
                 random_bit_sharings: list[dict[int, FieldElement]] | None = None,
                 mask_sharings: list[dict[int, FieldElement]] | None = None,
                 protocol_timeout: float = 60.0):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.bid = FieldElement(bid)
        self.network = network
        self.beacon = beacon
        self.protocol_timeout = protocol_timeout

        # Protocol instances
        self.rbc = RBCProtocol(party_id, n, f, network)
        self.ba = BAProtocol(party_id, n, f, network, beacon)
        self.css = CSSProtocol(party_id, n, f, network)
        self.acs = ACSProtocol(party_id, n, f, network, beacon, self.rbc, self.ba)

        # ACS factory for per-gate multiplication
        def make_acs():
            return ACSProtocol(party_id, n, f, network, beacon, self.rbc, self.ba)

        self.mpc = MPCArithmetic(party_id, n, f, network,
                                  css=self.css, rbc=self.rbc,
                                  acs_factory=make_acs)
        self.bit_decomp = BitDecomposition(party_id, n, f, self.mpc)
        self.comparison = ComparisonCircuit(self.mpc)
        self.output_privacy = OutputPrivacy(party_id, n, f, network, self.mpc)
        self.auction = SecondPriceAuction(
            party_id, n, f, network, self.mpc,
            self.bit_decomp, self.comparison, self.output_privacy)

        if random_bit_sharings:
            self.bit_decomp.load_random_bits(random_bit_sharings)

        self._mask_shares: list[FieldElement] = []
        if mask_sharings:
            self._mask_shares = [ms[party_id] for ms in mask_sharings]

        # Track CSS acceptances
        self._accepted_dealers: set[int] = set()
        self._enough_accepted = asyncio.Event()

        # Message dispatch — CSS echo/ready + RBC/BA + MPC open + output privacy
        self._handlers = {
            "RBC_INIT": self.rbc.handle_init,
            "RBC_ECHO": self.rbc.handle_echo,
            "RBC_READY": self.rbc.handle_ready,
            "BA_VOTE": self.ba.handle_vote,
            "BA_DECIDE": self.ba.handle_decide,
            "CSS_SHARE": self.css.handle_share,
            "CSS_ECHO": self.css.handle_echo,
            "CSS_READY": self.css.handle_ready,
            "CSS_RECOVER": self.css.handle_recover,
            "CSS_REVEAL": self.css.handle_reveal,
            "MPC_OPEN": self.mpc.handle_open,
            "MASK_SHARE": self.output_privacy.handle_mask_share,
        }

    async def run(self) -> FieldElement | None:
        """Main entry. Outer timeout is harness guard only."""
        dispatcher = asyncio.create_task(self._message_dispatcher())
        try:
            result = await asyncio.wait_for(
                self._run_protocol(), timeout=self.protocol_timeout)
            return result
        except asyncio.TimeoutError:
            return None
        finally:
            dispatcher.cancel()
            try:
                await dispatcher
            except asyncio.CancelledError:
                pass

    async def _run_protocol(self) -> FieldElement | None:
        """Fully event-driven protocol."""
        # Phase 1: Share own bid via CSS
        my_session = f"input_{self.party_id}"
        await self.css.share(self.bid, my_session)
        self._accepted_dealers.add(self.party_id)
        self._check_enough_accepted()

        # Phase 2: Wait for n-f CSS acceptances (event-driven)
        for pid in range(1, self.n + 1):
            if pid != self.party_id:
                asyncio.create_task(self._watch_css_acceptance(pid))
        await self._enough_accepted.wait()

        # Phase 3: ACS (event-driven RBC + BA)
        active_set = await self.acs.run(self._accepted_dealers)

        # Phase 4: Set active set for MPC
        self.mpc.set_active_set(active_set)

        # Phase 5: Collect bid shares
        bid_shares = {}
        for pid in active_set:
            bid_shares[pid] = self.css.get_share(f"input_{pid}")

        # Phase 6: Run auction
        result = await self.auction.run(
            bid_shares, active_set, self._mask_shares or None)
        return result

    async def _watch_css_acceptance(self, dealer_id: int):
        await self.css.wait_accepted(f"input_{dealer_id}")
        self._accepted_dealers.add(dealer_id)
        self._check_enough_accepted()

    def _check_enough_accepted(self):
        if len(self._accepted_dealers) >= self.n - self.f:
            self._enough_accepted.set()

    async def _message_dispatcher(self):
        readers = [self._channel_reader(s)
                   for s in range(1, self.n + 1) if s != self.party_id]
        await asyncio.gather(*readers)

    async def _channel_reader(self, sender_id: int):
        channel = self.network.channels[(sender_id, self.party_id)]
        while True:
            try:
                msg = await channel.receive()
                handler = self._handlers.get(msg.msg_type)
                if handler:
                    asyncio.create_task(handler(msg))
            except asyncio.CancelledError:
                break
