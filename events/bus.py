from collections.abc import Callable

from events.event import Event


class EventBus:
    def __init__(self) -> None:
        self.listeners: list[Callable[[Event], None]] = []

    def subscribe(self, listener: Callable[[Event], None]) -> None:
        self.listeners.append(listener)

    def emit(self, event: Event) -> None:
        for listener in self.listeners:
            listener(event)
