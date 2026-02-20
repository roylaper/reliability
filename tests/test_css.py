"""Tests for Complete Secret Sharing protocol."""

import sys
sys.path.insert(0, '..')

import asyncio
import pytest
from field import FieldElement
from polynomial import Polynomial
from network import Network
from css import CSSProtocol


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def run_css_test(n, f, secret_val, omitting=None):
    """Helper: run CSS share+recover with n parties."""
    net = Network(n)
    if omitting:
        net.set_omission(omitting)

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

    # Party 1 deals
    await css[0].share(secret, 'test')

    # Wait for acceptance (with timeout for omitting parties)
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
        # Verify shares reconstruct correctly
        pts = [(FieldElement(c.party_id), c.get_share('test')) for c in css]
        recovered = Polynomial.interpolate_at_zero(pts[:2])
        assert recovered == 42
    asyncio.run(_test())


def test_css_share_with_omission():
    async def _test():
        css, accepted = await run_css_test(4, 1, 42, omitting=4)
        # At least n-f=3 should accept
        assert len(accepted) >= 3
        assert 4 not in accepted
        # Reconstruct from honest parties
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
            assert recovered == secret, f"Failed for secret={secret}"
    asyncio.run(_test())
