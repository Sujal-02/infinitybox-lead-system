"""Free-trial spend guard. charge() is called inside the code that runs only on a cache miss, so cached reruns cost nothing.
Caps live in config/budgets.yaml; usage is persisted per calendar month in data/usage.json."""
import json
from datetime import date

from . import cfg
from .cfg import yml


class BudgetExceeded(RuntimeError):
    fatal = True  # retrying cannot help


run_used: dict[str, float] = {}


def _file():
    return cfg.ROOT / "data" / "usage.json"


def _ledger() -> dict:
    f = _file()
    return json.loads(f.read_text("utf-8")) if f.exists() else {}


def charge(service: str, n: float = 1) -> None:
    """Record n units of `service`, or raise BudgetExceeded if this run's or this month's cap would be passed."""
    caps = yml("budgets")
    month = date.today().strftime("%Y-%m")
    led = _ledger()
    used = led.setdefault(month, {}).get(service, 0)
    per_run, monthly = caps["per_run"].get(service), caps["monthly"].get(service)
    if per_run is not None and run_used.get(service, 0) + n > per_run:
        raise BudgetExceeded(f"{service}: per-run cap {per_run} reached (config/budgets.yaml)")
    if monthly is not None and used + n > monthly:
        raise BudgetExceeded(f"{service}: monthly cap {monthly} reached, {used:g} used (config/budgets.yaml)")
    run_used[service] = run_used.get(service, 0) + n
    led[month][service] = used + n
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(led, indent=1), "utf-8")


def summary() -> str:
    caps, month = yml("budgets"), date.today().strftime("%Y-%m")
    used = _ledger().get(month, {})
    return " | ".join(f"{s}: run {run_used.get(s, 0):g}/{caps['per_run'].get(s, '-')}, month {used.get(s, 0):g}/{caps['monthly'].get(s, '-')}"
                      for s in caps["monthly"])
