from abc import ABC, abstractmethod
import subprocess
import tomllib
import shlex
from typing import Optional
import importlib.util
import pathlib
import re

from dataclasses import dataclass, field
from .aio import command_runner_stream
from . import printer
from .printer import (
    ASK_USER,
    ERROR,
    ERROR_EXIT,
    INFO,
    GREEN,
    RED,
)
from .registry import MANAGERS as requested_manager

DEFAULT_SAVE_OUTPUT_FILE = "99.unsorted.py"


def command_runner(command: list[str]) -> tuple[int, str, str]:
    """
    Runs a command and returns the exit code.
    """
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.wait()
    return process.returncode, process.stdout.read(), process.stderr.read()


class PackageManager(ABC):
    # if the package manager supports multiple installs in one command
    SUPPORTS_MULTIPLE_INSTALLS = True

    @abstractmethod
    async def install(self, package_name: str) -> bool:
        """
        Given a package name, install the package.
        """
        pass

    @abstractmethod
    async def remove(self, package_name: str) -> bool:
        """
        Given a package name, remove the package.
        """
        pass

    @abstractmethod
    def check_installed(self, package_name: str) -> bool:
        """
        Given a package name, check if the package is installed.
        """
        pass

    @abstractmethod
    def list_installed(self) -> list[str]:
        """
        List all installed packages.
        """
        pass


@dataclass
class SimplePackageManager(PackageManager):
    """
    A simple package manager class that uses shell commands to install and remove packages.
    """

    install_cmd: str
    remove_cmd: str
    list_cmd: str
    supports_multi_pkgs: bool
    success_ret_code: set[int] = field(default_factory=lambda: {0})

    def check_ret_code(self, retcode: int) -> bool:
        """
        Check if the return code is in the success return code set.
        """
        return retcode in self.success_ret_code

    async def install(self, packages: list[PackageManager]) -> bool:
        if self.supports_multi_pkgs:
            cmd = self.install_cmd.replace(
                "{}", " ".join(pkg.get_part() for pkg in packages)
            )
            return self.check_ret_code(await command_runner_stream(shlex.split(cmd)))
        else:
            for pkg in packages:
                cmd = self.install_cmd.replace("{}", pkg.name)
                if not self.check_ret_code(
                    await command_runner_stream(shlex.split(cmd))
                ):
                    return False
            return True

    async def remove(self, package_names: list[str]) -> bool:
        if self.supports_multi_pkgs:
            cmd = self.remove_cmd.replace("{}", " ".join(package_names))
            return self.check_ret_code(await command_runner_stream(shlex.split(cmd)))
        else:
            for pkg_name in package_names:
                cmd = self.remove_cmd.replace("{}", pkg_name)
                if not self.check_ret_code(
                    await command_runner_stream(shlex.split(cmd))
                ):
                    return False
            return True

    def check_installed(self, package_name: str) -> bool:
        return package_name in self.installed

    def list_installed(self) -> list[str]:
        retcode, stdout, stderr = command_runner(shlex.split(self.list_cmd))
        if retcode != 0:
            ERROR_EXIT(f"Failed to list installed packages: {stderr}")
        return stdout.decode().splitlines()


