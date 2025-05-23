import asyncio
import os
import tomllib
from typing import Any, Callable, Dict, Iterable, Literal, Optional
import importlib.util

from pathlib import Path
from dataclasses import dataclass, field
from . import printer
from .helpers import ExitSignal, UserSelectOption, async_all, santise_variable_name
from .command import (
    Command,
    PipedCommand,
    CompoundCommand,
    FunctionCommand,
    ShellScript,
    UndefinedCommand,
)
from .printer import (
    ASK_USER,
    aERROR_EXIT,
    aINFO,
    GREEN,
    RED,
    aWARN,
)
from .registry import (
    MANAGERS as REQUESTED_MANAGERS,
    Package,
    DeclaredPackageState,
    USER_EXPORT,
)

DEFAULT_SAVE_OUTPUT_FILE = "99.unsorted.py"


OPERATION_LOCK = asyncio.Lock()


@dataclass
class CLIOptions:
    config_dir: Path
    paranoid: bool
    yes: bool
    force: bool
    sync: bool


@dataclass
class PackageManager:
    """
    A simple package manager class that uses shell commands to install and remove packages.
    """

    list_cmd: Command
    add_cmd: Command = field(default_factory=UndefinedCommand)
    remove_cmd: Command = field(default_factory=UndefinedCommand)
    extract_add_cmd_part: Command = field(default_factory=UndefinedCommand)
    supports_multi_pkgs: bool = False
    supports_save: bool = True
    disabled: bool = False
    success_ret_code: set[int] = field(default_factory=lambda: {0})

    async def install(self, packages: Iterable[Package]) -> bool:
        # collect all the install commands, depending on
        # if the package manager supports multiple installs in one command
        if self.supports_multi_pkgs:
            add_cmd_parts = [" ".join(pkg.get_add_cmd_part() for pkg in packages)]
        else:
            add_cmd_parts = [pkg.get_add_cmd_part() for pkg in packages]

        # run the install commands
        return await async_all(
            await self.add_cmd.with_replacement_part(add_cmd_part).run() for add_cmd_part in add_cmd_parts
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
            await self.remove_cmd.with_replacement_part(remove_cmd_part).run() for remove_cmd_part in remove_cmd_parts
        )

    async def list_installed(self) -> list[Package]:
        success, stdout, stderr = await self.list_cmd.run_with_output()
        if not success:
            await aERROR_EXIT(f"Failed to list installed packages: {stderr}")
        if isinstance(stdout, str):
            pkgs_str = stdout.splitlines()
            # if this command supports transforming pkg to add_cmd_part, do it
            # this normally enrich the package info from cli output

            if isinstance(self.extract_add_cmd_part, UndefinedCommand):
                pkgs = [Package(pkg) for pkg in pkgs_str]
            else:
                pkgs = []
                for pkg_str in pkgs_str:
                    ok, part, stderr = await self.extract_add_cmd_part.with_replacement_part(pkg_str).run_with_output()
                    if not ok:
                        raise ValueError(f"Error when processing for '{pkg_str}': {stderr}")
                    pkgs.append(Package(pkg_str, add_cmd_part=part.strip()))

            return pkgs
        return stdout


async def load_user_configs(config_dir: Path) -> None:
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
                func: Command = FunctionCommand(USER_EXPORT[cmd["py_func_name"]])
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
        elif "piped_cmd" in cmd:
            assert type(cmd["piped_cmd"]) is list
            func = PipedCommand(cmd["piped_cmd"])
            return func
        else:
            await aERROR_EXIT(f"Command '{key} for manager '{mgr_name}' has unknown info '{cmd}'")
    elif isinstance(cmd, list):
        return CompoundCommand([await load_command(c, key, mgr_name) for c in cmd])
    else:
        await aERROR_EXIT(f"Unsupported config type '{type(cmd)}' for command '{key}' in manager '{mgr_name}'")
    assert False, "Unreachable code"


