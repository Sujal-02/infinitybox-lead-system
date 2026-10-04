"""Command line for the whole pipeline: discover -> extract -> score -> people -> draft, plus sync to the sheet/workbook and
small utilities (quota, source checks). `python -m src.run all --city Pune` runs everything; see the README for the commands."""
import argparse
import io
import json
from datetime import date

from . import budget, cache, cfg, hierarchy, leads, sheet, store
from .cfg import env
from .discover import news, web
from .draft import draft
from .extract import extract
from .models import Account, Doc, Draft, Person, Score, Signal
from .people import find_people
from .score import score_all, top_signal

stats: dict = {}


# (store file, sheet tab, model): the five tables the pipeline keeps, in the order they are produced
TABLES = [("accounts", "Accounts", Account), ("signals", "Signals", Signal), ("people", "People", Person),
          ("scores", "Scores", Score), ("drafts", "Drafts", Draft)]


def local_tables() -> dict:
    """Every tab's rows from the local store (the same data that goes to Google Sheets)."""
    t = {tab: store.load(name, model) for name, tab, model in TABLES}
    t["Pipeline"] = leads.build() if t["Accounts"] else []
    return t


def export_workbook(path=None) -> str:
    path = str(path or store.DIR / "workbook.xlsx")
    sheet.export_xlsx(path, local_tables())
    return path


def sync() -> None:
    """Push local data to the sheet. Manual `status` edits on Accounts/Drafts survive.
    Without creds.json the same tables are written to a local Excel workbook instead."""
    if cfg.dry:
        return
    if not sheet.enabled():
        print(f"no Google Sheet configured (creds.json or SHEET_WEBHOOK_URL): wrote local workbook {export_workbook()}")
        return
    book = sheet.open_book()
    sheet.init(book)
    keep = {t: {r.id if t == "Accounts" else r.account_id: r.status for r in sheet.read(book, t)} for t in ("Accounts", "Drafts")}
    for name, tab, model in TABLES:
        rows = store.load(name, model)
        for r in rows:
            if tab in keep and keep[tab].get(getattr(r, "id", None) or r.account_id):
                r.status = keep[tab][getattr(r, "id", None) or r.account_id]
        sheet.replace(book, tab, rows)
    sheet.replace(book, "Pipeline", leads.build())
    try:
        book.worksheet("Pipeline").set_basic_filter()  # filter dropdowns on the header row
    except Exception as e:
        print(f"could not set sheet filter: {type(e).__name__}")


def do_discover(city: str, limit: int | None, wide: bool = False) -> None:
    if cfg.dry:
        docs = [Doc.model_validate(d) for d in json.loads((cfg.ROOT / "tests/fixtures/docs.json").read_text("utf-8"))]
        stats["docs_fixture"] = len(docs)
    else:
        docs, seen = [], set()
        sources = [("news", lambda c: news.fetch(c, wide))] + ([("web", (lambda c: web.fetch(c, 2, 1)) if limit else web.fetch)] if env("FIRECRAWL_API_KEY") else [])
        if not env("FIRECRAWL_API_KEY"):
            print("FIRECRAWL_API_KEY missing: web source skipped")
        for name, fn in sources:
            try:
                got = [d for d in fn(city) if d.url not in seen]
            except Exception as e:
                print(f"{name} failed: {e}")
                stats[f"{name}_failed"] = 1
                continue
            seen |= {d.url for d in got}
            docs += got
            stats[f"docs_{name}"] = len(got)
    store.save("docs", docs[:limit] if limit else docs)


def do_extract(city: str, limit: int | None) -> None:
    docs = store.load("docs", Doc)
    mf = store.DIR / "manual_extract.json"  # optional hand-made extractions: {url: {"items": [...]}}
    manual = json.loads(mf.read_text("utf-8")) if mf.exists() else None
    extract(docs[:limit] if limit else docs, city, accs := store.load("accounts", Account), sigs := store.load("signals", Signal), stats, manual)
    store.save("accounts", accs)
    store.save("signals", sigs)
    sync()


def do_score() -> list[Score]:
    scores = score_all(store.load("accounts", Account), store.load("signals", Signal), store.load("people", Person))
    store.save("scores", scores)
    sync()
    return scores


