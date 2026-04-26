from .asyncio_base import AsyncioContextBase
from .thread_aio import Context, Operation


class AsyncioContext(AsyncioContextBase):
    MAX_REQUESTS_DEFAULT = 512
    OPERATION_CLASS = Operation
    CONTEXT_CLASS = Context
