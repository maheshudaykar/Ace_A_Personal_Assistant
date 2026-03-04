"""AgentBus: Structured publish/subscribe communication between agents."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

__all__ = ["AgentMessage", "AgentBus"]

logger = logging.getLogger(__name__)

_MESSAGE_HISTORY_LIMIT = 1000


@dataclass
class AgentMessage:
    """Structured inter-agent message."""

    sender: str
    recipient: str
    message_type: str  # request, response, event, error
    payload: Dict[str, Any]
    correlation_id: str
    timestamp: float = field(default_factory=lambda: time.time())


class AgentBus:
    """Thread-safe publish/subscribe message bus for agent communication."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: Dict[str, List[Callable[[AgentMessage], None]]] = {}
        self._history: deque[AgentMessage] = deque(maxlen=_MESSAGE_HISTORY_LIMIT)

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, agent_id: str, handler: Callable[[AgentMessage], None]) -> None:
        """Register *handler* to receive messages addressed to *agent_id*."""
        with self._lock:
            self._handlers.setdefault(agent_id, []).append(handler)
        logger.debug("AgentBus: %s subscribed", agent_id)

    def unsubscribe(self, agent_id: str, handler: Callable[[AgentMessage], None]) -> None:
        """Remove *handler* for *agent_id*."""
        with self._lock:
            handlers = self._handlers.get(agent_id, [])
            if handler in handlers:
                handlers.remove(handler)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, message: AgentMessage) -> None:
        """Dispatch *message* to all registered handlers for its recipient."""
        with self._lock:
            self._history.append(message)
            handlers = list(self._handlers.get(message.recipient, []))

        logger.debug(
            "AgentBus: %s → %s [%s] corr=%s",
            message.sender,
            message.recipient,
            message.message_type,
            message.correlation_id,
        )
        for handler in handlers:
            try:
                handler(message)
            except Exception:
                logger.exception(
                    "AgentBus: handler error for recipient=%s", message.recipient
                )

    def send(
        self,
        sender: str,
        recipient: str,
        message_type: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> AgentMessage:
        """Convenience wrapper: build and publish a message, return it."""
        msg = AgentMessage(
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            payload=payload,
            correlation_id=correlation_id or str(uuid.uuid4()),
        )
        self.publish(msg)
        return msg

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_history(self) -> List[AgentMessage]:
        """Return a snapshot of the bounded message history."""
        with self._lock:
            return list(self._history)

    def clear_history(self) -> None:
        """Clear message history (useful for testing)."""
        with self._lock:
            self._history.clear()
