from abc import ABC, abstractmethod

class ObjectBase:
    __event_handlers = {}

    def __init__(self):
        """
        Initialize the object.
        """
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
        pass 

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
        if event in self.__event_handlers.keys():
            for handler in self.__event_handlers[event]:
                handler(*args)