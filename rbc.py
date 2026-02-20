"""Bracha Reliable Broadcast (RBC) for omission failure model.

Per-instance protocol keyed by (sender, tag).
Thresholds for n=4, f=1: echo=n-f=3, ready_amplify=f+1=2, deliver=n-f=3.
"""

import asyncio
import json
from network import Network, Message


class RBCInstance:
    """State for a single RBC instance (one sender, one tag)."""

    def __init__(self, sender: int, tag: str, party_id: int, n: int, f: int):
        self.sender = sender
        self.tag = tag
        self.party_id = party_id
        self.n = n
        self.f = f

        self.echo_counts: dict[str, set[int]] = {}  # payload_key -> set of echoers
        self.ready_counts: dict[str, set[int]] = {}  # payload_key -> set of ready senders
        self.sent_echo = False
        self.sent_ready = False
        self.delivered = False
        self.delivered_value = None
        self.delivered_event = asyncio.Event()
        self._payload_cache: dict[str, object] = {}  # payload_key -> payload

    def _payload_key(self, payload) -> str:
        return json.dumps(payload, sort_keys=True)


class RBCProtocol:
    """Manages multiple RBC instances for a party."""

    def __init__(self, party_id: int, n: int, f: int, network: Network):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network
        self._instances: dict[tuple[int, str], RBCInstance] = {}

    def _get_instance(self, sender: int, tag: str) -> RBCInstance:
        key = (sender, tag)
        if key not in self._instances:
            self._instances[key] = RBCInstance(sender, tag, self.party_id, self.n, self.f)
        return self._instances[key]

    async def broadcast(self, tag: str, payload):
        """Initiate RBC as the sender. Broadcasts INIT to all."""
        msg = Message("RBC_INIT", self.party_id, {
            "tag": tag,
            "payload": payload,
        }, tag)
        await self.network.broadcast(self.party_id, msg)
        # Also process own INIT
        await self._on_init(self.party_id, tag, payload)

    async def handle_init(self, msg: Message):
        """Handle RBC_INIT from the designated sender."""
        sender = msg.sender
        tag = msg.payload["tag"]
        payload = msg.payload["payload"]
        await self._on_init(sender, tag, payload)

    async def _on_init(self, sender: int, tag: str, payload):
        """On receiving INIT: send ECHO if not already sent."""
        inst = self._get_instance(sender, tag)
        if inst.sent_echo:
            return
        inst.sent_echo = True
        echo_msg = Message("RBC_ECHO", self.party_id, {
            "sender": sender,
            "tag": tag,
            "payload": payload,
        }, tag)
        await self.network.broadcast(self.party_id, echo_msg)
        # Process own echo
        await self._on_echo(self.party_id, sender, tag, payload)

    async def handle_echo(self, msg: Message):
        """Handle RBC_ECHO."""
        echoer = msg.sender
        original_sender = msg.payload["sender"]
        tag = msg.payload["tag"]
        payload = msg.payload["payload"]
        await self._on_echo(echoer, original_sender, tag, payload)

    async def _on_echo(self, echoer: int, sender: int, tag: str, payload):
        inst = self._get_instance(sender, tag)
        pk = inst._payload_key(payload)
        inst._payload_cache[pk] = payload

        if pk not in inst.echo_counts:
            inst.echo_counts[pk] = set()
        inst.echo_counts[pk].add(echoer)

        # If n-f echoes for same payload → send READY (once)
        if len(inst.echo_counts[pk]) >= self.n - self.f and not inst.sent_ready:
            inst.sent_ready = True
            ready_msg = Message("RBC_READY", self.party_id, {
                "sender": sender,
                "tag": tag,
                "payload": payload,
            }, tag)
            await self.network.broadcast(self.party_id, ready_msg)
            await self._on_ready(self.party_id, sender, tag, payload)

    async def handle_ready(self, msg: Message):
        """Handle RBC_READY."""
        ready_from = msg.sender
        original_sender = msg.payload["sender"]
        tag = msg.payload["tag"]
        payload = msg.payload["payload"]
        await self._on_ready(ready_from, original_sender, tag, payload)

    async def _on_ready(self, ready_from: int, sender: int, tag: str, payload):
        inst = self._get_instance(sender, tag)
        pk = inst._payload_key(payload)
        inst._payload_cache[pk] = payload

        if pk not in inst.ready_counts:
            inst.ready_counts[pk] = set()
        inst.ready_counts[pk].add(ready_from)

        # Amplification: if f+1 READYs and haven't sent READY → send READY
        if len(inst.ready_counts[pk]) >= self.f + 1 and not inst.sent_ready:
            inst.sent_ready = True
            ready_msg = Message("RBC_READY", self.party_id, {
                "sender": sender,
                "tag": tag,
                "payload": payload,
            }, tag)
            await self.network.broadcast(self.party_id, ready_msg)

        # Deliver: if n-f READYs → deliver
        if len(inst.ready_counts[pk]) >= self.n - self.f and not inst.delivered:
            inst.delivered = True
            inst.delivered_value = payload
            inst.delivered_event.set()

    async def wait_deliver(self, sender: int, tag: str, timeout: float = None):
        """Wait until the RBC instance for (sender, tag) delivers."""
        inst = self._get_instance(sender, tag)
        if timeout:
            await asyncio.wait_for(inst.delivered_event.wait(), timeout=timeout)
        else:
            await inst.delivered_event.wait()
        return inst.delivered_value

    def is_delivered(self, sender: int, tag: str) -> bool:
        key = (sender, tag)
        if key not in self._instances:
            return False
        return self._instances[key].delivered

    def get_delivered_value(self, sender: int, tag: str):
        return self._instances[(sender, tag)].delivered_value
