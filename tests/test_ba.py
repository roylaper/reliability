"""Tests for Binary Agreement with beacon coin."""

import asyncio
from core import rng
from sim.network import Network, UniformDelay, DropAll
from sim.beacon import RandomnessBeacon
from protocols.ba import BAProtocol


async def run_ba_test(inputs, omitting=None, seed=20):
    rng.set_seed(seed)
    n, f = 4, 1
    policy = DropAll(omitting) if omitting else None
    net = Network(n, delay_model=UniformDelay(0.0, 0.002), omission_policy=policy)
    beacon = RandomnessBeacon(threshold=f + 1)
    bas = [BAProtocol(i, n, f, net, beacon) for i in range(1, n + 1)]

    async def dispatch(idx):
        while True:
            for s in range(1, n + 1):
                if s == idx + 1:
                    continue
                msg = net.channels[(s, idx + 1)].try_receive()
                if msg:
                    h = {"BA_VOTE": bas[idx].handle_vote,
                         "BA_DECIDE": bas[idx].handle_decide}.get(msg.msg_type)
                    if h:
                        await h(msg)
            await asyncio.sleep(0.001)

    tasks = [asyncio.create_task(dispatch(i)) for i in range(n)]
    async def run_party(idx):
        try:
            return await asyncio.wait_for(
                bas[idx].run(ba_key="test", initial_estimate=inputs[idx]), timeout=5.0)
        except asyncio.TimeoutError:
            return None
    results = await asyncio.gather(*[run_party(i) for i in range(n)])
    for t in tasks:
        t.cancel()
    return results, beacon


def test_ba_unanimous_1():
    async def _test():
        results, _ = await run_ba_test([1, 1, 1, 1])
        for r in results:
            assert r == 1
    asyncio.run(_test())

def test_ba_unanimous_0():
    async def _test():
        results, _ = await run_ba_test([0, 0, 0, 0])
        for r in results:
            assert r == 0
    asyncio.run(_test())

def test_ba_majority_1():
    async def _test():
        results, _ = await run_ba_test([1, 1, 1, 0])
        for r in results:
            if r is not None:
                assert r == 1
    asyncio.run(_test())

def test_ba_agreement():
    async def _test():
        results, _ = await run_ba_test([1, 0, 1, 0], seed=25)
        decided = [r for r in results if r is not None]
        assert len(decided) >= 3
        assert all(v == decided[0] for v in decided)
    asyncio.run(_test())

def test_ba_with_omission():
    async def _test():
        results, _ = await run_ba_test([1, 1, 1, 0], omitting=4)
        for i in range(3):
            assert results[i] is not None
        assert all(results[i] == results[0] for i in range(3))
    asyncio.run(_test())
