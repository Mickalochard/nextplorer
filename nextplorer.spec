# PyInstaller spec pour nextplorer.exe (Windows).
# À exécuter SUR une machine Windows (pas de cross-compilation) :
#   pip install pyinstaller
#   pyinstaller nextplorer.spec
# Le résultat est dans dist/nextplorer/nextplorer.exe (mode --onedir, plus
# fiable et plus rapide à démarrer qu'un --onefile pour un outil qu'on relance
# souvent, ex. le menu clic-droit de l'Explorateur).

a = Analysis(
    ["bin/nextplorer"],
    pathex=[],
    binaries=[],
    datas=[
        ("nextplorer/_integrations", "nextplorer/_integrations"),
    ],
    hiddenimports=[
        "nextplorer.platform.windows",
        "win11toast",
        "winrt",
    ],
    hookspath=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nextplorer",
    console=True,  # CLI : on garde une console, pas de fenêtre GUI pour l'instant
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="nextplorer",
)
