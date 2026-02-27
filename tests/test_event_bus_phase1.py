"""Phase 1 tests for ace.ace_core.event_bus."""

from __future__ import annotations

import asyncio

import pytest

from ace.ace_core.event_bus import EventBus


@pytest.mark.asyncio
async def test_event_bus_dispatches() -> None:
    bus = EventBus()
    results = []

    def handler(event):
        results.append(event.payload["value"])

    bus.subscribe("test", handler)
    await bus.start()
    await bus.publish("test", {"value": 1}, priority=1)
    await asyncio.sleep(0.05)
    await bus.stop()

    assert results == [1]


@pytest.mark.asyncio
async def test_event_bus_dead_letter() -> None:
    bus = EventBus()

    def handler(_event):
        raise RuntimeError("boom")

    bus.subscribe("test", handler)
    await bus.start()
    await bus.publish("test", {"value": 1}, priority=1)
    await asyncio.sleep(0.05)
    await bus.stop()

    assert len(bus.dead_letter) == 1
