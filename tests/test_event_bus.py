"""Unit tests for ace_core.event_bus module."""

from ace_core.event_bus import Event, EventType, EventBus, get_event_bus, reset_event_bus


class TestEventType:
    """Test EventType enum."""
    
    def test_event_types_exist(self):
        """Test all expected event types exist."""
        assert EventType.SYSTEM_BOOT
        assert EventType.TASK_RECEIVED
        assert EventType.TASK_STARTED
        assert EventType.TASK_COMPLETED
        assert EventType.TASK_FAILED
        assert EventType.STATE_CHANGED
        assert EventType.LOG_MESSAGE
        assert EventType.SYSTEM_SHUTDOWN


class TestEvent:
    """Test Event dataclass."""
    
    def test_event_creation(self):
        """Test event creation."""
        event = Event(
            event_type=EventType.SYSTEM_BOOT,
            data={"version": "0.1"}
        )
        assert event.event_type == EventType.SYSTEM_BOOT
        assert event.data == {"version": "0.1"}
        assert event.event_id is not None
        assert event.timestamp is not None
    
    def test_event_id_format(self):
        """Test event ID is shortened UUID."""
        event = Event(
            event_type=EventType.SYSTEM_BOOT,
            data={}
        )
        # event_id should be 8 chars (shortened UUID)
        assert len(event.event_id) == 8
    
    def test_event_defaults(self):
        """Test event default values."""
        event = Event(event_type=EventType.TASK_COMPLETED)
        assert event.data == {}
        assert event.event_id is not None
        assert event.timestamp is not None


class TestEventBus:
    """Test EventBus class."""
    
    def test_event_bus_creation(self):
        """Test EventBus instantiation."""
        bus = EventBus()
        assert bus.subscribers == {}
        assert len(bus.event_history) == 0
    
    def test_subscribe(self):
        """Test subscribing to events."""
        bus = EventBus()
        def callback(event: Event) -> None:
            return None
        
        bus.subscribe(EventType.SYSTEM_BOOT, callback)
        
        assert EventType.SYSTEM_BOOT in bus.subscribers
        assert callback in bus.subscribers[EventType.SYSTEM_BOOT]
    
    def test_subscribe_multiple_callbacks(self):
        """Test multiple callbacks for same event type."""
        bus = EventBus()
        def cb1(event: Event) -> None:
            return None

        def cb2(event: Event) -> None:
            return None
        
        bus.subscribe(EventType.SYSTEM_BOOT, cb1)
        bus.subscribe(EventType.SYSTEM_BOOT, cb2)
        
        assert len(bus.subscribers[EventType.SYSTEM_BOOT]) == 2
    
    def test_publish_adds_to_history(self):
        """Test publishing event adds to history."""
        bus = EventBus()
        event = Event(event_type=EventType.SYSTEM_BOOT, data={})
        
        bus.publish(event)
        
        assert len(bus.event_history) == 1
        assert bus.event_history[0] == event
    
    def test_publish_calls_subscribers(self):
        """Test publishing calls subscriber callbacks."""
        bus = EventBus()
        called: list[Event] = []
        
        def callback(event: Event) -> None:
            called.append(event)
        
        bus.subscribe(EventType.SYSTEM_BOOT, callback)
        event = Event(event_type=EventType.SYSTEM_BOOT, data={})
        bus.publish(event)
        
        assert len(called) == 1
        assert called[0] == event
    
    def test_publish_only_calls_matching_subscribers(self):
        """Test only matching event type subscribers are called."""
        bus = EventBus()
        boot_called: list[Event] = []
        shutdown_called: list[Event] = []
        
        def boot_callback(event: Event) -> None:
            boot_called.append(event)
        
        def shutdown_callback(event: Event) -> None:
            shutdown_called.append(event)
        
        bus.subscribe(EventType.SYSTEM_BOOT, boot_callback)
        bus.subscribe(EventType.SYSTEM_SHUTDOWN, shutdown_callback)
        
        event = Event(event_type=EventType.SYSTEM_BOOT, data={})
        bus.publish(event)
        
        assert len(boot_called) == 1
        assert len(shutdown_called) == 0
    
    def test_event_history_max_size(self):
        """Test event history respects max_history limit."""
        bus = EventBus()
        bus.max_history = 5
        
        # Publish 10 events
        for i in range(10):
            event = Event(
                event_type=EventType.LOG_MESSAGE,
                data={"msg": f"Event {i}"}
            )
            bus.publish(event)
        
        # Should only keep last 5
        assert len(bus.event_history) == 5
    
    def test_get_history_all(self):
        """Test getting all event history."""
        bus = EventBus()
        
        for _ in range(3):
            event = Event(event_type=EventType.LOG_MESSAGE, data={})
            bus.publish(event)
        
        history = bus.get_history()
        assert len(history) == 3
    
    def test_get_history_by_type(self):
        """Test getting history filtered by event type."""
        bus = EventBus()
        
        bus.publish(Event(event_type=EventType.SYSTEM_BOOT, data={}))
        bus.publish(Event(event_type=EventType.LOG_MESSAGE, data={}))
        bus.publish(Event(event_type=EventType.SYSTEM_BOOT, data={}))
        
        boot_events = bus.get_history(event_type=EventType.SYSTEM_BOOT)
        assert len(boot_events) == 2
        
        log_events = bus.get_history(event_type=EventType.LOG_MESSAGE)
        assert len(log_events) == 1
    
    def test_get_history_with_limit(self):
        """Test getting history with limit."""
        bus = EventBus()
        
        for _ in range(10):
            bus.publish(Event(event_type=EventType.LOG_MESSAGE, data={}))
        
        history = bus.get_history(limit=3)
        assert len(history) == 3
    
    def test_get_history_limit_and_type(self):
        """Test getting history with both type and limit filters."""
        bus = EventBus()
        
        for _ in range(5):
            bus.publish(Event(event_type=EventType.SYSTEM_BOOT, data={}))
            bus.publish(Event(event_type=EventType.LOG_MESSAGE, data={}))
        
        boot_events = bus.get_history(event_type=EventType.SYSTEM_BOOT, limit=2)
        assert len(boot_events) == 2


class TestEventBusSingleton:
    """Test singleton pattern for EventBus."""
    
    def test_get_event_bus_returns_same_instance(self):
        """Test get_event_bus returns same instance."""
        reset_event_bus()  # Reset first
        
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        
        assert bus1 is bus2
    
    def test_reset_event_bus(self):
        """Test resetting event bus."""
        bus1 = get_event_bus()
        bus1.publish(Event(event_type=EventType.SYSTEM_BOOT, data={}))
        
        assert len(bus1.event_history) == 1
        
        reset_event_bus()
        bus2 = get_event_bus()
        
        assert bus1 is not bus2
        assert len(bus2.event_history) == 0
    
    def test_published_events_persist(self):
        """Test events published to global bus persist."""
        reset_event_bus()
        
        bus = get_event_bus()
        event = Event(event_type=EventType.SYSTEM_BOOT, data={"v": "1"})
        bus.publish(event)
        
        # Get the same bus again
        bus2 = get_event_bus()
        history = bus2.get_history()
        
        assert len(history) == 1
        assert history[0].data["v"] == "1"
