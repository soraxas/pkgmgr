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

CURRENT_PKG_CTX: Optional[str] = None
NEEDS_PREFIX = True


def print_prefix(**kw):
    global CURRENT_PKG_CTX, NEEDS_PREFIX
    pkg_txt = f"{BLUE}[{CURRENT_PKG_CTX}] " if CURRENT_PKG_CTX else ""
    print(f"{GREY}::: {pkg_txt}", **kw, end="")
    NEEDS_PREFIX = False


def my_print(text: str, color: str, end="\n", **kw) -> None:
    global CURRENT_PKG_CTX, NEEDS_PREFIX
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
