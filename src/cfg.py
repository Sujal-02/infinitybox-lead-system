import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
dry = False  # --dry-run: fixtures only, no network


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def yml(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8"))


def actor(name: str) -> dict:
    """Return the allowlisted Apify actor config; refuse anything not in actors.yaml."""
    cfg = yml("actors").get(name)
    if not cfg or cfg.get("id", "TODO") == "TODO":
        raise PermissionError(f"Apify actor '{name}' is not allowlisted in config/actors.yaml")
    return cfg
