import os
import asyncio
import typer

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from pkgmgr.helpers import ExitSignal

from pkgmgr import _version, core, printer
from pkgmgr.printer import VERBOSITY_CTX, Verbosity, aINFO, INFO


app = typer.Typer(help="Package Manager CLI")


@dataclass
class CLIOptions:
    config_dir: Path
    paranoid: bool
    yes: bool
    force: bool
    sync: bool


def get_default_config_path() -> Path:
    return Path(
        os.path.join(
            os.environ.get("APPDATA")
            or os.environ.get("XDG_CONFIG_HOME")
            or os.path.join(os.environ["HOME"], ".config"),
            "pkgmgr",
        )
    )


@app.callback(invoke_without_command=True)
def runner(
    ctx: typer.Context,
    config_dir: Path = typer.Option(
        get_default_config_path(),
        "-c",
        "--config-dir",
        help="Set the path to your configuration directory",
    ),
    paranoid: bool = typer.Option(
        False,
        "--paranoid",
        help="Always prompt before making any changes to the system",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Never prompt before making any changes to the system",
    ),
    verbose: int = typer.Option(
        Verbosity.INFO.value,
        "-v",
        "--verbose",
        count=True,
        help="Increase verbosity level (e.g., -v, -vv, -vvv)",
    ),
    force: bool = typer.Option(
        False,
        "-f",
        "--force",
        help="Allow overwriting existing files",
    ),
    sync: bool = typer.Option(
        False,
        "-s",
        "--sync",
        help="Run synchronously instead of asynchronously (useful for debugging)",
    ),
    version: bool = typer.Option(
        None,
        "--version",
        callback=lambda v: (print(f"pkgmgr {_version.version}"), raise_exit()) if v else None,
        is_eager=True,
        help="Show the version and exit",
    ),
):
    # Store shared args for use in commands
    ctx.obj = CLIOptions(
        config_dir=config_dir,
        paranoid=paranoid,
        yes=yes,
        force=force,
        sync=sync,
    )
    if verbose >= 4:
        VERBOSITY_CTX.set(Verbosity.DEBUG)
    elif verbose >= 3:
        VERBOSITY_CTX.set(Verbosity.INFO)
    elif verbose >= 2:
        VERBOSITY_CTX.set(Verbosity.WARN)
    elif verbose >= 1:
        VERBOSITY_CTX.set(Verbosity.ERROR)

    # 👇 If no command is provided, print help and exit
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def raise_exit():
    raise typer.Exit()


def complete_targets(ctx: typer.Context, incomplete: str):
    """
    Get a list of all available targets for autocompletion.
    """
    global_params = ctx.parent.params
    config_dir = global_params.get("config_dir", None) or get_default_config_path()
    # silence all output during loading
    VERBOSITY_CTX.set(Verbosity.ERROR)

    async def inner():
        manager = await core.load_all(config_dir)
        return list(manager.keys())

    try:
        return asyncio.run(inner())
    except Exception:
        return []


@app.command()
def save(ctx: typer.Context):
    """Save current state"""
    args: CLIOptions = ctx.obj

    async def run():
        manager = await core.load_all(args.config_dir)
        with printer.PKG_CTX("save"):
            await aINFO("Executing save...")
            await core.cmd_save(args.config_dir, manager, args)
            await aINFO("All done.")

    _run_async(run(), args.sync)


@app.command()
def apply(
    ctx: typer.Context,
    target: Optional[str] = typer.Argument(None, autocompletion=complete_targets),
):
    """Apply saved configuration"""
    args: CLIOptions = ctx.obj

    async def run():
        manager = await core.load_all(args.config_dir)
        with printer.PKG_CTX("apply"):
            await aINFO("Executing apply...")
            await core.cmd_apply(args, manager, target)
            await aINFO("All done.")

    _run_async(run(), args.sync)


@app.command()
def check(ctx: typer.Context):
    """Check current state"""
    args: CLIOptions = ctx.obj

    async def run():
        with printer.PKG_CTX("check"):
            await aINFO("Executing 'check' action...")
            await aINFO("All done.")

    _run_async(run(), args.sync)


@app.command()
def diff(
    ctx: typer.Context,
    target: Optional[str] = typer.Argument(None, autocompletion=complete_targets),
):
    """Show configuration difference"""
    args: CLIOptions = ctx.obj

    async def run():
        manager = await core.load_all(args.config_dir)
        with printer.PKG_CTX("diff"):
            await aINFO("Executing diff...")
            await core.cmd_diff(args, manager, target)
            await aINFO("All done.")

    _run_async(run(), args.sync)


def _run_async(coro, sync=False):
    try:
        if sync:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(coro)
        else:
            asyncio.run(coro)
    except (KeyboardInterrupt, ExitSignal):
        INFO("Exiting...")
        raise typer.Exit(1)


def main():
    app()


if __name__ == "__main__":
    app()
