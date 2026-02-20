"""Tests for Bracha Reliable Broadcast."""

import asyncio
from core import rng
from sim.network import Network, UniformDelay, DropAll
from protocols.rbc import RBCProtocol


async def run_rbc_test(sender_id, payload, omitting=None):
    n, f = 4, 1
    policy = DropAll(omitting) if omitting else None
    net = Network(n, delay_model=UniformDelay(0.0, 0.002), omission_policy=policy)
    rbcs = [RBCProtocol(i, n, f, net) for i in range(1, n + 1)]

    async def dispatch(idx):
        while True:
            for s in range(1, n + 1):
                if s == idx + 1:
                    continue
                ch = net.channels[(s, idx + 1)]
                msg = ch.try_receive()
                if msg:
                    h = {"RBC_INIT": rbcs[idx].handle_init,
                         "RBC_ECHO": rbcs[idx].handle_echo,
                         "RBC_READY": rbcs[idx].handle_ready}.get(msg.msg_type)
                    if h:
                        await h(msg)
            await asyncio.sleep(0.001)

    tasks = [asyncio.create_task(dispatch(i)) for i in range(n)]
    await rbcs[sender_id - 1].broadcast("test_tag", payload)
    delivered = {}
    for i in range(n):
        try:
            val = await asyncio.wait_for(
                rbcs[i].wait_deliver(sender_id, "test_tag"), timeout=3.0)
            delivered[i + 1] = val
        except asyncio.TimeoutError:
            delivered[i + 1] = None
    for t in tasks:
        t.cancel()
    return delivered


def test_rbc_all_honest():
    async def _test():
        rng.set_seed(10)
        d = await run_rbc_test(1, {"msg": "hello"})
        for pid in range(1, 5):
            assert d[pid] == {"msg": "hello"}
    asyncio.run(_test())

def test_rbc_sender_omits():
    async def _test():
        rng.set_seed(11)
        d = await run_rbc_test(1, {"msg": "hello"}, omitting=1)
        for pid in range(2, 5):
            assert d[pid] is None
    asyncio.run(_test())

def test_rbc_non_sender_omits():
    async def _test():
        rng.set_seed(12)
        d = await run_rbc_test(1, {"msg": "hello"}, omitting=4)
        for pid in range(1, 4):
            assert d[pid] == {"msg": "hello"}
        assert d[4] is None
    asyncio.run(_test())

def test_rbc_agreement():
    async def _test():
        rng.set_seed(13)
        d = await run_rbc_test(2, [1, 2, 3])
        values = [d[pid] for pid in range(1, 5) if d[pid] is not None]
        assert len(values) >= 3
        assert all(v == values[0] for v in values)
    asyncio.run(_test())
