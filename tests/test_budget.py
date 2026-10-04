import json
import shutil

import pytest

from src import budget, cfg


@pytest.fixture
def fake(monkeypatch):
    d = cfg.ROOT / "cache" / "_budget_test"
    monkeypatch.setattr(budget, "_file", lambda: d / "usage.json")
    monkeypatch.setattr(budget, "run_used", {})
    caps = {"per_run": {"hunter": 3, "apify": 1}, "monthly": {"hunter": 5, "apify": 0}}
    monkeypatch.setattr(budget, "yml", lambda name: caps)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_per_run_cap(fake):
    for _ in range(3):
        budget.charge("hunter")
    with pytest.raises(budget.BudgetExceeded, match="per-run"):
        budget.charge("hunter")


def test_monthly_cap_persists_across_runs(fake):
    for _ in range(3):
        budget.charge("hunter")
    budget.run_used.clear()                      # a new CLI run, same month
    budget.charge("hunter", 2)
    budget.run_used.clear()
    with pytest.raises(budget.BudgetExceeded, match="monthly"):
        budget.charge("hunter")
    assert list(json.loads((fake / "usage.json").read_text()).values())[0]["hunter"] == 5


def test_zero_cap_blocks_and_budget_stop_is_not_retried(fake):
    from src.cache import retry
    calls = []
    with pytest.raises(budget.BudgetExceeded):
        retry(lambda: calls.append(1) or budget.charge("apify"), tries=4, base=0)
    assert len(calls) == 1                       # fatal: no retries


def test_unlisted_service_is_uncapped(fake):
    budget.charge("firecrawl", 999)
