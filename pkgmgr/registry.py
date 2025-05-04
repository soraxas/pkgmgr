from dataclasses import dataclass, fields
from typing import Generator, Iterable, Optional, Union, Set
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
    If add_cmd_part is None, it is assumed that the package is installed via its own name.
    """

    name: str
    add_cmd_part: Optional[str] = None
    extra: Optional[str] = None
    metadata: Optional[dict] = None

    def __post_init__(self):
        if self.add_cmd_part and self.extra:
            raise ValueError("Cannot have both add_cmd_part and extra")
        if not self.extra:  # avoid whitespace
            self.extra = None
        if (
            not self.add_cmd_part or self.add_cmd_part == self.name
        ):  # pointless to store add_cmd_part if its the same as name
            self.add_cmd_part = None

    def get_add_cmd_part(self):
        if self.add_cmd_part:
            return self.add_cmd_part
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
        # return (self.name, self.add_cmd_part, self.extra)
        return self.name

    @property
    def is_unit(self):
        """
        Check if the package is a unit.
        """
        return self.add_cmd_part is None and self.extra is None and not self.metadata

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
        except TypeError:
            # not iterable.
            aERROR_EXIT(
                f"Package {package} is not a string, Package instance, nor list of Packages. Please check your configuration."
            )
        for pkg in some_object_iterator:
            yield from ensure_package(pkg)


class FalseDefaultDict:
    """
    A custom object that returns False for all attribute accesses unless explicitly set.

    Attributes are stored internally in a dictionary. If an attribute is accessed
    but has not been set, it returns False instead of raising an AttributeError.
    """

    def __init__(self):
        self._data = {}

    def __getattr__(self, name):
        return self._data.get(name, False)

    def __setattr__(self, name, value):
        if name == "_data":
            super().__setattr__(name, value)
        else:
            self._data[name] = value

    def __delattr__(self, name):
        if name in self._data:
            del self._data[name]

    def __repr__(self):
        return "Data({})".format(",".join(f"{k}={v}" for (k, v) in self._data.items()))


@dataclass
class DeclaredPackageState:
    """
    A class that allows user to declare desire package state.
    """

    name: str
    pkgs: Set[Package]
    ignore_pkgs: Set[Package]

    def add(self, package: Union[str, Package, Iterable[Package]]) -> "DeclaredPackageState":
        for pkg in ensure_package(package):
            if pkg in self.pkgs:
                WARN(
                    f"'{pkg}' was already added to '{self.name}'.",
                )
            else:
                self.pkgs.add(pkg)
        return self

    def __lshift__(self, *args) -> "DeclaredPackageState":
        return self.add(*args)

    def remove(self, package: Union[str, Package, Iterable[Package]]) -> "DeclaredPackageState":
        for pkg in ensure_package(package):
            try:
                self.pkgs.remove(pkg)
            except KeyError:
                WARN(
                    f"'{pkg}' does not exists in '{self.name}'.",
                )
        return self

    def __rshift__(self, *args) -> "DeclaredPackageState":
        return self.remove(*args)

    def ignore(self, *args: str) -> "DeclaredPackageState":
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

    data_pair: dict[str, DeclaredPackageState]

    def __init__(self):
        self.data_pair = {}

    def __getitem__(self, item: str) -> DeclaredPackageState:
        try:
            return self.data_pair[item]
        except KeyError:
            pass
        self.data_pair[item] = DeclaredPackageState(name=item, pkgs=set(), ignore_pkgs=set())
        return self.data_pair[item]


# This is a singleton object that stores the declared package managers.
MANAGERS = DeclaredPackageManagerRegistry()
# This is a global object that will allows user to store their own data.
USER_DATA = FalseDefaultDict()
