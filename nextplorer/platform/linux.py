"""Implémentation Linux (GNOME/KDE) de la couche d'abstraction plateforme."""
from __future__ import annotations

import configparser
import os
import re
import shlex
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

import psutil

from .. import state

MOUNT_NAME = "nextplorer-mount.service"

HANDLER_DESKTOP_ID = "nextplorer-open.desktop"
DESKTOP_DIR = Path.home() / ".local" / "share" / "applications"

_INTEGRATIONS_PKG = "nextplorer._integrations"
NAUTILUS_EXT_TARGET = Path.home() / ".local" / "share" / "nautilus-python" / "extensions" / "nextplorer_nautilus.py"
KDE_SERVICEMENU_TARGET = Path.home() / ".local" / "share" / "kio" / "servicemenus" / "nextplorer.desktop"

_DESKTOP_APP_DIRS = [
    Path.home() / ".local" / "share" / "applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
    Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
    Path("/var/lib/flatpak/exports/share/applications"),
]
_DESKTOP_FIELD_CODE_RE = re.compile(r"%[fFuUdDnNickvm]")


def notify(title: str, body: str, icon: str = "folder-remote") -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "--icon", icon, title, body], check=False)


def copy_to_clipboard(text: str) -> bool:
    # wl-copy et xclip se détachent en arrière-plan pour continuer à servir le
    # presse-papiers après leur retour ; sans ça ils héritent de notre
    # stdout/stderr et un appelant qui lit jusqu'à l'EOF (`$(...)`, `| tail`)
    # reste bloqué indéfiniment tant que ce processus détaché vit.
    if shutil.which("wl-copy"):
        subprocess.run(
            ["wl-copy"], input=text.encode(), check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    if shutil.which("xclip"):
        subprocess.run(
            ["xclip", "-selection", "clipboard"], input=text.encode(), check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    return False


def open_path(path: str) -> None:
    subprocess.run(["xdg-open", path], check=False)


def _resolve_desktop_exec(desktop_id: str) -> list[str] | None:
    """Résout la commande Exec= d'un .desktop, sans dépendre de gtk-launch
    (absent sous KDE sans paquets GTK) ni de gio (GNOME/GLib uniquement)."""
    for directory in _DESKTOP_APP_DIRS:
        candidate = directory / desktop_id
        if not candidate.is_file():
            continue
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(candidate)
        exec_line = parser.get("Desktop Entry", "Exec", fallback=None)
        if not exec_line:
            return None
        return shlex.split(_DESKTOP_FIELD_CODE_RE.sub("", exec_line))
    return None


def launch_browser(url: str) -> None:
    """Ouvre un lien dans le VRAI navigateur — jamais via xdg-open, qui reboucle sur nous."""
    saved_browser = state.load().get("fallback_browser_desktop")
    if saved_browser:
        command = _resolve_desktop_exec(saved_browser)
        if command:
            subprocess.run([*command, url], check=False)
            return
    subprocess.run(["xdg-open", url], check=False)


def _integration_bytes(filename: str) -> bytes:
    return resources.files(_INTEGRATIONS_PKG).joinpath(filename).read_bytes()


def _current_desktop() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def _install_gnome() -> None:
    NAUTILUS_EXT_TARGET.parent.mkdir(parents=True, exist_ok=True)
    if NAUTILUS_EXT_TARGET.exists() or NAUTILUS_EXT_TARGET.is_symlink():
        NAUTILUS_EXT_TARGET.unlink()
    NAUTILUS_EXT_TARGET.write_bytes(_integration_bytes("nautilus_extension.py"))
    subprocess.run(["nautilus", "-q"], check=False)
    print(f"Extension Nautilus installée ({NAUTILUS_EXT_TARGET}).")


def _install_kde() -> None:
    KDE_SERVICEMENU_TARGET.parent.mkdir(parents=True, exist_ok=True)
    KDE_SERVICEMENU_TARGET.write_bytes(_integration_bytes("nextplorer.desktop"))
    KDE_SERVICEMENU_TARGET.chmod(0o755)  # Dolphin ignore les menus de service non exécutables
    for tool in ("kbuildsycoca6", "kbuildsycoca5"):
        if shutil.which(tool):
            subprocess.run([tool], check=False)
            break
    print(f"Menu de service KDE installé ({KDE_SERVICEMENU_TARGET}).")


def install_file_manager_integration() -> int:
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


def install_url_handler(account_host: str) -> int:
    """Fait de nextplorer le gestionnaire des liens https : Nextcloud ouvre en local, le reste va au navigateur."""
    current = subprocess.run(
        ["xdg-mime", "query", "default", "x-scheme-handler/https"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()

    saved = state.load()
    if current and current != HANDLER_DESKTOP_ID and "fallback_browser_desktop" not in saved:
        saved["fallback_browser_desktop"] = current
        state.save(saved)

    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    nextplorer_bin = shutil.which("nextplorer") or str(Path(sys.executable).parent / "nextplorer")
    (DESKTOP_DIR / HANDLER_DESKTOP_ID).write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=nextplorer (ouverture Nextcloud)\n"
        "NoDisplay=true\n"
        f"Exec={nextplorer_bin} handle-url %u\n"
        "MimeType=x-scheme-handler/https;\n"
        "Terminal=false\n"
    )
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(DESKTOP_DIR)], check=False)

    subprocess.run(["xdg-mime", "default", HANDLER_DESKTOP_ID, "x-scheme-handler/https"], check=True)

    print(f"Gestionnaire installé pour https://{account_host}/f/…")
    print(f"Navigateur conservé pour tous les autres liens : {state.load().get('fallback_browser_desktop', '?')}")
    return 0


def uninstall_url_handler() -> int:
    previous = state.load().get("fallback_browser_desktop")
    if not previous:
        print("Aucun navigateur précédent enregistré — rien à restaurer.", file=sys.stderr)
        return 1
    subprocess.run(["xdg-mime", "default", previous, "x-scheme-handler/https"], check=True)
    print(f"Navigateur par défaut restauré : {previous}")
    return 0


def _fusermount_binary() -> str:
    return shutil.which("fusermount3") or shutil.which("fusermount") or "fusermount3"


def setup_permanent_mount(remote: str, local_path: Path) -> bool:
    """Écrit et active un service systemd --user qui monte `remote` sur
    `local_path` à chaque connexion. Renvoie False (dégradation propre, pas
    fatale) si systemd --user est indisponible."""
    from ..config import RCLONE_CONF_PATH

    rclone_bin = shutil.which("rclone") or "/usr/bin/rclone"
    unit = f"""[Unit]
Description=Montage Nextcloud nextplorer ({local_path})
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart={rclone_bin} mount {remote}: {local_path} --config {RCLONE_CONF_PATH} --vfs-cache-mode full --vfs-cache-max-age 72h
ExecStop={_fusermount_binary()} -u {local_path}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / MOUNT_NAME).write_text(unit)

    if not shutil.which("systemctl"):
        return False
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    result = subprocess.run(
        ["systemctl", "--user", "enable", "--now", MOUNT_NAME],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Avertissement : impossible d'activer le service systemd ({result.stderr.strip()})", file=sys.stderr)
        return False
    return True


def mount_status_summary() -> str:
    if not shutil.which("systemctl"):
        return "inconnu (systemctl introuvable)"
    result = subprocess.run(
        ["systemctl", "--user", "is-active", MOUNT_NAME],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or "inconnu"


def mount_control(action: str) -> int:
    """Fine surcouche à systemctl --user pour le service de montage créé par
    `nextplorer setup`, pour ne pas exiger de connaître systemd."""
    if not shutil.which("systemctl"):
        print("systemctl introuvable — le montage n'est pas géré par nextplorer sur ce poste.", file=sys.stderr)
        return 1
    result = subprocess.run(["systemctl", "--user", action, MOUNT_NAME])
    return result.returncode


def export_gpo_xml() -> int:
    print("Le déploiement par stratégie de groupe est spécifique à Windows — rien à faire sous Linux.", file=sys.stderr)
    return 1


def is_office_app_running() -> bool:
    names = {"soffice.bin", "soffice.exe"}
    return any((p.info.get("name") or "") in names for p in psutil.process_iter(["name"]))
