"""Tests for Complete Secret Sharing protocol (with finalization)."""

import asyncio
from core import rng
from core.field import FieldElement
from core.polynomial import Polynomial
from sim.network import Network, UniformDelay, DropAll
from protocols.css import CSSProtocol, CSSStatus


async def run_css_test(n, f, secret_val, omitting=None, seed=50):
    rng.set_seed(seed)
    policy = DropAll(omitting) if omitting else None
    net = Network(n, delay_model=UniformDelay(0.0, 0.002), omission_policy=policy)
    css = [CSSProtocol(i, n, f, net) for i in range(1, n + 1)]
    secret = FieldElement(secret_val)

    async def dispatch(idx):
        c = css[idx]
        while True:
            for s in range(1, n + 1):
                if s == idx + 1:
                    continue
                ch = net.channels[(s, idx + 1)]
                msg = ch.try_receive()
                if msg:
                    handler = {
                        'CSS_SHARE': c.handle_share,
                        'CSS_ECHO': c.handle_echo,
                        'CSS_READY': c.handle_ready,
                        'CSS_RECOVER': c.handle_recover,
                    }.get(msg.msg_type)
                    if handler:
                        await handler(msg)
            await asyncio.sleep(0.001)

    tasks = [asyncio.create_task(dispatch(i)) for i in range(n)]
    await css[0].share(secret, 'test')
    accepted = []
    for c in css:
        try:
            await asyncio.wait_for(c.wait_accepted('test'), timeout=2.0)
            accepted.append(c.party_id)
        except asyncio.TimeoutError:
            pass
    for t in tasks:
        t.cancel()
    return css, accepted


def test_css_share_all_honest():
    async def _test():
        css, accepted = await run_css_test(4, 1, 42)
        assert len(accepted) == 4
        pts = [(FieldElement(c.party_id), c.get_share('test')) for c in css]
        recovered = Polynomial.interpolate_at_zero(pts[:2])
        assert recovered == 42
    asyncio.run(_test())

def test_css_share_with_omission():
    async def _test():
        css, accepted = await run_css_test(4, 1, 42, omitting=4)
        assert len(accepted) >= 3
        assert 4 not in accepted
        honest = [c for c in css if c.party_id != 4 and c.party_id in accepted]
        pts = [(FieldElement(c.party_id), c.get_share('test')) for c in honest[:2]]
        recovered = Polynomial.interpolate_at_zero(pts)
        assert recovered == 42
    asyncio.run(_test())

def test_css_different_secrets():
    async def _test():
        for secret in [0, 1, 15, 31]:
            css, accepted = await run_css_test(4, 1, secret)
            pts = [(FieldElement(c.party_id), c.get_share('test')) for c in css]
            recovered = Polynomial.interpolate_at_zero(pts[:2])
            assert recovered == secret
    asyncio.run(_test())

def test_css_finalization_status():
    async def _test():
        css, accepted = await run_css_test(4, 1, 42)
        for c in css:
            assert c.get_status('test') == CSSStatus.FINALIZED
            assert c.get_vid('test') is not None
    asyncio.run(_test())

def test_css_vid_agreement():
    async def _test():
        css, accepted = await run_css_test(4, 1, 42, seed=55)
        vids = [c.get_vid('test') for c in css if c.party_id in accepted]
        assert all(v is not None for v in vids)
    asyncio.run(_test())
