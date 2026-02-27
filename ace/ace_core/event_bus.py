"""Async event bus with priority queue, pub/sub, and dead letter tracking."""

from __future__ import annotations

import asyncio
import inspect
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional


Handler = Callable[["Event"], Any] | Callable[["Event"], Awaitable[Any]]


@dataclass(frozen=True)
class Event:
    """Event envelope for the bus."""

    event_type: str
    payload: Dict[str, Any]
    priority: int
    timestamp: str


class EventBus:
    """Priority-based async event bus with pub/sub and dead letter queue."""

    def __init__(self, max_workers: int = 4) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, Event]] = asyncio.PriorityQueue()
        self._subscribers: Dict[str, List[Handler]] = {}
        self._dead_letter: List[Dict[str, Any]] = []
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None
        self._counter = 0

    @property
    def dead_letter(self) -> List[Dict[str, Any]]:
        """Return dead letter records for failed handlers."""
        return list(self._dead_letter)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Subscribe a handler to an event type (use '*' for wildcard)."""
        self._subscribers.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: Dict[str, Any], priority: int) -> None:
        """Publish an event to the bus with priority 0-4."""
        if priority < 0 or priority > 4:
            raise ValueError("priority must be between 0 and 4")
        timestamp = datetime.now(timezone.utc).isoformat()
        event = Event(event_type=event_type, payload=payload, priority=priority, timestamp=timestamp)
        self._counter += 1
        await self._queue.put((priority, self._counter, event))

    async def start(self) -> None:
        """Start the event bus processing loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the event bus processing loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._executor.shutdown(wait=False)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                _, _, event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            await self._handle_event(event)
            self._queue.task_done()

    async def _handle_event(self, event: Event) -> None:
        handlers = self._subscribers.get(event.event_type, []) + self._subscribers.get("*", [])
        if not handlers:
            return
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(self._executor, handler, event)
            except Exception as exc:  # noqa: BLE001
                self._dead_letter.append(
                    {
                        "event_type": event.event_type,
                        "timestamp": event.timestamp,
                        "handler": getattr(handler, "__name__", "handler"),
                        "error": str(exc),
                    }
                )
