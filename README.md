# pkgmgr

A repeatable and self-documenting OS package manager.

A wannabe [nixos](https://nixos.org/) and [aconfmgr](https://github.com/CyberShadow/aconfmgr), `pkgmgr` aims to bring declarative package management to your system—without the intrusiveness or complexity of NixOS. Manage your system configuration and installed packages in a reproducible, version-controlled way.

## Features

- Declarative package management
- Less intrusive than NixOS
- Inspired by tools like aconfmgr

1. Get differences between system state and saved config

  <div align="center">
    <img width="986" alt="Screenshot diff" src="https://github.com/user-attachments/assets/38e55646-32b6-4fb2-8bc6-07e6ae3e15c4" />
  </div>


2. Apply the changes to make system state match the saved config

  <div align="center">
    <img width="986" alt="Screenshot apply" src="https://github.com/user-attachments/assets/f82f58f9-f470-4452-9b98-805f77330185" />
  </div>
