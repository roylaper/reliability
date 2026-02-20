"""Tests for Binary Agreement with beacon coin."""

import sys
sys.path.insert(0, '..')

import asyncio
import rng
from network import Network, UniformDelay, DropAll
from beacon import RandomnessBeacon
from ba import BAProtocol


async def run_ba_test(inputs, omitting=None, seed=20):
    """Helper: run BA with 4 parties, return decided values."""
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
                ch = net.channels[(s, idx + 1)]
                msg = ch.try_receive()
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
                bas[idx].run(ba_index=0, initial_estimate=inputs[idx]),
                timeout=5.0)
        except asyncio.TimeoutError:
            return None

    results = await asyncio.gather(*[run_party(i) for i in range(n)])
    for t in tasks:
        t.cancel()
    return results, beacon


def test_ba_unanimous_1():
    """All parties input 1 → decide 1."""
    async def _test():
        results, beacon = await run_ba_test([1, 1, 1, 1])
        for i, r in enumerate(results):
            assert r == 1, f"P{i+1} decided {r}, expected 1"
    asyncio.run(_test())


def test_ba_unanimous_0():
    """All parties input 0 → decide 0."""
    async def _test():
        results, beacon = await run_ba_test([0, 0, 0, 0])
        for i, r in enumerate(results):
            assert r == 0, f"P{i+1} decided {r}, expected 0"
    asyncio.run(_test())


def test_ba_majority_1():
    """3 parties input 1, 1 inputs 0 → decide 1."""
    async def _test():
        results, beacon = await run_ba_test([1, 1, 1, 0])
        for i, r in enumerate(results):
            if r is not None:
                assert r == 1, f"P{i+1} decided {r}, expected 1"
    asyncio.run(_test())


def test_ba_agreement():
    """All honest parties decide same value regardless of inputs."""
    async def _test():
        results, _ = await run_ba_test([1, 0, 1, 0], seed=25)
        decided = [r for r in results if r is not None]
        assert len(decided) >= 3
        assert all(v == decided[0] for v in decided), \
            f"Agreement violated: {results}"
    asyncio.run(_test())


def test_ba_with_omission():
    """Party 4 omits. 3 honest parties should still decide."""
    async def _test():
        results, _ = await run_ba_test([1, 1, 1, 0], omitting=4)
        for i in range(3):
            assert results[i] is not None, f"P{i+1} didn't decide"
        decided = [r for r in results[:3]]
        assert all(v == decided[0] for v in decided)
    asyncio.run(_test())
