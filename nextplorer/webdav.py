"""Appels WebDAV Nextcloud : chemin local <-> identifiant de fichier (fileid),
et verrouillage natif Nextcloud (phase 2 : nextplorer-lock-watch)."""
from __future__ import annotations

import dataclasses
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote, unquote, urlsplit

import requests

from .config import NextcloudAccount

DAV_NS = "DAV:"
OC_NS = "http://owncloud.org/ns"
NC_NS = "http://nextcloud.org/ns"

_PROPFIND_FILEID_BODY = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:prop>
    <oc:fileid/>
  </d:prop>
</d:propfind>
"""

_PROPFIND_LIST_BODY = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:prop>
    <oc:fileid/>
  </d:prop>
</d:propfind>
"""


class NotFoundError(Exception):
    pass


class ShareError(Exception):
    pass


def _quote_path(relative_path: str) -> str:
    return "/".join(quote(segment) for segment in relative_path.split("/"))


def _dav_url(account: NextcloudAccount, relative_path: str) -> str:
    return account.webdav_root.rstrip("/") + "/" + _quote_path(relative_path)


def own_uid(account: NextcloudAccount) -> str:
    """Identifiant Nextcloud (uid interne) du compte, tel qu'utilisé dans webdav_root."""
    marker = "/dav/files/"
    idx = account.webdav_root.find(marker)
    if idx == -1:
        return ""
    return account.webdav_root[idx + len(marker):].split("/", 1)[0]


def fileid_for_relative_path(account: NextcloudAccount, relative_path: str) -> str:
    """Interroge le fileid Nextcloud du fichier situé à relative_path (relatif à webdav_root)."""
    url = _dav_url(account, relative_path)
    resp = requests.request(
        "PROPFIND", url,
        data=_PROPFIND_FILEID_BODY,
        headers={"Depth": "0", "Content-Type": "application/xml"},
        auth=(account.username, account.password),
        timeout=15,
    )
    if resp.status_code == 404:
        raise NotFoundError(f"Fichier introuvable côté serveur : {relative_path}")
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    fileid_el = root.find(f".//{{{OC_NS}}}fileid")
    if fileid_el is None or not fileid_el.text:
        raise NotFoundError(f"Pas de fileid renvoyé pour : {relative_path}")
    return fileid_el.text.strip()


def _containing_dir_for_fileid(account: NextcloudAccount, fileid: str) -> str:
    """Suit la redirection du lien public /f/<fileid> pour retrouver le dossier parent."""
    resp = requests.get(
        f"{account.base_url}/f/{fileid}",
        auth=(account.username, account.password),
        allow_redirects=False,
        timeout=15,
    )
    if resp.status_code == 404:
        raise NotFoundError(f"Aucun fichier ne correspond à fileid={fileid}")
    location = resp.headers.get("Location")
    if resp.status_code not in (301, 302, 303, 307, 308) or not location:
        raise NotFoundError(f"Réponse inattendue du serveur pour fileid={fileid} (HTTP {resp.status_code})")

    query = parse_qs(urlsplit(location).query)
    directory = query.get("dir", ["/"])[0]
    return directory


def relative_path_for_fileid(account: NextcloudAccount, fileid: str) -> str:
    """Retrouve le chemin (relatif à webdav_root) du fichier portant ce fileid."""
    directory = _containing_dir_for_fileid(account, fileid)

    url = account.webdav_root.rstrip("/") + "/" + _quote_path(directory.strip("/")) + "/"
    resp = requests.request(
        "PROPFIND", url,
        data=_PROPFIND_LIST_BODY,
        headers={"Depth": "1", "Content-Type": "application/xml"},
        auth=(account.username, account.password),
        timeout=15,
    )
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    dav_root_path = urlsplit(account.webdav_root).path.rstrip("/")
    for response_el in root.findall(f"{{{DAV_NS}}}response"):
        fileid_el = response_el.find(f".//{{{OC_NS}}}fileid")
        if fileid_el is not None and fileid_el.text == str(fileid):
            href = response_el.find(f"{{{DAV_NS}}}href").text
            return unquote(href[len(dav_root_path):]).lstrip("/")

    raise NotFoundError(f"fileid={fileid} annoncé dans {directory} mais introuvable au listing")


