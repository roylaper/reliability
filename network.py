"""Async communication layer for MPC parties with omission simulation."""

import asyncio
import random
import time
from dataclasses import dataclass, field as datafield


@dataclass
class Message:
    """Tagged message with protocol identifier."""
    msg_type: str
    sender: int
    payload: dict
    session_id: str = ""


class NetworkMetrics:
    """Track communication metrics."""

    def __init__(self):
        self.messages_sent = 0
        self.messages_dropped = 0
        self.start_time = None

    def start(self):
        self.start_time = time.time()

    @property
    def elapsed(self):
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time


class MessageChannel:
    """Unidirectional async channel between two parties."""

    def __init__(self, sender_id: int, receiver_id: int):
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.dropped = False
        self.delay_range = (0.0, 0.01)  # seconds

    async def send(self, message: Message, metrics: NetworkMetrics):
        metrics.messages_sent += 1
        if self.dropped:
            metrics.messages_dropped += 1
            return
        delay = random.uniform(*self.delay_range)
        if delay > 0:
            await asyncio.sleep(delay)
        await self.queue.put(message)

    async def receive(self):
        return await self.queue.get()

    def try_receive(self):
        try:
            return self.queue.get_nowait()
        except asyncio.QueueEmpty:
            return None


class Network:
    """Manages all channels between n parties."""

    def __init__(self, n: int):
        self.n = n
        self.channels: dict[tuple[int, int], MessageChannel] = {}
        self.metrics = NetworkMetrics()

        for i in range(1, n + 1):
            for j in range(1, n + 1):
                if i != j:
                    self.channels[(i, j)] = MessageChannel(i, j)

    async def send(self, sender: int, receiver: int, msg: Message):
        await self.channels[(sender, receiver)].send(msg, self.metrics)

    async def broadcast(self, sender: int, msg: Message):
        tasks = []
        for j in range(1, self.n + 1):
            if j != sender:
                tasks.append(self.send(sender, j, msg))
        await asyncio.gather(*tasks)

    def set_omission(self, party_id: int, direction: str = 'both'):
        """Simulate omission failure: drop messages to/from party_id."""
        for (s, r), ch in self.channels.items():
            if direction in ('send', 'both') and s == party_id:
                ch.dropped = True
            if direction in ('receive', 'both') and r == party_id:
                ch.dropped = True

    def get_incoming_channels(self, party_id: int) -> list[MessageChannel]:
        """Get all channels where party_id is the receiver."""
        return [
            self.channels[(s, party_id)]
            for s in range(1, self.n + 1)
            if s != party_id
        ]
