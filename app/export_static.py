"""Builds the read-only copy of the lead desk for GitHub Pages: dashboard/index.html + dashboard/data/*.json.
Personal details are removed before anything is written: contact names, emails and LinkedIn profiles are blanked, and any
email address or contact name found elsewhere in a lead is replaced. Company-level facts (trigger, score, sources) stay.

    python -m app.export_static             # rebuild index.html and the data snapshot
    python -m app.export_static --html-only # rebuild index.html only (what CI checks; needs no run data)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard"
SKIP = {"bengaluru_agent1"}  # superseded first agent run
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def scrub(lead: dict) -> dict:
    names = sorted({c["name"] for c in lead["contacts"] if c.get("name")}, key=len, reverse=True)
    for c in lead["contacts"]:
        c.update(name="", email="", email_status="", linkedin="", source_url="", why="", hidden=True)
    blob = json.dumps(lead, ensure_ascii=False)
    for n in names:
        blob = blob.replace(n, "[name hidden]")
    return json.loads(EMAIL.sub("[email hidden]", blob))


def html() -> str:
    src = (ROOT / "app" / "static" / "index.html").read_text("utf-8")
    flag = '<script>window.STATIC_BASE = "data/";</script>\n'
    i = src.rindex("<script>")
    return src[:i] + flag + src[i:]


def build(html_only: bool = False) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(html(), "utf-8", newline="\n")
    if html_only:
        return
    from app import data, drafting, server  # imported late: the html-only path must work without the pipeline's dependencies
    (OUT / "data").mkdir(exist_ok=True)
    keep = [d for d in data.available() if d["id"] not in SKIP]
    for old in (OUT / "data").glob("*.json"):
        old.unlink()
    for d in keep:
        leads = [scrub(l) for l in data.load(d["id"])]
        (OUT / "data" / f"leads_{d['id']}.json").write_text(json.dumps(leads, ensure_ascii=False), "utf-8")
    (OUT / "data" / "datasets.json").write_text(json.dumps(keep), "utf-8")
    (OUT / "data" / "styles.json").write_text(json.dumps({"styles": server.styles(), "facts": drafting.facts()}, ensure_ascii=False), "utf-8")
    print(f"wrote {len(keep)} lead lists to {OUT}")


if __name__ == "__main__":
    build("--html-only" in sys.argv)
