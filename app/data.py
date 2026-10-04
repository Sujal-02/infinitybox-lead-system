"""Loads leads for the app from a local data folder (pipeline output or a Gemini-agent run) into one common shape."""
import json
import re
from datetime import date
from pathlib import Path

from brain import scoring
from src import hierarchy
from src.cfg import ROOT, yml
from src.models import Account, Person, Score, Signal
from .explain import explain

DATASETS = {
    "pune": {"label": "Pune (pipeline)", "kind": "pipeline", "dir": "data", "city": "Pune"},
    "bengaluru": {"label": "Bengaluru (pipeline)", "kind": "pipeline", "dir": "data_blr", "city": "Bangalore"},
    "bengaluru_agent": {"label": "Bengaluru (Gemini agent)", "kind": "agent", "dir": "data_brain2"},
    "bengaluru_agent1": {"label": "Bengaluru (Gemini agent, first run)", "kind": "agent", "dir": "data_brain"},
}


def _dynamic() -> dict:
    """Lists made by the app's "Find leads" button live in data_<city>/; they show up here without any config."""
    out, known = {}, {d["dir"] for d in DATASETS.values()}
    for p in sorted(ROOT.glob("data_*")):
        f = p / "accounts.json"
        if p.name in known or not f.exists():
            continue
        rows = json.loads(f.read_text("utf-8"))
        city = rows[0]["city"] if rows else p.name[5:].title()
        out[p.name[5:]] = {"label": f"{city} (pipeline)", "kind": "pipeline", "dir": p.name, "city": city}
    return out


def config(ds_id: str) -> dict:
    return {**DATASETS, **_dynamic()}[ds_id]  # a newer run in data_<city>/ replaces the built-in list of the same name


def available() -> list[dict]:
    out = []
    for k, d in {**DATASETS, **_dynamic()}.items():
        probe = ROOT / d["dir"] / ("accounts.json" if d["kind"] == "pipeline" else "leads.json")
        if probe.exists():
            out.append({"id": k, "label": d["label"], "sheet": d["kind"] == "pipeline", "city": d.get("city", "")})
    return out


def _j(path: Path):
    return json.loads(path.read_text("utf-8")) if path.exists() else []


def _contact(p: Person) -> dict:
    return {"name": p.name, "title": p.role, "email": p.email, "email_status": p.email_status, "linkedin": p.profile_url,
            "tier": p.tier, "relevance": p.role_match, "why": p.why, "source": p.source, "source_url": p.source_url}


def recommend(segment: str, triggers: list[str], contacts: list[dict]) -> str:
    """Which email style to suggest first (a hint only: the user can pick any style)."""
    styles = yml("templates")["styles"]
    targets = [c for c in contacts if c["relevance"] >= hierarchy.TARGET]
    if not targets:
        return "gatekeeper_intro"
    for sid, s in styles.items():
        if segment in s["for"] and any(t in s["triggers"] for t in triggers):
            return sid
    return {"caterer": "caterer_partner", "fitout": "fitout_partner"}.get(segment, "trigger_first")


def _lead(a: Account, sigs: list[Signal], people: list[Person], why_now: str = "", extra: dict | None = None) -> dict:
    sigs = sorted(sigs, key=lambda s: s.date, reverse=True)
    real = sorted([p for p in people if p.source != "linkedin-search-link"], key=lambda p: -p.role_match)
    contacts = [_contact(p) for p in real]
    triggers = sorted({s.type for s in sigs})
    ex = explain(a, sigs, people)
    return {"id": a.id, "company": a.name, "city": a.city, "segment": a.segment, "kind": a.org_kind or hierarchy.classify(a.segment, a.name),
            "score": ex, "why_now": why_now or (sigs[0].summary if sigs else ""), "triggers": triggers, "website": a.domain,
            "linkedin_company": a.linkedin_url, "contacts": contacts,
            "search_links": [{"role": p.role, "url": p.profile_url} for p in people if p.source == "linkedin-search-link"],
            "sources": [{"type": s.type, "date": s.date.isoformat(), "headline": s.summary, "url": s.source_url, "quote": s.evidence} for s in sigs],
            "recommended_style": recommend(a.segment, triggers, contacts), **(extra or {})}


def load(ds_id: str) -> list[dict]:
    d = config(ds_id)
    base = ROOT / d["dir"]
    out = []
    if d["kind"] == "pipeline":
        accs = {a["id"]: Account.model_validate(a) for a in _j(base / "accounts.json")}
        sigs = [Signal.model_validate(s) for s in _j(base / "signals.json")]
        people = [Person.model_validate(p) for p in _j(base / "people.json")]
        for sc in (Score.model_validate(s) for s in _j(base / "scores.json")):
            a = accs[sc.account_id]
            if d.get("city") and a.city != d["city"]:  # a data folder can hold several cities
                continue
            out.append(_lead(a, [s for s in sigs if s.account_id == a.id], [p for p in people if p.account_id == a.id]))
    else:
        meta = (json.loads((base / "meta.json").read_text("utf-8")) if (base / "meta.json").exists() else {})
        city = meta.get("city", "Bangalore")
        for l in _j(base / "leads.json"):
            slug = re.sub(r"\W+", "-", l["company"].lower()).strip("-")
            kind = hierarchy.classify(l["segment"], l["company"], l["summary"])
            a = Account(id=slug, name=l["company"], city=city, segment=l["segment"], first_seen=date.today(), org_kind=kind,
                        domain=l.get("website", ""), linkedin_url=l.get("linkedin_company_url", ""))
            s = Signal(id="s", account_id=slug, type=l["trigger_type"], date=date.fromisoformat(l["event_date"]), summary=l["summary"],
                       source_url=l["source_url"], evidence=l["evidence"])
            sc = scoring.score_lead(l, city, {})
            people = [Person(account_id=slug, role=c.get("title", ""), name=c.get("name", ""), email=c.get("email", ""), email_status=c["email_status"],
                             profile_url=c.get("linkedin_url", ""), source="agent", role_match=c["relevance"], tier=c["tier"], why=c["why"])
                      for c in sc["contacts"]]
            out.append(_lead(a, [s], people, why_now=l["why_now"], extra={"buyer_logic": l.get("buyer_logic", "")}))
    out.sort(key=lambda x: -x["score"]["total"])
    for i, l in enumerate(out, 1):
        l["rank"] = i
    return out
