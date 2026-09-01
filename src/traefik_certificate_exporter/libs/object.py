from abc import abstractmethod
from collections.abc import Callable
from typing import Any


class ObjectBase:
    # Per-instance, and it must stay that way. As a class attribute this dict was shared
    # by every ObjectBase ever constructed -- `on()` mutates it in place and so never
    # created an instance attribute -- which meant emitting an event on one exporter also
    # ran every other exporter's handlers, and the registry grew without bound.
    __event_handlers: dict[str, list[Callable[..., Any]]]

    def __init__(self):
        """
        Initialize the object.
        """
        self.__event_handlers = {}
        self.on("progress", self._handle_on_progress)

    def on(self, event, handler):
        """
        Add a handler for the event.

        @param event - The event to add a handler for
        @param handler - The handler to add
        """
        if event in self.__event_handlers:
            self.__event_handlers[event].append(handler)
        else:
            self.__event_handlers[event] = [handler]

    @abstractmethod
    def _handle_on_progress(self, message):
        """
        Handle the progress of a task.

        Parameters:
            self: the object instance
            message: a message indicating the progress

        Returns:
            None
        """

    def _raise_on_progress(self, message):
        """
        Raise an event on progress.

        @param message - The message to raise
        """
        self._emit("progress", message)

    def _emit(self, event, *args):
        """
        Emit/Trigger an event.

        @param event - The event to emit
        @param args - The arguments to pass to the handler
        """
        if event in self.__event_handlers:
            for handler in self.__event_handlers[event]:
                handler(*args)
