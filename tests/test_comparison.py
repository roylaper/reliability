"""Tests for bit decomposition and comparison circuit."""

import sys
sys.path.insert(0, '..')

import asyncio
from field import FieldElement
from polynomial import Polynomial
from network import Network
from mpc_arithmetic import MPCArithmetic
from bit_decomposition import BitDecomposition, preprocess_random_bit_sharings
from comparison import ComparisonCircuit


def make_sharing(n, f, secret):
    poly = Polynomial.random(f, FieldElement(secret))
    return [poly.evaluate(FieldElement(i)) for i in range(1, n + 1)]


def reconstruct(shares):
    pts = [(FieldElement(i + 1), s) for i, s in enumerate(shares)]
    return Polynomial.interpolate_at_zero(pts[:2])


async def setup_mpc(n=4, f=1, num_random_bits=10):
    """Setup MPC infrastructure for tests."""
    net = Network(n)
    mpc = [MPCArithmetic(i, n, f, net) for i in range(1, n + 1)]
    active = {1, 2, 3}
    for m in mpc:
        m.set_active_set(active)

    rbs = preprocess_random_bit_sharings(n, f, num_random_bits)
    bd = [BitDecomposition(i, n, f, mpc[i - 1]) for i in range(1, n + 1)]
    cmp = [ComparisonCircuit(mpc[i - 1]) for i in range(1, n + 1)]
    for b in bd:
        b.load_random_bits(rbs)

    return net, mpc, bd, cmp


def start_dispatchers(net, mpc, n=4):
    """Start message dispatch tasks."""
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
                await asyncio.sleep(0)
            await asyncio.sleep(0.001)
    return [asyncio.create_task(dispatch(i)) for i in range(n)]


def test_bit_decomposition_13():
    """Decompose 13 = 01101 into shared bits."""
    async def _test():
        net, mpc, bd, _ = await setup_mpc(num_random_bits=5)
        shares = make_sharing(4, 1, 13)

        tasks = start_dispatchers(net, mpc)
        all_bits = await asyncio.gather(*[
            bd[i].decompose(shares[i], 5, 'bd') for i in range(4)
        ])
        for t in tasks:
            t.cancel()

        for b in range(5):
            val = reconstruct([all_bits[i][b] for i in range(4)])
            expected = (13 >> b) & 1
            assert val.to_int() == expected, f"Bit {b}: got {val.to_int()}, expected {expected}"
    asyncio.run(_test())


def test_bit_decomposition_0():
    async def _test():
        net, mpc, bd, _ = await setup_mpc(num_random_bits=5)
        shares = make_sharing(4, 1, 0)
        tasks = start_dispatchers(net, mpc)
        all_bits = await asyncio.gather(*[
            bd[i].decompose(shares[i], 5, 'bd') for i in range(4)
        ])
        for t in tasks:
            t.cancel()
        for b in range(5):
            val = reconstruct([all_bits[i][b] for i in range(4)])
            assert val.to_int() == 0
    asyncio.run(_test())


def test_bit_decomposition_31():
    async def _test():
        net, mpc, bd, _ = await setup_mpc(num_random_bits=5)
        shares = make_sharing(4, 1, 31)
        tasks = start_dispatchers(net, mpc)
        all_bits = await asyncio.gather(*[
            bd[i].decompose(shares[i], 5, 'bd') for i in range(4)
        ])
        for t in tasks:
            t.cancel()
        for b in range(5):
            val = reconstruct([all_bits[i][b] for i in range(4)])
            expected = (31 >> b) & 1
            assert val.to_int() == expected
    asyncio.run(_test())


def test_comparison_20_gt_13():
    async def _test():
        net, mpc, bd, cmp = await setup_mpc(num_random_bits=10)
        shares_a = make_sharing(4, 1, 20)
        shares_b = make_sharing(4, 1, 13)

        tasks = start_dispatchers(net, mpc)

        async def party_work(idx):
            bits_a = await bd[idx].decompose(shares_a[idx], 5, 'a')
            bits_b = await bd[idx].decompose(shares_b[idx], 5, 'b')
            return await cmp[idx].greater_than(
                list(reversed(bits_a)), list(reversed(bits_b)), 'cmp')

        results = await asyncio.gather(*[party_work(i) for i in range(4)])
        for t in tasks:
            t.cancel()

        val = reconstruct(results)
        assert val.to_int() == 1, f"20 > 13 should be 1, got {val.to_int()}"
    asyncio.run(_test())


def test_comparison_5_not_gt_20():
    async def _test():
        net, mpc, bd, cmp = await setup_mpc(num_random_bits=10)
        shares_a = make_sharing(4, 1, 5)
        shares_b = make_sharing(4, 1, 20)

        tasks = start_dispatchers(net, mpc)

        async def party_work(idx):
            bits_a = await bd[idx].decompose(shares_a[idx], 5, 'a')
            bits_b = await bd[idx].decompose(shares_b[idx], 5, 'b')
            return await cmp[idx].greater_than(
                list(reversed(bits_a)), list(reversed(bits_b)), 'cmp')

        results = await asyncio.gather(*[party_work(i) for i in range(4)])
        for t in tasks:
            t.cancel()

        val = reconstruct(results)
        assert val.to_int() == 0, f"5 > 20 should be 0, got {val.to_int()}"
    asyncio.run(_test())


def test_comparison_equal_is_not_gt():
    """Equal values: a > a should be 0."""
    async def _test():
        net, mpc, bd, cmp = await setup_mpc(num_random_bits=10)
        shares_a = make_sharing(4, 1, 15)
        shares_b = make_sharing(4, 1, 15)

        tasks = start_dispatchers(net, mpc)

        async def party_work(idx):
            bits_a = await bd[idx].decompose(shares_a[idx], 5, 'a')
            bits_b = await bd[idx].decompose(shares_b[idx], 5, 'b')
            return await cmp[idx].greater_than(
                list(reversed(bits_a)), list(reversed(bits_b)), 'cmp')

        results = await asyncio.gather(*[party_work(i) for i in range(4)])
        for t in tasks:
            t.cancel()

        val = reconstruct(results)
        assert val.to_int() == 0
    asyncio.run(_test())
