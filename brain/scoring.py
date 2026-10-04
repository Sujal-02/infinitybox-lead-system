"""Deterministic scoring and contact relevance for agent-saved leads. The LLM never scores: this reuses the pipeline's rules
(config/weights.yaml, config/triggers.yaml: recency decay, fit, reach) and the contact hierarchy (config/hierarchy.yaml)."""
import re
from datetime import date

from src import hierarchy
from src.models import Account, Person, Signal
from src.score import score_account

# a trigger label must be supported by words in the evidence/summary (the LLM stretched labels in the first run)
SUPPORT = {
    "new_campus": r"campus|office|centre|center|facility|gcc|headquarter|hq\b|opens|inaugurat|unit\b|hospital|plant|building|expan",
    "lease": r"leas|sq\.? ?ft|square f|rent|tenan|pre-?leas",
    "cafeteria_revamp": r"cafeteria|canteen|food court|kitchen|dining|\bmess\b|pantry|renovat|revamp",
    "tender": r"tender|\bbid\b|rfp|rfq|e-?procure|contract",
    "caterer_renewal": r"cater|food service|contract",
    "esg_plastic": r"plastic|sustainab|waste|esg|brsr|single-use|net[- ]zero|recycl",
}
HIRING_WHEN = r"hiring|recruit|vacanc|\bjob|opening|appoint"
HIRING_WHAT = r"facilit|workplace|admin|real estate|cafeteria|canteen|kitchen|catering|food|hospitality"


def trigger_supported(trigger: str, text: str) -> bool:
    t = text.lower()
    if trigger == "facilities_hiring":
        return bool(re.search(HIRING_WHEN, t) and re.search(HIRING_WHAT, t))
    return bool(re.search(SUPPORT[trigger], t))


def score_lead(lead: dict, city: str, email_status: dict[str, str]) -> dict:
    kind = hierarchy.classify(lead["segment"], lead["company"], lead["summary"])
    slug = re.sub(r"\W+", "-", lead["company"].lower()).strip("-")
    a = Account(id=slug, name=lead["company"], city=city, segment=lead["segment"], first_seen=date.today(), org_kind=kind)
    sig = Signal(id="s", account_id=slug, type=lead["trigger_type"], date=date.fromisoformat(lead["event_date"]), summary=lead["summary"],
                 source_url=lead["source_url"], evidence=lead["evidence"])
    people, contacts = [], []
    for c in lead.get("contacts") or []:
        rel = hierarchy.relevance(c.get("title", ""), kind, [lead["trigger_type"]]) if c.get("title") else hierarchy.Rel(0.0, "none", "no title")
        if not c.get("title") and c.get("email"):  # a mailbox: judged by its name
            rel = hierarchy.mailbox_relevance(c["email"].split("@")[0], kind, [lead["trigger_type"]])
        status = email_status.get((c.get("email") or "").lower(), "published" if c.get("email") else "")
        people.append(Person(account_id=slug, role=c.get("title", ""), name=c.get("name", ""), email=c.get("email", ""), email_status=status,
                             source="agent", role_match=rel.score, tier=rel.tier, why=rel.why))
        contacts.append({**c, "email_status": status, "relevance": rel.score, "tier": rel.tier, "why": rel.why})
    s = score_account(a, [sig], people, date.today())
    return {"total": s.total, "fit": s.fit, "trigger": s.trigger, "reach": s.reach, "reason": s.reason, "org_kind": kind, "contacts": contacts}
