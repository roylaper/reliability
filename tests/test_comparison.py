"""Tests for bit decomposition and comparison circuit."""

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
from circuits.bit_decomposition import BitDecomposition, preprocess_random_bit_sharings
from circuits.comparison import ComparisonCircuit


def make_sharing(n, f, secret):
    poly = Polynomial.random(f, FieldElement(secret))
    return [poly.evaluate(FieldElement(i)) for i in range(1, n + 1)]

def reconstruct(shares):
    pts = [(FieldElement(i + 1), s) for i, s in enumerate(shares)]
    return Polynomial.interpolate_at_zero(pts[:2])


async def setup_full_stack(n=4, f=1, num_random_bits=10):
    """Setup full MPC stack with bit decomposition and comparison."""
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

    rbs = preprocess_random_bit_sharings(n, f, num_random_bits)
    bd = [BitDecomposition(i, n, f, mpcs[i - 1]) for i in range(1, n + 1)]
    cmp = [ComparisonCircuit(mpcs[i - 1]) for i in range(1, n + 1)]
    for b in bd:
        b.load_random_bits(rbs)

    return net, rbcs, bas, csss, mpcs, bd, cmp


def start_dispatchers(net, rbcs, bas, csss, mpcs, n=4):
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
                msg = net.channels[(s, idx + 1)].try_receive()
                if msg and msg.msg_type in handlers:
                    await handlers[msg.msg_type](msg)
            await asyncio.sleep(0.001)
    return [asyncio.create_task(dispatch(i)) for i in range(n)]


def test_bit_decomposition_13():
    async def _test():
        net, rbcs, bas, csss, mpcs, bd, cmp = await setup_full_stack(num_random_bits=5)
        for m in mpcs:
            m.set_active_set({1, 2, 3})
        shares = make_sharing(4, 1, 13)
        tasks = start_dispatchers(net, rbcs, bas, csss, mpcs)
        all_bits = await asyncio.gather(*[
            bd[i].decompose(shares[i], 5, 'bd') for i in range(4)])
        for t in tasks:
            t.cancel()
        for b in range(5):
            val = reconstruct([all_bits[i][b] for i in range(4)])
            assert val.to_int() == (13 >> b) & 1
    asyncio.run(_test())

def test_bit_decomposition_0():
    async def _test():
        net, rbcs, bas, csss, mpcs, bd, cmp = await setup_full_stack(num_random_bits=5)
        for m in mpcs:
            m.set_active_set({1, 2, 3})
        shares = make_sharing(4, 1, 0)
        tasks = start_dispatchers(net, rbcs, bas, csss, mpcs)
        all_bits = await asyncio.gather(*[
            bd[i].decompose(shares[i], 5, 'bd') for i in range(4)])
        for t in tasks:
            t.cancel()
        for b in range(5):
            assert reconstruct([all_bits[i][b] for i in range(4)]).to_int() == 0
    asyncio.run(_test())

def test_bit_decomposition_31():
    async def _test():
        net, rbcs, bas, csss, mpcs, bd, cmp = await setup_full_stack(num_random_bits=5)
        for m in mpcs:
            m.set_active_set({1, 2, 3})
        shares = make_sharing(4, 1, 31)
        tasks = start_dispatchers(net, rbcs, bas, csss, mpcs)
        all_bits = await asyncio.gather(*[
            bd[i].decompose(shares[i], 5, 'bd') for i in range(4)])
        for t in tasks:
            t.cancel()
        for b in range(5):
            assert reconstruct([all_bits[i][b] for i in range(4)]).to_int() == (31 >> b) & 1
    asyncio.run(_test())

def test_comparison_20_gt_13():
    async def _test():
        net, rbcs, bas, csss, mpcs, bd, cmp = await setup_full_stack(num_random_bits=10)
        for m in mpcs:
            m.set_active_set({1, 2, 3})
        shares_a = make_sharing(4, 1, 20)
        shares_b = make_sharing(4, 1, 13)
        tasks = start_dispatchers(net, rbcs, bas, csss, mpcs)
        async def work(idx):
            bits_a = await bd[idx].decompose(shares_a[idx], 5, 'a')
            bits_b = await bd[idx].decompose(shares_b[idx], 5, 'b')
            return await cmp[idx].greater_than(
                list(reversed(bits_a)), list(reversed(bits_b)), 'cmp')
        results = await asyncio.gather(*[work(i) for i in range(4)])
        for t in tasks:
            t.cancel()
        assert reconstruct(results).to_int() == 1
    asyncio.run(_test())

def test_comparison_5_not_gt_20():
    async def _test():
        net, rbcs, bas, csss, mpcs, bd, cmp = await setup_full_stack(num_random_bits=10)
        for m in mpcs:
            m.set_active_set({1, 2, 3})
        shares_a = make_sharing(4, 1, 5)
        shares_b = make_sharing(4, 1, 20)
        tasks = start_dispatchers(net, rbcs, bas, csss, mpcs)
        async def work(idx):
            bits_a = await bd[idx].decompose(shares_a[idx], 5, 'a')
            bits_b = await bd[idx].decompose(shares_b[idx], 5, 'b')
            return await cmp[idx].greater_than(
                list(reversed(bits_a)), list(reversed(bits_b)), 'cmp')
        results = await asyncio.gather(*[work(i) for i in range(4)])
        for t in tasks:
            t.cancel()
        assert reconstruct(results).to_int() == 0
    asyncio.run(_test())

def test_comparison_equal_is_not_gt():
    async def _test():
        net, rbcs, bas, csss, mpcs, bd, cmp = await setup_full_stack(num_random_bits=10)
        for m in mpcs:
            m.set_active_set({1, 2, 3})
        shares_a = make_sharing(4, 1, 15)
        shares_b = make_sharing(4, 1, 15)
        tasks = start_dispatchers(net, rbcs, bas, csss, mpcs)
        async def work(idx):
            bits_a = await bd[idx].decompose(shares_a[idx], 5, 'a')
            bits_b = await bd[idx].decompose(shares_b[idx], 5, 'b')
            return await cmp[idx].greater_than(
                list(reversed(bits_a)), list(reversed(bits_b)), 'cmp')
        results = await asyncio.gather(*[work(i) for i in range(4)])
        for t in tasks:
            t.cancel()
        assert reconstruct(results).to_int() == 0
    asyncio.run(_test())
