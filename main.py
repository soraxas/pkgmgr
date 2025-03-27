from abc import ABC, abstractmethod
import subprocess
import sys
import tomllib
import shlex
from typing import Optional
import threading
import importlib.util
import pathlib
import printer

from dataclasses import dataclass
from printer import (
    ASK_USER,
    ERROR,
    ERROR_EXIT,
    GREEN,
    INFO,
    RED,
    TERM_STDERR,
    TERM_STDOUT,
)
from registry import MANAGERS as requested_manager


def stream_output(pipe, print_func):
    """Reads output from a pipe and prints it with the given color."""
    # for line in iter(pipe.readline, ''):
    #     print_func(line.strip())
    """Reads output from a pipe character-by-character and prints it with the given color."""
    needs_prefix = True
    for char in iter(lambda: pipe.read(1), ""):
        if needs_prefix:
            needs_prefix = False
            print_func("", end="")
        print(f"{char}", end="", flush=True)
        if char == "\n":
            needs_prefix = True
    pipe.close()


def handle_input(process):
    """Reads user input and forwards it to the subprocess, detecting Enter key presses."""
    while process.poll() is None:
        try:
            user_input = input()
            print(f"\033[94m[INPUT] {user_input}\033[0m")  # Print input with prefix
            process.stdin.write(user_input + "\n")
            process.stdin.flush()
        except EOFError:
            break


def command_runner_stream(command: list[str]) -> bool:
    """
    Runs a command given as a list of strings and prints stdout in green and stderr in red in real-time.
    """
    TERM_STDOUT(f"$ {' '.join(command)}")
    process = subprocess.Popen(
        command,
        stdin=sys.stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_thread = threading.Thread(
        target=stream_output, args=(process.stdout, TERM_STDOUT)
    )
    stderr_thread = threading.Thread(
        target=stream_output, args=(process.stderr, TERM_STDERR)
    )

    stdout_thread.start()
    stderr_thread.start()

    stdout_thread.join()
    stderr_thread.join()

    return process.wait() == 0


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
    def install(self, package_name: str) -> bool:
        """
        Given a package name, install the package.
        """
        pass

    @abstractmethod
    def remove(self, package_name: str) -> bool:
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


from aio import command_runner_stream


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


@dataclass
class DeclaredPackageManager:
    """
    A class to store the packages declared by the user.
    """

    pkgs: list[str]

    def add(self, package_name: str):
        self.pkgs.append(package_name)

    def remove(self, package_name: str):
        self.pkgs.remove(package_name)


class DeclaredPackageManagerRegistry:
    """
    A registry for user to declared package wanted to be installed.
    """

    data_pair: dict[str, tuple[SimplePackageManager, DeclaredPackageManager]] = {}

    def __getitem__(self, item: str) -> DeclaredPackageManager:
        try:
            return self.data_pair[item][1]
        except KeyError:
            pass
        if item not in MANAGERS_CONFIGS:
            ERROR_EXIT(f"Manager {item} not found in config.toml")
        config = MANAGERS_CONFIGS[item]
        mgr = SimplePackageManager(
            config["install_cmd"],
            config["remove_cmd"],
            config["list_cmd"],
            config.get("supports_multi_pkgs", False),
        )
        self.data_pair[item] = (mgr, DeclaredPackageManager(config.get("packages", [])))
        return self.data_pair[item][1]


with open("config.toml", "rb") as f:
    config = tomllib.load(f)

    MANAGERS_CONFIGS = config.get("manager")
    if MANAGERS_CONFIGS is None:
        ERROR("No package managers found in config.toml")
        exit(1)


async def run():

    # import all .py file in the current directory
    for file in sorted(pathlib.Path("./configs").glob("*.py")):
        spec = importlib.util.spec_from_file_location(file.name, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

    for requested_mgr in requested_manager.data_pair.values():
        if requested_mgr.name not in MANAGERS_CONFIGS:
            ERROR_EXIT(f"Manager for '{requested_mgr.name}' not found in config.toml")

        mgr_config = MANAGERS_CONFIGS[requested_mgr.name]
        pkg_mgr = SimplePackageManager(
            mgr_config["install_cmd"],
            mgr_config["remove_cmd"],
            mgr_config["list_cmd"],
            mgr_config.get("supports_multi_pkgs", False),
        )

        printer.CURRENT_PKG_CTX = requested_mgr.name

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
                    if not await pkg_mgr.install(
                        [pkg.get_part() for pkg in will_install_packages]
                    ):
                        ERROR_EXIT("Failed to install packages.")

                if not_recorded:
                    if not await pkg_mgr.remove(not_recorded):
                        ERROR_EXIT(f"Failed to remove packages.")

            else:
                ERROR_EXIT("Aborted.")

            INFO(f"Applied.")
        else:
            INFO(f"No Change.")


import asyncio

if __name__ == "__main__":
    asyncio.run(run())  # Example usage
