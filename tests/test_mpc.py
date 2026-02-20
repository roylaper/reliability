"""Tests for MPC arithmetic (addition and multiplication)."""

import asyncio
from core.field import FieldElement
from core.polynomial import Polynomial
from sim.network import Network, UniformDelay
from protocols.mpc_arithmetic import MPCArithmetic


def make_sharing(n, f, secret):
    poly = Polynomial.random(f, FieldElement(secret))
    return [poly.evaluate(FieldElement(i)) for i in range(1, n + 1)]

def reconstruct(shares, indices=None):
    if indices is None:
        indices = list(range(1, len(shares) + 1))
    pts = [(FieldElement(i), s) for i, s in zip(indices, shares)]
    return Polynomial.interpolate_at_zero(pts[:2])


async def run_mul_test(a_val, b_val):
    n, f = 4, 1
    net = Network(n, delay_model=UniformDelay(0.0, 0.002))
    mpc = [MPCArithmetic(i, n, f, net) for i in range(1, n + 1)]
    active = {1, 2, 3}
    for m in mpc:
        m.set_active_set(active)
    shares_a = make_sharing(n, f, a_val)
    shares_b = make_sharing(n, f, b_val)

    async def dispatch(idx):
        while True:
            for s in range(1, n + 1):
                if s == idx + 1:
                    continue
                ch = net.channels[(s, idx + 1)]
                msg = ch.try_receive()
                if msg:
                    if msg.msg_type == 'MUL_RESHARE':
                        await mpc[idx].handle_reshare(msg)
                    elif msg.msg_type == 'MPC_OPEN':
                        await mpc[idx].handle_open(msg)
            await asyncio.sleep(0.001)

    tasks = [asyncio.create_task(dispatch(i)) for i in range(n)]
    results = await asyncio.gather(*[
        mpc[i].multiply(shares_a[i], shares_b[i], 'mul_test') for i in range(n)])
    for t in tasks:
        t.cancel()
    product = reconstruct(results)
    return product.to_int()


def test_add_shares():
    n, f = 4, 1
    shares_a = make_sharing(n, f, 5)
    shares_b = make_sharing(n, f, 7)
    mpc = MPCArithmetic(1, n, f, None)
    result = [mpc.add(shares_a[i], shares_b[i]) for i in range(n)]
    assert reconstruct(result) == 12

def test_sub_shares():
    n, f = 4, 1
    shares_a = make_sharing(n, f, 20)
    shares_b = make_sharing(n, f, 7)
    mpc = MPCArithmetic(1, n, f, None)
    result = [mpc.sub(shares_a[i], shares_b[i]) for i in range(n)]
    assert reconstruct(result) == 13

def test_scalar_mul():
    n, f = 4, 1
    shares = make_sharing(n, f, 5)
    mpc = MPCArithmetic(1, n, f, None)
    result = [mpc.scalar_mul(FieldElement(3), shares[i]) for i in range(n)]
    assert reconstruct(result) == 15

def test_multiply_basic():
    asyncio.run((async_test := run_mul_test(5, 7))).__class__  # force run
    async def _t():
        assert await run_mul_test(5, 7) == 35
    asyncio.run(_t())

def test_multiply_by_zero():
    async def _t():
        assert await run_mul_test(0, 13) == 0
    asyncio.run(_t())

def test_multiply_by_one():
    async def _t():
        assert await run_mul_test(1, 25) == 25
    asyncio.run(_t())

def test_multiply_large():
    async def _t():
        assert await run_mul_test(31, 30) == 930
    asyncio.run(_t())

def test_open_value():
    async def _test():
        n, f = 4, 1
        net = Network(n, delay_model=UniformDelay(0.0, 0.002))
        mpc = [MPCArithmetic(i, n, f, net) for i in range(1, n + 1)]
        for m in mpc:
            m.set_active_set({1, 2, 3})
        shares = make_sharing(n, f, 42)

        async def dispatch(idx):
            while True:
                for s in range(1, n + 1):
                    if s == idx + 1:
                        continue
                    ch = net.channels[(s, idx + 1)]
                    msg = ch.try_receive()
                    if msg and msg.msg_type == 'MPC_OPEN':
                        await mpc[idx].handle_open(msg)
                await asyncio.sleep(0.001)

        tasks = [asyncio.create_task(dispatch(i)) for i in range(n)]
        results = await asyncio.gather(*[
            mpc[i].open_value(shares[i], 'open_test') for i in range(n)])
        for t in tasks:
            t.cancel()
        for r in results:
            assert r == 42
    asyncio.run(_test())
