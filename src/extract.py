"""Step 2: turn raw docs into signals. A keyword prefilter drops irrelevant headlines, Gemini reads the rest in batches,
and a signal is kept only if its evidence is a verbatim substring of the document (the anti-hallucination guard)."""
import hashlib
import re
from datetime import date

from pydantic import BaseModel

from . import cfg, llm
from .models import Account, Doc, Segment, Signal, TriggerType
from .resolve import resolve

PROMPT = """You extract sales triggers for InfinityBox, which sells warewashing and kitchen design to cafeterias.
From the text, list companies in or near {city} with a concrete recent event of these types:
new_campus, lease, cafeteria_revamp, tender, caterer_renewal, esg_plastic, facilities_hiring.
Segments: corporate (office employer), caterer (food-service operator), fitout (interiors/fit-out contractor), institution (college/hospital/hostel).
Rules:
- evidence: copy a snippet VERBATIM from the text (max 200 chars). Do not paraphrase.
- date: YYYY-MM-DD of the event/posting if stated, else "".
- size_est (seats/headcount), caterer, domain: only if explicitly stated, else null / "".
- conf: 0-1 confidence the event is real and recent.
- doc: if the text is a numbered list [0], [1], ..., the number of the item the event comes from; else 0.
- If nothing qualifies return {{"items": []}}.
Today is {today}.

TEXT:
{text}"""

KEEP = re.compile(r"campus|leas(e|es|ed|ing)\b|sq\.? ?ft|square feet|cafeteria|canteen|food court|cater|\bmess\b|hostel|tender|housekeeping|"
                  r"\bGCC\b|capability cent|new (office|centre|center|facility|plant|hospital)|opens|inaugurat|expands|plastic|zero waste|"
                  r"facilit(y|ies)|hiring|set(s|ting)? up|establish|hospital|\bbeds\b|seats?\b|data cent", re.I)
DROP = re.compile(r"collapse|clash|protest|ragging|murder|arrest|accident|share price|\bIPO\b|profit|\bQ[1-4]\b|cutoff|admission|exam\b|"
                  r"police|fire breaks|stock|sensex|nifty|report:|survey", re.I)
BATCH = 20  # short news headlines per LLM call (a call is a free-tier request, a headline is not)


class Item(BaseModel):
    company: str
    segment: Segment
    type: TriggerType
    date: str = ""
    summary: str
    evidence: str
    size_est: int | None = None
    caterer: str = ""
    domain: str = ""
    conf: float = 0.5
    doc: int = 0


class Extraction(BaseModel):
    items: list[Item] = []


def _n(s: str) -> str:
    return " ".join(s.split())


def evidence_ok(evidence: str, text: str) -> bool:
    return bool(evidence.strip()) and _n(evidence) in _n(text)


def _date(s: str, fallback: date) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        return fallback


def prefilter(d: Doc) -> bool:
    """Cheap keyword gate for news headlines, so the LLM budget goes to plausible signals only."""
    t = d.title or d.text
    return bool(KEEP.search(t)) and not DROP.search(t)


def extract(docs: list[Doc], city: str, accounts: list[Account], signals: list[Signal], stats: dict,
            manual: dict | None = None) -> None:
    """Mutates accounts/signals. Rows whose evidence is not in the fetched text are dropped.
    `manual` (url -> Extraction dict) is a fallback for when the LLM is unavailable. Short news headlines are
    prefiltered and sent in batches; long pages one call each."""
    have = {s.id for s in signals}

    def ingest(items, pick):
        for it in items:
            d = pick(it)
            if d is None or not evidence_ok(it.evidence, d.text):  # the snippet must be in the very text it came from
                print(f"rejected (evidence not in text): {it.company} / {it.evidence[:60]!r}")
                stats["rejected_evidence"] = stats.get("rejected_evidence", 0) + 1
                continue
            a = resolve(accounts, it.company, city, it.segment, it.size_est, it.caterer)  # LLM "domain" ignored: it returns the news publisher
            sid = hashlib.sha1(f"{a.id}{it.type}{d.url}".encode()).hexdigest()[:10]
            if sid in have:
                continue
            have.add(sid)
            signals.append(Signal(id=sid, account_id=a.id, type=it.type, date=_date(it.date, d.date), summary=it.summary,
                                  source_url=d.url, evidence=it.evidence, conf=it.conf))
            stats[f"signals_{d.source}"] = stats.get(f"signals_{d.source}", 0) + 1

    singles, batched = [], []
    for d in docs:
        if d.source == "news" and not cfg.dry:
            if prefilter(d):
                batched.append(d)
            else:
                stats["prefilter_skipped"] = stats.get("prefilter_skipped", 0) + 1
        else:
            singles.append(d)
    for i, d in enumerate(singles):
        try:
            try:
                res = llm.ask(PROMPT.format(city=city, today=date.today(), text=d.text[:6000]), Extraction, tag=f"extract_{i}")
            except Exception:
                if not (manual and d.url in manual):  # hand-made extraction is only a fallback when the LLM is unavailable
                    raise
                res = Extraction.model_validate(manual[d.url])
        except Exception as e:
            print(f"extract failed {d.url}: {str(e)[:120]}")
            stats["extract_failed"] = stats.get("extract_failed", 0) + 1
            continue
        ingest(res.items, lambda it, d=d: d)
    for k in range(0, len(batched), BATCH):
        group = batched[k:k + BATCH]
        text = "\n".join(f"[{j}] {d.text[:300]} (published {d.date})" for j, d in enumerate(group))
        try:
            res = llm.ask(PROMPT.format(city=city, today=date.today(), text=text), Extraction, tag=f"extract_batch_{k}")
        except Exception as e:
            print(f"extract batch {k // BATCH} failed: {str(e)[:120]}")
            stats["extract_failed"] = stats.get("extract_failed", 0) + len(group)
            continue
        ingest(res.items, lambda it, group=group: group[it.doc] if 0 <= it.doc < len(group) else None)
