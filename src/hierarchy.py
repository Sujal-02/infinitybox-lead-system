"""Contact relevance: how likely a title/mailbox is the right person for what InfinityBox sells, per kind of organisation.
See config/hierarchy.yaml for the tiers. Pure functions, no network."""
import re
from dataclasses import dataclass

from .cfg import yml

BASE = {"tier1": 0.9, "tier2": 0.7, "tier3": 0.4}
LABEL = {"tier1": "decision maker", "tier2": "day-to-day owner", "tier3": "gatekeeper (route, not the buyer)",
         "generic": "generic mailbox", "none": "not relevant"}
TARGET = 0.6  # at or above: a real target (tier1/tier2)
PHRASE_NOISE = {"head", "officer", "manager", "director", "of", "and", "the", "in", "chief"}
MAILBOX_NOISE = {"office", "officer", "head", "manager", "director", "info", "contact", "mail", "enquiry", "enquiries", "support", "hello", "dept", "the"}

KIND_RULES = {  # segment -> [(kind, regex on name + signal text)], first match wins; last entry is the default
    "institution": [("hospital", r"hospital|medical|clinic|health|aiims|nursing"),
                    ("government", r"government|govt|state of|prison|department|corporation|authority|municipal|pmrda|pmc\b|ministry|defence|laborator|hemrl|railway|commission|council|panchayat"),
                    ("education", "")],
    "corporate": [("manufacturing", r"manufactur|plant\b|factory|motors|automation|industr|machin|steel|chemical|chemie|land rover|forging"),
                  ("corporate", "")],
    "caterer": [("caterer", "")],
    "fitout": [("fitout", "")],
}


@dataclass
class Rel:
    score: float
    tier: str
    why: str


def classify(segment: str, name: str, text: str = "") -> str:
    blob, strong = name.lower(), f"{name} {'manufacturing' if 'manufacturing' in text.lower() else ''}".lower()
    for kind, rx in KIND_RULES[segment]:
        # the name decides; signal text only counts when it says "manufacturing" ("Factory Lab" does not make TCS a plant)
        if not rx or re.search(rx, blob) or (kind == "manufacturing" and "manufacturing" in strong):
            return kind
    return segment


def _toks(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def _strict(t: str, w: str) -> bool:
    """Same word, allowing only plural/-y forms (facility = facilities); no prefixes ("corporatehr" is not "corporate")."""
    norm = lambda x: re.sub(r"ies$", "y", x).rstrip("s")
    return norm(t) == norm(w)


def _match(phrase: str, toks: list[str], strict: bool = False) -> bool:
    """The phrase's words appear in the title in order and close together (exact for short words, 5-letter prefix for
    longer: facility = facilities). "AMS Delivery Manager ... Food Service" must not match "food services manager"."""
    words = [w for w in _toks(phrase) if w not in ("of", "and", "the", "in", "for")]
    same = _strict if strict else (lambda t, w: t == w or (len(w) > 3 and len(t) > 3 and t[:5] == w[:5]))
    for start in range(len(toks)):
        i, last = start, start
        for w in words:
            while i < len(toks) and not same(toks[i], w):
                i += 1
            if i >= len(toks):
                break
            last, i = i, i + 1
        else:
            if last - start < len(words) + 2:
                return True
    return False


def _has(words: list[str], low: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}", low) for w in words)


def relevance(title: str, kind: str, triggers=()) -> Rel:
    h = yml("hierarchy")
    k, toks, low = h["kinds"][kind], _toks(title), title.lower()
    hit = next(((t, p) for t in ("tier1", "tier2", "tier3") for p in k[t] if _match(p, toks)), None)
    if not hit:
        return Rel(0.0, "none", "no target role keyword in the title")
    tier, phrase = hit
    if tier != "tier1" and any(_match(x, toks) for x in k["exclude"]):
        return Rel(0.0, "none", "excluded role (not involved in cafeteria/kitchen/facilities)")
    score, notes = BASE[tier], [f"{LABEL[tier]}: matches '{phrase}'"]
    for t in triggers:
        if _has(h["trigger_boost"].get(t, []), low):
            score += 0.1
            notes.append(f"relevant to the {t} trigger")
            break
    if _has(h["senior_words"], low):
        score += 0.05
    if _has(h["junior_words"], low) and tier != "tier3":
        score -= 0.15
        notes.append("junior title")
    return Rel(round(min(max(score, 0.0), 1.0), 2), tier, "; ".join(notes))


def mailbox_relevance(local: str, kind: str, triggers=()) -> Rel:
    """A published address like estate@ / registrar@ / info@, judged by its name."""
    words = [w for w in re.findall(r"[a-z]+", local.lower()) if w not in MAILBOX_NOISE]
    r = relevance(" ".join(words), kind, triggers) if all(w in sum((_toks(x) for t in ("tier1", "tier2", "tier3") for x in yml("hierarchy")["kinds"][kind][t]), []) or w[:-1] in sum((_toks(x) for t in ("tier1", "tier2", "tier3") for x in yml("hierarchy")["kinds"][kind][t]), []) for w in words) else Rel(0.0, "none", "")
    if r.score:
        return r
    k = yml("hierarchy")["kinds"][kind]
    for tier in ("tier1", "tier2", "tier3"):  # estate@ is the office that "Estate Officer" belongs to
        for phrase in k[tier]:
            need = [w for w in _toks(phrase) if w not in PHRASE_NOISE]  # every distinctive word of the title must be in the mailbox name
            if need and all(any(_strict(t, w) for t in words) for w in need):
                if tier != "tier1" and any(_match(x, words) for x in k["exclude"]):
                    continue
                return Rel(round(BASE[tier] - 0.1, 2), tier, f"mailbox name points to the {phrase} office ({LABEL[tier]})")
    return Rel(0.15, "generic", "generic mailbox, no role stated")


def titles_for(kind: str, tiers=("tier1", "tier2")) -> list[str]:
    return [p for t in tiers for p in yml("hierarchy")["kinds"][kind][t]]


def page_hints(kind: str) -> list[tuple[str, int]]:
    """(word, priority) for choosing which website pages to read; lower priority number = read first."""
    k, out = yml("hierarchy")["kinds"][kind], [("contact", 0)]
    for tier, rank in (("tier1", 1), ("tier2", 1), ("tier3", 2)):
        out += [(w, rank) for p in k[tier] for w in re.findall(r"[a-z]{5,}", p.lower()) if w not in ("head", "officer", "manager", "director")]
    return out + [("leadership", 3), ("team", 3), ("about", 3)]


def search_terms(kind: str) -> str:
    return yml("hierarchy")["kinds"][kind]["search_terms"]


def query_words(kind: str, n: int = 10) -> list[str]:
    """Search terms for a boolean job-title query: each tier1/tier2 title minus filler words ("head of real estate" -> "real estate"),
    so single noise words like "real" or "services" are never searched alone."""
    seen = []
    for phrase in titles_for(kind):
        term = " ".join(w for w in _toks(phrase) if w not in PHRASE_NOISE and len(w) > 2)
        if term and term not in seen and term.rstrip("s") not in seen and not any(term == x + "s" for x in seen):
            seen.append(term)
    return seen[:n]
