"""Binary Agreement (BA) using beacon as common coin.

Ben-Or style: each round, parties vote; if supermajority → decide,
if simple majority → adopt, else → use beacon coin.
"""

import asyncio
from sim.network import Network, Message
from sim.beacon import RandomnessBeacon


class BAInstance:
    """State for a single BA instance."""

    def __init__(self, ba_index: int, party_id: int, n: int, f: int):
        self.ba_index = ba_index
        self.party_id = party_id
        self.n = n
        self.f = f

        self.estimate: int = -1  # 0 or 1, set when run() called
        self.round: int = 1
        # round -> value -> set of voters
        self.votes: dict[int, dict[int, set[int]]] = {}
        self.decided = False
        self.decided_value: int = -1
        self.decided_event = asyncio.Event()
        self._vote_events: dict[int, asyncio.Event] = {}  # round -> event

    def _ensure_round(self, r: int):
        if r not in self.votes:
            self.votes[r] = {0: set(), 1: set()}
        if r not in self._vote_events:
            self._vote_events[r] = asyncio.Event()


class BAProtocol:
    """Manages multiple BA instances for a party."""

    def __init__(self, party_id: int, n: int, f: int,
                 network: Network, beacon: RandomnessBeacon):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network
        self.beacon = beacon
        self._instances: dict[int, BAInstance] = {}

    def _get_instance(self, ba_index: int) -> BAInstance:
        if ba_index not in self._instances:
            self._instances[ba_index] = BAInstance(
                ba_index, self.party_id, self.n, self.f)
        return self._instances[ba_index]

    async def run(self, ba_index: int, initial_estimate: int) -> int:
        """Run BA for given index. Returns decided value (0 or 1)."""
        inst = self._get_instance(ba_index)
        inst.estimate = initial_estimate

        while not inst.decided:
            r = inst.round
            inst._ensure_round(r)

            # Broadcast vote for this round
            vote_msg = Message("BA_VOTE", self.party_id, {
                "ba_index": ba_index,
                "round": r,
                "value": inst.estimate,
            }, f"ba_{ba_index}_{r}")
            await self.network.broadcast(self.party_id, vote_msg)

            # Record own vote
            inst.votes[r][inst.estimate].add(self.party_id)
            inst._vote_events[r].set()

            # Wait for n-f votes total for this round
            while not inst.decided:
                total = len(inst.votes[r][0]) + len(inst.votes[r][1])
                if total >= self.n - self.f:
                    break
                inst._vote_events[r].clear()
                await inst._vote_events[r].wait()

            if inst.decided:
                break

            # Decision logic
            count_0 = len(inst.votes[r][0])
            count_1 = len(inst.votes[r][1])

            if count_1 >= self.n - self.f:
                # Supermajority for 1 → decide 1
                inst.decided = True
                inst.decided_value = 1
                inst.decided_event.set()
                await self._broadcast_decide(ba_index, 1)
            elif count_0 >= self.n - self.f:
                # Supermajority for 0 → decide 0
                inst.decided = True
                inst.decided_value = 0
                inst.decided_event.set()
                await self._broadcast_decide(ba_index, 0)
            elif count_1 >= self.f + 1:
                # Simple majority for 1
                inst.estimate = 1
                inst.round += 1
            elif count_0 >= self.f + 1:
                # Simple majority for 0
                inst.estimate = 0
                inst.round += 1
            else:
                # No majority → use beacon coin
                beacon_idx = ba_index * 1000 + r
                coin = await self.beacon.request(beacon_idx, self.party_id)
                inst.estimate = coin.to_int() % 2
                inst.round += 1

        return inst.decided_value

    async def _broadcast_decide(self, ba_index: int, value: int):
        msg = Message("BA_DECIDE", self.party_id, {
            "ba_index": ba_index,
            "value": value,
        }, f"ba_{ba_index}_decide")
        await self.network.broadcast(self.party_id, msg)

    async def handle_vote(self, msg: Message):
        """Handle incoming BA_VOTE."""
        ba_index = msg.payload["ba_index"]
        r = msg.payload["round"]
        value = msg.payload["value"]
        voter = msg.sender

        inst = self._get_instance(ba_index)
        inst._ensure_round(r)
        inst.votes[r][value].add(voter)
        inst._vote_events[r].set()

    async def handle_decide(self, msg: Message):
        """Handle incoming BA_DECIDE — adopt decision if not yet decided."""
        ba_index = msg.payload["ba_index"]
        value = msg.payload["value"]

        inst = self._get_instance(ba_index)
        if not inst.decided:
            inst.decided = True
            inst.decided_value = value
            inst.decided_event.set()
