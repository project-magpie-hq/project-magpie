from collections.abc import Awaitable

import asyncio


def run_async_task[T](awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)
