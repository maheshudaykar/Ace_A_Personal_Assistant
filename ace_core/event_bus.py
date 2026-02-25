"""Basic event bus for ACE Phase 0 - minimal pub/sub"""

from dataclasses import dataclass, field
from typing import Callable, Optional, Any
from enum import Enum
from datetime import datetime
import uuid
import logging

logger = logging.getLogger("ACE.EventBus")


class EventType(Enum):
    """Phase 0 event types"""
    SYSTEM_BOOT = "system.boot"
    SYSTEM_SHUTDOWN = "system.shutdown"
    TASK_RECEIVED = "task.received"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    STATE_CHANGED = "state.changed"
    LOG_MESSAGE = "log.message"


@dataclass
class Event:
    """Simple event structure"""
    event_type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    data: dict[str, Any] = field(default_factory=lambda: {})
    
    def __str__(self) -> str:
        return f"Event({self.event_type.value}, {self.event_id})"


class EventBus:
    """
    Phase 0 minimal event bus - simple pub/sub without async/priority.
    
    This is deliberately simplified for Phase 0.
    Phase 1+ will add async, priority queue, event replay, etc.
    """
    
    def __init__(self):
        self.subscribers: dict[EventType, list[Callable[["Event"], None]]] = {}
        self.event_history: list[Event] = []
        self.max_history = 1000
        logger.info("EventBus initialized")
    
    def subscribe(self, event_type: EventType, handler: Callable[["Event"], None]) -> None:
        """
        Subscribe to event type.
        
        Args:
            event_type: Event type to subscribe to
            handler: Callback function called with Event as argument
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)
        logger.debug(f"Subscriber registered for {event_type.value}")
    
    def publish(self, event: Event) -> None:
        """
        Publish event to all subscribers.
        
        Args:
            event: Event to publish
        """
        # Store in history
        self.event_history.append(event)
        if len(self.event_history) > self.max_history:
            self.event_history.pop(0)
        
        # Call subscribers
        if event.event_type in self.subscribers:
            for handler in self.subscribers[event.event_type]:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"Error in event handler: {e}")
        
        logger.debug(f"Event published: {event}")
    
    def publish_simple(self, event_type: EventType, data: Optional[dict[str, Any]] = None) -> None:
        """
        Convenience method to publish event with just type and data.
        
        Args:
            event_type: Type of event
            data: Optional event data
        """
        event = Event(event_type=event_type, data=data or {})
        self.publish(event)
    
    def get_history(self, event_type: Optional[EventType] = None, limit: int = 10) -> list[Event]:
        """
        Get event history.
        
        Args:
            event_type: Filter by event type (None = all)
            limit: Maximum number of events to return
        
        Returns:
            List of events
        """
        if event_type is None:
            return self.event_history[-limit:]
        return [e for e in self.event_history if e.event_type == event_type][-limit:]
    
    def clear_history(self):
        """Clear event history."""
        self.event_history.clear()
        logger.info("Event history cleared")


# Global event bus instance (Phase 0 simplified approach)
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create global event bus instance."""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus


def reset_event_bus():
    """Reset global event bus (for testing)."""
    global _global_event_bus
    _global_event_bus = EventBus()
