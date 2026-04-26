from .asyncio_base import AsyncioContextBase
from .linux_aio import Context, Operation


class AsyncioContext(AsyncioContextBase):
    OPERATION_CLASS = Operation
    CONTEXT_CLASS = Context

    def _create_context(self, max_requests):
        context = super()._create_context(max_requests)
        self.loop.add_reader(context.fileno, self._on_read_event)
        return context

    def _on_done(self, future, result):
        """
        Allow to set result directly.
        Cause process_events running in the same thread
        """
        if future.done():
            return
        future.set_result(True)

    def _destroy_context(self):
        self.loop.remove_reader(self.context.fileno)

    def _on_read_event(self):
        self.context.poll()
        self.context.process_events()
