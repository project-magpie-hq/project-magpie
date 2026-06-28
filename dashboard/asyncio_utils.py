import asyncio
from collections.abc import Coroutine


def run_async_task[T](coro: Coroutine[None, None, T]) -> T:
    return asyncio.run(coro)
