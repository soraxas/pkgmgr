from abc import ABC, abstractmethod
from argparse import Namespace
import subprocess
import asyncio

import tomllib
import shlex
from typing import Any, Callable, Dict, Iterable, Optional
import importlib.util
import pathlib
import re

from collections.abc import AsyncIterable
from dataclasses import dataclass, field
from . import printer
from .helpers import async_all
from .command import (
    Command,
    CompoundCommand,
    FunctionCommand,
    ShellScript,
    UndefinedCommand,
)
from .printer import (
    ASK_USER,
    aERROR,
    aERROR_EXIT,
    aINFO,
    GREEN,
    RED,
    aWARN,
)
from .registry import (
    MANAGERS as REQUESTED_MANAGERS,
    Package,
    DeclaredPackageManager,
    USER_EXPORT,
)

DEFAULT_SAVE_OUTPUT_FILE = "99.unsorted.py"


# def command_runner(command: list[str]) -> tuple[int, str, str]:
#     """
#     Runs a command and returns the exit code.
#     """
#     process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#     assert process.stdout is not None
#     assert process.stderr is not None
#     process.wait()
#     return (
#         process.returncode,
#         process.stdout.read().decode(),
#         process.stderr.read().decode(),
#     )


@dataclass
class PackageManager:
    """
    A simple package manager class that uses shell commands to install and remove packages.
    """

    list_cmd: Command
    install_cmd: Command = field(default_factory=lambda: UndefinedCommand())
    remove_cmd: Command = field(default_factory=lambda: UndefinedCommand())
    supports_multi_pkgs: bool = False
    disabled: bool = False
    success_ret_code: set[int] = field(default_factory=lambda: {0})

    async def install(self, packages: Iterable[Package]) -> bool:
        # collect all the install commands, depending on
        # if the package manager supports multiple installs in one command
        if self.supports_multi_pkgs:
            install_cmd_parts = [
                " ".join(pkg.get_install_cmd_part() for pkg in packages)
            ]
        else:
            install_cmd_parts = [pkg.get_install_cmd_part() for pkg in packages]

        # run the install commands
        return await async_all(
            await self.install_cmd.with_replacement_part(install_cmd_part).run()
            for install_cmd_part in install_cmd_parts
        )

    async def remove(self, package: Iterable[Package]) -> bool:
        # collect all the remove commands, depending on
        # if the package manager supports multiple removes in one command
        if self.supports_multi_pkgs:
            remove_cmd_parts = [" ".join(pkg.name for pkg in package)]
        else:
            remove_cmd_parts = [pkg.name for pkg in package]

        # run the remove commands
        return await async_all(
            await self.remove_cmd.with_replacement_part(remove_cmd_part).run()
            for remove_cmd_part in remove_cmd_parts
        )

    async def list_installed(self) -> list[str]:
        success, stdout, stderr = await self.list_cmd.run_with_output()
        if not success:
            await aERROR_EXIT(f"Failed to list installed packages: {stderr}")
        if isinstance(stdout, str):
            return stdout.splitlines()
        return stdout


async def load_user_configs(config_dir: pathlib.Path) -> None:
    """
    Load user configs from the config directory.
    """
    # import all .py file in the config directory
    with printer.PKG_CTX("pkg-state"):
        for file in sorted(config_dir.glob("*.py")):
            await aINFO(f"Sourcing '{file}'...")
            spec = importlib.util.spec_from_file_location(file.name, file)
            assert spec is not None
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)


async def load_command(
    cmd,
    key: str,
    mgr_name: str,
) -> Command:
    if isinstance(cmd, str):
        return ShellScript(cmd)
    elif isinstance(cmd, dict):
        if "py_func_name" in cmd:
            try:
                func = FunctionCommand(USER_EXPORT[cmd["py_func_name"]])
            except KeyError:
                await aERROR_EXIT(
                    f"The specified functino '{cmd['py_func_name']}' is not exported from the module. "
                    f"You can export it by the decorator '@export' in the module. E.g.:\n\n"
                    f"from pkgmgr.registry import export\n\n"
                    f"@export\n"
                    f"def {cmd['py_func_name']}():\n"
                    f"    pass\n"
                )
            return func
        else:
            await aERROR_EXIT(
                f"Manager '{mgr_name}' is missing required command '{key}'"
            )
    elif isinstance(cmd, list):
        return CompoundCommand([await load_command(c, key, mgr_name) for c in cmd])
    else:
        await aERROR_EXIT(
            f"Unsupported config type '{type(cmd)}' for command '{key}' in manager '{mgr_name}'"
        )
    assert False, "Unreachable code"


