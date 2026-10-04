"""Local JSON store in data/. Pipeline steps read/write here; sync pushes to the sheet."""
import json

from pydantic import BaseModel

from .cfg import ROOT, env

DIR = ROOT / env("DATA_DIR", "data")  # DATA_DIR=data_blr keeps one city's run apart from the others


def load(name: str, model: type[BaseModel]) -> list:
    p = DIR / f"{name}.json"
    return [model.model_validate(x) for x in json.loads(p.read_text("utf-8"))] if p.exists() else []


def save(name: str, rows: list[BaseModel]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{name}.json").write_text(json.dumps([r.model_dump(mode="json") for r in rows], indent=1), "utf-8")
