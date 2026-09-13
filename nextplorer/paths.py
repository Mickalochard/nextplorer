"""Chemins de configuration utilisateur, portables Linux/Windows."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def user_config_dir(app_name: str) -> Path:
    """Dossier de config d'une appli pour l'utilisateur courant.

    Linux : ~/.config/<app_name>/  (convention XDG).
    Windows : %APPDATA%\\<app_name>\\  — c'est aussi là que rclone range son
    propre rclone.conf par défaut, pas dans ~/.config (qui n'existe pas
    nativement sous Windows).
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / app_name
    return Path.home() / ".config" / app_name
