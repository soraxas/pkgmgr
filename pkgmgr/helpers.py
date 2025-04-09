import asyncio
from collections.abc import AsyncIterable
import sys


async def async_all(async_iterable: AsyncIterable[object]) -> bool:
    async for element in async_iterable:
        if not element:
            return False
    return True


class ExitSignal(Exception):
    pass


async def async_input_non_blocking(prompt="> "):
    """This is needed as asyncio does not support non-blocking input natively."""
    reader = await connect_stdin_stdout()
    print(prompt, end="", flush=True)
    return (await reader.readline()).decode().strip()


async def connect_stdin_stdout():
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    return reader
