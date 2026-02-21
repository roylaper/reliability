"""Tests for Agreement on Common Set (RBC + BA based)."""

import asyncio
from core import rng
from sim.network import Network, UniformDelay, DropAll
from sim.beacon import RandomnessBeacon
from protocols.rbc import RBCProtocol
from protocols.ba import BAProtocol
from protocols.acs import ACSProtocol


async def run_acs_test(accepted_per_party, omitting=None, seed=30):
    rng.set_seed(seed)
    n, f = 4, 1
    policy = DropAll(omitting) if omitting else None
    net = Network(n, delay_model=UniformDelay(0.0, 0.002), omission_policy=policy)
    beacon = RandomnessBeacon(threshold=f + 1)
    rbcs = [RBCProtocol(i, n, f, net) for i in range(1, n + 1)]
    bas = [BAProtocol(i, n, f, net, beacon) for i in range(1, n + 1)]
    acss = [ACSProtocol(i, n, f, net, beacon, rbcs[i - 1], bas[i - 1])
            for i in range(1, n + 1)]

    async def dispatch(idx):
        while True:
            for s in range(1, n + 1):
                if s == idx + 1:
                    continue
                msg = net.channels[(s, idx + 1)].try_receive()
                if msg:
                    handlers = {
                        "RBC_INIT": rbcs[idx].handle_init,
                        "RBC_ECHO": rbcs[idx].handle_echo,
                        "RBC_READY": rbcs[idx].handle_ready,
                        "BA_VOTE": bas[idx].handle_vote,
                        "BA_DECIDE": bas[idx].handle_decide,
                    }
                    h = handlers.get(msg.msg_type)
                    if h:
                        await h(msg)
            await asyncio.sleep(0.001)

    tasks = [asyncio.create_task(dispatch(i)) for i in range(n)]
    async def run_party(idx):
        try:
            return await asyncio.wait_for(
                acss[idx].run(accepted_per_party[idx]), timeout=10.0)
        except asyncio.TimeoutError:
            return None
    results = await asyncio.gather(*[run_party(i) for i in range(n)])
    for t in tasks:
        t.cancel()
    return results


def test_acs_all_honest():
    async def _test():
        results = await run_acs_test([{1,2,3,4}] * 4)
        for r in results:
            assert r is not None
            assert len(r) >= 3
    asyncio.run(_test())

def test_acs_one_omitter():
    async def _test():
        accepted = [{1,2,3}, {1,2,3}, {1,2,3}, {1,2,3,4}]
        results = await run_acs_test(accepted, omitting=4)
        for i in range(3):
            assert results[i] is not None
            assert len(results[i]) >= 3
            assert 4 not in results[i]
    asyncio.run(_test())

def test_acs_agreement():
    async def _test():
        results = await run_acs_test([{1,2,3,4}] * 4)
        honest = [r for r in results if r is not None]
        assert len(honest) >= 3
        assert all(r == honest[0] for r in honest)
    asyncio.run(_test())
