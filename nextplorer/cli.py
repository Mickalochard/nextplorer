"""Interface en ligne de commande nextplorer (phase 1 : liens portables)."""
from __future__ import annotations

import argparse
import re
import sys
import time
from urllib.parse import urlsplit

import requests

from . import lockwatch, pathmap, platform, setup, webdav
from .config import CONFIG_PATH, Config, load_config

FILEID_IN_URL = re.compile(r"/f/(\d+)(?:[/?#]|$)")


def _notify(title: str, body: str, icon: str = "folder-remote") -> None:
    platform.notify(title, body, icon)


def _copy_to_clipboard(text: str) -> bool:
    return platform.copy_to_clipboard(text)


def cmd_resolve(config: Config, path: str) -> str:
    _root, relative = pathmap.local_to_relative(config, path)
    fileid = webdav.fileid_for_relative_path(config.account, relative)
    return config.account.link_for(fileid)


def cmd_copy(config: Config, path: str) -> int:
    try:
        link = cmd_resolve(config, path)
    except (pathmap.OutsideMountError, webdav.NotFoundError, requests.RequestException) as exc:
        _notify("Lien Nextcloud", f"Échec : {exc}", icon="dialog-error")
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    copied = _copy_to_clipboard(link)
    print(link)
    if copied:
        _notify("Lien Nextcloud copié", link)
    else:
        _notify("Lien Nextcloud", "Copié dans la sortie standard (aucun outil presse-papiers trouvé)")
    return 0


def _open_local(config: Config, relative: str, local_path: str) -> None:
    """Ouvre le fichier local, en tenant compte du verrou applicatif pour les
    documents bureautiques (phase 2 : nextplorer-lock-watch)."""
    if not lockwatch.is_office_document(local_path):
        platform.open_path(local_path)
        return

    lock = lockwatch.foreign_lock(config, relative)
    if lock is not None:
        duration = lockwatch.format_duration(int(time.time()) - lock.locked_since)
        _notify(
            "Fichier verrouillé",
            f"Ouvert par {lock.owner_displayname} depuis {duration} — ouverture en lecture seule.",
            icon="dialog-warning",
        )
        lockwatch.open_readonly(local_path)
        return

    lockwatch.open_editable(config, relative, local_path)


def cmd_share(config: Config, path: str) -> int:
    """Crée un lien externe public (lecture seule, sans mot de passe ni
    expiration) et le copie dans le presse-papiers. Pour resserrer les droits,
    direction l'interface web Nextcloud."""
    try:
        _root, relative = pathmap.local_to_relative(config, path)
        link = webdav.create_public_link(config.account, relative)
    except (pathmap.OutsideMountError, webdav.NotFoundError, webdav.ShareError, requests.RequestException) as exc:
        _notify("Lien externe Nextcloud", f"Échec : {exc}", icon="dialog-error")
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    copied = _copy_to_clipboard(link)
    print(link)
    if copied:
        _notify("Lien externe copié", link)
    else:
        _notify("Lien externe Nextcloud", "Copié dans la sortie standard (aucun outil presse-papiers trouvé)")
    return 0


def cmd_open(config: Config, url_or_fileid: str) -> int:
    match = FILEID_IN_URL.search(url_or_fileid)
    fileid = match.group(1) if match else url_or_fileid.strip()

    try:
        relative = webdav.relative_path_for_fileid(config.account, fileid)
        local_path = pathmap.relative_to_local(config, relative)
    except (webdav.NotFoundError, FileNotFoundError, requests.RequestException) as exc:
        print(f"Résolution locale impossible ({exc}) — ouverture dans le navigateur.", file=sys.stderr)
        platform.launch_browser(url_or_fileid)
        return 1

    _open_local(config, relative, local_path)
    print(local_path)
    return 0


def cmd_handle_url(config: Config, url: str) -> int:
    """Point d'entrée du gestionnaire de protocole (voir install-handler)."""
    account_host = urlsplit(config.account.base_url).hostname
    match = FILEID_IN_URL.search(url)

    if urlsplit(url).hostname != account_host or not match:
        platform.launch_browser(url)
        return 0

    fileid = match.group(1)
    try:
        relative = webdav.relative_path_for_fileid(config.account, fileid)
        local_path = pathmap.relative_to_local(config, relative)
    except (webdav.NotFoundError, FileNotFoundError, requests.RequestException) as exc:
        _notify("Lien Nextcloud", f"Pas trouvé localement, ouverture dans le navigateur ({exc})", icon="dialog-warning")
        platform.launch_browser(url)
        return 0

    _open_local(config, relative, local_path)
    return 0


def cmd_install_handler(config: Config) -> int:
    account_host = urlsplit(config.account.base_url).hostname
    return platform.install_url_handler(account_host)


