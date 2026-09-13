"""Petit état local persistant (pas de secret dedans) : navigateur d'origine à restaurer."""
from __future__ import annotations

import json
from pathlib import Path

STATE_PATH = Path.home() / ".config" / "nextplorer" / "state.json"


def load() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text())


def save(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=2))
