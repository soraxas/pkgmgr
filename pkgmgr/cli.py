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
        type=str,
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
        "command",
        choices=["save", "apply", "check", "diff"],
        help="Command to execute",
    )

    # subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # # Save action
    # save_parser = subparsers.add_parser("save", help="Update the configuration to reflect the current state of the system")
    # # Apply action
    # apply_parser = subparsers.add_parser("apply", help="Update the system to reflect the current contents of the configuration")
    # # Check action
    # check_parser = subparsers.add_parser("check", help="Syntax-check and lint the configuration")
    # # Diff action
    # diff_parser = subparsers.add_parser("diff", help="Compare configuration and system")

    args = parser.parse_args()

    from . import core
    from . import printer
    from .printer import INFO

    manager = core.load_all(args.config_dir)

    with printer.PKG_CTX:
        INFO(f"Executing {args.command}...")

        if args.command == "save":
            asyncio.run()

        elif args.command == "apply":
            asyncio.run(core.cmd_apply(manager))

        elif args.command == "check":
            print("Executing 'check' action...")

        elif args.command == "diff":
            print("Executing 'diff' action...")

        INFO("All done.")
    # else:
    #     parser.print_help()


if __name__ == "__main__":
    main()