def load_user_configs(config_dir: pathlib.Path) -> None:
    """
    Load user configs from the config directory.
    """
    # import all .py file in the config directory
    for file in sorted(config_dir.glob("*.py")):
        spec = importlib.util.spec_from_file_location(file.name, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


def load_mgr_config(
    config_dir: pathlib.Path, requested_mgrs: list[str]
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

    mgrs = {}
    for mgr_name in requested_mgrs:
        if mgr_name not in managers_conf:
            ERROR_EXIT(f"Manager for '{mgr_name}' not found in {pkg_mgr_config}")
        mgr_config = managers_conf[mgr_name]
        if any(
            key not in mgr_config for key in ["install_cmd", "remove_cmd", "list_cmd"]
        ):
            ERROR_EXIT(
                f"Manager '{mgr_name}' is missing required commands in config.toml"
            )

        pkg_mgr = SimplePackageManager(
            mgr_config["install_cmd"],
            mgr_config["remove_cmd"],
            mgr_config["list_cmd"],
            mgr_config.get("supports_multi_pkgs", False),
        )
        mgrs[mgr_name] = pkg_mgr

    return mgrs


def load_all(config_dir: str = "./configs"):
    config_dir = pathlib.Path(config_dir)
    if not config_dir.is_dir():
        ERROR_EXIT(f"Config directory '{config_dir}' does not exist.")

    with printer.PKG_CTX:
        INFO(f"Loading manager definition...")
        load_user_configs(config_dir)

        INFO(f"Collecting desire package state...")
        managers = load_mgr_config(config_dir, requested_manager.data_pair.keys())
        return managers


async def collect_state(
    requested_mgr: PackageManager, pkg_mgr: PackageManager
) -> tuple[set[PackageManager], set[str]]:
    """
    Collect the state of all package managers.
    """
    INFO(f"Checking packages state...")

    want_installed = requested_mgr.pkgs
    currently_installed_packages = set(pkg_mgr.list_installed())

    #######################################################

    pkgs_wanted = set()
    for package in want_installed:
        if package.name not in currently_installed_packages:
            pkgs_wanted.add(package)

    #######################################################

    pkgs_not_recorded = currently_installed_packages - {
        want_installed.name for want_installed in want_installed
    }
    return pkgs_wanted, pkgs_not_recorded


def santise_variable_name(var_str: str):
    """
    Sanitise a variable name by replacing non-alphanumeric characters with underscores.
    """
    return re.sub("\W|^(?=\d)", "_", var_str)


async def cmd_save(
    config_dir: pathlib.Path, managers: dict[str, PackageManager]
) -> None:
    if (config_dir / DEFAULT_SAVE_OUTPUT_FILE).is_file():
        ERROR_EXIT(
            f"File '{DEFAULT_SAVE_OUTPUT_FILE}' already exists. Refusing to continue. "
            "Please organise your packages definition in the config directory first."
        )

    packages_to_write_functor = []

    # process all requested managers and see if we need to write anything
    for requested_mgr in requested_manager.data_pair.values():
        pkg_mgr = managers[requested_mgr.name]

        with printer.PKG_CTX(requested_mgr.name):

            pkgs_wanted, pkgs_not_recorded = await collect_state(requested_mgr, pkg_mgr)

            pkgs_wanted = sorted(pkgs_wanted, key=lambda pkg: pkg.name)
            pkgs_not_recorded = sorted(pkgs_not_recorded)

            if pkgs_wanted or pkgs_not_recorded:

                def functor(file):
                    IDEN_var_name = santise_variable_name(requested_mgr.name)

                    file.write("\n" + "#" * 25 + "\n")
                    file.write(f"# {requested_mgr.name}\n")
                    file.write("#" * 25 + "\n")

                    file.write(f'\n{IDEN_var_name} = MANAGERS["{IDEN_var_name}"]\n')

                    # invert to bring the config up-to-speed

                    if pkgs_not_recorded:
                        file.write(f"\n# wanted\n")
                        for pkg_name in pkgs_not_recorded:
                            file.write(f'{IDEN_var_name} << "{pkg_name}"\n')
                    if pkgs_wanted:
                        file.write(f"\n# unwanted\n")
                        for pkg in pkgs_wanted:
                            file.write(f'{IDEN_var_name} >> "{pkg.name}"\n')

                packages_to_write_functor.append(functor)

    # only start a new file if we have something to write
    if packages_to_write_functor:
        with open(
            config_dir / DEFAULT_SAVE_OUTPUT_FILE,
            "a",
            encoding="utf-8",
        ) as f:

            f.write("from pkgmgr.registry import MANAGERS, Package\n\n")

            for functor in packages_to_write_functor:

                functor(file=f)


async def cmd_apply(managers: dict[str, PackageManager]) -> None:
    for requested_mgr in requested_manager.data_pair.values():

        pkg_mgr = managers[requested_mgr.name]

        with printer.PKG_CTX(requested_mgr.name):

            pkgs_wanted, pkgs_not_recorded = await collect_state(requested_mgr, pkg_mgr)

            if pkgs_wanted or pkgs_not_recorded:
                INFO("The following changes to packages will be applied:")

                for package in pkgs_wanted:
                    INFO(f"  + {package.name}", GREEN)
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
