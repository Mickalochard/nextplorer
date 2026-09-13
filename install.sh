#!/bin/sh
# Installe nextplorer (pip --user) puis lance directement la configuration.
# Usage : git clone <ce dépôt> && cd nextplorer && ./install.sh
set -e

cd "$(dirname "$0")"

echo "=== Installation de nextplorer ==="
python3 -m pip install --user .

case ":$PATH:" in
    *:"$HOME/.local/bin":*) ;;
    *)
        echo ""
        echo "Attention : $HOME/.local/bin n'est pas dans ton PATH."
        echo "Ajoute cette ligne à ~/.bashrc (ou ~/.zshrc), puis rouvre un terminal :"
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo ""
        ;;
esac

echo ""
echo "=== Configuration ==="
exec "$HOME/.local/bin/nextplorer" setup
