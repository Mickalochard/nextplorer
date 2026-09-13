"""Résolution de la configuration nextplorer : Nextcloud + correspondances de montage."""
from __future__ import annotations

import base64
import configparser
import dataclasses
import json
from pathlib import Path

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .paths import user_config_dir

CONFIG_PATH = user_config_dir("nextplorer") / "config.json"
RCLONE_CONF_PATH = user_config_dir("rclone") / "rclone.conf"


@dataclasses.dataclass
class NextcloudAccount:
    base_url: str          # ex: https://nuage.example.org
    webdav_root: str       # ex: https://nuage.example.org/remote.php/dav/files/<uid>/
    username: str
    password: str          # en clair, jamais journalisé ni affiché
    link_template: str = "{base}/f/{fileid}"

    def link_for(self, fileid: str) -> str:
        return self.link_template.format(base=self.base_url.rstrip("/"), fileid=fileid)


@dataclasses.dataclass
class Config:
    account: NextcloudAccount
    mounts: dict[str, str]  # chemin local absolu -> nom informatif (rclone remote, "sync-client", ...)


# Clé fixe utilisée par rclone pour son "obscure" (obfuscation déclarée non
# sécurisée par rclone lui-même — sert juste à éviter la lecture à l'épaule
# dans rclone.conf). Reproduite ici pour réutiliser tel quel le mot de passe
# déjà configuré côté rclone, sans dupliquer un secret dans un second fichier.
_RCLONE_OBSCURE_KEY = bytes([
    0x9c, 0x93, 0x5b, 0x48, 0x73, 0x0a, 0x55, 0x4d,
    0x6b, 0xfd, 0x7c, 0x63, 0xc8, 0x86, 0xa9, 0x2b,
    0xd3, 0x90, 0x19, 0x8e, 0xb8, 0x12, 0x8a, 0xfb,
    0xf4, 0xde, 0x16, 0x2b, 0x8b, 0x95, 0xf6, 0x38,
])


def _reveal_rclone_password(obscured: str) -> str:
    raw = base64.urlsafe_b64decode(obscured + "=" * (-len(obscured) % 4))
    iv, ciphertext = raw[:16], raw[16:]
    decryptor = Cipher(algorithms.AES(_RCLONE_OBSCURE_KEY), modes.CTR(iv)).decryptor()
    return (decryptor.update(ciphertext) + decryptor.finalize()).decode("utf-8")


def _base_url_from_webdav_root(webdav_root: str) -> str:
    # https://host/remote.php/dav/files/<uid>/  ->  https://host
    marker = "/remote.php/dav/"
    idx = webdav_root.find(marker)
    return webdav_root[:idx] if idx != -1 else webdav_root.rstrip("/")


def resolve_webdav_root(base_url: str, username: str, password: str) -> str:
    """Détermine la racine WebDAV réelle d'un compte via l'API OCS.

    Le segment /dav/files/<id>/ utilise l'identifiant interne Nextcloud, qui
    peut différer du login sur une instance adossée à un LDAP/SSO (observé en
    pratique : id = UUID, login = "prenom.nom"). On l'interroge au lieu de
    supposer id == username.
    """
    resp = requests.get(
        base_url.rstrip("/") + "/ocs/v1.php/cloud/user",
        params={"format": "json"},
        auth=(username, password),
        headers={"OCS-APIRequest": "true"},
        timeout=15,
    )
    resp.raise_for_status()
    uid = resp.json()["ocs"]["data"]["id"]
    return f"{base_url.rstrip('/')}/remote.php/dav/files/{uid}/"


def _load_from_rclone(remote_name: str | None = None) -> NextcloudAccount:
    if not RCLONE_CONF_PATH.exists():
        raise FileNotFoundError(f"Pas de config rclone trouvée ({RCLONE_CONF_PATH})")

    parser = configparser.ConfigParser()
    parser.read(RCLONE_CONF_PATH)

    candidates = [
        name for name in parser.sections()
        if parser[name].get("type") == "webdav" and parser[name].get("vendor") == "nextcloud"
    ]
    if remote_name:
        if remote_name not in candidates:
            raise ValueError(f"Remote rclone '{remote_name}' introuvable ou non-Nextcloud")
        chosen = remote_name
    elif len(candidates) == 1:
        chosen = candidates[0]
    elif not candidates:
        raise ValueError("Aucun remote rclone de type webdav/nextcloud trouvé")
    else:
        raise ValueError(
            f"Plusieurs remotes Nextcloud dans rclone.conf ({candidates}) — "
            f"lance `nextplorer setup` pour créer une config explicite (~/.config/nextplorer/config.json)"
        )

    section = parser[chosen]
    webdav_root = section["url"]
    username = section["user"]
    password = _reveal_rclone_password(section["pass"])

    return NextcloudAccount(
        base_url=_base_url_from_webdav_root(webdav_root),
        webdav_root=webdav_root,
        username=username,
        password=password,
    )


def _load_from_nextplorer_config() -> Config:
    data = json.loads(CONFIG_PATH.read_text())
    account = _load_from_rclone(remote_name=data["rclone_remote"])
    mounts = {data["local_path"]: f"géré par nextplorer (remote rclone « {data['rclone_remote']} »)"}
    return Config(account=account, mounts=mounts)


def save_nextplorer_config(*, rclone_remote: str, local_path: str) -> None:
    """Écrit ~/.config/nextplorer/config.json (voir `nextplorer setup`).

    Volontairement minimal : le reste (serveur, identifiant, racine WebDAV)
    est déjà dans rclone.conf sous ce nom de remote, pas de duplication."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({
        "rclone_remote": rclone_remote,
        "local_path": local_path,
    }, indent=2))


def load_config() -> Config:
    """Charge la config nextplorer.

    Priorité à ~/.config/nextplorer/config.json, écrit par `nextplorer setup`. À
    défaut, repli sur l'ancien comportement (phase 1, avant `setup`) :
    dérivation automatique depuis rclone.conf — ne fonctionne que s'il y a
    exactement un remote webdav/nextcloud et un des dossiers locaux usuels.
    Conservé pour ne pas casser une installation existante qui n'a pas
    encore relancé `nextplorer setup`.
    """
    if CONFIG_PATH.exists():
        return _load_from_nextplorer_config()

    account = _load_from_rclone()

    mounts: dict[str, str] = {}
    for candidate, label in [
        (Path.home() / "Nextcloud", "client officiel (sync complète)"),
        (Path.home() / "NextcloudMount", "montage rclone webdav"),
    ]:
        if candidate.is_dir():
            mounts[str(candidate)] = label

    return Config(account=account, mounts=mounts)
