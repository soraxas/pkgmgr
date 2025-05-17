# pkgmgr

<a href="https://pypi.org/project/pkgmgr/">
<img src="https://img.shields.io/pypi/v/pkgmgr.svg?label=PyPI&color=blue" alt="PyPI version">
</a>
<a href="https://pypi.org/project/pkgmgr/">
<img src="https://img.shields.io/pypi/dm/pkgmgr.svg?label=Downloads&color=blue" alt="PyPI downloads">
</a>
<a href="https://github.com/soraxas/pkgmgr/blob/main/LICENSE">
<img src="https://img.shields.io/github/license/soraxas/pkgmgr.svg" alt="License">
</a>
<a href="https://www.python.org/downloads/">
<img src="https://img.shields.io/pypi/pyversions/pkgmgr.svg?logo=python&logoColor=white" alt="Python versions">
</a>
<a href="https://github.com/astral-sh/ruff">
<img src="https://img.shields.io/badge/linter-ruff-0f172a?logo=ruff&logoColor=white" alt="Linter: Ruff">
</a>

A repeatable and self-documenting OS package manager.

A wannabe [nixos](https://nixos.org/) and [aconfmgr](https://github.com/CyberShadow/aconfmgr), `pkgmgr` aims to bring declarative package management to your system—without the intrusiveness or complexity of NixOS. Manage your system configuration and installed packages in a reproducible, version-controlled way.

## Features

- Declarative package management
- Less intrusive than NixOS
- Inspired by tools like aconfmgr

## Examples

1. Get differences between system state and saved config

  <div align="center">
    <img width="986" alt="Screenshot diff" src="https://github.com/user-attachments/assets/38e55646-32b6-4fb2-8bc6-07e6ae3e15c4" />
  </div>


2. Apply the changes to make system state match the saved config

  <div align="center">
    <img width="986" alt="Screenshot apply" src="https://github.com/user-attachments/assets/f82f58f9-f470-4452-9b98-805f77330185" />
  </div>
