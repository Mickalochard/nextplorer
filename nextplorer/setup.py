"""Assistant de configuration : `nextplorer setup`.

Demande serveur + identifiants, crée le remote rclone correspondant, met en
place un montage permanent (service systemd --user sous Linux, tâche
planifiée sous Windows — voir nextplorer/platform/), et écrit
~/.config/nextplorer/config.json. Objectif : qu'une personne qui n'a jamais
touché rclone reparte avec un poste fonctionnel après cette seule commande.
"""
from __future__ import annotations

import getpass
import subprocess
import sys
from pathlib import Path

import requests

from . import platform
from .config import resolve_webdav_root, save_nextplorer_config

RCLONE_REMOTE_NAME = "nextplorer"
SYSTEMD_UNIT_NAME = platform.MOUNT_NAME  # rétro-compat (nom historique) : identifiant du montage géré


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix} : ").strip()
    return value or default or ""


def _verify_account(webdav_root: str, username: str, password: str) -> None:
    resp = requests.request(
        "PROPFIND", webdav_root,
        headers={"Depth": "0"},
        auth=(username, password),
        timeout=15,
    )
    if resp.status_code != 207:
        raise RuntimeError(f"Connexion WebDAV impossible (HTTP {resp.status_code}) — vérifie l'URL et le mot de passe")


def run_setup() -> int:
    print("=== Configuration de nextplorer ===\n")

    base_url = _prompt("URL du serveur Nextcloud (ex: https://nuage.example.org)").rstrip("/")
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    username = _prompt("Identifiant")
    password = getpass.getpass("Mot de passe d'application (créé dans Nextcloud → Sécurité) : ")

    print("Vérification…", end=" ", flush=True)
    try:
        webdav_root = resolve_webdav_root(base_url, username, password)
        _verify_account(webdav_root, username, password)
    except (requests.RequestException, RuntimeError, KeyError) as exc:
        print("échec.")
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    print("OK.")

    default_mount = str(Path.home() / "NextcloudMount")
    local_path_str = _prompt("Dossier de montage local", default_mount)
    local_path = Path(local_path_str).expanduser().resolve()
    local_path.mkdir(parents=True, exist_ok=True)

    print(f"Création du remote rclone « {RCLONE_REMOTE_NAME} »…")
    result = subprocess.run(
        [
            "rclone", "config", "create", RCLONE_REMOTE_NAME, "webdav",
            f"url={webdav_root}", "vendor=nextcloud", f"user={username}", f"pass={password}",
            "--obscure",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Échec de la création du remote rclone : {result.stderr.strip()}", file=sys.stderr)
        return 1

    print("Mise en place du montage permanent…")
    if platform.setup_permanent_mount(RCLONE_REMOTE_NAME, local_path):
        print("Montage activé — il démarrera automatiquement à chaque connexion.")
    else:
        print(
            "Montage permanent indisponible : lance-le manuellement avec :\n"
            f"  rclone mount {RCLONE_REMOTE_NAME}: {local_path} --vfs-cache-mode full",
            file=sys.stderr,
        )

    save_nextplorer_config(rclone_remote=RCLONE_REMOTE_NAME, local_path=str(local_path))

    print("\nConfiguration enregistrée (~/.config/nextplorer/config.json).")
    print("Prochaines étapes suggérées :")
    print("  nextplorer doctor              # vérifier que tout est en place")
    print("  nextplorer install-handler     # ouvrir les liens Nextcloud localement")
    print("  nextplorer install-integration # ajouter le clic-droit dans le gestionnaire de fichiers")
    return 0
