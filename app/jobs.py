"""Runs the lead pipeline for one city as a background process, so a non-technical user can press a button instead of a terminal.
Each city writes to its own data folder (data_<city>), so runs never overwrite each other. One job at a time."""
import os
import re
import subprocess
import sys
import time

from src.cfg import ROOT, yml

STATE = ROOT / "app_data"
SIZES = {
    "quick": {"label": "Quick look", "minutes": "about 3 to 5 minutes", "cost": "uses very little of your free credits", "args": ["--limit", "60", "--top", "3"]},
    "standard": {"label": "Standard", "minutes": "about 8 to 12 minutes", "cost": "uses a moderate amount of free credits", "args": ["--limit", "150", "--top", "5"]},
    "full": {"label": "Full run", "minutes": "about 15 to 25 minutes", "cost": "uses the most free credits", "args": ["--top", "8"]},
}
STAGES = [("docs", "Collected news and pages"), ("signals", "Found buying signals"), ("scores", "Scored the leads"),
          ("people", "Looked up contacts"), ("drafts", "Wrote starter emails")]
JOB: dict = {"proc": None}


def slug(city: str) -> str:
    return re.sub(r"\W+", "_", city.lower()).strip("_")


def cities() -> list[str]:
    return list(yml("cities"))


def sizes() -> dict:
    """On the public host (BUDGET_PROFILE=demo) only the smallest run is offered, so one click cannot use the whole allowance."""
    return {"quick": SIZES["quick"]} if os.getenv("BUDGET_PROFILE") == "demo" else SIZES


def start(city: str, size: str) -> tuple[int, dict]:
    if city not in cities() or size not in sizes():
        return 422, {"error": "unknown city or size"}
    p = JOB.get("proc")
    if p and p.poll() is None:
        return 409, {"error": f"A run for {JOB['city']} is already in progress. Please wait for it to finish."}
    STATE.mkdir(exist_ok=True)
    folder = f"data_{slug(city)}"
    log = open(STATE / "job.log", "w", encoding="utf-8")
    env = {**os.environ, "DATA_DIR": folder, "PYTHONIOENCODING": "utf-8", "DRY_RUN": "0"}
    cmd = [sys.executable, "-m", "src.run", "all", "--city", city, "--wide", *SIZES[size]["args"]]
    JOB.update(proc=subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT), city=city, size=size, folder=folder, started=time.time(), log=log)
    return 200, {"started": True}


def status() -> dict:
    p = JOB.get("proc")
    if not p:
        return {"state": "idle"}
    code = p.poll()
    state = "running" if code is None else "done" if code == 0 else "failed"
    base = ROOT / JOB["folder"]
    done = [k for k, _ in STAGES if (base / f"{k}.json").exists() and (base / f"{k}.json").stat().st_mtime >= JOB["started"] - 1]
    lines = (STATE / "job.log").read_text("utf-8", errors="replace").splitlines()[-14:] if (STATE / "job.log").exists() else []
    lines = [re.sub(r"(api_key|token|key)=[^&\s]+", r"\1=***", l) for l in lines]
    return {"state": state, "city": JOB["city"], "size": JOB["size"], "elapsed": int(time.time() - JOB["started"]), "dataset": slug(JOB["city"]),
            "stages": [{"id": k, "label": l, "done": k in done} for k, l in STAGES], "tail": lines}