def keep_known(old: list[Person], fresh: list[Person]) -> list[Person]:
    """A rerun that finds no real contact (a source failed, a quota ran out) must not wipe contacts we already have."""
    real = lambda ps: [p for p in ps if p.source != "linkedin-search-link"]
    return fresh if real(fresh) else fresh + real(old)


def do_people(top: int, city: str) -> None:
    accs = {a.id: a for a in store.load("accounts", Account)}
    ids = [s.account_id for s in store.load("scores", Score) if accs[s.account_id].city == city][:top]
    all_people = store.load("people", Person)
    people = [p for p in all_people if p.account_id not in ids]
    old_people = {i: [p for p in all_people if p.account_id == i] for i in ids}
    sigs = store.load("signals", Signal)
    for i in ids:
        a = accs[i]
        mine = [x for x in sigs if x.account_id == i]
        a.org_kind = hierarchy.classify(a.segment, a.name, " ".join(x.summary for x in mine))
        people += keep_known(old_people.get(i, []), find_people(a, stats, triggers=sorted({x.type for x in mine})))
    store.save("accounts", list(accs.values()))  # domains found along the way
    store.save("people", people)
    do_score()  # reach changes with people found


def quota_data() -> dict:
    """Live free-trial balances from each provider's own API. Each entry is {"label","left","total","note"} or {"label","error"}."""
    import requests
    out = {}
    try:
        d = requests.get("https://api.hunter.io/v2/account", params={"api_key": env("HUNTER_API_KEY")}, timeout=20).json()["data"]["requests"]["searches"]
        out["hunter"] = {"label": "Email lookups (Hunter)", "left": d["available"] - d["used"], "total": d["available"], "note": "searches left this month"}
    except Exception as e:
        out["hunter"] = {"label": "Email lookups (Hunter)", "error": type(e).__name__}
    try:
        d = requests.get("https://api.firecrawl.dev/v2/team/credit-usage", headers={"Authorization": "Bearer " + env("FIRECRAWL_API_KEY")}, timeout=20).json()["data"]
        out["firecrawl"] = {"label": "Web pages (Firecrawl)", "left": d["remainingCredits"], "total": d["planCredits"], "note": f"credits left, resets {d['billingPeriodEnd'][:10]}"}
    except Exception as e:
        out["firecrawl"] = {"label": "Web pages (Firecrawl)", "error": type(e).__name__}
    try:
        from . import budget as _b
        caps, used = cfg.yml("budgets")["monthly"], _b._ledger().get(date.today().strftime("%Y-%m"), {})
        out["gemini"] = {"label": "AI writing (Gemini)", "left": max(0, caps["gemini"] - used.get("gemini", 0)), "total": caps["gemini"], "note": "requests left under your monthly cap"}
    except Exception as e:
        out["gemini"] = {"label": "AI writing (Gemini)", "error": type(e).__name__}
    return out


def do_quota() -> None:
    """Print the live free-trial balances (the same numbers the app shows on Home)."""
    for k, v in quota_data().items():
        print(f"{k:<10} " + (f"{v['left']:g} of {v['total']:g} {v['note']}" if "left" in v else f"unavailable ({v['error']})"))
    try:
        from apify_client import ApifyClient
        lim = ApifyClient(env("APIFY_TOKEN")).user().limits()
        print(f"apify      plan cap ${lim.limits.max_monthly_usage_usd:g}/month, cycle ends {lim.monthly_usage_cycle.end_at:%Y-%m-%d} (the LinkedIn actor also has its own free-run limit)")
    except Exception as e:
        print(f"apify      unavailable ({type(e).__name__})")
    try:
        from . import llm
        from .extract import Extraction
        llm._gemini('Return {"items": []}', Extraction)
        print("gemini     working")
    except Exception as e:
        print(f"gemini     NOT working: {type(e).__name__} {str(e)[:90]}")
    print("\nspent by this project:", budget.summary())


