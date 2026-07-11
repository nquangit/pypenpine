import asyncio

import pytest

from penpine.auth.gate import RefreshGate


async def test_exclusive_waits_for_inflight_to_drain():
    gate = RefreshGate()
    order = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def worker():
        async with gate.access():
            started.set()
            order.append("access-in")
            await release.wait()
        order.append("access-out")

    async def refresher():
        async with gate.exclusive():
            order.append("exclusive-body")

    w = asyncio.create_task(worker())
    await started.wait()
    r = asyncio.create_task(refresher())
    await asyncio.sleep(0.02)
    assert "exclusive-body" not in order
    release.set()
    await asyncio.gather(w, r)
    assert order == ["access-in", "access-out", "exclusive-body"]


async def test_new_access_blocked_during_exclusive():
    gate = RefreshGate()
    order = []
    in_exclusive = asyncio.Event()
    finish_exclusive = asyncio.Event()

    async def refresher():
        async with gate.exclusive():
            in_exclusive.set()
            order.append("exclusive-in")
            await finish_exclusive.wait()
        order.append("exclusive-out")

    async def worker():
        async with gate.access():
            order.append("access-body")

    r = asyncio.create_task(refresher())
    await in_exclusive.wait()
    w = asyncio.create_task(worker())
    await asyncio.sleep(0.02)
    assert "access-body" not in order
    finish_exclusive.set()
    await asyncio.gather(r, w)
    assert order == ["exclusive-in", "exclusive-out", "access-body"]


async def test_two_exclusives_serialize():
    gate = RefreshGate()
    order = []

    async def refresher(tag):
        async with gate.exclusive():
            order.append(f"{tag}-in")
            await asyncio.sleep(0.01)
            order.append(f"{tag}-out")

    await asyncio.gather(refresher("a"), refresher("b"))
    assert order in (
        ["a-in", "a-out", "b-in", "b-out"],
        ["b-in", "b-out", "a-in", "a-out"],
    )


async def test_lease_releases_on_exception():
    gate = RefreshGate()
    with pytest.raises(ValueError):
        async with gate.access():
            raise ValueError("boom")
    async with gate.exclusive():
        pass
