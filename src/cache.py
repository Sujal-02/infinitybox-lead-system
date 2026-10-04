"""Disk cache and retry helper. Every paid API call goes through `cached`, so reruns and tests cost nothing."""
import hashlib
import json
import time

from .cfg import ROOT

DIR = ROOT / "cache"
enabled = True  # --no-cache sets False


def cached(name: str, args, fn):
    """Return fn() from disk if this (name, args) was seen before; else call and store."""
    key = hashlib.sha256(json.dumps([name, args], sort_keys=True, default=str).encode()).hexdigest()[:24]
    path = DIR / f"{name}-{key}.json"
    if enabled and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    out = fn()
    DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, default=str), encoding="utf-8")
    return out


def retry(fn, tries: int = 4, base: float = 1.0):
    """Call fn with exponential backoff; re-raise after the last try."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            code = getattr(e, "code", None) or getattr(getattr(e, "response", None), "status_code", None)
            if i == tries - 1 or getattr(e, "fatal", False) or (isinstance(code, int) and 400 <= code < 500 and code != 429):  # client errors won't fix themselves
                raise
            time.sleep(base * 2**i)
