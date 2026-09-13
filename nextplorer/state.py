"""Petit état local persistant (pas de secret dedans) : navigateur d'origine à restaurer."""
from __future__ import annotations

import json

from .paths import user_config_dir

STATE_PATH = user_config_dir("nextplorer") / "state.json"


def load() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text())


def save(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=2))
