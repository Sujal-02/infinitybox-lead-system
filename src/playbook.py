"""Template-driven outreach. The email is assembled from config/playbook.yaml; the LLM only fills one slot (event_phrase,
a restatement of the trigger) and picks line ids. Everything it chose is validated here before anything is rendered."""
import re

from pydantic import BaseModel

from .cfg import yml


class Choice(BaseModel):
    to_role: str
    event_phrase: str     # e.g. "opened a 830,000 sq ft campus in Bengaluru": restates the trigger, nothing else
    value_id: str
    condition_id: str = "none"
    cta_id: str = "call_15"


def options(segment: str) -> str:
    """The menu shown to the LLM: ids only with their text, for this segment."""
    p = yml("playbook")
    lines = [f'value_id: {k} = "{v["text"]}"' for k, v in p["value_lines"].items() if segment in v["for"]]
    lines += [f'condition_id: {k} = "{v["text"]}"' for k, v in p["conditions"].items() if segment in v["for"]]
    lines += [f'cta_id: {k} = "{v}"' for k, v in p["ctas"].items()]
    return "\n".join(lines)


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


def validate(choice: Choice, segment: str, evidence: str) -> list[str]:
    """Problems with a choice; empty list = fine. The event phrase must be supported by the evidence text."""
    p, bad = yml("playbook"), []
    ph = choice.event_phrase.strip()
    if not ph or len(ph.split()) > 16:
        bad.append("event_phrase must be 1-16 words")
    low = ph.lower()
    for w in p["forbidden_words"]:
        if w.lower() in low:
            bad.append(f"event_phrase contains forbidden word {w!r}")
    ev = evidence.lower()
    unsupported = [t for t in _words(ph) if t not in ev and t[:5] not in ev]  # prefix match: "leased" ~ "leases"
    if len(unsupported) > max(1, len(_words(ph)) // 4):
        bad.append(f"event_phrase uses words not in the evidence: {sorted(unsupported)[:6]} (restate only what the evidence says)")
    nums = re.findall(r"\d[\d,.]*", ph)
    if any(n.strip(".,") not in evidence for n in nums):
        bad.append("event_phrase has a number that is not in the evidence")
    v, c = p["value_lines"].get(choice.value_id), p["conditions"].get(choice.condition_id)
    if not v or segment not in v["for"]:
        bad.append(f"value_id {choice.value_id!r} is not allowed for segment {segment}")
    if not c or segment not in c["for"]:
        bad.append(f"condition_id {choice.condition_id!r} is not allowed for segment {segment}")
    if choice.cta_id not in p["ctas"]:
        bad.append(f"cta_id {choice.cta_id!r} unknown")
    return bad


def render(company: str, segment: str, choice: Choice) -> tuple[str, str]:
    """(subject, body) from the playbook. Raises ValueError if the result breaks the word limit or forbidden words."""
    p = yml("playbook")
    parts = [p["opening"].format(company=company, event_phrase=choice.event_phrase.strip().rstrip(".")),
             p["value_lines"][choice.value_id]["text"], p["conditions"][choice.condition_id]["text"], p["ctas"][choice.cta_id]]
    body = " ".join(x for x in parts if x)
    if len(body.split()) > p["max_words"]:
        raise ValueError(f"email is {len(body.split())} words; limit {p['max_words']}")
    return p["subjects"][segment].format(company=company), body
