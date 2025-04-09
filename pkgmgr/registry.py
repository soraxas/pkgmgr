from dataclasses import dataclass, fields
from typing import Generator, Iterable, Optional, Union, Set, List
from .printer import aERROR_EXIT, WARN

USER_EXPORT = {}


def export(function):
    """
    Allow user to export a function to be used in the package manager.

    Example:
    ```
    from pkgmgr.registry import export

    @export
    def my_function():
        pass
    ```
    """
    if not callable(function):
        raise TypeError("export() requires a callable")

    USER_EXPORT[function.__name__] = function
    return function


@dataclass
class Package:
    """
    A class that represents a package.
    If install_cmd_part is None, it is assumed that the package is installed via its own name.
    """

    name: str
    install_cmd: Optional[str] = None
    extra: Optional[str] = None
    metadata: Optional[dict] = None

    def __post_init__(self):
        if self.install_cmd and self.extra:
            raise ValueError("Cannot have both install_cmd and extra")

    def get_install_cmd_part(self):
        if self.install_cmd:
            return self.install_cmd
        if self.extra:
            return f"{self.name} {self.extra}"
        return self.name

    def __lt__(self, other):
        return self.equality_key < other.equality_key

    @property
    def equality_key(self):
        """
        A key that can be used to compare two packages.
        """
        # return (self.name, self.install_cmd, self.extra)
        return self.name

    @property
    def is_unit(self):
        """
        Check if the package is a unit.
        """
        return self.install_cmd is None and self.extra is None and not self.metadata

    def __eq__(self, other):
        if isinstance(other, Package):
            return self.equality_key == other.equality_key
        elif isinstance(other, str) and self.is_unit:
            # If the other is a string and the package is a unit, we can compare by name
            return self.name == other
        raise NotImplementedError(f"Cannot compare Package with {type(other)}.")

    def __hash__(self):
        return hash(self.equality_key)

    def get_config_repr(self):
        """
        Get a string representation of the package for configuration.
        """
        if self.is_unit:
            return f"{self.name!r}"
        return self

    def __str__(self):
        if self.is_unit:
            # Only the name is present, so we return just the name
            return self.name

        # Automatically collect non-None and non-empty fields
        field_strs = [f"{self.name!r}"]

        field_strs.extend(
            [
                f"{f.name}={repr(getattr(self, f.name))}"
                for f in fields(self)
                if f.name != "name" and getattr(self, f.name) is not None
            ]
        )

        return f"Package({', '.join(field_strs)})"


def ensure_package(
    package: Union[str, Package, Iterable[Package]],
) -> Generator[Package, None, None]:
    """
    Ensure that the package is a Package instance.
    """
    if isinstance(package, str):
        yield Package(package)
        return
    elif isinstance(package, Package):
        yield package
        return
    else:
        try:
            some_object_iterator = iter(package)
        except TypeError as te:
            # not iterable.
            aERROR_EXIT(
                f"Package {package} is not a string, Package instance, nor list of Packages. Please check your configuration."
            )
        for pkg in some_object_iterator:
            yield from ensure_package(pkg)


@dataclass
class DeclaredPackageManager:
    """
    A class that represents a manager for user to declare packages.
    """

    name: str
    pkgs: Set[Package]
    ignore_pkgs: Set[Package]

    def add(
        self, package: Union[str, Package, Iterable[Package]]
    ) -> "DeclaredPackageManager":
        for pkg in ensure_package(package):
            if pkg in self.pkgs:
                WARN(
                    f"'{pkg}' was already added to '{self.name}'.",
                )
            else:
                self.pkgs.add(pkg)
        return self

    def __lshift__(self, *args) -> "DeclaredPackageManager":
        return self.add(*args)

    def remove(
        self, package: Union[str, Package, Iterable[Package]]
    ) -> "DeclaredPackageManager":
        for pkg in ensure_package(package):
            try:
                self.pkgs.remove(pkg)
            except KeyError:
                WARN(
                    f"'{pkg}' does not exists in '{self.name}'.",
                )
        return self

    def __rshift__(self, *args) -> "DeclaredPackageManager":
        return self.remove(*args)

    def ignore(self, *args: str) -> "DeclaredPackageManager":
        """
        Ignore packages.
        """
        for pkg in args:
            self.ignore_pkgs.add(Package(pkg))
        return self


@dataclass
class DeclaredPackageManagerRegistry:
    """
    A class to store the declared package managers.
    """

    data_pair: dict[str, DeclaredPackageManager]

    def __init__(self):
        self.data_pair = {}

    def __getitem__(self, item: str) -> DeclaredPackageManager:
        try:
            return self.data_pair[item]
        except KeyError:
            pass
        self.data_pair[item] = DeclaredPackageManager(
            name=item, pkgs=set(), ignore_pkgs=set()
        )
        return self.data_pair[item]


MANAGERS = DeclaredPackageManagerRegistry()
