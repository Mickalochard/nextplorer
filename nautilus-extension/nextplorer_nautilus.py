"""Extension Nautilus : "Copier le lien Nextcloud" dans le menu clic droit.

Installation : lier/copier ce fichier dans
~/.local/share/nautilus-python/extensions/nextplorer_nautilus.py puis redémarrer
Nautilus (nautilus -q).
"""
import subprocess
from urllib.parse import unquote, urlsplit

import gi

gi.require_version("Nautilus", "4.1")
from gi.repository import GObject, Nautilus

NEXTPLORER_BIN = "nextplorer"  # doit être dans le PATH (voir README d'installation)


def _local_path(nautilus_file) -> str | None:
    uri = nautilus_file.get_uri()
    parts = urlsplit(uri)
    if parts.scheme != "file":
        return None
    return unquote(parts.path)


class NextplorerMenuProvider(GObject.GObject, Nautilus.MenuProvider):
    def _copy_link(self, _menu, path: str):
        subprocess.Popen([NEXTPLORER_BIN, "copy", path])

    def _share_link(self, _menu, path: str):
        subprocess.Popen([NEXTPLORER_BIN, "share", path])

    def get_file_items(self, files):
        if len(files) != 1:
            return []
        path = _local_path(files[0])
        if not path:
            return []

        copy_item = Nautilus.MenuItem(
            name="Nextplorer::CopyLink",
            label="Copier le lien Nextcloud",
            tip="Copie un lien qui rouvre ce fichier chez n'importe quel collègue",
        )
        copy_item.connect("activate", self._copy_link, path)

        share_item = Nautilus.MenuItem(
            name="Nextplorer::ShareLink",
            label="Copier un lien externe (public)",
            tip="Crée un lien public en lecture seule et le copie — réglages avancés (mot de passe, expiration) sur l'interface web Nextcloud",
        )
        share_item.connect("activate", self._share_link, path)

        return [copy_item, share_item]

    def get_background_items(self, folder):
        return []