async def load_mgr_config(
    config_dir: pathlib.Path, requested_mgrs: Iterable[str]
) -> dict[str, PackageManager]:
    """
    Load package manager config from the config directory.
    """
    # import all .py file in the config directory
    pkg_mgr_config = config_dir / "pkgmgr.toml"
    if not pkg_mgr_config.is_file():
        await aERROR_EXIT(f"Config file '{pkg_mgr_config}' does not exist.")

    with open(pkg_mgr_config, "rb") as f:
        config = tomllib.load(f)

        try:
            managers_conf = config["manager"]
        except KeyError:
            await aERROR_EXIT("No package managers found in config.toml")

    mgrs_def: dict[str, PackageManager] = {}
    for mgr_name, mgr_config in managers_conf.items():

        kwargs: Dict[str, Any] = {}

        for key in ["list_cmd"]:
            try:
                cmd = mgr_config[key]

                kwargs[key] = await load_command(cmd, key, mgr_name)

            except KeyError:
                await aERROR_EXIT(
                    f"Manager '{mgr_name}' is missing required command '{key}'"
                )
        kwargs["supports_multi_pkgs"] = mgr_config.get("supports_multi_pkgs", False)
        kwargs["disabled"] = mgr_config.get("disabled", False)
        if "success_ret_code" in mgr_config:
            kwargs["success_ret_code"] = set(mgr_config["success_ret_code"])

        pkg_mgr = PackageManager(**kwargs)  # type: ignore
        mgrs_def[mgr_name] = pkg_mgr

    for mgr_name in requested_mgrs:
        if mgr_name not in mgrs_def:
            await aERROR_EXIT(f"Manager for '{mgr_name}' not found in {pkg_mgr_config}")

    return dict(filter(lambda x: not x[1].disabled, mgrs_def.items()))


async def load_all(config_dir_str: str = "./configs"):
    config_dir = pathlib.Path(config_dir_str)
    if not config_dir.is_dir():
        await aERROR_EXIT(f"Config directory '{config_dir}' does not exist.")

    with printer.PKG_CTX:
        with printer.PKG_CTX("load-conf"):
            await aINFO(f"Collecting desire package state in '{config_dir}/'...")
            await load_user_configs(config_dir)

            await aINFO(
                f"Loading manager definition at '{config_dir / "pkgmgr.toml"}'..."
            )
            managers = await load_mgr_config(
                config_dir, REQUESTED_MANAGERS.data_pair.keys()
            )
        return managers


async def collect_state(
    requested_mgr: DeclaredPackageManager, pkg_mgr: PackageManager, sort: bool = True
) -> tuple[set[Package], set[Package]]:
    """
    Collect the state of all package managers.
    """
    await aINFO(f"Checking packages state...")

    want_installed = requested_mgr.pkgs
    currently_installed_packages = set(
        Package(pkg) if isinstance(pkg, str) else pkg
        for pkg in (await pkg_mgr.list_installed())
    )

    #######################################################

    pkgs_wanted = set()
    for package in want_installed:
        if package not in currently_installed_packages:
            pkgs_wanted.add(package)

    #######################################################

    pkgs_not_recorded = (
        currently_installed_packages - set(want_installed) - requested_mgr.ignore_pkgs
    )

    if sort:
        pkgs_wanted = set(sorted(pkgs_wanted))
        pkgs_not_recorded = set(sorted(pkgs_not_recorded))

    return pkgs_wanted, pkgs_not_recorded


def santise_variable_name(var_str: str):
    """
    Sanitise a variable name by replacing non-alphanumeric characters with underscores.
    """
    return re.sub("\W|^(?=\d)", "_", var_str)


async def save_wanted_pkgs_to_file(file, pkg_mgr_name, pkgs_wanted, pkgs_not_recorded):
    IDEN_var_name = santise_variable_name(pkg_mgr_name)

    file.write("\n" + "#" * 25 + "\n")
    file.write(f"# {pkg_mgr_name}\n")
    file.write("#" * 25 + "\n")

    file.write(f'\n{IDEN_var_name} = MANAGERS["{IDEN_var_name}"]\n')

    # invert to bring the config up-to-speed

    if pkgs_not_recorded:
        file.write(f"\n# wanted\n")
        for pkg_name in pkgs_not_recorded:
            file.write(f"{IDEN_var_name} << {pkg_name.get_config_repr()}\n")
            await aINFO(f"Added {pkg_name}")
    if pkgs_wanted:
        file.write(f"\n# unwanted\n")
        for pkg in pkgs_wanted:
            file.write(f"{IDEN_var_name} >> {pkg.name!r}\n")
            await aINFO(f"To remove {pkg!r}")


