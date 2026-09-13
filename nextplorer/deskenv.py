"""Intégration gestionnaire de fichiers (GNOME/Nautilus, KDE/Dolphin) et
pilotage du montage géré par nextplorer (voir `nextplorer setup`)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .setup import SYSTEMD_UNIT_NAME

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NAUTILUS_EXT_SOURCE = PROJECT_ROOT / "nautilus-extension" / "nextplorer_nautilus.py"
NAUTILUS_EXT_TARGET = Path.home() / ".local" / "share" / "nautilus-python" / "extensions" / "nextplorer_nautilus.py"

KDE_SERVICEMENU_SOURCE = PROJECT_ROOT / "kde-integration" / "nextplorer.desktop"
KDE_SERVICEMENU_TARGET = Path.home() / ".local" / "share" / "kio" / "servicemenus" / "nextplorer.desktop"


def _current_desktop() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def _install_gnome() -> None:
    NAUTILUS_EXT_TARGET.parent.mkdir(parents=True, exist_ok=True)
    if NAUTILUS_EXT_TARGET.exists() or NAUTILUS_EXT_TARGET.is_symlink():
        NAUTILUS_EXT_TARGET.unlink()
    NAUTILUS_EXT_TARGET.symlink_to(NAUTILUS_EXT_SOURCE)
    subprocess.run(["nautilus", "-q"], check=False)
    print(f"Extension Nautilus installée ({NAUTILUS_EXT_TARGET}).")


def _install_kde() -> None:
    KDE_SERVICEMENU_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KDE_SERVICEMENU_SOURCE, KDE_SERVICEMENU_TARGET)
    KDE_SERVICEMENU_TARGET.chmod(0o755)  # Dolphin ignore les menus de service non exécutables
    for tool in ("kbuildsycoca6", "kbuildsycoca5"):
        if shutil.which(tool):
            subprocess.run([tool], check=False)
            break
    print(f"Menu de service KDE installé ({KDE_SERVICEMENU_TARGET}).")


def install_integration() -> int:
    """Détecte GNOME et/ou KDE (via XDG_CURRENT_DESKTOP, avec heuristiques de
    repli) et installe l'intégration correspondante. Peut installer les deux
    si les deux semblent présents — sans risque, juste inutile sur l'autre."""
    desktop = _current_desktop()
    installed = False

    if "GNOME" in desktop or shutil.which("nautilus"):
        _install_gnome()
        installed = True
    if "KDE" in desktop or (Path.home() / ".local" / "share" / "kio").exists():
        _install_kde()
        installed = True

    if not installed:
        print(
            f"Environnement de bureau non reconnu (XDG_CURRENT_DESKTOP={desktop!r}) — "
            "aucune intégration installée automatiquement. Installe-la manuellement "
            "(voir README) ou signale ton environnement.",
            file=sys.stderr,
        )
        return 1
    return 0


def mount_control(action: str) -> int:
    """Fine surcouche à systemctl --user pour le service de montage créé par
    `nextplorer setup`, pour ne pas exiger de connaître systemd."""
    if not shutil.which("systemctl"):
        print("systemctl introuvable — le montage n'est pas géré par nextplorer sur ce poste.", file=sys.stderr)
        return 1
    result = subprocess.run(["systemctl", "--user", action, SYSTEMD_UNIT_NAME])
    return result.returncode
