"""Flat, filterable lead view: one row per account with score, best contact and every link that backs the lead."""
import csv
import json
from datetime import date, timedelta

from . import store
from .models import Account, LeadRow, Person, Score, Signal
from .score import top_signal


def kind(url: str) -> str:
    return "tender" if "tender" in url.lower() else "news"


def _ranked(people: list[Person]) -> list[Person]:
    """Real contacts, best first: relevance decides (a target without an email beats a gatekeeper with one)."""
    real = [p for p in people if p.source != "linkedin-search-link"]
    return sorted(real, key=lambda p: (p.role_match >= 0.6, p.role_match, bool(p.email), bool(p.name)), reverse=True)


def _who(p: Person) -> str:
    return ", ".join(x for x in (p.name, p.role, p.email) if x)


def build() -> list[LeadRow]:
    accs = {a.id: a for a in store.load("accounts", Account)}
    sigs, people = store.load("signals", Signal), store.load("people", Person)
    rows, per_city = [], {}
    for sc in sorted(store.load("scores", Score), key=lambda s: -s.total):
        a = accs[sc.account_id]
        g = sorted([s for s in sigs if s.account_id == a.id], key=lambda s: s.date, reverse=True)
        ps = [p for p in people if p.account_id == a.id]
        ranked = _ranked(ps)
        c, c2 = (ranked + [None, None])[:2]
        link = next((p for p in ps if p.source == "linkedin-search-link"), None)
        per_city[a.city] = per_city.get(a.city, 0) + 1
        rows.append(LeadRow(
            rank=per_city[a.city], account=a.name, city=a.city, segment=a.segment, total=sc.total, fit=sc.fit, trigger=sc.trigger,
            reach=sc.reach, reason=sc.reason, triggers=",".join(sorted({s.type for s in g})),
            source_kinds=",".join(sorted({kind(s.source_url) for s in g})), newest_signal=g[0].date.isoformat() if g else "",
            website=a.domain, linkedin_company=a.linkedin_url,
            contact_name=c.name if c else "", contact_title=(c.role if c else (link.role if link else "")),
            contact_linkedin=(c.profile_url if c and c.profile_url else (link.profile_url if link else "")),
            contact_email=c.email if c else "", email_status=c.email_status if c else "", contact_source=c.source if c else "",
            contact_tier=c.tier if c else "", contact_why=c.why if c else "", second_contact=_who(c2) if c2 else "",
            contact_page=c.source_url if c else "", n_sources=len({s.source_url for s in g}),
            evidence_links="\n".join(f"{s.type} | {s.date} | {s.summary} | {s.source_url}" for s in g)))
    return rows


def apply_filters(rows: list[LeadRow], city=None, segment=None, trigger=None, min_score=0.0, has_contact=False,
                  has_email=False, since_days=None, source_kind=None, tier=None) -> list[LeadRow]:
    cutoff = (date.today() - timedelta(days=since_days)).isoformat() if since_days else ""
    return [r for r in rows
            if (not city or r.city.lower() == city.lower())
            and (not segment or r.segment == segment)
            and (not trigger or trigger in r.triggers.split(","))
            and r.total >= min_score
            and (not tier or r.contact_tier == tier)
            and (not has_contact or r.contact_name)
            and (not has_email or r.contact_email)
            and (not cutoff or r.newest_signal >= cutoff)
            and (not source_kind or source_kind in r.source_kinds.split(","))]


def export(rows: list[LeadRow], path: str, fmt: str) -> None:
    if fmt == "json":
        open(path, "w", encoding="utf-8").write(json.dumps([r.model_dump() for r in rows], indent=1, ensure_ascii=False))
    elif fmt == "csv":
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(LeadRow.model_fields))
            w.writeheader()
            w.writerows(r.model_dump() for r in rows)
    else:
        out = ["| # | Account | City | Segment | Score | Why now | Contact | Email | LinkedIn | Backing links |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            who = f"{r.contact_name}, {r.contact_title}" if r.contact_name else f"(none found) {r.contact_title}"
            links = "<br>".join(f"[{l.split(' | ')[0]}]({l.rsplit(' | ', 1)[1]})" for l in r.evidence_links.splitlines())
            li = f"[profile]({r.contact_linkedin})" if r.contact_linkedin else ""
            co = f" / [company]({r.linkedin_company})" if r.linkedin_company else ""
            out.append(f"| {r.rank} | {r.account} | {r.city} | {r.segment} | {r.total} | {r.reason} | {who} | "
                       f"{r.contact_email + ' (' + r.email_status + ')' if r.contact_email else ''} | {li}{co} | {links} |")
        open(path, "w", encoding="utf-8").write("\n".join(out))
