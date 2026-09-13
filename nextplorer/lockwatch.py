"""Verrouillage applicatif à l'ouverture de documents bureautiques (phase 2).

Politique retenue : on avertit mais on ne bloque jamais. Si un collègue a
déjà le fichier ouvert, on l'ouvre quand même, en lecture seule, avec une
notification indiquant qui et depuis combien de temps.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from . import platform, webdav
from .config import Config
from .webdav import LockInfo

OFFICE_EXTENSIONS = {
    ".odt", ".ods", ".odp", ".odg", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".rtf", ".csv",
}

LOCK_TIMEOUT_SECONDS = 1800
RENEW_INTERVAL_SECONDS = 600
POLL_INTERVAL_SECONDS = 2
STARTUP_TIMEOUT_SECONDS = 120


def is_office_document(local_path: str) -> bool:
    return Path(local_path).suffix.lower() in OFFICE_EXTENSIONS


def _sidecar_lock_path(local_path: Path) -> Path:
    """Fichier de verrou que LibreOffice crée/supprime lui-même à côté du document ouvert."""
    return local_path.parent / f".~lock.{local_path.name}#"


def format_duration(seconds: int) -> str:
    minutes = max(seconds // 60, 0)
    if minutes < 1:
        return "moins d'une minute"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


def foreign_lock(config: Config, relative_path: str) -> LockInfo | None:
    """Renvoie les infos du verrou si le fichier est verrouillé par quelqu'un d'autre."""
    status = webdav.lock_status(config.account, relative_path)
    if status is None or status.owner_uid == webdav.own_uid(config.account):
        return None
    return status


def open_readonly(local_path: str) -> None:
    subprocess.Popen(["soffice", "--view", local_path])


def open_editable(config: Config, relative_path: str, local_path: str) -> None:
    """Pose le verrou serveur, ouvre le document, et lance la surveillance en arrière-plan
    pour relâcher le verrou dès la fermeture (dans un processus détaché : cette fonction
    ne doit pas bloquer l'appelant)."""
    webdav.acquire_lock(config.account, relative_path, LOCK_TIMEOUT_SECONDS)
    subprocess.Popen(["soffice", local_path])
    subprocess.Popen(
        [sys.executable, "-m", "nextplorer.cli", "_watch-lock", relative_path, local_path],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def watch_and_release(config: Config, relative_path: str, local_path: str) -> None:
    """Attend l'ouverture puis la fermeture du document (via son fichier de verrou
    LibreOffice), en renouvelant le verrou serveur tant qu'il reste ouvert, puis le
    relâche. À lancer dans un processus séparé (voir `open_editable`).

    Un crash de LibreOffice laisse le fichier de verrou en place (contrairement à
    une fermeture normale) : on considère aussi le document fermé si plus aucun
    LibreOffice ne tourne, pour ne pas garder le verrou serveur indéfiniment.
    """
    sidecar = _sidecar_lock_path(Path(local_path))

    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while not sidecar.exists() and time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)

    last_renew = time.monotonic()
    while sidecar.exists() and platform.is_office_app_running():
        time.sleep(POLL_INTERVAL_SECONDS)
        if time.monotonic() - last_renew > RENEW_INTERVAL_SECONDS:
            webdav.acquire_lock(config.account, relative_path, LOCK_TIMEOUT_SECONDS)
            last_renew = time.monotonic()

    webdav.release_lock(config.account, relative_path)
