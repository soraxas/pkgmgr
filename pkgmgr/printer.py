import sys
from typing import Optional


GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[33m"
PINK = "\033[95m"
CYAN = "\033[96m"
GREY = "\033[90m"
END = "\033[0m"
NORMAL = END


NEEDS_PREFIX = True


class PackageContext:
    """
    A context manager for package management.
    It sets the current package context and resets it when exiting the context.
    """

    def __init__(self):
        self.current_pkg: Optional[str] = None
        self.stack_depth: int = 0

    def __call__(self, pkg_name: str):
        self.current_pkg = pkg_name
        return self

    def __enter__(self):
        self.stack_depth += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stack_depth -= 1
        self.current_pkg = None


PKG_CTX = PackageContext()


def print_prefix(**kw):
    global NEEDS_PREFIX
    pkg_txt = f"{BLUE}[{PKG_CTX.current_pkg}] " if PKG_CTX.current_pkg else ""
    print(f"{GREY}{':' * PKG_CTX.stack_depth} {pkg_txt}", **kw, end="")
    sys.stdout.flush()
    NEEDS_PREFIX = False


def my_print(text: str, color: str, end="\n", **kw) -> None:
    global NEEDS_PREFIX
    if NEEDS_PREFIX:
        print_prefix()
    print(f"{color}{text}{END}", **kw, end=end)
    NEEDS_PREFIX = True


def TERM_STDOUT(text: str, **kw):
    my_print(text, NORMAL, **kw)


def TERM_STDERR(text: str, **kw) -> str:
    my_print(text, PINK, **kw, file=sys.stderr)


def INFO(text: str, color=CYAN) -> None:
    my_print(text, color)


def ERROR(text: str) -> None:
    my_print(text, RED, file=sys.stderr)


def ERROR_EXIT(*args, **kw):
    ERROR(*args, **kw)
    exit(1)


def ASK_USER(question: str) -> bool:
    """
    Ask the user a yes/no question and return the answer.
    """
    while True:
        answer = input(f"{GREY}> {CYAN}{question} (y/n){END} ").lower()
        if answer in ["y", "yes"]:
            return True
        elif answer in ["n", "no"]:
            return False
        else:
            ERROR(f"Invalid input, please enter 'y' or 'n'{END}")