def for_each_registered_mgr(managers: dict[str, PackageManager]):
    """
    Helper genrator to loop through defined managers and registered managers.
    """
    for pkg_mgr_name, pkg_mgr in managers.items():
        with printer.PKG_CTX(pkg_mgr_name):
            requested_mgr = REQUESTED_MANAGERS[pkg_mgr_name]
            yield pkg_mgr_name, pkg_mgr, requested_mgr


async def cmd_save(
    config_dir: pathlib.Path, managers: dict[str, PackageManager], args: Namespace
) -> None:
    if not args.force and (config_dir / DEFAULT_SAVE_OUTPUT_FILE).is_file():
        await aERROR_EXIT(
            f"File '{DEFAULT_SAVE_OUTPUT_FILE}' already exists. Refusing to continue. "
            "Please organise your packages definition in the config directory first."
        )

    packages_to_write = []

    # process all requested managers and see if we need to write anything
    for pkg_mgr_name, pkg_mgr, requested_mgr in for_each_registered_mgr(managers):
        pkgs_wanted, pkgs_not_recorded = await collect_state(requested_mgr, pkg_mgr)

        if pkgs_wanted or pkgs_not_recorded:
            packages_to_write.append((pkg_mgr_name, pkgs_wanted, pkgs_not_recorded))

    # only start a new file if we have something to write
    if packages_to_write:
        with open(
            config_dir / DEFAULT_SAVE_OUTPUT_FILE,
            "a",
            encoding="utf-8",
        ) as f:

            f.write("from pkgmgr.registry import MANAGERS, Package\n\n")

            for datapack in packages_to_write:
                await save_wanted_pkgs_to_file(f, *datapack)


async def cmd_apply(args: Namespace, managers: dict[str, PackageManager]) -> None:

    async def inner_apply(
        name: str, pkg_mgr: PackageManager, requested_mgr: DeclaredPackageManager
    ):
        pkgs_wanted, pkgs_not_recorded = await collect_state(requested_mgr, pkg_mgr)

        if pkgs_wanted or pkgs_not_recorded:
            await aINFO("The following changes to packages are detected:")

            for package in pkgs_wanted:
                await aINFO(f"  + {package}", GREEN)
            for package_name in pkgs_not_recorded:
                await aINFO(f"  - {package_name}", RED)

            can_install = not isinstance(pkg_mgr.install_cmd, UndefinedCommand)
            can_remove = not isinstance(pkg_mgr.remove_cmd, UndefinedCommand)

            if not can_install and not can_remove:
                await aWARN(
                    f"Manager '{name}' does not support installing or removing packages. "
                )
                await aWARN(
                    "You can define `install_cmd` / `remove_cmd` in the config file to enable apply cmd."
                )
            elif await ASK_USER("Do you want to apply the changes?"):
                if can_install and pkgs_wanted:
                    if not await pkg_mgr.install(pkgs_wanted):
                        await aERROR_EXIT("Failed to install packages.")

                if can_remove and pkgs_not_recorded:
                    if not await pkg_mgr.remove(pkgs_not_recorded):
                        await aERROR_EXIT(f"Failed to remove packages.")

                await aINFO(f"Applied.")
            else:
                await aERROR("Aborted.")

        else:
            await aINFO(f"No Change.")

    await apply_on_each_pkg(
        args.sync,
        functor=inner_apply,
        managers=managers,
    )


async def cmd_diff(args: Namespace, managers: dict[str, PackageManager]) -> None:

    async def inner_diff(name, pkg_mgr, requested_mgr):
        pkgs_wanted, pkgs_not_recorded = await collect_state(requested_mgr, pkg_mgr)

        if pkgs_wanted or pkgs_not_recorded:
            await aINFO("Diff of current system against the configs:")

            for package in pkgs_wanted:
                await aINFO(f"  + {package}", GREEN)
            for package_name in pkgs_not_recorded:
                await aINFO(f"  - {package_name}", RED)

        else:
            await aINFO(f"No Change.")

    await apply_on_each_pkg(
        args.sync,
        functor=inner_diff,
        managers=managers,
    )


async def apply_on_each_pkg(
    use_sync: bool,
    functor: Callable[[str, PackageManager, DeclaredPackageManager], Any],
    managers: dict[str, PackageManager],
):
    """
    A helper function to apply a function on each package manager.
    """

    async def wrapper(name, pkg_mgr, requested_mgr):
        # this wrapper enable the context manager to be used
        # in the async function
        with printer.PKG_CTX(name):
            return await functor(name, pkg_mgr, requested_mgr)

    tasks = []
    for name, pkg_mgr, requested_mgr in for_each_registered_mgr(managers):
        if use_sync:
            await wrapper(name, pkg_mgr, requested_mgr)
        else:
            tasks.append(wrapper(name, pkg_mgr, requested_mgr))
    await asyncio.gather(*tasks, return_exceptions=True)
