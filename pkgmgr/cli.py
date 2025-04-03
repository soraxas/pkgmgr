import os
import argparse
import asyncio
from pathlib import Path


def main():

    from . import _version

    configpath = os.path.join(
        os.environ.get("APPDATA")
        or os.environ.get("XDG_CONFIG_HOME")
        or os.path.join(os.environ["HOME"], ".config"),
        "pkgmgr",
    )

    parser = argparse.ArgumentParser(
        description="Package Manager",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {_version.version}"
    )

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
        "command",
        choices=["save", "apply", "check", "diff"],
        help="Command to execute",
    )

    args = parser.parse_args()

    from . import core
    from . import printer
    from .printer import INFO

    manager = core.load_all(args.config_dir)

    with printer.PKG_CTX(args.command):
        INFO(f"Executing {args.command}...")

        if args.command == "save":
            asyncio.run(core.cmd_save(args.config_dir, manager, args))

        elif args.command == "apply":
            asyncio.run(core.cmd_apply(manager))

        elif args.command == "check":
            print("Executing 'check' action...")

        elif args.command == "diff":
            asyncio.run(core.cmd_diff(manager))

        INFO("All done.")
    # else:
    #     parser.print_help()


if __name__ == "__main__":
    main()