def cmd_uninstall_handler(config: Config) -> int:
    return platform.uninstall_url_handler()


def cmd_doctor(config: Config) -> int:
    if CONFIG_PATH.exists():
        print(f"Config           : {CONFIG_PATH} (créée par `nextplorer setup`)")
        print(f"Montage          : {platform.mount_status_summary()} ({platform.MOUNT_NAME})")
    else:
        print("Config           : détection automatique via rclone.conf (legacy — lance `nextplorer setup` pour fixer une config explicite)")

    print(f"Compte Nextcloud : {config.account.username} @ {config.account.base_url}")
    print(f"Racine WebDAV    : {config.account.webdav_root}")
    print("Dossiers locaux connus :")
    if not config.mounts:
        print("  (aucun trouvé — ni ~/Nextcloud ni ~/NextcloudMount)")
    for root, label in config.mounts.items():
        print(f"  - {root}  [{label}]")

    print("Test de connexion WebDAV… ", end="", flush=True)
    try:
        resp = requests.request(
            "PROPFIND", config.account.webdav_root,
            headers={"Depth": "0"},
            auth=(config.account.username, config.account.password),
            timeout=15,
        )
        if resp.status_code == 207:
            print("OK")
        else:
            print(f"réponse inattendue (HTTP {resp.status_code})")
            return 1
    except requests.RequestException as exc:
        print(f"échec ({exc})")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nextplorer", description="Liens portables pour fichiers Nextcloud")
    sub = parser.add_subparsers(dest="command", required=True)

    p_copy = sub.add_parser("copy", help="Copier le lien Nextcloud d'un fichier local")
    p_copy.add_argument("path")

    p_resolve = sub.add_parser("resolve", help="Afficher le lien sans le copier (debug)")
    p_resolve.add_argument("path")

    p_share = sub.add_parser(
        "share",
        help="Créer un lien externe public (lecture seule) et le copier dans le presse-papiers",
    )
    p_share.add_argument("path")

    p_open = sub.add_parser("open", help="Ouvrir localement un lien/fileid Nextcloud")
    p_open.add_argument("url_or_fileid")

    p_handle = sub.add_parser("handle-url", help="[interne] appelé par le gestionnaire de protocole")
    p_handle.add_argument("url")

    p_watch = sub.add_parser("_watch-lock", help="[interne] surveille et relâche le verrou après édition")
    p_watch.add_argument("relative_path")
    p_watch.add_argument("local_path")

    sub.add_parser("install-handler", help="Faire de nextplorer le gestionnaire des liens Nextcloud")
    sub.add_parser("uninstall-handler", help="Restaurer le navigateur par défaut d'origine")

    sub.add_parser("setup", help="Configurer nextplorer (serveur, identifiants, montage permanent)")
    sub.add_parser("install-integration", help="Ajouter le clic-droit dans le gestionnaire de fichiers (Nautilus/Dolphin/Explorateur)")

    p_mount = sub.add_parser("mount", help="Piloter le montage géré par nextplorer")
    p_mount.add_argument("action", choices=["status", "start", "stop"])

    sub.add_parser(
        "export-gpo-xml",
        help="[Windows] Générer le XML d'association par défaut pour déploiement GPO/Intune",
    )

    sub.add_parser("doctor", help="Vérifier la configuration et la connexion")

    args = parser.parse_args(argv)

    if args.command == "setup":
        try:
            return setup.run_setup()
        except (EOFError, KeyboardInterrupt):
            print("\nConfiguration interrompue.", file=sys.stderr)
            return 130
    if args.command == "install-integration":
        return platform.install_file_manager_integration()
    if args.command == "mount":
        return platform.mount_control(args.action)
    if args.command == "export-gpo-xml":
        return platform.export_gpo_xml()

    try:
        config = load_config()
    except Exception as exc:  # config error : message clair, pas de traceback
        print(f"Configuration nextplorer invalide : {exc}", file=sys.stderr)
        return 2

    if args.command == "copy":
        return cmd_copy(config, args.path)
    if args.command == "resolve":
        print(cmd_resolve(config, args.path))
        return 0
    if args.command == "share":
        return cmd_share(config, args.path)
    if args.command == "open":
        return cmd_open(config, args.url_or_fileid)
    if args.command == "handle-url":
        return cmd_handle_url(config, args.url)
    if args.command == "_watch-lock":
        lockwatch.watch_and_release(config, args.relative_path, args.local_path)
        return 0
    if args.command == "install-handler":
        return cmd_install_handler(config)
    if args.command == "uninstall-handler":
        return cmd_uninstall_handler(config)
    if args.command == "doctor":
        return cmd_doctor(config)
    return 1


if __name__ == "__main__":
    sys.exit(main())
