"""LLM-written email drafts, guided by a style (config/templates.yaml) and bound by the playbook (config/playbook.yaml):
the model may state only the approved facts about InfinityBox, may not use forbidden words, and may only quote numbers that
are in the lead's evidence. The result is a starting point that the user edits; nothing here sends anything."""
import re
from urllib.parse import quote

from pydantic import BaseModel

from src import llm
from src.cfg import yml


class DraftOut(BaseModel):
    subject: str
    body: str  # the message text only: no greeting and no sign-off (the app adds those)


def facts() -> list[str]:
    p = yml("playbook")
    f = p["facts"]
    lines = [v for v in f.values() if isinstance(v, str)] + [p["value_lines"]["warewash_core"]["text"], *f.get("verified_claims", [])]
    return list(dict.fromkeys(lines))


def _first_name(name: str) -> str:
    n = re.sub(r"^(dr|prof|mr|mrs|ms|shri|smt)[.\s]+", "", (name or "").strip(), flags=re.I)
    return n.split()[0].title() if n else ""


def assemble(subject: str, body: str, contact: dict | None) -> tuple[str, str]:
    """Add the greeting (only if we know a name) and the sign-off placeholder around the model's message."""
    t = yml("templates")
    first = _first_name((contact or {}).get("name", ""))
    parts = [t["greeting"].format(first_name=first)] if first else []
    return subject.strip(), "\n\n".join(parts + [body.strip(), t["signoff"]])


def _allowed_text(lead: dict, notes: str) -> str:
    srcs = " ".join(f"{s['quote']} {s['headline']}" for s in lead["sources"])
    return f"{srcs} {lead['why_now']} {notes} {' '.join(facts())}".lower()


def problems(lead: dict, subject: str, body: str, notes: str = "", whole: bool = False) -> list[str]:
    """Hard guardrails. `body` is the model's message, or the whole edited email when whole=True."""
    pb, t = yml("playbook"), yml("templates")
    text = f"{subject}\n{body}"
    bad = []
    for w in pb["forbidden_words"]:
        if re.search(rf"(?<![A-Za-z]){re.escape(w.strip())}", text, re.I):
            bad.append(f"uses a word we do not claim: '{w.strip()}'")
    allowed = _allowed_text(lead, notes)
    for n in re.findall(r"\d[\d,.]*\d|\d", text):
        n = n.strip(".,")
        big = len(re.sub(r"\D", "", n)) >= 3 or "," in n or "." in n
        if big and n not in allowed:
            bad.append(f"number '{n}' is not in the evidence")
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        bad.append("contains an email address (the draft must not invent one)")
    limit = t["max_words"] if whole else pb["max_words"]
    if len(body.split()) > limit:
        bad.append(f"{len(body.split())} words; the limit is {limit}")
    if "infinitybox" not in text.lower():
        bad.append("does not mention InfinityBox")
    if len(subject.split()) > 12 or not subject.strip():
        bad.append("subject should be 1-12 words")
    return bad


def _prompt(lead: dict, style_id: str, contact: dict | None, notes: str) -> str:
    s = yml("templates")["styles"][style_id]
    pb = yml("playbook")
    src = lead["sources"][0] if lead["sources"] else {"quote": "", "headline": "", "date": ""}
    who = (f"{contact['name'] or 'a contact'}, {contact['title']}" if contact else "no specific person (address the organisation's facilities / cafeteria owner)")
    return f"""You write one outreach email draft for InfinityBox. A human will edit it before anything happens. Write the MESSAGE ONLY:
no greeting and no sign-off (the app adds those).

About the lead
- Company: {lead['company']} ({lead['segment']}, {lead['city']})
- Trigger ({src['date']}): {src['headline']}
- Evidence, verbatim from the source: "{src['quote']}"
- Why it matters now: {lead['why_now']}
- Writing to: {who}
- Extra note from the user: {notes or 'none'}

Style: {s['name']}. Structure to follow: {s['structure']}

About InfinityBox: you may state ONLY these facts, in your own words, and nothing else:
{chr(10).join('- ' + f for f in facts())}
Never claim: certifications, technology, savings, percentages, guarantees, past clients, or anything not in the list above. Words you must not use: {', '.join(pb['forbidden_words'])}.

Rules
- At most {pb['max_words']} words. Plain, friendly, specific. No buzzwords, no flattery, no exclamation marks.
- The first sentence must state the trigger using only words and numbers from the evidence.
- Anything you do not know about them (their caterer, their plans, their needs) must be written as an "if" or a question, never as a fact.
- Do not invent names, email addresses, numbers, dates or events.
Return JSON: {{"subject": "...", "body": "..."}} (subject: 3-9 words)."""


def generate(lead: dict, style_id: str, contact: dict | None, notes: str = "") -> dict:
    def check(o: DraftOut):
        bad = problems(lead, o.subject, o.body, notes)
        if bad:
            raise ValueError("; ".join(bad))
    out = llm.ask(_prompt(lead, style_id, contact, notes), DraftOut, check=check)
    subject, body = assemble(out.subject, out.body, contact)
    return {"subject": subject, "body": body, "words": len(out.body.split()), "style": style_id}


def gmail_url(to: str, subject: str, body: str) -> str:
    """A Gmail compose link, pre-filled. The USER presses send in Gmail; nothing in this app emails anyone."""
    return f"https://mail.google.com/mail/?view=cm&fs=1&to={quote(to)}&su={quote(subject)}&body={quote(body)}"
