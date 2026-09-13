# nextplorer — portable Nextcloud links + application-level locking

*[Version française détaillée](docs/README.fr.md)*

Restores the "copy a file's path, send it by email/chat, the recipient
clicks it and it opens" workflow that most teams lose when moving from a
classic SMB file server to Nextcloud mounted over WebDAV (rclone). Also adds
protection against silent overwrites when two people edit the same document
at once, and one-click public share links.

## Features

- **Copy internal link** — right-click a file → "Copy Nextcloud link". The
  copied link (`https://.../f/<id>`) works for any colleague with access to
  the file, regardless of where they mounted it locally.
- **Open link locally** — clicking a Nextcloud link (email, chat, terminal…)
  resolves it to the local file (via your synced/mounted folder) and opens
  it directly with its associated application, instead of going through the
  browser. Any other link still opens the browser normally.
- **Application-level locking (`nextplorer-lock-watch`)** — for office documents
  (odt/ods/odp/doc/docx/xls/xlsx/ppt/pptx/rtf/csv), `nextplorer open` acquires a
  native Nextcloud lock on open and releases it automatically when
  LibreOffice closes the file. If a colleague already has it open, you get a
  clear notification and the file opens read-only instead — opening is never
  blocked outright.
- **External share link** — right-click → "Copy external link (public)"
  creates a public, read-only Nextcloud share link (no password, no
  expiration) and copies it immediately. Need a password, an expiration
  date, or upload rights? Use the Nextcloud web UI for that share — nextplorer
  doesn't reimplement it.

## Requirements

- Linux with GNOME or KDE Plasma (Windows/macOS are not supported).
- A Nextcloud server (tested against Nextcloud 33; the native locking API
  has been available since around Nextcloud 24-25).
- `python3`, `rclone`, `systemd` (for the permanent mount), and the Python
  packages `requests` and `cryptography`.
- Clipboard: `wl-copy` (Wayland) or `xclip` (X11). Notifications:
  `notify-send`. GNOME integration additionally needs `nautilus-python`; KDE
  needs nothing extra (uses Dolphin's built-in service menu mechanism).

## Installation

```sh
git clone <this repo>
cd nextplorer
ln -sf "$(pwd)/bin/nextplorer" ~/.local/bin/nextplorer

nextplorer setup               # server URL, credentials, permanent mount (systemd)
nextplorer install-integration # right-click menu in Nautilus (GNOME) or Dolphin (KDE)
nextplorer install-handler     # make nextplorer handle Nextcloud links
```

`nextplorer setup` asks for your Nextcloud server URL, username, and an
[app password](https://docs.nextcloud.com/server/latest/user_manual/en/session_management.html#managing-devices)
(never your main account password). It then creates a dedicated rclone
remote, a systemd --user service that mounts it automatically on login, and
writes `~/.config/nextplorer/config.json`.

`install-handler` remembers your current default browser and restores it
with `nextplorer uninstall-handler` if needed — only links to your configured
Nextcloud server are intercepted; everything else still opens your regular
browser exactly as before.

## Try it

```sh
nextplorer doctor            # check the account, connection and mount
nextplorer copy <path>       # copy the internal link for a local file
nextplorer share <path>      # create and copy a public external link
nextplorer open <link>       # resolve a link back to the local file and open it
nextplorer mount status      # check the systemd-managed mount, if you used `setup`
```

## How locking works

Nextcloud exposes a native application-locking API (`LOCK`/`UNLOCK` over
WebDAV with an `X-User-Lock` header) distinct from generic RFC4918 WebDAV
locking. nextplorer uses it directly, so the lock is visible from the Nextcloud
web UI too:

1. On `nextplorer open` for an office document, it checks for an existing lock.
   If someone else holds it, you're notified and the file opens read-only
   (`soffice --view`) — never blocked.
2. Otherwise it acquires the lock (30 min server-side) and opens the file
   normally.
3. A detached background process watches the `.~lock.<name>#` file that
   LibreOffice itself creates/removes while the document is open, renewing
   the server lock every 10 minutes and releasing it as soon as that file is
   gone.
4. A LibreOffice crash leaves that file behind (unlike a normal close), so
   the watcher also checks whether LibreOffice is still actually running,
   and releases the lock anyway if not. As a last resort, the lock expires
   server-side after 30 minutes without renewal regardless.

This "warn, never block" policy is deliberate: a stale lock blocking a
colleague's work is worse than occasionally missing one.

## Known limitations

- Single Nextcloud account per `nextplorer setup`.
- Locking only understands LibreOffice (via its `.~lock.*#` convention) and
  only kicks in for files opened through an nextplorer link — double-clicking a
  file directly in your file manager doesn't acquire a lock.
- The KDE Dolphin service menu was written and checked against KDE's
  documentation but not tested on a real Plasma session (this project is
  developed on GNOME) — reports/fixes welcome.
- Windows and macOS are out of scope.

## License

MIT — see [LICENSE](LICENSE).