async def load_mgr_config(config_dir: Path, requested_mgrs: Iterable[str]) -> dict[str, PackageManager]:
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

        # configs that require special handling
        if "success_ret_code" in mgr_config:
            kwargs["success_ret_code"] = set(mgr_config.pop("success_ret_code"))

        for key in ["list_cmd", "add_cmd", "remove_cmd", "extract_add_cmd_part"]:
            cmd = mgr_config.pop(key, None)
            if cmd:
                kwargs[key] = await load_command(cmd, key, mgr_name)

        # pass the rest of the config as kwargs
        kwargs.update(mgr_config)

        try:
            pkg_mgr = PackageManager(**kwargs)  # type: ignore
        except TypeError as e:
            simplified_msg = str(e).replace(f"{PackageManager.__name__}.__init__()", "").strip()

            await aERROR_EXIT(f"Error loading package manager '{mgr_name}': {simplified_msg}")
        mgrs_def[mgr_name] = pkg_mgr

    for mgr_name in requested_mgrs:
        if mgr_name not in mgrs_def:
            await aERROR_EXIT(f"Manager for '{mgr_name}' not found in {pkg_mgr_config}")

    return dict(filter(lambda x: not x[1].disabled, mgrs_def.items()))


async def load_all(config_dir: Path = Path("./configs")):
    if not config_dir.is_dir():
        await aERROR_EXIT(f"Config directory '{config_dir}' does not exist.")

    with printer.PKG_CTX:
        with printer.PKG_CTX("load-conf"):
            await aINFO(f"Collecting desire package state in '{config_dir}/'...")
            await load_user_configs(config_dir)

            await aINFO(f"Loading manager definition at '{config_dir / 'pkgmgr.toml'}'...")
            managers = await load_mgr_config(config_dir, REQUESTED_MANAGERS.data_pair.keys())
        return managers


async def collect_state(
    requested_state: DeclaredPackageState, pkg_mgr: PackageManager, sort: bool = True
) -> tuple[list[Package], list[Package]]:
    """
    Collect the state of all package managers.
    """
    await aINFO("Checking packages state...")

    want_installed = requested_state.pkgs
    currently_installed_packages = set(await pkg_mgr.list_installed())

    #######################################################

    pkgs_wanted = set()
    for package in want_installed:
        if package not in currently_installed_packages:
            pkgs_wanted.add(package)

    #######################################################

    pkgs_not_recorded = currently_installed_packages - set(want_installed) - requested_state.ignore_pkgs

    if sort:
        return sorted(pkgs_wanted), sorted(pkgs_not_recorded)

    return list(pkgs_wanted), list(pkgs_not_recorded)


async def save_wanted_pkgs_to_file(
    file, pkg_mgr_name: str, pkgs_wanted: list[Package], pkgs_not_recorded: list[Package]
):
    IDEN_var_name = santise_variable_name(pkg_mgr_name)

    file.write("\n" + "#" * 25 + "\n")
    file.write(f"# {pkg_mgr_name}\n")
    file.write("#" * 25 + "\n")

    file.write(f'\n{IDEN_var_name} = MANAGERS["{IDEN_var_name}"]\n')

    # invert to bring the config up-to-speed

    if pkgs_not_recorded:
        file.write("\n# wanted\n")
        for pkg_name in pkgs_not_recorded:
            file.write(f"{IDEN_var_name} << {pkg_name.get_config_repr()}\n")
            await aINFO(f"Added {pkg_name}")
    if pkgs_wanted:
        file.write("\n# unwanted\n")
        for pkg in pkgs_wanted:
            file.write(f"{IDEN_var_name} >> {pkg.name!r}\n")
            await aINFO(f"To remove {pkg!r}")


def for_each_registered_mgr(managers: dict[str, PackageManager]):
    """
    Helper genrator to loop through defined managers and registered managers.
    """
    for pkg_mgr_name, pkg_mgr in managers.items():
        with printer.PKG_CTX(pkg_mgr_name):
            requested_state = REQUESTED_MANAGERS[pkg_mgr_name]
            yield pkg_mgr_name, pkg_mgr, requested_state


