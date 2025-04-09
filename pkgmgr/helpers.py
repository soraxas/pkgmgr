import asyncio
from collections.abc import AsyncIterable
import os
import re
import shlex
import sys


async def async_all(async_iterable: AsyncIterable[object]) -> bool:
    async for element in async_iterable:
        if not element:
            return False
    return True


class ExitSignal(Exception):
    pass


def santise_variable_name(var_str: str):
    """
    Sanitise a variable name by replacing non-alphanumeric characters with underscores.
    """
    return re.sub("\W|^(?=\d)", "_", var_str)


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


def smart_expand(token: str) -> str:
    if token.startswith(("~", "$HOME", "/")):
        return os.path.expandvars(os.path.expanduser(token))
    return token


def split_script_as_shell(script: str) -> list[str]:
    """
    Split a script into a list of commands.
    """
    return [smart_expand(s) for s in shlex.split(script)]
