import os
import argparse
import asyncio
from pathlib import Path

from pkgmgr.helpers import ExitSignal


def main():
    from . import _version

    configpath = os.path.join(
        os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.environ["HOME"], ".config"),
        "pkgmgr",
    )

    parser = argparse.ArgumentParser(
        description="Package Manager",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version.version}")

    parser.add_argument(
        "-c",
        "--config-dir",
        type=Path,
        help="Set the path to your configuration directory",
        default=Path(configpath),
    )
    parser.add_argument(
        "--paranoid",
        action="store_true",
        help="Always prompt before making any changes to the system",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Never prompt before making any changes to the system",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress with additional detail",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Allow overwriting existing files",
    )
    parser.add_argument(
        "-s",
        "--sync",
        action="store_true",
        help="Run synchronously instead of asynchronously, whcih is useful for debugging",
    )

    parser.add_argument(
        "command",
        choices=["save", "apply", "check", "diff"],
        help="Command to execute",
    )

    args = parser.parse_args()

    from . import core
    from . import printer
    from .printer import aINFO, INFO

    async def run():
        manager = await core.load_all(args.config_dir)

        with printer.PKG_CTX(args.command):
            await aINFO(f"Executing {args.command}...")

            if args.command == "save":
                await core.cmd_save(args.config_dir, manager, args)

            elif args.command == "apply":
                await core.cmd_apply(args, manager)

            elif args.command == "check":
                await aINFO("Executing 'check' action...")

            elif args.command == "diff":
                await core.cmd_diff(args, manager)

            await aINFO("All done.")

    try:
        asyncio.run(run())
    except (KeyboardInterrupt, ExitSignal):
        INFO("Exiting...")
        exit(1)


if __name__ == "__main__":
    main()
