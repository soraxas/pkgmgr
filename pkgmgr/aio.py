import asyncio
import sys

from . import printer
from .printer import TERM_STDERR, TERM_STDOUT


async def stream_output(stream: asyncio.StreamReader, suffix: str, print_func):
    """Reads output from a stream character-by-character, detects newlines, and request a prefix when so."""

    with printer.PKG_CTX(suffix):
        while not stream.at_eof():
            char = await stream.read(1)
            char = char.decode()

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


async def handle_input(process: asyncio.subprocess.Process):
    """Reads user input and forwards it to the subprocess, detecting Enter key presses."""
    stdin_reader = await connect_stdin_stdout()
    while True:
        try:
            user_input = (await stdin_reader.readline()).decode().strip()
        except asyncio.CancelledError:
            break

        # print prefix, as user had entered something, i.e., newline
        printer.NEEDS_PREFIX = True

        process.stdin.write((user_input + "\n").encode())

        await process.stdin.drain()


async def command_runner_stream(command: str) -> int:
    """
    Runs a command given as a list of strings and prints stdout in green and stderr in red in real-time.
    Adds a prefix for new lines and detects user input.
    Returns the process return code.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_task = asyncio.create_task(stream_output(process.stdout, ">&1", TERM_STDOUT))
    stderr_task = asyncio.create_task(stream_output(process.stderr, ">&2", TERM_STDOUT))
    input_task = asyncio.create_task(handle_input(process))

    # Wait for process to finish and ensure input task is properly cleaned up
    return_code = await process.wait()

    # Once process is complete, cancel the input task and ensure clean-up
    input_task.cancel()

    await asyncio.wait(
        [stdout_task, stderr_task, input_task],  # return_when=asyncio.FIRST_COMPLETED
    )

    # print(f"Process exited with return code: {return_code}")
    return return_code


# if __name__ == "__main__":
#     asyncio.run(
#         command_runner_stream(["python", "-c", "input('here ')"])
#     )  # Example usage
