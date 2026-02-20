"""Async communication layer for MPC parties with configurable delays and omission policies."""

import asyncio
import time
from dataclasses import dataclass
from collections import defaultdict

from core import rng


# --- Delay Models ---

class DelayModel:
    """Base class for message delay models."""
    def sample(self) -> float:
        return 0.0


class UniformDelay(DelayModel):
    def __init__(self, min_d: float = 0.0, max_d: float = 0.01):
        self.min_d = min_d
        self.max_d = max_d

    def sample(self) -> float:
        return rng.uniform(self.min_d, self.max_d)


class ExponentialDelay(DelayModel):
    def __init__(self, mean: float = 0.01):
        self.lambd = 1.0 / mean if mean > 0 else 100.0

    def sample(self) -> float:
        return rng.expovariate(self.lambd)


class FixedDelay(DelayModel):
    def __init__(self, delay: float = 0.0):
        self.delay = delay

    def sample(self) -> float:
        return self.delay


class AdversarialDelay(DelayModel):
    """Delay specific sender->receiver pairs more than others."""
    def __init__(self, slow_pairs: set[tuple[int, int]] = None,
                 slow_range: tuple[float, float] = (0.1, 0.5),
                 fast_range: tuple[float, float] = (0.0, 0.005)):
        self.slow_pairs = slow_pairs or set()
        self.slow_range = slow_range
        self.fast_range = fast_range
        self._current_sender = None
        self._current_receiver = None

    def set_context(self, sender: int, receiver: int):
        self._current_sender = sender
        self._current_receiver = receiver

    def sample(self) -> float:
        if (self._current_sender, self._current_receiver) in self.slow_pairs:
            return rng.uniform(*self.slow_range)
        return rng.uniform(*self.fast_range)


# --- Omission Policies ---

class OmissionPolicy:
    """Base class for omission fault policies."""
    def should_drop(self, sender: int, receiver: int, msg) -> bool:
        return False


class DropAll(OmissionPolicy):
    """Drop all messages to/from a party."""
    def __init__(self, party_id: int, direction: str = 'both'):
        self.party_id = party_id
        self.direction = direction

    def should_drop(self, sender, receiver, msg) -> bool:
        if self.direction in ('send', 'both') and sender == self.party_id:
            return True
        if self.direction in ('receive', 'both') and receiver == self.party_id:
            return True
        return False


class DropProb(OmissionPolicy):
    """Drop messages from a party with probability p."""
    def __init__(self, party_id: int, p: float = 0.5):
        self.party_id = party_id
        self.p = p

    def should_drop(self, sender, receiver, msg) -> bool:
        if sender == self.party_id:
            return rng.random() < self.p
        return False


class DropTypes(OmissionPolicy):
    """Drop only specific message types from a party."""
    def __init__(self, party_id: int, msg_types: set[str], p: float = 1.0):
        self.party_id = party_id
        self.msg_types = msg_types
        self.p = p

    def should_drop(self, sender, receiver, msg) -> bool:
        if sender == self.party_id and msg.msg_type in self.msg_types:
            return rng.random() < self.p
        return False


class SelectiveOmission(OmissionPolicy):
    """Party sends to some recipients but omits to others.

    Models the key adversarial behavior: a corrupt party selectively
    chooses which parties receive its messages.
    """
    def __init__(self, party_id: int, drop_to: set[int]):
        """
        party_id: the omitting party
        drop_to: set of party IDs that will NOT receive messages from party_id
        """
        self.party_id = party_id
        self.drop_to = drop_to

    def should_drop(self, sender, receiver, msg) -> bool:
        return sender == self.party_id and receiver in self.drop_to


class CompositeOmission(OmissionPolicy):
    """Combine multiple omission policies (drop if ANY policy says drop)."""
    def __init__(self, policies: list[OmissionPolicy]):
        self.policies = policies

    def should_drop(self, sender, receiver, msg) -> bool:
        return any(p.should_drop(sender, receiver, msg) for p in self.policies)


class BurstDrop(OmissionPolicy):
    """Drop messages from a party during time intervals."""
    def __init__(self, party_id: int, bursts: list[tuple[float, float]] = None):
        self.party_id = party_id
        self.bursts = bursts or []
        self._start_time = time.time()

    def should_drop(self, sender, receiver, msg) -> bool:
        if sender != self.party_id:
            return False
        elapsed = time.time() - self._start_time
        return any(t0 <= elapsed <= t1 for t0, t1 in self.bursts)


# --- Messages and Metrics ---

@dataclass
class Message:
    """Tagged message with protocol identifier."""
    msg_type: str
    sender: int
    payload: dict
    session_id: str = ""


class NetworkMetrics:
    """Track communication metrics including per-type counts."""

    def __init__(self):
        self.messages_sent = 0
        self.messages_dropped = 0
        self.by_type: dict[str, int] = defaultdict(int)
        self.start_time = None

    def start(self):
        self.start_time = time.time()

    @property
    def elapsed(self):
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time


# --- Channel and Network ---

class MessageChannel:
    """Unidirectional async channel between two parties."""

    def __init__(self, sender_id: int, receiver_id: int):
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.queue: asyncio.Queue = asyncio.Queue()

    async def send(self, message: Message, delay: float):
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

    def __init__(self, n: int, delay_model: DelayModel | None = None,
                 omission_policy: OmissionPolicy | None = None):
        self.n = n
        self.delay_model = delay_model or UniformDelay(0.0, 0.01)
        self.omission_policy = omission_policy
        self.channels: dict[tuple[int, int], MessageChannel] = {}
        self.metrics = NetworkMetrics()

        for i in range(1, n + 1):
            for j in range(1, n + 1):
                if i != j:
                    self.channels[(i, j)] = MessageChannel(i, j)

    async def send(self, sender: int, receiver: int, msg: Message):
        self.metrics.messages_sent += 1
        self.metrics.by_type[msg.msg_type] += 1

        # Check omission policy
        if self.omission_policy and self.omission_policy.should_drop(sender, receiver, msg):
            self.metrics.messages_dropped += 1
            return

        # Compute delay
        if isinstance(self.delay_model, AdversarialDelay):
            self.delay_model.set_context(sender, receiver)
        delay = self.delay_model.sample()

        await self.channels[(sender, receiver)].send(msg, delay)

    async def broadcast(self, sender: int, msg: Message):
        tasks = []
        for j in range(1, self.n + 1):
            if j != sender:
                tasks.append(self.send(sender, j, msg))
        await asyncio.gather(*tasks)

    def set_omission(self, party_id: int, direction: str = 'both'):
        """Convenience: set a DropAll omission policy for a party."""
        self.omission_policy = DropAll(party_id, direction)

    def get_incoming_channels(self, party_id: int) -> list[MessageChannel]:
        return [
            self.channels[(s, party_id)]
            for s in range(1, self.n + 1)
            if s != party_id
        ]
