from dataclasses import dataclass
from typing import Optional, Union

@dataclass
class Package:
    """
    A class that represents a package.
    If install_cmd_part is None, it is assumed that the package is installed via its own name.
    """
    name: str
    install_cmd_part: Optional[str] = None

    def get_part(self):
        return self.name if self.install_cmd_part is None else self.install_cmd_part

    def __hash__(self):
        return hash(self.name)

@dataclass
class DeclaredPackageManager:
    """
    A class that represents a manager for user to declare packages.
    """
    name: str
    pkgs: list[str]

    def add(self, package: Union[str, Package]) -> "DeclaredPackageManager":
        if isinstance(package, str):
            package = Package(package)
        self.pkgs.append(package)
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