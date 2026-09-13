"""Interface en ligne de commande nextplorer (phase 1 : liens portables)."""
from __future__ import annotations

import argparse
import configparser
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from . import deskenv, lockwatch, pathmap, setup, state, webdav
from .config import CONFIG_PATH, Config, load_config

FILEID_IN_URL = re.compile(r"/f/(\d+)(?:[/?#]|$)")
HANDLER_DESKTOP_ID = "nextplorer-open.desktop"
DESKTOP_DIR = Path.home() / ".local" / "share" / "applications"


def _notify(title: str, body: str, icon: str = "folder-remote") -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "--icon", icon, title, body], check=False)


def _copy_to_clipboard(text: str) -> bool:
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
        subprocess.run(["xdg-open", local_path], check=False)
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
        subprocess.run(["xdg-open", url_or_fileid], check=False)
        return 1

    _open_local(config, relative, local_path)
    print(local_path)
    return 0


_DESKTOP_APP_DIRS = [
    Path.home() / ".local" / "share" / "applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
    Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
    Path("/var/lib/flatpak/exports/share/applications"),
]
_DESKTOP_FIELD_CODE_RE = re.compile(r"%[fFuUdDnNickvm]")


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


def _launch_fallback_browser(url: str) -> None:
    """Ouvre un lien dans le VRAI navigateur — jamais via xdg-open, qui reboucle sur nous."""
    saved_browser = state.load().get("fallback_browser_desktop")
    if saved_browser:
        command = _resolve_desktop_exec(saved_browser)
        if command:
            subprocess.run([*command, url], check=False)
            return
    subprocess.run(["xdg-open", url], check=False)


def cmd_handle_url(config: Config, url: str) -> int:
    """Point d'entrée du gestionnaire de protocole (voir install-handler)."""
    account_host = urlsplit(config.account.base_url).hostname
    match = FILEID_IN_URL.search(url)

    if urlsplit(url).hostname != account_host or not match:
        _launch_fallback_browser(url)
        return 0

    fileid = match.group(1)
    try:
        relative = webdav.relative_path_for_fileid(config.account, fileid)
        local_path = pathmap.relative_to_local(config, relative)
    except (webdav.NotFoundError, FileNotFoundError, requests.RequestException) as exc:
        _notify("Lien Nextcloud", f"Pas trouvé localement, ouverture dans le navigateur ({exc})", icon="dialog-warning")
        _launch_fallback_browser(url)
        return 0

    _open_local(config, relative, local_path)
    return 0


def cmd_install_handler(config: Config) -> int:
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
    nextplorer_bin = shutil.which("nextplorer") or str(Path(__file__).resolve().parent.parent / "bin" / "nextplorer")
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

    account_host = urlsplit(config.account.base_url).hostname
    print(f"Gestionnaire installé pour https://{account_host}/f/…")
    print(f"Navigateur conservé pour tous les autres liens : {state.load().get('fallback_browser_desktop', '?')}")
    return 0


def cmd_uninstall_handler(config: Config) -> int:
    previous = state.load().get("fallback_browser_desktop")
    if not previous:
        print("Aucun navigateur précédent enregistré — rien à restaurer.", file=sys.stderr)
        return 1
    subprocess.run(["xdg-mime", "default", previous, "x-scheme-handler/https"], check=True)
    print(f"Navigateur par défaut restauré : {previous}")
    return 0


def cmd_doctor(config: Config) -> int:
    if CONFIG_PATH.exists():
        print(f"Config           : {CONFIG_PATH} (créée par `nextplorer setup`)")
        status = subprocess.run(
            ["systemctl", "--user", "is-active", setup.SYSTEMD_UNIT_NAME],
            capture_output=True, text=True,
        )
        print(f"Montage systemd  : {status.stdout.strip() or 'inconnu'} ({setup.SYSTEMD_UNIT_NAME})")
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
    sub.add_parser("install-integration", help="Ajouter le clic-droit dans le gestionnaire de fichiers (Nautilus/Dolphin)")

    p_mount = sub.add_parser("mount", help="Piloter le montage géré par nextplorer (service systemd --user)")
    p_mount.add_argument("action", choices=["status", "start", "stop"])

    sub.add_parser("doctor", help="Vérifier la configuration et la connexion")

    args = parser.parse_args(argv)

    if args.command == "setup":
        try:
            return setup.run_setup()
        except (EOFError, KeyboardInterrupt):
            print("\nConfiguration interrompue.", file=sys.stderr)
            return 130
    if args.command == "install-integration":
        return deskenv.install_integration()
    if args.command == "mount":
        return deskenv.mount_control(args.action)

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