async def cmd_save(args: CLIOptions, managers: dict[str, PackageManager], target: Optional[str] = None) -> None:
    if not args.force and (args.config_dir / DEFAULT_SAVE_OUTPUT_FILE).is_file():
        # test if the file exists but is actually empty. (if so, its ok to overwrite)
        if os.stat(args.config_dir / DEFAULT_SAVE_OUTPUT_FILE).st_size > 0:
            # file is not empty
            await aERROR_EXIT(
                f"File '{DEFAULT_SAVE_OUTPUT_FILE}' already exists. Refusing to continue. "
                "Please organise your packages definition in the config directory first. [use -f to force]"
            )

    # since this is async, not thread, we can safely use a list to store result.
    packages_to_write = []

    async def inner_save(name: str, pkg_mgr: PackageManager, requested_state: DeclaredPackageState):
        try:
            pkgs_wanted, pkgs_not_recorded = await collect_state(requested_state, pkg_mgr)
        except ExitSignal:
            # perhaps this package uses binary that does not exists
            return

        if pkgs_wanted or pkgs_not_recorded:
            if not pkg_mgr.supports_save:
                await aWARN(f"Manager '{name}' has changes, but does not support saving packages to config. ")
                await aWARN("Use `diff_cmd` to see the changes.")
            else:
                packages_to_write.append((name, pkgs_wanted, pkgs_not_recorded))

    await apply_on_each_pkg(
        args.sync,
        functor=inner_save,
        managers=managers,
        target=target,
    )

    # only start a new file if we have something to write
    if packages_to_write:
        #######################################################
        # create options for user to select
        def get_info_confirm_func(pkg_name: str, msg: str, color: str):
            async def info_confirm(prefix: str):
                with printer.PKG_CTX("confirm"):
                    with printer.PKG_CTX(pkg_name):
                        await aINFO(f"{prefix}{msg}", color)

            return info_confirm

        options: list[UserSelectOption[tuple[str, Optional[Package], Optional[Package]]]] = []
        for name, pkgs_wanted, pkgs_not_recorded in packages_to_write:
            for package in pkgs_not_recorded:
                options.append(
                    UserSelectOption(
                        print=get_info_confirm_func(name, f"Adding {package}", GREEN),
                        data=(name, None, package),
                    )
                )
            for package in pkgs_wanted:
                options.append(
                    UserSelectOption(
                        print=get_info_confirm_func(name, f"Removing {package}", RED),
                        data=(name, package, None),
                    )
                )
        async with OPERATION_LOCK:
            # collect the options into a dict
            options = await ASK_USER("Do you want to save the changes?", options)
            if options:
                to_apply: dict[str, tuple[list[Package], list[Package]]] = {}
                for name, pkg_wanted, pkg_not_recorded in (o.data for o in options):
                    data = to_apply.setdefault(name, ([], []))
                    if pkg_wanted:
                        data[0].append(pkg_wanted)
                    if pkg_not_recorded:
                        data[1].append(pkg_not_recorded)
            #######################################################

            # Check if file exists and if import line needs to be added
            import_line = "from pkgmgr.registry import MANAGERS, Package\n\n"
            file_path = args.config_dir / DEFAULT_SAVE_OUTPUT_FILE
            needs_import = True

            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    if import_line in f.read():
                        needs_import = False

            with open(file_path, "a", encoding="utf-8") as f:
                if needs_import:
                    f.write(import_line)
                for name, (pkgs_wanted, pkgs_not_recorded) in to_apply.items():
                    await save_wanted_pkgs_to_file(f, name, pkgs_wanted, pkgs_not_recorded)


