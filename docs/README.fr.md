# nextplorer — liens portables Nextcloud + verrouillage applicatif

*Version française détaillée. Voir [../README.md](../README.md) pour la version anglaise (audience externe).*

Rétablit le geste « copier le chemin d'un fichier, l'envoyer par mail, le
collègue clique et ça ouvre le fichier » — perdu en passant d'un ancien
serveur SMB à Nextcloud monté en WebDAV (rclone). Ajoute aussi une
protection contre les écrasements en cas d'édition simultanée d'un même
document par deux collègues, et la création rapide de liens externes publics.

## Ce que ça fait

- **Copier le lien** : clic droit sur un fichier → « Copier le lien
  Nextcloud ». Le lien copié (`https://.../f/<id>`) fonctionne pour
  n'importe quel collègue ayant accès au fichier, quel que soit son point de
  montage.
- **Ouvrir le lien** : cliquer un lien Nextcloud (mail, tchat, terminal…)
  retrouve le fichier sur le poste local et l'ouvre directement avec son
  application associée — sans passer par le navigateur. Tout autre lien
  continue d'ouvrir le navigateur normalement.
- **Verrouillage applicatif (`nextplorer-lock-watch`)** : pour les documents
  bureautiques (odt/ods/odp/doc/docx/xls/xlsx/ppt/pptx/rtf/csv), `nextplorer
  open` pose un verrou natif Nextcloud à l'ouverture et le relâche
  automatiquement à la fermeture de LibreOffice. Si un collègue a déjà le
  fichier ouvert, une notification l'indique et le fichier s'ouvre en
  lecture seule — l'ouverture n'est jamais bloquée.
- **Lien externe** : clic droit → « Copier un lien externe (public) » crée un
  lien public Nextcloud (lecture seule, sans mot de passe ni expiration) et
  le copie directement. Pour resserrer les droits (mot de passe, expiration,
  dépôt de fichiers…), direction l'interface web Nextcloud.

## Installation

```sh
git clone <ce dépôt>
cd nextplorer
python3 -m pip install --user .

nextplorer setup               # serveur, identifiants, montage permanent (systemd)
nextplorer install-integration # clic-droit dans Nautilus (GNOME) ou Dolphin (KDE)
nextplorer install-handler     # ouvrir les liens Nextcloud localement
```

`pip install --user .` place directement une commande `nextplorer`
fonctionnelle dans ton `PATH` (via `~/.local/bin`, déjà inclus sur la
plupart des bureaux Linux) — pas de lien symbolique à créer à la main, ça
marche quel que soit le nom du dossier où tu as cloné le dépôt.

`nextplorer setup` crée un remote rclone dédié, un service systemd --user qui
monte automatiquement au démarrage, et écrit
`~/.config/nextplorer/config.json`. `install-handler` mémorise le navigateur
par défaut actuel et le restaure avec `nextplorer uninstall-handler` en cas de
besoin — seuls les liens vers ton serveur Nextcloud sont interceptés.

Dépendances système : `python3`, `rclone`, `systemd` (montage permanent),
le module Python `requests`, le module `cryptography`. Presse-papiers :
`wl-copy` (Wayland) ou `xclip` (X11). Notifications : `notify-send`.
Intégration GNOME : `nautilus-python`. Intégration KDE : rien de plus
(mécanisme natif Dolphin).

### Poste déjà configuré avant `nextplorer setup`

Si `~/.config/rclone/rclone.conf` contient déjà un unique remote
`webdav`/`vendor=nextcloud` et un dossier `~/Nextcloud` ou
`~/NextcloudMount`, nextplorer continue de fonctionner sans avoir besoin de
`setup` (repli automatique). `nextplorer doctor` indique quelle configuration
est utilisée.

## Comment marche le verrouillage (`nextplorer-lock-watch`)

Le serveur Nextcloud (testé sur la version 33) expose une API de
verrouillage applicatif native (`LOCK`/`UNLOCK` WebDAV avec l'en-tête
`X-User-Lock`), distincte du verrouillage WebDAV générique RFC4918. C'est
elle qu'utilise nextplorer :

1. À l'ouverture d'un fichier bureautique via `nextplorer open`, on vérifie le
   verrou (`nextplorer/webdav.py: lock_status`). S'il appartient à quelqu'un
   d'autre, on notifie et on ouvre en lecture seule (`soffice --view`) —
   sans jamais bloquer.
2. Sinon, on pose le verrou (`acquire_lock`, valable 30 min côté serveur) et
   on lance LibreOffice normalement.
3. Un processus détaché (`nextplorer _watch-lock`, sous-commande interne)
   surveille le fichier `.~lock.<nom>#` que LibreOffice crée/supprime
   lui-même pendant qu'il a le document ouvert. Le verrou serveur est
   renouvelé toutes les 10 min tant que ce fichier existe, et relâché dès
   qu'il disparaît.
4. Si LibreOffice plante, il laisse ce fichier de verrou orphelin
   (contrairement à une fermeture normale) : `nextplorer-lock-watch` vérifie aussi
   qu'un processus LibreOffice tourne encore, sinon il relâche le verrou
   serveur quand même. En dernier recours, le verrou expire de toute façon
   côté serveur au bout de 30 min sans renouvellement.

Cette politique (avertir sans jamais bloquer) est un choix assumé : mieux
vaut risquer d'ignorer un verrou périmé que d'empêcher un collègue de
travailler à cause d'un verrou resté posé par erreur.

## Tester

```sh
nextplorer doctor                 # vérifie compte + connexion, sans jamais rien afficher de secret
nextplorer resolve <chemin>       # affiche le lien sans le copier (debug)
nextplorer copy <chemin>          # copie le lien interne dans le presse-papiers
nextplorer share <chemin>         # crée un lien externe public et le copie
nextplorer open <lien>            # ouvre localement le fichier correspondant
nextplorer mount status           # état du montage géré par nextplorer (si `setup` a été utilisé)
```

## Ce qui manque encore

- Un seul compte Nextcloud géré à la fois par `nextplorer setup`.
- Le verrouillage ne couvre que LibreOffice (détection via son fichier
  `.~lock.*#`) et que le flux « ouvrir via un lien nextplorer » — un
  double-clic direct sur le fichier dans le gestionnaire de fichiers ne pose
  pas de verrou.
- L'intégration KDE (menu de service Dolphin) n'a été validée que contre la
  documentation KDE, pas testée en conditions réelles (poste de
  développement sous GNOME).
- Windows et macOS ne sont pas supportés.
