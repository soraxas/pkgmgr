from dataclasses import dataclass
from typing import Generator, Iterable, Optional, Union
from .printer import ERROR_EXIT


class Package:
    """
    A class that represents a package.
    If install_cmd_part is None, it is assumed that the package is installed via its own name.
    """

    def __init__(
        self,
        name: str,
        *,
        install_cmd: Optional[str] = None,
        extra: Optional[str] = None,
    ):
        if install_cmd and extra:
            raise ValueError("Cannot have both install_cmd and extra")
        self.name = name
        self.install_cmd = install_cmd
        self.extra = extra

    def get_part(self):
        if self.install_cmd:
            return self.install_cmd
        if self.extra:
            return f"{self.name} {self.extra}"
        return self.name

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return f"Package({self.name})"


def ensure_package(
    package: Union[str, Package, Iterable[Package]],
) -> Generator[Package]:
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
            ERROR_EXIT(
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
    pkgs: list[Package]

    def add(
        self, package: Union[str, Package, Iterable[Package]]
    ) -> "DeclaredPackageManager":
        self.pkgs.extend(ensure_package(package))
        return self

    def __lshift__(self, *args) -> "DeclaredPackageManager":
        return self.add(*args)

    def remove(self, package_name: str) -> "DeclaredPackageManager":
        self.pkgs = [pkg for pkg in self.pkgs if pkg.name != package_name]
        return self

    def __rshift__(self, package_name: str) -> "DeclaredPackageManager":
        return self.remove(package_name)


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
        self.data_pair[item] = DeclaredPackageManager(name=item, pkgs=[])
        return self.data_pair[item]


MANAGERS = DeclaredPackageManagerRegistry()
