# Windows : build et déploiement

Non testé en conditions réelles au moment de l'écriture (ce dépôt est
développé sur une machine Linux) — écrit d'après la documentation
Microsoft/rclone/PyInstaller. À valider et corriger sur une vraie machine
Windows ; merci de remonter les erreurs rencontrées.

## 1. Développer/tester rapidement (sans empaqueter)

Plus rapide à itérer qu'un rebuild `.exe` à chaque changement :

```powershell
git clone <ce dépôt>
cd nextplorer
.\install.ps1
```

(équivalent Windows de `install.sh` — installe puis enchaîne sur
`nextplorer setup`. Non testé en conditions réelles, voir plus bas. Si
l'exécution de scripts est bloquée par la politique système :
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` avant de le
lancer.)

Prérequis :
- Python 3.10+ (depuis python.org ou le Microsoft Store).
- [rclone](https://rclone.org/downloads/) et [WinFsp](https://winfsp.dev/rel/)
  (ou `winget install -e --id Rclone.Rclone` /
  `winget install -e --id WinFsp.WinFsp`) — WinFsp est le pilote noyau requis
  par rclone pour monter un lecteur réseau sous Windows.
- LibreOffice, si le verrouillage applicatif doit fonctionner (repose sur son
  fichier `.~lock.<nom>#`, identique sous Windows).

## 2. Empaqueter en `.exe`

```powershell
python -m pip install pyinstaller
pyinstaller nextplorer.spec
```

Résultat : `dist/nextplorer/nextplorer.exe` (mode dossier, pas
`--onefile` — démarre plus vite, important pour une commande relancée à
chaque clic-droit dans l'Explorateur). Distribuer tout le dossier
`dist/nextplorer/`.

Si PyInstaller ne trouve pas les modules WinRT de `win11toast` à
l'exécution (erreur au lancement, pas à la compilation), ajouter dans
`nextplorer.spec` des `hiddenimports` plus précis, par exemple
`winrt.windows.ui.notifications`, `winrt.windows.data.xml.dom` — ce sont des
paquets à espaces de noms dynamiques que l'analyse statique de PyInstaller
peut manquer.

## 3. Déploiement sur un parc géré (le cas CDG16)

Le blocage Windows (impossible de définir le gestionnaire `https` par
défaut par programme, depuis Windows 8, protection anti-détournement de
navigateur) a une solution officielle pour un parc de postes géré :

1. Sur un poste de référence : installer nextplorer, lancer
   `nextplorer install-handler`, puis choisir manuellement « Nextplorer »
   dans Paramètres → Applications → Applications par défaut → `.https`.
2. Exporter l'association :
   ```powershell
   dism /online /export-defaultappassociations:NextplorerDefaultAppAssociations.xml
   ```
   (ou utiliser directement `nextplorer export-gpo-xml`, qui génère un XML
   minimal ciblant uniquement `http`/`https` sans dépendre d'un export
   DISM complet.)
3. Déposer ce fichier sur un partage accessible à tous les postes
   (ex. `\\serveur\partage\NextplorerDefaultAppAssociations.xml`).
4. Stratégie de groupe : *Configuration ordinateur → Modèles
   d'administration → Composants Windows → Explorateur de fichiers →
   « Set a default associations configuration file »* → Activé, avec le
   chemin UNC du fichier.
5. Réappliqué à chaque connexion, sur tout le parc, sans action utilisateur.

Équivalent pour un parc géré en Intune : stratégie de configuration
`ApplicationDefaults` (Policy CSP), même fichier XML.

Sources :
- https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/export-or-import-default-application-associations?view=windows-11
- https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-applicationdefaults

## 4. Points à vérifier en premier sur une vraie machine Windows

- `install.ps1` lui-même : jamais exécuté (pas de PowerShell disponible côté
  développement) — vérifier qu'il tourne tel quel avant tout le reste.
- `platform/windows.py` : le montage (tâche planifiée + WinFsp), les clés de
  registre du menu Explorateur et de l'enregistrement `https`, les
  notifications toast, le presse-papiers.
- Nom du process LibreOffice tel que `psutil` le voit réellement
  (`soffice.bin` supposé par analogie avec Linux — pourrait être
  `soffice.exe`, à corriger dans `platform/windows.py::is_office_app_running`
  si besoin).
- Que `soffice`/`soffice --view` se lance bien tel quel (résolution PATH) ou
  s'il faut chercher `soffice.exe` explicitement.
