"""Correspondance entre chemin local (dossier synchronisé/monté) et chemin WebDAV relatif."""
from __future__ import annotations

from pathlib import Path

from .config import Config


class OutsideMountError(Exception):
    pass


def local_to_relative(config: Config, local_path: str) -> tuple[str, str]:
    """Renvoie (racine_locale, chemin_relatif_webdav) pour un chemin de fichier local."""
    resolved = Path(local_path).expanduser().resolve()
    for root in config.mounts:
        root_path = Path(root).resolve()
        try:
            relative = resolved.relative_to(root_path)
        except ValueError:
            continue
        return root, relative.as_posix()
    raise OutsideMountError(
        f"{local_path} n'est dans aucun dossier Nextcloud connu ({list(config.mounts)})"
    )


def relative_to_local(config: Config, relative_path: str) -> str:
    """Renvoie le premier chemin local existant correspondant à un chemin WebDAV relatif."""
    candidates = []
    for root in config.mounts:
        candidate = Path(root) / relative_path
        candidates.append(candidate)
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "Fichier non trouvé localement (pas encore synchronisé/monté sur ce poste) : "
        + ", ".join(str(c) for c in candidates)
    )
