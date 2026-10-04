"""Plain-language breakdown of a lead's score. Mirrors src/score.py exactly (a test asserts the totals agree), so the numbers
a non-technical user sees are the numbers the system actually used."""
from datetime import date

from src.cfg import yml
from src.models import Account, Person, Signal
from src.score import LABEL, contrib

TYPE_LABEL = {k: v.capitalize() for k, v in LABEL.items()}


def explain(a: Account, sigs: list[Signal], people: list[Person], today: date | None = None) -> dict:
    today, w, trig_cfg = today or date.today(), yml("weights"), yml("triggers")
    f, r = w["fit"], w["reach"]
    # ---- fit
    fit_parts = [{"label": "Kind of organisation we sell to", "pts": f["segment_match"], "note": a.segment}]
    in_city = a.city in yml("cities")
    fit_parts.append({"label": "City we cover", "pts": f["city_match"] if in_city else 0, "note": a.city})
    size_pts = f["size"] * min(a.size_est or 0, f["size_cap"]) / f["size_cap"]
    fit_parts.append({"label": "Size", "pts": round(size_pts, 1), "note": f"about {a.size_est:,} seats" if a.size_est else "size not known"})
    cafe = bool(a.caterer or any(s.type in ("cafeteria_revamp", "caterer_renewal") for s in sigs))
    fit_parts.append({"label": "Cafeteria or caterer evidence", "pts": f["cafeteria"] if cafe else 0,
                      "note": "found" if cafe else "none found yet"})
    # ---- trigger: only the strongest signal per type counts
    best = {}
    for s in sigs:
        c = contrib(s, today)
        if s.type not in best or c > best[s.type][0]:
            best[s.type] = (c, s)
    trig_parts = [{"label": TYPE_LABEL[t], "pts": round(c, 1), "date": s.date.isoformat(), "age_days": max((today - s.date).days, 0),
                   "weight": trig_cfg[t]["weight"], "half_life": trig_cfg[t]["half_life"]} for t, (c, s) in best.items()]
    trig_total = min(sum(c for c, _ in best.values()), w["trigger_cap"])
    # ---- reach
    named = any(p.name and p.role_match >= 0.6 for p in people)
    gate = any(p.source != "linkedin-search-link" and p.role_match >= 0.3 for p in people)
    ver = any(p.email_status == "valid" and p.role_match >= 0.6 for p in people)
    other = any(p.email and p.role_match >= 0.6 for p in people)
    reach_parts = [
        {"label": "A named person in a buying role", "pts": r["named_person"] if named else (r["gatekeeper"] if gate else 0),
         "note": "found" if named else ("only a gatekeeper found" if gate else "not found yet")},
        {"label": "An email for that person", "pts": r["verified_email"] if ver else (r["other_email"] if other else 0),
         "note": "verified" if ver else ("found, not verified" if other else "not found")},
        {"label": "Caterer known", "pts": r["known_caterer"] if a.caterer else 0, "note": a.caterer or "unknown"}]
    fit_total, reach_total = sum(p["pts"] for p in fit_parts), sum(p["pts"] for p in reach_parts)
    tips = []
    if not a.size_est:
        tips.append(f"Finding the number of seats could add up to {f['size']:g} points.")
    if not named:
        tips.append(f"Finding a named person in a facilities or admin role would add {r['named_person']} points.")
    if not (ver or other):
        tips.append("Finding that person's email would add up to %d points." % r["verified_email"])
    if trig_parts and min(p["age_days"] for p in trig_parts) > 45:
        tips.append("The trigger is a few weeks old: events lose half their value every 60-90 days.")
    return {"total": round(fit_total + trig_total + reach_total, 1),
            "fit": {"score": round(fit_total, 1), "max": 40, "parts": fit_parts},
            "trigger": {"score": round(trig_total, 1), "max": w["trigger_cap"], "parts": trig_parts},
            "reach": {"score": reach_total, "max": 15, "parts": reach_parts}, "tips": tips}
