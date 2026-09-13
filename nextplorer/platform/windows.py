"""Implémentation Windows de la couche d'abstraction plateforme.

Non testé en conditions réelles au moment de l'écriture (poste de dev sous
Linux) — écrit d'après la documentation Microsoft/rclone/WinFsp, à valider
sur un vrai poste Windows (voir docs/BUILD_WINDOWS.md)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import winreg
from pathlib import Path

import psutil
import pyperclip

from .. import state

MOUNT_NAME = "NextplorerMount"

# ProgId qu'on déclare pour gérer https — pas un vrai protocole custom : on
# se porte simplement candidat dans le mécanisme "Default Programs".
APP_PROGID = "Nextplorer.https"
APP_NAME = "Nextplorer"


def notify(title: str, body: str, icon: str = "folder-remote") -> None:
    try:
        from win11toast import toast
        toast(title, body)
    except Exception:
        pass  # notification best-effort, jamais bloquant


def copy_to_clipboard(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def open_path(path: str) -> None:
    os.startfile(path)  # noqa: S606 — équivalent direct de xdg-open sous Windows


def _own_command_prefix() -> str:
    """Commande pour se relancer soi-même : l'exe gelé (PyInstaller) tel
    quel, ou `python -m nextplorer.cli` en développement/pip install."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m nextplorer.cli'


def _current_https_progid() -> str | None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "ProgId")
            return value
    except OSError:
        return None


def _resolve_progid_open_command(progid: str) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{progid}\shell\open\command") as key:
            template, _ = winreg.QueryValueEx(key, None)
            return template
    except OSError:
        return None


def launch_browser(url: str) -> None:
    """Ouvre un lien dans le VRAI navigateur — jamais via open_path, qui
    reboucle sur nous si on est enregistré comme gestionnaire https."""
    saved_progid = state.load().get("fallback_browser_progid")
    if saved_progid:
        template = _resolve_progid_open_command(saved_progid)
        if template:
            command = template.replace("%1", url) if "%1" in template else f'{template} "{url}"'
            subprocess.run(command, shell=True, check=False)
            return
    open_path(url)


def install_file_manager_integration() -> int:
    """Ajoute deux entrées au menu clic-droit de l'Explorateur, pour
    n'importe quel fichier (HKEY_CURRENT_USER, pas besoin d'admin, pas de
    DLL COM à enregistrer)."""
    prefix = _own_command_prefix()
    entries = [
        ("Nextplorer.CopyLink", "Copier le lien Nextcloud", "copy"),
        ("Nextplorer.ShareLink", "Copier un lien externe (public)", "share"),
    ]
    for verb, label, action in entries:
        key_path = rf"Software\Classes\*\shell\{verb}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, label)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{prefix} {action} "%1"')

    print("Entrées ajoutées au menu clic-droit de l'Explorateur (Copier le lien / Copier un lien externe).")
    return 0


def _register_https_capability() -> None:
    prefix = _own_command_prefix()

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{APP_PROGID}\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{prefix} handle-url "%1"')

    caps_path = rf"Software\{APP_NAME}\Capabilities"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, caps_path) as key:
        winreg.SetValueEx(key, "ApplicationName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(
            key, "ApplicationDescription", 0, winreg.REG_SZ,
            "Liens Nextcloud portables et verrouillage applicatif",
        )
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, caps_path + r"\URLAssociations") as key:
        winreg.SetValueEx(key, "https", 0, winreg.REG_SZ, APP_PROGID)
        winreg.SetValueEx(key, "http", 0, winreg.REG_SZ, APP_PROGID)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications") as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, caps_path)


def install_url_handler(account_host: str) -> int:
    """Déclare nextplorer comme gestionnaire https possible, puis renvoie
    vers les Paramètres Windows : depuis Windows 8, aucune application ne
    peut choisir ce rôle par défaut par elle-même (anti-détournement de
    navigateur). Pour un parc géré (GPO/Intune), voir `nextplorer
    export-gpo-xml` — ça évite ce choix manuel à chaque poste."""
    saved = state.load()
    current_progid = _current_https_progid()
    if current_progid and current_progid != APP_PROGID and "fallback_browser_progid" not in saved:
        saved["fallback_browser_progid"] = current_progid
        state.save(saved)

    _register_https_capability()

    subprocess.run(["cmd", "/c", "start", "ms-settings:defaultapps"], check=False)
    print(f"Nextplorer est enregistré comme gestionnaire possible pour https://{account_host}/f/…")
    print(
        "Windows ne permet pas de le rendre défaut automatiquement (protection "
        "anti-détournement de navigateur) : dans la fenêtre Paramètres qui vient "
        "de s'ouvrir, choisis « Nextplorer » pour le protocole HTTPS."
    )
    print("Pour un parc de postes géré (GPO/Intune), voir `nextplorer export-gpo-xml`.")
    return 0