def do_leads(a) -> None:
    rows = leads.apply_filters(leads.build(), city=a.city if not a.all_cities else None, segment=a.segment, trigger=a.trigger,
                               min_score=a.min_score, has_contact=a.has_contact, has_email=a.has_email,
                               since_days=a.since_days, source_kind=a.source_kind, tier=a.tier)
    path = a.out or f"data/leads_{(a.city if not a.all_cities else 'all').lower()}.{a.format}"
    leads.export(rows, path, a.format)
    for r in rows[:a.top or 25]:
        who = f"{r.contact_name} ({r.contact_title[:35]})" if r.contact_name else "no named contact"
        print(f"{r.rank:>3} {r.account[:30]:<30} {r.segment[:5]:<6}{r.total:>5}  {who}  {r.contact_email or ''}")
    print(f"\n{len(rows)} leads -> {path}")


def do_contacts(account_id: str) -> None:
    """Explain the contact hierarchy for one account: every candidate found, its tier, relevance and why. Saves the result."""
    from .people import discover, select
    accs = store.load("accounts", Account)
    a = next((x for x in accs if x.id == account_id), None)
    if not a:
        raise SystemExit(f"unknown account id {account_id!r}")
    sigs = [x for x in store.load("signals", Signal) if x.account_id == a.id]
    a.org_kind = hierarchy.classify(a.segment, a.name, " ".join(x.summary for x in sigs))
    triggers = sorted({x.type for x in sigs})
    print(f"{a.name} | kind={a.org_kind} | triggers={triggers} | site={a.domain or '-'}")
    cands = discover(a, stats, triggers)
    chosen = {id(p) for p in select(cands)}
    for p in cands:
        print(f"{'*' if id(p) in chosen else ' '} {p.role_match:.2f} {p.tier:<7} {p.name or '(mailbox)':<28} {p.role[:45]:<46} {p.email or '-'}")
        print(f"      why: {p.why}")
    print("\n* = selected;", stats)
    store.save("accounts", accs)
    old = [p for p in store.load("people", Person) if p.account_id == a.id]
    store.save("people", [p for p in store.load("people", Person) if p.account_id != a.id]
               + keep_known(old, find_people(a, stats, triggers=triggers)))


def do_draft(top: int, city: str) -> None:
    accs = {a.id: a for a in store.load("accounts", Account)}
    sigs, people = store.load("signals", Signal), store.load("people", Person)
    out = []
    for sc in [x for x in store.load("scores", Score) if accs[x.account_id].city == city][:top]:
        s = top_signal([x for x in sigs if x.account_id == sc.account_id], date.today())
        ps = [p for p in people if p.account_id == sc.account_id]
        if not s or not ps:
            continue
        try:
            out.append(draft(accs[sc.account_id], s, next((p for p in ps if p.name), ps[0])))
        except Exception as e:
            print(f"draft dropped for {sc.account_id}: {e}")
            stats["draft_failed"] = stats.get("draft_failed", 0) + 1
    store.save("drafts", out)
    sync()


def do_check_city_sources() -> None:
    """Check every URL in config/city_sources.yaml; write a city -> category report (sorted, with a fix list) to the data folder."""
    from .sources import check_city, city_report
    rows = check_city()
    store.save("city_sources", rows)
    text = city_report(rows, date.today().isoformat())
    path = store.DIR / "city_sources_report.md"
    store.DIR.mkdir(exist_ok=True)
    io.open(path, "w", encoding="utf-8").write(text)
    print(text[text.index("## Summary by city"):text.index("## Shared") if "## Shared" in text else text.index("## All cities")])
    print("report:", path)


def do_check_sources() -> None:
    from collections import Counter
    from .sources import check_all
    src = check_all()
    store.save("sources", src)
    print("sources:", dict(Counter(s.status for s in src)))
    for s in src:
        if s.status == "dead":
            print(f"  dead: {s.name} {s.url} {s.http or ''}")
    if not cfg.dry and sheet.enabled():
        book = sheet.open_book()
        sheet.init(book)
        sheet.replace(book, "Sources", src)


def do_apify_test(n: int, city: str) -> None:
    """Run the Apify people layer (primary actor, then the fallback) on the top-n scored accounts of a city and print who it finds."""
    from .people import from_apify
    if not env("APIFY_TOKEN"):
        raise SystemExit("APIFY_TOKEN is empty: set it in .env first")
    accs = {a.id: a for a in store.load("accounts", Account)}
    for sc in [x for x in store.load("scores", Score) if accs[x.account_id].city == city][:n]:
        a = accs[sc.account_id]
        a.org_kind = hierarchy.classify(a.segment, a.name)
        print(f"\n{a.name} ({a.org_kind})")
        try:
            for p in sorted(from_apify(a, hierarchy.titles_for(a.org_kind), stats), key=lambda p: -p.role_match):
                print(f"  {p.role_match:.2f} {p.tier:<6} {p.name:<26} {p.role[:44]:<45} {p.source.split(':')[-1]}")
        except Exception as e:
            print(f"  failed: {type(e).__name__} {str(e)[:120]}")
    store.save("accounts", list(accs.values()))
    print("\n", stats)


