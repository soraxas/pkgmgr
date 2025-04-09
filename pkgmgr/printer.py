import sys
import asyncio

from contextvars import ContextVar
from .helpers import ExitSignal


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
                self.current_pkg.set(prefix[-2])
            else:
                self.current_pkg.set(None)


PKG_CTX = PackageContext()


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


def my_print(text: str, color: str, end="\n", **kw):
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
    await amy_print(text, color)


def INFO(text: str, color=CYAN):
    my_print(text, color)


async def aWARN(text: str, color=PINK):
    await amy_print(text, color)


def WARN(text: str, color=PINK):
    my_print(text, color)


async def aERROR(text: str):
    await amy_print(text, RED, file=sys.stderr)


async def aERROR_EXIT(*args, **kw):
    await aERROR(*args, **kw)
    raise ExitSignal()


async def async_input(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


async def ASK_USER(question: str) -> bool:
    # try:
    global NEEDS_PREFIX

    while True:
        async with PRINT_LOCK:
            print_prefix()
            answer = (
                await async_input(
                    f"{PURPLE}{BOLD}> {UNDERLINE}{question}{END} {PURPLE}(y/n){LIGHT_BLUE} "
                )
            ).lower()
        NEEDS_PREFIX = True
        if answer in ["y", "yes"]:
            return True
        elif answer in ["n", "no"]:
            return False
        else:
            await aERROR(f"Invalid input, please enter 'y' or 'n'{END}")


# except KeyboardInterrupt:
#     print("\nOperation cancelled by user.")
#     return False