@dataclasses.dataclass
class LockInfo:
    owner_uid: str
    owner_displayname: str
    locked_since: int  # timestamp Unix, horloge serveur
    timeout_seconds: int


_PROPFIND_LOCK_BODY = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:" xmlns:nc="http://nextcloud.org/ns">
  <d:prop>
    <nc:lock/>
    <nc:lock-owner/>
    <nc:lock-owner-displayname/>
    <nc:lock-time/>
    <nc:lock-timeout/>
  </d:prop>
</d:propfind>
"""

_LOCK_BODY = """<?xml version="1.0" encoding="utf-8"?>
<d:lockinfo xmlns:d="DAV:">
  <d:lockscope><d:exclusive/></d:lockscope>
  <d:locktype><d:write/></d:locktype>
  <d:owner>nextplorer</d:owner>
</d:lockinfo>
"""


def lock_status(account: NextcloudAccount, relative_path: str) -> LockInfo | None:
    """Verrou natif Nextcloud actif sur ce fichier, ou None si libre.

    Utilise les propriétés nc:lock-* (verrou "applicatif" Nextcloud, visible
    dans l'interface web), pas le verrouillage WebDAV RFC4918 générique.
    """
    resp = requests.request(
        "PROPFIND", _dav_url(account, relative_path),
        data=_PROPFIND_LOCK_BODY,
        headers={"Depth": "0", "Content-Type": "application/xml"},
        auth=(account.username, account.password),
        timeout=15,
    )
    if resp.status_code == 404:
        raise NotFoundError(f"Fichier introuvable côté serveur : {relative_path}")
    resp.raise_for_status()

    root = ET.fromstring(resp.content)

    def prop(name: str) -> str | None:
        el = root.find(f".//{{{NC_NS}}}{name}")
        return el.text if el is not None and el.text else None

    if prop("lock") != "1":
        return None
    return LockInfo(
        owner_uid=prop("lock-owner") or "",
        owner_displayname=prop("lock-owner-displayname") or "?",
        locked_since=int(prop("lock-time") or 0),
        timeout_seconds=int(prop("lock-timeout") or 0),
    )


def acquire_lock(account: NextcloudAccount, relative_path: str, timeout_seconds: int) -> bool:
    """Pose (ou renouvelle) le verrou natif Nextcloud sur ce fichier pour le compte courant."""
    resp = requests.request(
        "LOCK", _dav_url(account, relative_path),
        data=_LOCK_BODY,
        headers={
            "Content-Type": "application/xml",
            "X-User-Lock": "1",
            "Timeout": f"Second-{timeout_seconds}",
        },
        auth=(account.username, account.password),
        timeout=15,
    )
    return resp.status_code == 200


def release_lock(account: NextcloudAccount, relative_path: str) -> bool:
    """Relâche le verrou natif Nextcloud posé par le compte courant sur ce fichier."""
    resp = requests.request(
        "UNLOCK", _dav_url(account, relative_path),
        headers={"X-User-Lock": "1"},
        auth=(account.username, account.password),
        timeout=15,
    )
    return resp.status_code in (200, 204)


def create_public_link(account: NextcloudAccount, relative_path: str) -> str:
    """Crée un lien externe public (lecture seule, sans mot de passe ni
    expiration) et renvoie son URL. Pour resserrer les droits (mot de passe,
    expiration, dépôt de fichiers…), c'est à faire depuis l'interface web
    Nextcloud — on ne réimplémente pas ces réglages ici."""
    resp = requests.post(
        account.base_url.rstrip("/") + "/ocs/v2.php/apps/files_sharing/api/v1/shares",
        params={"format": "json"},
        data={
            "path": "/" + relative_path,
            "shareType": 3,
            "permissions": 1,
        },
        auth=(account.username, account.password),
        headers={"OCS-APIRequest": "true"},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()["ocs"]
    if payload["meta"]["statuscode"] != 200:
        raise ShareError(payload["meta"].get("message") or "Échec de la création du lien externe")
    return payload["data"]["url"]
