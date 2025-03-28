from abc import ABC, abstractmethod
import subprocess
import tomllib
import shlex
from typing import Optional
import importlib.util
import pathlib

from dataclasses import dataclass
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

    async def install(self, package_names: list[str]) -> bool:
        if self.supports_multi_pkgs:
            cmd = self.install_cmd.replace("{}", " ".join(package_names))
            return await command_runner_stream(shlex.split(cmd))
        else:
            for pkg_name in package_names:
                cmd = self.install_cmd.replace("{}", pkg_name)
                if not await command_runner_stream(shlex.split(cmd)):
                    return False
            return True

    async def remove(self, package_names: list[str]) -> bool:
        if self.supports_multi_pkgs:
            cmd = self.remove_cmd.replace("{}", " ".join(package_names))
            return await command_runner_stream(shlex.split(cmd))
        else:
            for pkg_name in package_names:
                cmd = self.remove_cmd.replace("{}", pkg_name)
                if not await command_runner_stream(shlex.split(cmd)):
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


async def cmd_apply(managers: dict[str, PackageManager]) -> None:
    for requested_mgr in requested_manager.data_pair.values():

        pkg_mgr = managers[requested_mgr.name]

        with printer.PKG_CTX(requested_mgr.name):

            INFO(f"Checking packages state...")

            want_installed = requested_mgr.pkgs
            currently_installed_packages = set(pkg_mgr.list_installed())

            #######################################################

            will_install_packages = set()
            for package in want_installed:
                if package.name not in currently_installed_packages:
                    will_install_packages.add(package)

            #######################################################

            not_recorded = currently_installed_packages - {
                want_installed.name for want_installed in want_installed
            }
            if will_install_packages or not_recorded:
                INFO("The following changes to packages will be applied:")

                for package in will_install_packages:
                    INFO(f"  + {package.name}", GREEN)
                for package_name in not_recorded:
                    INFO(f"  - {package_name}", RED)

                if ASK_USER("Do you want to apply the changes?"):
                    if will_install_packages:
                        if not await pkg_mgr.install():
                            [pkg.get_part() for pkg in will_install_packages]
                            ERROR_EXIT("Failed to install packages.")

                    if not_recorded:
                        if not await pkg_mgr.remove(not_recorded):
                            ERROR_EXIT(f"Failed to remove packages.")

                else:
                    ERROR_EXIT("Aborted.")

                INFO(f"Applied.")
            else:
                INFO(f"No Change.")
