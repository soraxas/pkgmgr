import asyncio
import sys
import shutil

from io import StringIO
from typing import Callable, Coroutine, Tuple

from pkgmgr.helpers import ExitSignal, connect_stdin_stdout


from . import printer
from .printer import TERM_STDOUT


async def stream_output(
    stream: asyncio.StreamReader,
    suffix: str,
    print_func: Callable[..., Coroutine],
    additional_output=None,
    show_output: bool = True,
):
    """Reads output from a stream character-by-character, detects newlines, and request a prefix when so."""

    with printer.PKG_CTX(suffix):
        _char_buffer = bytearray()
        while not stream.at_eof():
            _byte = await stream.read(1)  # Read one byte at a time
            if not _byte:  # End of stream
                break

            _char_buffer.append(_byte[0])  # Append byte to buffer

            try:
                char = _char_buffer.decode()  # Try decoding the accumulated bytes
                _char_buffer.clear()  # Clear buffer on successful decode
            except UnicodeDecodeError:
                # Handle non-decodable characters
                continue

            if additional_output:
                additional_output.write(char)

            if show_output and char:
                # if we needs prefix now, print it.
                if printer.NEEDS_PREFIX:
                    await print_func("", end="")
                    printer.NEEDS_PREFIX = False

                sys.stdout.write(char)
                sys.stdout.flush()
                if char == "\n":
                    printer.NEEDS_PREFIX = True


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
    # check if the given command is valid / exists
    if not command:
        await printer.aERROR("Command is empty")
        raise ExitSignal()
    if not shutil.which(command[0]):
        await printer.aERROR(f"Command not found: {command[0]}")
        raise ExitSignal()
    # if sudo is used, check the actual command is valid
    if command[0] == "sudo" and len(command) > 1 and not shutil.which(command[1]):
        await printer.aERROR(f"Command not found: {command[1]}")
        raise ExitSignal()

    await printer.aINFO(f"{printer.BLUE}${printer.LIGHT_BLUE} {' '.join(command)}")
    process = await asyncio.create_subprocess_exec(
        *command,
        # Investigate if the following line (stdin) is needed
        # stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    tasks = []
    if process.stdout:
        tasks.append(
            asyncio.create_task(
                stream_output(
                    process.stdout,
                    ">&1",
                    TERM_STDOUT,
                    additional_output=stdout_capture,
                    show_output=show_output,
                )
            )
        )
    if process.stderr:
        tasks.append(
            asyncio.create_task(
                stream_output(
                    process.stderr,
                    ">&2",
                    TERM_STDOUT,
                    additional_output=stderr_capture,
                    show_output=show_output,
                )
            )
        )
    if process.stdin:
        input_task = asyncio.create_task(handle_input(process.stdin))
        tasks.append(input_task)

    # Wait for process to finish and ensure input task is properly cleaned up
    try:
        return_code = await process.wait()
    except asyncio.exceptions.CancelledError:
        # If the process is cancelled, we need to ensure that the input task is also cancelled
        for t in tasks:
            t.cancel()

        # ❗ Kill the subprocess to prevent lingering pipe cleanup
        process.kill()
        await process.wait()
        raise ExitSignal()

    finally:
        if process.stdin:
            # Once process is complete, cancel the input task and ensure clean-up
            input_task.cancel()

        await asyncio.wait(tasks)

    return return_code


async def command_runner_stream_with_output(
    command: list[str],
    show_output: bool = False,
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