def report() -> None:
    sigs = {}
    for s in store.load("signals", Signal):
        sigs.setdefault(s.account_id, s)
    names = {a.id: a.name for a in store.load("accounts", Account)}
    print("\nTop accounts:")
    for sc in store.load("scores", Score)[:25]:
        s = sigs.get(sc.account_id)
        print(f"{sc.rank:>3}. {names[sc.account_id]:<30} {sc.total:>5}  {sc.reason}  {s.source_url if s else ''}")
    print("\nPer-source counts:", stats or "none")


def main(argv=None):
    p = argparse.ArgumentParser(prog="src.run")
    p.add_argument("cmd", choices=["init", "sheet_check", "check_city_sources", "export", "quota", "leads", "contacts", "check_sources", "apify_test", "discover", "extract", "score", "people", "draft", "all"])
    p.add_argument("--city", default=env("CITY", "Bangalore"))
    p.add_argument("--top", type=int)
    p.add_argument("--limit", type=int)
    p.add_argument("--dry-run", action="store_true", help="use fixtures, no network, no sheet")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--wide", action="store_true", help="also use the news query bank (cafeteria, caterer, ESG, hiring, institutions)")
    f = p.add_argument_group("leads filters")
    f.add_argument("--segment", choices=["corporate", "caterer", "fitout", "institution"])
    f.add_argument("--trigger", help="e.g. new_campus, lease, tender, cafeteria_revamp")
    f.add_argument("--min-score", type=float, default=0.0)
    f.add_argument("--has-contact", action="store_true", help="only leads with a named contact")
    f.add_argument("--has-email", action="store_true", help="only leads with an email returned by Hunter/website")
    f.add_argument("--since-days", type=int, help="newest signal within N days")
    f.add_argument("--source-kind", choices=["news", "tender"])
    f.add_argument("--tier", choices=["tier1", "tier2", "tier3", "generic"], help="tier of the best contact")
    f.add_argument("--account", help="account id, for the `contacts` command")
    f.add_argument("--all-cities", action="store_true")
    f.add_argument("--format", choices=["csv", "md", "json"], default="csv")
    f.add_argument("--out")
    a = p.parse_args(argv)

    cache.enabled = not a.no_cache
    if a.cmd == "init":  # only the flag skips the sheet; DRY_RUN env is for pipeline commands
        if a.dry_run:
            print("tabs:", ", ".join(sheet.TABS))
        else:
            print("created:", ", ".join(sheet.init(sheet.open_book())) or "nothing (all tabs exist)")
        return
    if a.cmd == "sheet_check":
        return print(sheet.check())
    cfg.dry = a.dry_run or env("DRY_RUN") == "1"
    if a.cmd == "check_city_sources":
        return do_check_city_sources()
    if a.cmd == "export":
        print("wrote", export_workbook(a.out))
        return
    if a.cmd == "quota":
        return do_quota()
    if a.cmd == "leads":
        return do_leads(a)
    if a.cmd == "contacts":
        return do_contacts(a.account)
    if a.cmd == "check_sources":
        return do_check_sources()
    if a.cmd == "apify_test":
        return do_apify_test(a.top or 5, a.city)
    n_people = a.top or int(env("TOP_N_PEOPLE", "40"))
    if a.cmd in ("discover", "all"):
        do_discover(a.city, a.limit, a.wide)
    if a.cmd in ("extract", "all"):
        do_extract(a.city, a.limit)
    if a.cmd in ("score", "all"):
        do_score()
    if a.cmd in ("people", "all"):
        do_people(n_people, a.city)
    if a.cmd in ("draft", "all"):
        do_draft(a.top if a.cmd == "draft" and a.top else 5, a.city)
    report()


if __name__ == "__main__":
    main()
