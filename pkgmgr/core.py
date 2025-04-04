from abc import ABC, abstractmethod
import subprocess
import tomllib
import shlex
from typing import Any, Dict, Iterable, Optional
import importlib.util
import pathlib
import re

from dataclasses import dataclass, field
from . import printer
from .command import Command, FunctionCommand, ShellScript
from .printer import (
    ASK_USER,
    ERROR,
    ERROR_EXIT,
    INFO,
    GREEN,
    RED,
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


class PackageManager(ABC):
    # if the package manager supports multiple installs in one command
    SUPPORTS_MULTIPLE_INSTALLS = True

    @abstractmethod
    async def install(self, packages: list[Package]) -> bool:
        """
        Given a package name, install the package.
        """
        pass

    @abstractmethod
    async def remove(self, package: list[Package]) -> bool:
        """
        Given a package name, remove the package.
        """
        pass

    @abstractmethod
    async def list_installed(self) -> list[str]:
        """
        List all installed packages.
        """
        pass


from collections.abc import AsyncIterable


async def async_all(async_iterable: AsyncIterable[object]) -> bool:
    async for element in async_iterable:
        if not element:
            return False
    return True


@dataclass
class SimplePackageManager(PackageManager):
    """
    A simple package manager class that uses shell commands to install and remove packages.
    """

    install_cmd: Command
    remove_cmd: Command
    list_cmd: Command
    supports_multi_pkgs: bool
    success_ret_code: set[int] = field(default_factory=lambda: {0})

    async def install(self, packages: list[Package]) -> bool:
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

    async def remove(self, package: list[Package]) -> bool:
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
            ERROR_EXIT(f"Failed to list installed packages: {stderr}")
        if isinstance(stdout, str):
            return stdout.splitlines()
        return stdout


def load_user_configs(config_dir: pathlib.Path) -> None:
    """
    Load user configs from the config directory.
    """
    # import all .py file in the config directory
    with printer.PKG_CTX("pkg-state"):
        for file in sorted(config_dir.glob("*.py")):
            INFO(f"Sourcing '{file}'...")
            spec = importlib.util.spec_from_file_location(file.name, file)
            assert spec is not None
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)


def load_mgr_config(
    config_dir: pathlib.Path, requested_mgrs: Iterable[str]
) -> dict[str, PackageManager]:
    """
    Load package manager config from the config directory.
    """
    # import all .py file in the config directory
    pkg_mgr_config = config_dir / "pkgmgr.toml"
    if not pkg_mgr_config.is_file():
        ERROR_EXIT(f"Config file '{pkg_mgr_config}' does not exist.")

    with open(pkg_mgr_config, "rb") as f:
        config = tomllib.load(f)

        managers_conf = config.get("manager")
        if managers_conf is None:
            ERROR("No package managers found in config.toml")
            exit(1)

    mgrs: dict[str, PackageManager] = {}
    for mgr_name, mgr_config in managers_conf.items():

        kwargs: Dict[str, Any] = {}

        for key in ["install_cmd", "remove_cmd", "list_cmd"]:
            try:
                cmd = mgr_config[key]
                if isinstance(cmd, str):
                    kwargs[key] = ShellScript(cmd)
                elif isinstance(cmd, dict):
                    if "py_func_name" in cmd:
                        try:
                            func = FunctionCommand(USER_EXPORT[cmd["py_func_name"]])
                        except KeyError:
                            ERROR_EXIT(
                                f"The specified functino '{cmd['py_func_name']}' is not exported from the module. "
                                f"You can export it by the decorator '@export' in the module. E.g.:\n\n"
                                f"from pkgmgr.registry import export\n\n"
                                f"@export\n"
                                f"def {cmd['py_func_name']}():\n"
                                f"    pass\n"
                            )
                        kwargs[key] = func
                    else:
                        ERROR_EXIT(
                            f"Manager '{mgr_name}' is missing required command '{key}'"
                        )
            except KeyError:
                ERROR_EXIT(f"Manager '{mgr_name}' is missing required command '{key}'")
        kwargs["supports_multi_pkgs"] = mgr_config.get("supports_multi_pkgs", False)
        if "success_ret_code" in mgr_config:
            kwargs["success_ret_code"] = set(mgr_config["success_ret_code"])

        pkg_mgr = SimplePackageManager(**kwargs)  # type: ignore
        mgrs[mgr_name] = pkg_mgr

    for mgr_name in requested_mgrs:
        if mgr_name not in mgrs:
            ERROR_EXIT(f"Manager for '{mgr_name}' not found in {pkg_mgr_config}")

    return mgrs


