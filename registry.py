from dataclasses import dataclass


@dataclass
class DeclaredPackageManager:
    name: str
    pkgs: list[str]

    def add(self, package_name: str) -> "DeclaredPackageManager":
        self.pkgs.append(package_name)
        return self

    def __lshift__(self, package_name: str) -> "DeclaredPackageManager":
        return self.add(package_name)

    def remove(self, package_name: str) -> "DeclaredPackageManager":
        self.pkgs.remove(package_name)
        return self

    def __rshift__(self, package_name: str) -> "DeclaredPackageManager":
        return self.remove(package_name)


@dataclass
class DeclaredPackageManagerRegistry:
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