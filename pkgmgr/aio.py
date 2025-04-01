import asyncio
import sys
from io import StringIO
from typing import Optional, Tuple


from . import printer
from .printer import TERM_STDERR, TERM_STDOUT


async def stream_output(
    stream: asyncio.StreamReader, suffix: str, print_func, additional_output=None
):
    """Reads output from a stream character-by-character, detects newlines, and request a prefix when so."""

    with printer.PKG_CTX(suffix):
        while not stream.at_eof():
            char = (await stream.read(1)).decode()

            if additional_output:
                additional_output.write(char)

            if char:
                # if we needs prefix now, print it.
                if printer.NEEDS_PREFIX:
                    print_func(f"", end="")
                    printer.NEEDS_PREFIX = False

                sys.stdout.write(char)
                sys.stdout.flush()
                if char == "\n":
                    printer.NEEDS_PREFIX = True


async def connect_stdin_stdout():
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    return reader


async def handle_input(writer: asyncio.StreamWriter):
    """Reads user input and forwards it to the subprocess, detecting Enter key presses."""
    stdin_reader = await connect_stdin_stdout()
    while True:
        try:
            user_input = (await stdin_reader.readline()).decode().strip()
        except asyncio.CancelledError:
            break

        # print prefix, as user had entered something, i.e., newline
        printer.NEEDS_PREFIX = True

        writer.write((user_input + "\n").encode())

        await writer.drain()


async def command_runner_stream(
    command: list[str],
    show_output: bool = True,
    stdout_capture=None,
    stderr_capture=None,
) -> int:
    """
    Runs a command given as a list of strings and prints stdout in green and stderr in red in real-time.
    Adds a prefix for new lines and detects user input.
    Returns the process return code.
    """
    printer.INFO(f"{printer.BLUE}${printer.LIGHT_BLUE} {' '.join(command)}")
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    tasks = []
    if process.stdout:
        tasks.append(
            asyncio.create_task(
                stream_output(
                    process.stdout, ">&1", TERM_STDOUT, additional_output=stdout_capture
                )
            )
        )
    if process.stderr:
        tasks.append(
            asyncio.create_task(
                stream_output(
                    process.stderr, ">&2", TERM_STDOUT, additional_output=stderr_capture
                )
            )
        )
    if process.stdin:
        input_task = asyncio.create_task(handle_input(process.stdin))

    # Wait for process to finish and ensure input task is properly cleaned up
    return_code = await process.wait()

    if process.stdin:
        # Once process is complete, cancel the input task and ensure clean-up
        input_task.cancel()

    await asyncio.wait(tasks)

    return return_code


async def command_runner_stream_with_output(
    command: list[str],
    show_output: bool = True,
) -> Tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    ret_code = await command_runner_stream(
        command,
        show_output=show_output,
        stdout_capture=stdout,
        stderr_capture=stderr,
    )
    return ret_code, stdout.getvalue(), stderr.getvalue()