def load_all(config_dir_str: str = "./configs"):
    config_dir = pathlib.Path(config_dir_str)
    if not config_dir.is_dir():
        ERROR_EXIT(f"Config directory '{config_dir}' does not exist.")

    with printer.PKG_CTX:
        with printer.PKG_CTX("load-conf"):
            INFO(f"Collecting desire package state in '{config_dir}/'...")
            load_user_configs(config_dir)

            INFO(f"Loading manager definition...")
            managers = load_mgr_config(config_dir, REQUESTED_MANAGERS.data_pair.keys())
        return managers


async def collect_state(
    requested_mgr: DeclaredPackageManager, pkg_mgr: PackageManager
) -> tuple[set[Package], set[Package]]:
    """
    Collect the state of all package managers.
    """
    INFO(f"Checking packages state...")

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
    return pkgs_wanted, pkgs_not_recorded


def santise_variable_name(var_str: str):
    """
    Sanitise a variable name by replacing non-alphanumeric characters with underscores.
    """
    return re.sub("\W|^(?=\d)", "_", var_str)


def save_wanted_pkgs_to_file(file, pkg_mgr_name, pkgs_wanted, pkgs_not_recorded):
    IDEN_var_name = santise_variable_name(pkg_mgr_name)

    file.write("\n" + "#" * 25 + "\n")
    file.write(f"# {pkg_mgr_name}\n")
    file.write("#" * 25 + "\n")

    file.write(f'\n{IDEN_var_name} = MANAGERS["{IDEN_var_name}"]\n')

    # invert to bring the config up-to-speed

    if pkgs_not_recorded:
        file.write(f"\n# wanted\n")
        for pkg_name in pkgs_not_recorded:
            file.write(f"{IDEN_var_name} << {pkg_name!r}\n")
            INFO(f"Added {pkg_name}")
    if pkgs_wanted:
        file.write(f"\n# unwanted\n")
        for pkg in pkgs_wanted:
            file.write(f"{IDEN_var_name} >> {pkg.name!r}\n")
            INFO(f"To remove {pkg_name}")


def for_each_registered_mgr(managers: dict[str, PackageManager]):
    """
    Helper genrator to loop through defined managers and registered managers.
    """
    for pkg_mgr_name, pkg_mgr in managers.items():
        with printer.PKG_CTX(pkg_mgr_name):
            requested_mgr = REQUESTED_MANAGERS[pkg_mgr_name]
            yield pkg_mgr_name, pkg_mgr, requested_mgr


async def cmd_save(
    config_dir: pathlib.Path, managers: dict[str, PackageManager]
) -> None:
    if (config_dir / DEFAULT_SAVE_OUTPUT_FILE).is_file():
        ERROR_EXIT(
            f"File '{DEFAULT_SAVE_OUTPUT_FILE}' already exists. Refusing to continue. "
            "Please organise your packages definition in the config directory first."
        )

    packages_to_write = []

    # process all requested managers and see if we need to write anything
    for pkg_mgr_name, pkg_mgr, requested_mgr in for_each_registered_mgr(managers):
        pkgs_wanted_set, pkgs_not_recorded_set = await collect_state(
            requested_mgr, pkg_mgr
        )

        pkgs_wanted = sorted(pkgs_wanted_set, key=lambda pkg: pkg.name)
        pkgs_not_recorded = sorted(pkgs_not_recorded_set)

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

            for args in packages_to_write:
                save_wanted_pkgs_to_file(f, *args)


async def cmd_apply(managers: dict[str, PackageManager]) -> None:

    for _, pkg_mgr, requested_mgr in for_each_registered_mgr(managers):
        pkgs_wanted, pkgs_not_recorded = await collect_state(requested_mgr, pkg_mgr)

        if pkgs_wanted or pkgs_not_recorded:
            INFO("The following changes to packages will be applied:")

            for package in pkgs_wanted:
                INFO(f"  + {package}", GREEN)
            for package_name in pkgs_not_recorded:
                INFO(f"  - {package_name}", RED)

            if ASK_USER("Do you want to apply the changes?"):
                if pkgs_wanted:
                    if not await pkg_mgr.install(pkgs_wanted):
                        ERROR_EXIT("Failed to install packages.")

                if pkgs_not_recorded:
                    if not await pkg_mgr.remove(pkgs_not_recorded):
                        ERROR_EXIT(f"Failed to remove packages.")

            else:
                ERROR_EXIT("Aborted.")

            INFO(f"Applied.")
        else:
            INFO(f"No Change.")


async def cmd_diff(managers: dict[str, PackageManager]) -> None:
    for _, pkg_mgr, requested_mgr in for_each_registered_mgr(managers):
        pkgs_wanted, pkgs_not_recorded = await collect_state(requested_mgr, pkg_mgr)

        if pkgs_wanted or pkgs_not_recorded:
            INFO("Diff of current system against the configs:")

            for package in pkgs_wanted:
                INFO(f"  + {package}", GREEN)
            for package_name in pkgs_not_recorded:
                INFO(f"  - {package_name}", RED)

        else:
            INFO(f"No Change.")
