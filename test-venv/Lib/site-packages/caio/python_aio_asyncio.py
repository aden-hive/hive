from .asyncio_base import AsyncioContextBase
from .python_aio import Context, Operation


class AsyncioContext(AsyncioContextBase):
    OPERATION_CLASS = Operation
    CONTEXT_CLASS = Context

    def _destroy_context(self):
        self.context.close()
