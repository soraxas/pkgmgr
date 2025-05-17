import re
import sys
import asyncio

from enum import Enum
from contextvars import ContextVar

from .helpers import ExitSignal, UserSelectOption, async_input_non_blocking, T


PRINT_LOCK = asyncio.Lock()


GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[33m"
PINK = "\033[95m"
CYAN = "\033[96m"
GREY = "\033[90m"
BROWN = "\033[0;33m"
BLUE = "\033[0;34m"
PURPLE = "\033[0;35m"
LIGHT_BLUE = "\033[0;36m"
LIGHT_GRAY = "\033[0;37m"
END = "\033[0m"
NORMAL = END
UNDERLINE = "\033[4m"
BOLD = "\033[1m"

NEEDS_PREFIX = True


class PackageContext:
    """
    A context manager for package management.
    It sets the current package context and resets it when exiting the context.
    """

    def __init__(self):
        self.current_pkg: ContextVar = ContextVar("current_pkg", default=None)
        self.current_pkg_tokens = []

        # self.current_pkg: Optional[str] = None
        # self.stack_depth: int = 0

    def __call__(self, pkg_name: str):
        prefix = self.current_pkg.get()
        if prefix is not None:
            prefix = f"{prefix}:{pkg_name}"
        else:
            prefix = pkg_name
        self.current_pkg.set(prefix)

        return self

    def __enter__(self):
        # self.stack_depth += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # self.stack_depth -= 1
        prefix = self.current_pkg.get()
        if prefix is not None:
            prefix = prefix.split(":")
            if len(prefix) > 1:
                self.current_pkg.set(":".join(prefix[:-1]))
            else:
                self.current_pkg.set(None)


class Verbosity(Enum):
    """
    Enum for verbosity levels.
    """

    SILENT = 0
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4


PKG_CTX = PackageContext()
VERBOSITY_CTX = ContextVar("verbosity", default=Verbosity.INFO)


def print_prefix(**kw):
    """
    Assumes the print lock is already acquired.
    """
    global NEEDS_PREFIX

    pkg = PKG_CTX.current_pkg.get()
    pkg_txt = f"{BROWN}[{pkg}] " if pkg else ""
    print(f"{GREY}:: {pkg_txt}", **kw, end="")
    sys.stdout.flush()
    NEEDS_PREFIX = False


async def amy_print(*args, **kwargs):
    async with PRINT_LOCK:
        my_print(*args, **kwargs)


def my_print(text: str, color: str, end="\n", msg_level: Verbosity = Verbosity.INFO, **kw):
    if VERBOSITY_CTX.get().value < msg_level.value:
        return
    global NEEDS_PREFIX
    if NEEDS_PREFIX:
        print_prefix()
    print(f"{color}{text}{END}", **kw, end=end)
    NEEDS_PREFIX = True


async def TERM_STDOUT(text: str, **kw):
    await amy_print(text, NORMAL, **kw)


async def TERM_STDERR(text: str, **kw):
    await amy_print(text, PINK, **kw, file=sys.stderr)


async def aINFO(text: str, color=CYAN):
    await amy_print(text, color, msg_level=Verbosity.INFO)


def INFO(text: str, color=CYAN):
    my_print(text, color, msg_level=Verbosity.INFO)


async def aWARN(text: str, color=PINK):
    await amy_print(text, color, msg_level=Verbosity.WARN)


async def aDEBUG(text: str, color=GREY):
    await amy_print(text, color, msg_level=Verbosity.DEBUG)


def WARN(text: str, color=PINK):
    my_print(text, color, msg_level=Verbosity.WARN)


async def aERROR(text: str):
    await amy_print(text, RED, file=sys.stderr, msg_level=Verbosity.ERROR)


async def aERROR_EXIT(*args, **kw):
    await aERROR(*args, **kw)
    raise ExitSignal()


async def parse_indices(index_str: str, max_value: int, min_value: int = 1) -> list[int]:
    """
    Parse a string of indices into a list of integers.
    The indices can be a single number, a range, or a comma-separated list.
    Examples:
    - "1" -> [1]
    - "1-3" -> [1, 2, 3]
    - "1,2,3 5" -> [1, 2, 3, 5]
    - "1-3,5" -> [1, 2, 3, 5]
    """
    if max_value < min_value:
        raise ValueError("max_value must be greater than or equal to min_value")

    result = set()
    tokens = re.split(r"[,\s]+", index_str.strip())

    for token in tokens:
        if "-" in token:
            try:
                start, end = map(int, token.split("-", 1))
                if start > end:
                    await aERROR(f"Invalid range: '{token}' (start > end)")
                for i in range(start, end + 1):
                    if i < min_value or i > max_value:
                        await aERROR(f"{i} is out of range ({min_value}-{max_value})")
                    result.add(i)
            except ValueError:
                await aERROR(f"Invalid range format: '{token}'")
        elif token:
            try:
                i = int(token)
                if i < min_value or i > max_value:
                    await aERROR(f"{i} is out of range ({min_value}-{max_value})")
                result.add(i)
            except ValueError:
                await aERROR(f"Invalid number: '{token}'")

    return sorted(result)


async def ASK_USER(question: str, options: list[UserSelectOption[T]]) -> list[UserSelectOption[T]]:
    global NEEDS_PREFIX

    while True:
        # print the options
        if len(options) == 1:
            await options[0].print("")
        else:
            max_width = len(str(len(options)))
            for index, option in enumerate(options):
                await option.print(f"{index + 1:{max_width}d} ")

        if True:
            option_str = ""
            if len(options) > 1:
                option_str = f"/1-{len(options)}"
            async with PRINT_LOCK:
                print_prefix()
                try:
                    answer = (
                        await async_input_non_blocking(
                            f"{PURPLE}{BOLD}> {UNDERLINE}{question}{END} {PURPLE}(y/n{option_str}){LIGHT_GRAY} "
                        )
                    ).lower()
                except:
                    # when error, we need to end the line
                    print()  # complete the newline
                    raise
                finally:
                    # always reset the prefix after user input
                    NEEDS_PREFIX = True

            if answer in ["y", "yes"]:
                return options
            elif answer in ["n", "no"]:
                return []
            if len(options) > 1:
                indices = await parse_indices(answer, len(options))
                if indices:
                    # select the options
                    options = [options[i - 1] for i in indices]
                    continue

            await aERROR(f"Invalid input, please enter 'y' or 'n'{END}")


# except KeyboardInterrupt:
#     print("\nOperation cancelled by user.")
#     return False
