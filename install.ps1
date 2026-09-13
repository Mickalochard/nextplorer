# Installe nextplorer (pip --user) puis lance directement la configuration.
# Usage : git clone <ce dépôt> ; cd nextplorer ; .\install.ps1
# Non testé en conditions réelles (écrit sur une machine Linux) — voir
# docs/BUILD_WINDOWS.md. Si l'exécution de scripts est bloquée, lancer
# d'abord : Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Installation de nextplorer ==="
python -m pip install --user .

$userScripts = python -c "import site, os; print(os.path.join(site.getuserbase(), 'Scripts'))"
if (-not ($env:Path -split ";" | Where-Object { $_ -eq $userScripts })) {
    Write-Host ""
    Write-Host "Attention : $userScripts n'est pas dans ton PATH."
    Write-Host "Ajoute-le (Paramètres système > Variables d'environnement), puis rouvre un terminal."
    Write-Host ""
}

Write-Host ""
Write-Host "=== Configuration ==="
& (Join-Path $userScripts "nextplorer.exe") setup
