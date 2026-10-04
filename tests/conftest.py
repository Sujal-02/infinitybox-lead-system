"""Tests must behave the same on a developer machine (with a real .env) and on a clean CI runner: no test may reach a real sheet,
change a real allowance or depend on a real access code, so those settings are cleared for every test."""
import pytest

SETTINGS = ("SHEET_WEBHOOK_URL", "SHEET_API_TOKEN", "GSHEET_ID", "ACCESS_CODE", "ALLOWED_ORIGIN", "APPS_SCRIPT_URL", "BUDGET_PROFILE")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for k in SETTINGS:
        monkeypatch.delenv(k, raising=False)