async def cmd_apply(args: CLIOptions, managers: dict[str, PackageManager], target: Optional[str] = None) -> None:
    async def inner_apply(name: str, pkg_mgr: PackageManager, requested_state: DeclaredPackageState):
        pkgs_wanted, pkgs_not_recorded = await collect_state(requested_state, pkg_mgr)

        if pkgs_wanted or pkgs_not_recorded:
            await aINFO("The following changes to packages are detected:")

            #######################################################
            # create options for user to select
            def get_info_confirm_func(msg: str, color: str):
                async def info_confirm(prefix: str):
                    # with printer.PKG_CTX("confirm"):
                    #     with printer.PKG_CTX(pkg_name):
                    await aINFO(f"{prefix}{msg}", color)

                return info_confirm

            can_install = not isinstance(pkg_mgr.add_cmd, UndefinedCommand)
            can_remove = not isinstance(pkg_mgr.remove_cmd, UndefinedCommand)
            if not can_install and not can_remove:
                await aWARN(f"Manager '{name}' does not support installing or removing packages. ")
                await aWARN("You can define `add_cmd` / `remove_cmd` in the config file to enable apply cmd.")

            #######################################################
            # create options for user to select
            options: list[UserSelectOption[tuple[Literal["wanted", "not_wanted"], Package]]] = []
            for package in pkgs_wanted:
                options.append(
                    UserSelectOption(
                        print=get_info_confirm_func(f"+ {package}", GREEN),
                        data=("wanted", package),
                    )
                )
            for package in pkgs_not_recorded:
                options.append(
                    UserSelectOption(
                        print=get_info_confirm_func(f"- {package}", RED),
                        data=("not_wanted", package),
                    )
                )

            async with OPERATION_LOCK:
                options = await ASK_USER("Do you want to apply the changes?", options)
                if options:
                    wanted, not_wanted = [], []
                    for desire, pkg in (o.data for o in options):
                        if desire == "wanted":
                            wanted.append(pkg)
                        else:
                            not_wanted.append(pkg)

                    if wanted:
                        if not can_install:
                            await aWARN(f"Manager '{name}' does not support installing packages.")
                        else:
                            if not await pkg_mgr.install(wanted):
                                await aERROR_EXIT("Failed to add packages.")

                    if not_wanted:
                        if not can_remove:
                            await aWARN(f"Manager '{name}' does not support removing packages.")
                        else:
                            if not await pkg_mgr.remove(not_wanted):
                                await aERROR_EXIT("Failed to remove packages.")

                    await aINFO("Applied.")
                else:
                    await aINFO("Aborted.")

        else:
            await aINFO("No Change.")

    await apply_on_each_pkg(
        args.sync,
        functor=inner_apply,
        managers=managers,
        target=target,
    )


async def cmd_diff(args: CLIOptions, managers: dict[str, PackageManager], target: Optional[str] = None) -> None:
    async def inner_diff(name, pkg_mgr, requested_state):
        pkgs_wanted, pkgs_not_recorded = await collect_state(requested_state, pkg_mgr)

        if pkgs_wanted or pkgs_not_recorded:
            await aINFO("Diff of current system against the configs:")

            for package in pkgs_wanted:
                await aINFO(f"+ {package}", GREEN)
            for package_name in pkgs_not_recorded:
                await aINFO(f"- {package_name}", RED)

        else:
            await aINFO("No Change.")

    await apply_on_each_pkg(
        args.sync,
        functor=inner_diff,
        managers=managers,
        target=target,
    )


async def apply_on_each_pkg(
    use_sync: bool,
    functor: Callable[[str, PackageManager, DeclaredPackageState], Any],
    managers: dict[str, PackageManager],
    target: Optional[str] = None,
):
    """
    A helper function to apply a function on each package manager.
    """

    async def wrapper(name, pkg_mgr, requested_state):
        # this wrapper enable the context manager to be used
        # in the async function
        with printer.PKG_CTX(name):
            return await functor(name, pkg_mgr, requested_state)

    registered_mgr = for_each_registered_mgr(managers)
    if target is not None and target not in managers:
        registered_mgr = list(filter(lambda x: x[0] == target, registered_mgr))
        if len(registered_mgr) == 0:
            await aERROR_EXIT(f"Target '{target}' not found in registered managers.")

    tasks = []
    for name, pkg_mgr, requested_state in for_each_registered_mgr(managers):
        if target is not None and name != target:
            # skip this package manager
            continue
        if use_sync:
            await wrapper(name, pkg_mgr, requested_state)
        else:
            tasks.append(wrapper(name, pkg_mgr, requested_state))

    # the taks returns nothing. if it did, those would be exception.
    for error in filter(None, await asyncio.gather(*tasks, return_exceptions=True)):
        raise error
