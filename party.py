"""Party: encapsulates a single MPC participant with event-driven message dispatch."""

import asyncio
from field import FieldElement
from network import Network, Message
from beacon import RandomnessBeacon
from css import CSSProtocol
from acs import ACSProtocol
from mpc_arithmetic import MPCArithmetic
from bit_decomposition import BitDecomposition
from comparison import ComparisonCircuit
from auction import SecondPriceAuction


class Party:
    """A single party in the MPC auction protocol."""

    def __init__(self, party_id: int, n: int, f: int, bid: int,
                 network: Network, beacon: RandomnessBeacon,
                 random_bit_sharings: list[dict[int, FieldElement]] | None = None):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.bid = FieldElement(bid)
        self.network = network
        self.beacon = beacon

        # Protocol instances
        self.css = CSSProtocol(party_id, n, f, network)
        self.acs = ACSProtocol(party_id, n, f, network)
        self.mpc = MPCArithmetic(party_id, n, f, network)
        self.bit_decomp = BitDecomposition(party_id, n, f, self.mpc)
        self.comparison = ComparisonCircuit(self.mpc)
        self.auction = SecondPriceAuction(
            party_id, n, f, network, self.mpc,
            self.bit_decomp, self.comparison, self.css)

        # Load preprocessed random bits
        if random_bit_sharings:
            self.bit_decomp.load_random_bits(random_bit_sharings)

        # Message dispatch table
        self._handlers = {
            "CSS_SHARE": self.css.handle_share,
            "CSS_ECHO": self.css.handle_echo,
            "CSS_READY": self.css.handle_ready,
            "CSS_RECOVER": self.css.handle_recover,
            "CSS_REVEAL": self.css.handle_reveal,
            "ACS_VOTE": self.acs.handle_vote,
            "MUL_RESHARE": self.mpc.handle_reshare,
            "MPC_OPEN": self.mpc.handle_open,
        }

    # Overall timeout for an omitting party to detect exclusion
    PROTOCOL_TIMEOUT = 30.0

    async def run(self) -> FieldElement | None:
        """Main party coroutine. Returns auction output."""
        dispatcher = asyncio.create_task(self._message_dispatcher())

        try:
            result = await asyncio.wait_for(
                self._run_protocol(), timeout=self.PROTOCOL_TIMEOUT)
            return result
        except asyncio.TimeoutError:
            # This party was likely omitted from the protocol
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

        # Phase 2: Wait for n-f=3 CSS sharings to be accepted
        accepted_dealers = set()
        accepted_dealers.add(self.party_id)  # We accept our own

        wait_tasks = []
        for pid in range(1, self.n + 1):
            if pid != self.party_id:
                wait_tasks.append(self._wait_for_acceptance(pid, accepted_dealers))
        await asyncio.gather(*wait_tasks)

        # Need at least n-f accepted dealers to proceed
        if len(accepted_dealers) < self.n - self.f:
            return None

        # Phase 3: ACS to agree on active set
        active_set = await asyncio.wait_for(
            self.acs.run(accepted_dealers), timeout=10.0)

        # Phase 4: Set active set for MPC multiplication
        self.mpc.set_active_set(active_set)

        # Phase 5: Collect our shares of each active party's bid
        bid_shares = {}
        for pid in active_set:
            session = f"input_{pid}"
            bid_shares[pid] = self.css.get_share(session)

        # Phase 6: Run auction computation
        result = await self.auction.run(bid_shares, active_set)
        return result

    async def _wait_for_acceptance(self, dealer_id: int, accepted: set):
        """Wait for a specific dealer's CSS sharing to be accepted."""
        session = f"input_{dealer_id}"
        try:
            await asyncio.wait_for(
                self.css.wait_accepted(session),
                timeout=2.0  # Timeout for detecting omitting parties
            )
            accepted.add(dealer_id)
        except asyncio.TimeoutError:
            # Dealer is probably omitting — don't add to accepted set
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