def uninstall_url_handler() -> int:
    saved_progid = state.load().get("fallback_browser_progid")
    for key_path in (
        rf"Software\Classes\{APP_PROGID}\shell\open\command",
        rf"Software\Classes\{APP_PROGID}\shell\open",
        rf"Software\Classes\{APP_PROGID}\shell",
        rf"Software\Classes\{APP_PROGID}",
        rf"Software\{APP_NAME}\Capabilities\URLAssociations",
        rf"Software\{APP_NAME}\Capabilities",
    ):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except OSError:
            pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications", 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except OSError:
        pass

    print("Nextplorer retiré des applications candidates pour https.")
    if saved_progid:
        print(f"Rouvre les Paramètres Windows si tu veux repasser explicitement sur ton navigateur précédent ({saved_progid}).")
    return 0


def export_gpo_xml() -> int:
    """Génère un XML d'association par défaut (format DISM
    /Export-DefaultAppAssociations) prêt à déployer via la stratégie de
    groupe « Set a default associations configuration file », pour router
    https vers Nextplorer sur tout un parc de postes sans action utilisateur.
    Voir docs/BUILD_WINDOWS.md pour le déploiement GPO."""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<DefaultAssociations>
    <Association Identifier="https" ProgId="{APP_PROGID}" ApplicationName="{APP_NAME}" />
    <Association Identifier="http" ProgId="{APP_PROGID}" ApplicationName="{APP_NAME}" />
</DefaultAssociations>
"""
    output = Path.cwd() / "NextplorerDefaultAppAssociations.xml"
    output.write_text(xml, encoding="utf-8")
    print(f"Fichier généré : {output}")
    print(
        "Déploiement : stratégie de groupe Ordinateur > Modèles d'administration > "
        "Composants Windows > Explorateur de fichiers > « Set a default associations "
        "configuration file », avec le chemin UNC de ce fichier."
    )
    return 0


def _winfsp_installed() -> bool:
    for candidate in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WinFsp",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "WinFsp",
    ):
        if candidate.exists():
            return True
    return False


def setup_permanent_mount(remote: str, local_path: Path) -> bool:
    """Crée une tâche planifiée qui monte `remote` sur `local_path` à chaque
    connexion — l'équivalent Windows d'un service systemd --user. Renvoie
    False (dégradation propre) si WinFsp (requis par rclone pour monter sous
    Windows) n'est pas installé."""
    if not _winfsp_installed():
        print(
            "WinFsp n'est pas installé (nécessaire pour monter Nextcloud sous Windows).\n"
            "Installe-le puis relance `nextplorer setup` :\n"
            "  winget install -e --id WinFsp.WinFsp",
            file=sys.stderr,
        )
        return False

    from ..config import RCLONE_CONF_PATH

    rclone_bin = shutil.which("rclone") or "rclone.exe"
    task_command = (
        f'"{rclone_bin}" mount {remote}: "{local_path}" '
        f'--config "{RCLONE_CONF_PATH}" --vfs-cache-mode full --vfs-cache-max-age 72h'
    )
    result = subprocess.run(
        [
            "schtasks", "/create", "/f",
            "/sc", "onlogon",
            "/rl", "limited",
            "/tn", MOUNT_NAME,
            "/tr", task_command,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Échec de la création de la tâche planifiée : {result.stderr.strip()}", file=sys.stderr)
        return False

    subprocess.run(["schtasks", "/run", "/tn", MOUNT_NAME], capture_output=True, text=True)
    return True


def mount_status_summary() -> str:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", MOUNT_NAME, "/fo", "LIST"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return "absente"
    for line in result.stdout.splitlines():
        if line.lower().startswith("status:"):
            return line.split(":", 1)[1].strip()
    return "inconnu"


def mount_control(action: str) -> int:
    verb = {"start": "/run", "stop": "/end", "status": "/query"}.get(action)
    if verb is None:
        print(f"Action inconnue : {action}", file=sys.stderr)
        return 1
    extra = ["/v", "/fo", "LIST"] if action == "status" else []
    result = subprocess.run(["schtasks", verb, "/tn", MOUNT_NAME, *extra])
    return result.returncode


def is_office_app_running() -> bool:
    names = {"soffice.bin", "soffice.exe"}
    return any((p.info.get("name") or "") in names for p in psutil.process_iter(["name"]))
