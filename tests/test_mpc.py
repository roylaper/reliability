"""Tests for MPC arithmetic (addition and multiplication)."""

import asyncio
from core import rng
from core.field import FieldElement
from core.polynomial import Polynomial
from sim.network import Network, UniformDelay
from sim.beacon import RandomnessBeacon
from protocols.rbc import RBCProtocol
from protocols.ba import BAProtocol
from protocols.css import CSSProtocol
from protocols.acs import ACSProtocol
from protocols.mpc_arithmetic import MPCArithmetic


def make_sharing(n, f, secret):
    poly = Polynomial.random(f, FieldElement(secret))
    return [poly.evaluate(FieldElement(i)) for i in range(1, n + 1)]

def reconstruct(shares):
    pts = [(FieldElement(i + 1), s) for i, s in enumerate(shares)]
    return Polynomial.interpolate_at_zero(pts[:2])


def setup_mpc_stack(n=4, f=1):
    """Create full MPC stack for all parties (CSS+RBC+BA+ACS+MPC)."""
    rng.set_seed(42)
    net = Network(n, delay_model=UniformDelay(0.0, 0.002))
    beacon = RandomnessBeacon(threshold=f + 1)
    rbcs = [RBCProtocol(i, n, f, net) for i in range(1, n + 1)]
    bas = [BAProtocol(i, n, f, net, beacon) for i in range(1, n + 1)]
    csss = [CSSProtocol(i, n, f, net) for i in range(1, n + 1)]

    mpcs = []
    for i in range(1, n + 1):
        idx = i - 1
        def make_acs(idx=idx):
            return ACSProtocol(idx + 1, n, f, net, beacon, rbcs[idx], bas[idx])
        mpc = MPCArithmetic(i, n, f, net, css=csss[idx], rbc=rbcs[idx],
                            acs_factory=make_acs)
        mpcs.append(mpc)

    return net, beacon, rbcs, bas, csss, mpcs


def start_full_dispatchers(net, rbcs, bas, csss, mpcs, n=4):
    """Start dispatchers that handle ALL message types."""
    async def dispatch(idx):
        handlers = {
            "RBC_INIT": rbcs[idx].handle_init,
            "RBC_ECHO": rbcs[idx].handle_echo,
            "RBC_READY": rbcs[idx].handle_ready,
            "BA_VOTE": bas[idx].handle_vote,
            "BA_DECIDE": bas[idx].handle_decide,
            "CSS_SHARE": csss[idx].handle_share,
            "CSS_ECHO": csss[idx].handle_echo,
            "CSS_READY": csss[idx].handle_ready,
            "MPC_OPEN": mpcs[idx].handle_open,
        }
        while True:
            for s in range(1, n + 1):
                if s == idx + 1:
                    continue
                ch = net.channels[(s, idx + 1)]
                msg = ch.try_receive()
                if msg and msg.msg_type in handlers:
                    await handlers[msg.msg_type](msg)
            await asyncio.sleep(0.001)
    return [asyncio.create_task(dispatch(i)) for i in range(n)]


def test_add_shares():
    shares_a = make_sharing(4, 1, 5)
    shares_b = make_sharing(4, 1, 7)
    mpc = MPCArithmetic(1, 4, 1, None)
    result = [mpc.add(shares_a[i], shares_b[i]) for i in range(4)]
    assert reconstruct(result) == 12

def test_sub_shares():
    shares_a = make_sharing(4, 1, 20)
    shares_b = make_sharing(4, 1, 7)
    mpc = MPCArithmetic(1, 4, 1, None)
    result = [mpc.sub(shares_a[i], shares_b[i]) for i in range(4)]
    assert reconstruct(result) == 13

def test_scalar_mul():
    shares = make_sharing(4, 1, 5)
    mpc = MPCArithmetic(1, 4, 1, None)
    result = [mpc.scalar_mul(FieldElement(3), shares[i]) for i in range(4)]
    assert reconstruct(result) == 15

def test_multiply_basic():
    async def _test():
        net, beacon, rbcs, bas, csss, mpcs = setup_mpc_stack()
        active = {1, 2, 3}
        for m in mpcs:
            m.set_active_set(active)
        shares_a = make_sharing(4, 1, 5)
        shares_b = make_sharing(4, 1, 7)
        tasks = start_full_dispatchers(net, rbcs, bas, csss, mpcs)
        results = await asyncio.gather(*[
            mpcs[i].multiply(shares_a[i], shares_b[i], 'test_mul')
            for i in range(4)])
        for t in tasks:
            t.cancel()
        product = reconstruct(results)
        assert product == 35
    asyncio.run(_test())

def test_multiply_by_zero():
    async def _test():
        net, beacon, rbcs, bas, csss, mpcs = setup_mpc_stack()
        for m in mpcs:
            m.set_active_set({1, 2, 3})
        shares_a = make_sharing(4, 1, 0)
        shares_b = make_sharing(4, 1, 13)
        tasks = start_full_dispatchers(net, rbcs, bas, csss, mpcs)
        results = await asyncio.gather(*[
            mpcs[i].multiply(shares_a[i], shares_b[i], 'test_mul0')
            for i in range(4)])
        for t in tasks:
            t.cancel()
        assert reconstruct(results) == 0
    asyncio.run(_test())

def test_multiply_by_one():
    async def _test():
        net, beacon, rbcs, bas, csss, mpcs = setup_mpc_stack()
        for m in mpcs:
            m.set_active_set({1, 2, 3})
        shares_a = make_sharing(4, 1, 1)
        shares_b = make_sharing(4, 1, 25)
        tasks = start_full_dispatchers(net, rbcs, bas, csss, mpcs)
        results = await asyncio.gather(*[
            mpcs[i].multiply(shares_a[i], shares_b[i], 'test_mul1')
            for i in range(4)])
        for t in tasks:
            t.cancel()
        assert reconstruct(results) == 25
    asyncio.run(_test())

def test_multiply_large():
    async def _test():
        net, beacon, rbcs, bas, csss, mpcs = setup_mpc_stack()
        for m in mpcs:
            m.set_active_set({1, 2, 3})
        shares_a = make_sharing(4, 1, 31)
        shares_b = make_sharing(4, 1, 30)
        tasks = start_full_dispatchers(net, rbcs, bas, csss, mpcs)
        results = await asyncio.gather(*[
            mpcs[i].multiply(shares_a[i], shares_b[i], 'test_mull')
            for i in range(4)])
        for t in tasks:
            t.cancel()
        assert reconstruct(results) == 930
    asyncio.run(_test())

def test_open_value():
    async def _test():
        rng.set_seed(42)
        net = Network(4, delay_model=UniformDelay(0.0, 0.002))
        mpcs = [MPCArithmetic(i, 4, 1, net) for i in range(1, 5)]
        shares = make_sharing(4, 1, 42)

        async def dispatch(idx):
            while True:
                for s in range(1, 5):
                    if s == idx + 1:
                        continue
                    msg = net.channels[(s, idx + 1)].try_receive()
                    if msg and msg.msg_type == 'MPC_OPEN':
                        await mpcs[idx].handle_open(msg)
                await asyncio.sleep(0.001)

        tasks = [asyncio.create_task(dispatch(i)) for i in range(4)]
        results = await asyncio.gather(*[
            mpcs[i].open_value(shares[i], 'open_test') for i in range(4)])
        for t in tasks:
            t.cancel()
        for r in results:
            assert r == 42
    asyncio.run(_test())
