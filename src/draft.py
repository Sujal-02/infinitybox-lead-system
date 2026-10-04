"""Outreach drafts from the playbook (config/playbook.yaml). The LLM only fills an event phrase and picks line ids;
the email text itself comes from the approved playbook, so it cannot invent claims about InfinityBox."""
from . import llm, playbook
from .models import Account, Draft, Person, Signal
from .playbook import Choice

PROMPT = """You choose parts of an outreach email for InfinityBox. You do NOT write the email: it is assembled from an approved playbook.
Company: {company} ({segment}, {city})
Person or role to address: {role}
Trigger: {summary}
Evidence (verbatim from the source): "{evidence}"

Return JSON with:
- to_role: the role to address (use the one above unless it clearly does not fit).
- event_phrase: restate the trigger as a short phrase that continues "Saw that {company} ..." (e.g. "opened a new campus in Bengaluru").
  Use only words and numbers that appear in the evidence or trigger. No claims, no predictions, no opinions.
- value_id, condition_id, cta_id: choose from the menu below.
Menu:
{menu}"""


def _check(segment: str, evidence: str):
    def check(c: Choice):
        bad = playbook.validate(c, segment, evidence)
        if bad:
            raise ValueError("; ".join(bad))
    return check


def draft(a: Account, sig: Signal, person: Person, manual=None) -> Draft:  # `manual` kept for call compatibility; unused
    ev = f"{sig.evidence} {sig.summary}"
    p = PROMPT.format(company=a.name, segment=a.segment, city=a.city, role=person.role, summary=sig.summary,
                      evidence=sig.evidence, menu=playbook.options(a.segment))
    c = llm.ask(p, Choice, tag="draft", check=_check(a.segment, ev))
    subject, body = playbook.render(a.name, a.segment, c)
    return Draft(account_id=a.id, role=c.to_role or person.role, subject=subject, body=body, trigger_used=sig.id)
