from datetime import date

from .cfg import yml
from .models import Account, Person, Score, Signal

LABEL = {"new_campus": "new campus", "lease": "new lease", "cafeteria_revamp": "cafeteria revamp", "tender": "tender",
         "caterer_renewal": "caterer renewal", "esg_plastic": "plastic/ESG push", "facilities_hiring": "hiring facilities"}


def contrib(s: Signal, today: date) -> float:
    """weight * 0.5 ** (age_days / half_life). Future-dated signals count as age 0."""
    t = yml("triggers")[s.type]
    return t["weight"] * 0.5 ** (max((today - s.date).days, 0) / t["half_life"])


def top_signal(sigs: list[Signal], today: date) -> Signal | None:
    return max(sigs, key=lambda s: contrib(s, today), default=None)


def score_account(a: Account, sigs: list[Signal], people: list[Person], today: date) -> Score:
    w = yml("weights")
    f = w["fit"]
    fit = f["segment_match"] + (f["city_match"] if a.city in yml("cities") else 0)
    fit += f["size"] * min(a.size_est or 0, f["size_cap"]) / f["size_cap"]
    if a.caterer or any(s.type in ("cafeteria_revamp", "caterer_renewal") for s in sigs):
        fit += f["cafeteria"]
    best = {}  # the same event reported by five outlets must not count five times: strongest signal per trigger type
    for s in sigs:
        best[s.type] = max(best.get(s.type, 0.0), contrib(s, today))
    trig = min(sum(best.values()), w["trigger_cap"])
    r = w["reach"]
    reach = (r["named_person"] if any(p.name and p.role_match >= 0.6 for p in people)
             else r["gatekeeper"] if any(p.source != "linkedin-search-link" and p.role_match >= 0.3 for p in people) else 0) \
        + (r["verified_email"] if any(p.email_status == "valid" and p.role_match >= 0.6 for p in people)
           else r["other_email"] if any(p.email and p.role_match >= 0.6 for p in people) else 0) \
        + (r["known_caterer"] if a.caterer else 0)
    parts, seen = [], set()
    for s in sorted(sigs, key=lambda s: -contrib(s, today)):
        if s.type not in seen and len(seen) < 2:
            seen.add(s.type)
            parts.append(f"{LABEL[s.type]} ({s.date:%b %Y})")
    if a.size_est:
        parts.append(f"~{a.size_est:,} seats")
    if a.caterer:
        parts.append(f"caterer {a.caterer}")
    return Score(account_id=a.id, fit=round(fit, 1), trigger=round(trig, 1), reach=reach,
                 total=round(fit + trig + reach, 1), reason=" + ".join(parts), updated=today.isoformat())


def score_all(accounts, signals, people, today: date | None = None) -> list[Score]:
    today = today or date.today()
    out = [score_account(a, [s for s in signals if s.account_id == a.id], [p for p in people if p.account_id == a.id], today)
           for a in accounts]
    out.sort(key=lambda s: -s.total)
    for i, s in enumerate(out, 1):
        s.rank = i
    return out
