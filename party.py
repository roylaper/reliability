"""Party: encapsulates a single MPC participant with event-driven message dispatch.

Uses RBC + BA based ACS (theory-faithful), CSS with RBC evidence,
and output privacy via mask-and-open.
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
                 protocol_timeout: float = 30.0):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.bid = FieldElement(bid)
        self.network = network
        self.beacon = beacon
        self.protocol_timeout = protocol_timeout

        # Protocol instances
        self.rbc = RBCProtocol(party_id, n, f, network)
        self.css = CSSProtocol(party_id, n, f, network)
        self.acs = ACSProtocol(party_id, n, f, network, beacon, self.rbc)
        self.mpc = MPCArithmetic(party_id, n, f, network)
        self.bit_decomp = BitDecomposition(party_id, n, f, self.mpc)
        self.comparison = ComparisonCircuit(self.mpc)
        self.output_privacy = OutputPrivacy(party_id, n, f, network, self.mpc)
        self.auction = SecondPriceAuction(
            party_id, n, f, network, self.mpc,
            self.bit_decomp, self.comparison, self.output_privacy)

        # Load preprocessed random bits
        if random_bit_sharings:
            self.bit_decomp.load_random_bits(random_bit_sharings)

        # Store mask sharings for output privacy
        self._mask_shares: list[FieldElement] = []
        if mask_sharings:
            self._mask_shares = [ms[party_id] for ms in mask_sharings]

        # Message dispatch table
        self._handlers = {
            # RBC messages (used by ACS)
            "RBC_INIT": self.rbc.handle_init,
            "RBC_ECHO": self.rbc.handle_echo,
            "RBC_READY": self.rbc.handle_ready,
            # BA messages (used by ACS)
            "BA_VOTE": self.acs.ba.handle_vote,
            "BA_DECIDE": self.acs.ba.handle_decide,
            # CSS messages (direct echo/ready)
            "CSS_SHARE": self.css.handle_share,
            "CSS_ECHO": self.css.handle_echo,
            "CSS_READY": self.css.handle_ready,
            "CSS_RECOVER": self.css.handle_recover,
            "CSS_REVEAL": self.css.handle_reveal,
            # MPC messages
            "MUL_RESHARE": self.mpc.handle_reshare,
            "MPC_OPEN": self.mpc.handle_open,
            # Output privacy messages
            "MASK_SHARE": self.output_privacy.handle_mask_share,
        }

    async def run(self) -> FieldElement | None:
        """Main party coroutine. Returns auction output."""
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
        """Execute the full auction protocol."""
        # Phase 1: Share own bid via CSS
        my_session = f"input_{self.party_id}"
        await self.css.share(self.bid, my_session)

        # Phase 2: Wait for n-f=3 CSS sharings to be accepted (finalized)
        accepted_dealers = set()
        accepted_dealers.add(self.party_id)

        wait_tasks = []
        for pid in range(1, self.n + 1):
            if pid != self.party_id:
                wait_tasks.append(self._wait_for_acceptance(pid, accepted_dealers))
        await asyncio.gather(*wait_tasks)

        if len(accepted_dealers) < self.n - self.f:
            return None

        # Phase 3: ACS to agree on active set (uses RBC + BA internally)
        active_set = await asyncio.wait_for(
            self.acs.run(accepted_dealers), timeout=15.0)

        # Phase 4: Set active set for MPC multiplication
        self.mpc.set_active_set(active_set)

        # Phase 5: Collect our shares of each active party's bid
        bid_shares = {}
        for pid in active_set:
            session = f"input_{pid}"
            bid_shares[pid] = self.css.get_share(session)

        # Phase 6: Run auction with output privacy
        result = await self.auction.run(
            bid_shares, active_set, self._mask_shares or None)
        return result

    async def _wait_for_acceptance(self, dealer_id: int, accepted: set):
        session = f"input_{dealer_id}"
        try:
            await asyncio.wait_for(
                self.css.wait_accepted(session), timeout=3.0)
            accepted.add(dealer_id)
        except asyncio.TimeoutError:
            pass

    async def _message_dispatcher(self):
        """Event-driven message dispatch: one reader per incoming channel."""
        readers = []
        for sender_id in range(1, self.n + 1):
            if sender_id != self.party_id:
                readers.append(self._channel_reader(sender_id))
        await asyncio.gather(*readers)

    async def _channel_reader(self, sender_id: int):
        """Read messages from a single incoming channel and dispatch."""
        channel = self.network.channels[(sender_id, self.party_id)]
        while True:
            try:
                msg = await channel.receive()
                handler = self._handlers.get(msg.msg_type)
                if handler:
                    asyncio.create_task(handler(msg))
            except asyncio.CancelledError:
                break
