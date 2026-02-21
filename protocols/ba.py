"""Binary Agreement (BA) using beacon as common coin.

Supports string-based instance keys for namespacing (per-gate ACS, etc.).
"""

import asyncio
from sim.network import Network, Message
from sim.beacon import RandomnessBeacon


class BAInstance:
    def __init__(self, ba_key: str, party_id: int, n: int, f: int):
        self.ba_key = ba_key
        self.party_id = party_id
        self.n = n
        self.f = f
        self.estimate: int = -1
        self.round: int = 1
        self.votes: dict[int, dict[int, set[int]]] = {}
        self.decided = False
        self.decided_value: int = -1
        self.decided_event = asyncio.Event()
        self._vote_events: dict[int, asyncio.Event] = {}

    def _ensure_round(self, r: int):
        if r not in self.votes:
            self.votes[r] = {0: set(), 1: set()}
        if r not in self._vote_events:
            self._vote_events[r] = asyncio.Event()


class BAProtocol:
    """Manages multiple BA instances, keyed by string."""

    def __init__(self, party_id: int, n: int, f: int,
                 network: Network, beacon: RandomnessBeacon):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network
        self.beacon = beacon
        self._instances: dict[str, BAInstance] = {}
        self._beacon_counter = 0

    def _get_instance(self, ba_key: str) -> BAInstance:
        if ba_key not in self._instances:
            self._instances[ba_key] = BAInstance(ba_key, self.party_id, self.n, self.f)
        return self._instances[ba_key]

    async def run(self, ba_key: str, initial_estimate: int) -> int:
        """Run BA for given key. Returns decided value (0 or 1)."""
        inst = self._get_instance(ba_key)
        inst.estimate = initial_estimate

        while not inst.decided:
            r = inst.round
            inst._ensure_round(r)

            await self.network.broadcast(self.party_id, Message(
                "BA_VOTE", self.party_id, {
                    "ba_key": ba_key, "round": r, "value": inst.estimate,
                }, f"ba:{ba_key}:{r}"))

            inst.votes[r][inst.estimate].add(self.party_id)
            inst._vote_events[r].set()

            while not inst.decided:
                total = len(inst.votes[r][0]) + len(inst.votes[r][1])
                if total >= self.n - self.f:
                    break
                inst._vote_events[r].clear()
                await inst._vote_events[r].wait()

            if inst.decided:
                break

            count_0 = len(inst.votes[r][0])
            count_1 = len(inst.votes[r][1])

            if count_1 >= self.n - self.f:
                inst.decided = True
                inst.decided_value = 1
                inst.decided_event.set()
                await self._broadcast_decide(ba_key, 1)
            elif count_0 >= self.n - self.f:
                inst.decided = True
                inst.decided_value = 0
                inst.decided_event.set()
                await self._broadcast_decide(ba_key, 0)
            elif count_1 >= self.f + 1:
                inst.estimate = 1
                inst.round += 1
            elif count_0 >= self.f + 1:
                inst.estimate = 0
                inst.round += 1
            else:
                self._beacon_counter += 1
                coin = await self.beacon.request(
                    self._beacon_counter, self.party_id)
                inst.estimate = coin.to_int() % 2
                inst.round += 1

        return inst.decided_value

    async def _broadcast_decide(self, ba_key: str, value: int):
        await self.network.broadcast(self.party_id, Message(
            "BA_DECIDE", self.party_id, {
                "ba_key": ba_key, "value": value,
            }, f"ba:{ba_key}:decide"))

    async def handle_vote(self, msg: Message):
        ba_key = msg.payload["ba_key"]
        r = msg.payload["round"]
        value = msg.payload["value"]
        inst = self._get_instance(ba_key)
        inst._ensure_round(r)
        inst.votes[r][value].add(msg.sender)
        inst._vote_events[r].set()

    async def handle_decide(self, msg: Message):
        ba_key = msg.payload["ba_key"]
        value = msg.payload["value"]
        inst = self._get_instance(ba_key)
        if not inst.decided:
            inst.decided = True
            inst.decided_value = value
            inst.decided_event.set()
            for evt in inst._vote_events.values():
                evt.set()
