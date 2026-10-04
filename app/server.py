"""Web app (standard library only). By default bound to 127.0.0.1 for one person on one machine.
"Send" is a placeholder (app/mailer.py): it records the message in an outbox and offers a pre-filled Gmail compose link.

Hosted mode (for the GitHub Pages dashboard), all through environment variables:
  ACCESS_CODE      every /api call must send it as the X-Access-Code header (wrong codes are rate limited)
  ALLOWED_ORIGIN   the Pages site that may call this API from a browser (CORS), e.g. https://user.github.io
  BUDGET_PROFILE   "demo" caps paid-API use with the small allowance in config/budgets.yaml and offers only the Quick look
  HOST / PORT      listen address (a host sets PORT; HOST=0.0.0.0 to accept outside connections)"""
import hmac
import json
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.cfg import ROOT, yml
from src import budget, sheet, store
from src import run as pipeline
from src.cfg import env
from . import data, drafting, jobs, mailer

STATE = ROOT / "app_data"
STATIC = Path(__file__).parent / "static"
CACHE: dict[str, list[dict]] = {}
SITE = ROOT / "inbound"
QUEUES = {"corporate": "warewashing", "institution": "warewashing", "fitout": "kitchen design", "caterer": "partner"}  # same rule as inbound/apps_script.gs
TYPES = {".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}


FUNNEL = ["view", "calc_start", "items", "result", "form_open", "lead"]
FUNNEL_LABEL = {"view": "Visited the page", "calc_start": "Started the calculator", "items": "Chose their items", "result": "Saw their result",
                "form_open": "Opened the form", "lead": "Sent an enquiry"}


def record_event(body: dict) -> tuple[int, dict]:
    """Anonymous page event (no personal data). Capped list so the file cannot grow without bound."""
    if body.get("event") not in FUNNEL or not body.get("sid"):
        return 422, {"error": "unknown event"}
    clip = lambda v: str(v or "")[:100]
    ev = {k: clip(body.get(k)) for k in ("ts", "sid", "event", "utm_source", "utm_medium", "utm_campaign", "ref", "path")}
    out = _read("events.json") or []
    out.append(ev)
    _write("events.json", out[-5000:])
    return 200, {"ok": True}


_SHEET: dict[str, tuple[float, list[dict]]] = {}  # tab -> (time read, rows)


def sheet_tab(tab: str) -> list[dict]:
    """Rows of a tab in the Google Sheet, read through the Apps Script gateway and kept for 20 s so page loads stay quick.
    This is where the live public page (on GitHub Pages) stores enquiries and visit events. [] when no gateway is set or it fails."""
    if not os.getenv("SHEET_WEBHOOK_URL"):
        return []
    hit = _SHEET.get(tab)
    if hit and time.time() - hit[0] < 20:
        return hit[1]
    try:
        v = sheet.open_book().call("values", tab) or []
        rows = [dict(zip(v[0], r)) for r in v[1:]]
    except Exception:  # a sheet hiccup must not break the dashboard: show the last rows we had
        rows = hit[1] if hit else []
    _SHEET[tab] = (time.time(), rows)
    return rows


def inbound() -> list[dict]:
    """Enquiries from the public page: this app's own store plus the Google Sheet "Leads" tab, newest first.
    Each row says where it came from (`source`), so the dashboard can show both."""
    mine = [{**r, "source": "app"} for r in (_read("inbound_leads.json") or [])]
    num = lambda v: int(float(v)) if str(v).replace(".", "", 1).isdigit() else 0
    theirs = [{**r, "seats": num(r.get("seats")), "meals": num(r.get("meals")), "source": "sheet"} for r in sheet_tab("Leads") if r.get("company")]
    return sorted(mine + theirs, key=lambda r: str(r.get("ts", "")), reverse=True)


def funnel() -> dict:
    """Unique visitors reaching each step, overall and per outreach campaign (utm_campaign). Counts this app's events and the sheet's."""
    ev = (_read("events.json") or []) + [e for e in sheet_tab("Events") if e.get("event") in FUNNEL and e.get("sid")]
    def count(rows):
        seen = {s: {e["sid"] for e in rows if e["event"] == s} for s in FUNNEL}
        return [{"step": s, "label": FUNNEL_LABEL[s], "visitors": len(seen[s])} for s in FUNNEL]
    camps = sorted({e["utm_campaign"] for e in ev if e.get("utm_campaign")})
    return {"overall": count(ev), "campaigns": [{"campaign": c, "steps": count([e for e in ev if e.get("utm_campaign") == c])} for c in camps]}


def record_lead(body: dict) -> tuple[int, dict]:
    """Inbound lead from the public page: validate, route by segment, store. A filled honeypot is dropped silently (bots)."""
    if body.get("website"):
        return 200, {"ok": True}
    seg, email, company = body.get("segment"), (body.get("contact") or "").strip(), (body.get("company") or "").strip()
    if seg not in QUEUES or not company or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return 422, {"error": "company, a valid email and a valid segment are required"}
    clip = lambda v: str(v or "")[:200]
    inputs = {"contact": email, "setup": clip(body.get("setup")), "calc": body.get("inputs") or {}}
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "company": clip(company), "role": clip(body.get("role")), "city": clip(body.get("city")),
           "segment": seg, "seats": int(body.get("seats") or 0), "meals": int(body.get("meals") or 0), "inputs_json": json.dumps(inputs, ensure_ascii=False),
           "queue": QUEUES[seg], "owner": ""}
    out = _read("inbound_leads.json") or []
    out.insert(0, rec)
    _write("inbound_leads.json", out)
    return 200, {"ok": True, "queue": rec["queue"]}


def _read(name: str):
    p = STATE / name
    return json.loads(p.read_text("utf-8")) if p.exists() else ([] if name in ("outbox.json", "inbound_leads.json", "events.json") else {})


def _write(name: str, obj) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False), "utf-8")


EXPORT_LOCK = threading.Lock()  # the export briefly points the pipeline's store at one city's folder


def workbook_bytes(ds: str) -> bytes | None:
    """The same tables the Google Sheet would hold (Accounts, Signals, People, Scores, Drafts, Pipeline) as an .xlsx for one city's run.
    This is the local "sheet" a person without a Google account can open in Excel."""
    d = data.config(ds)
    if d["kind"] != "pipeline":
        return None
    out = STATE / "export.xlsx"
    STATE.mkdir(parents=True, exist_ok=True)
    with EXPORT_LOCK:
        keep, store.DIR = store.DIR, ROOT / d["dir"]
        try:
            pipeline.export_workbook(out)
        finally:
            store.DIR = keep
    return out.read_bytes()


def inject_script_url(page: bytes) -> bytes:
    """The public page stores enquiries by posting to the Apps Script web app. On a hosted server (ACCESS_CODE set) the page is served
    from here, so the address is filled in when it is sent: APPS_SCRIPT_URL, else the gateway address already configured."""
    url = os.getenv("APPS_SCRIPT_URL") or (os.getenv("SHEET_WEBHOOK_URL") if os.getenv("ACCESS_CODE") else "")
    if not url or not re.fullmatch(r"https://script\.google\.com/[A-Za-z0-9._/-]+", url):
        return page
    return page.replace(b'APPS_SCRIPT_URL: ""', b'APPS_SCRIPT_URL: "' + url.encode() + b'"', 1)


def sheet_status() -> dict:
    """What the Google Sheet holds: accounts per city, so the dashboard can offer Load (import) and Save (export)."""
    if not sheet.enabled():
        return {"enabled": False}
    try:
        book = sheet.open_book()
        return {"enabled": True, "title": book.title, "cities": sheet.cities(book)}
    except Exception as e:
        return {"enabled": True, "error": f"{type(e).__name__}: {str(e)[:120]}", "cities": {}}


def sheet_save(ds: str) -> dict:
    """EXPORT one local lead list to the sheet (only that city's rows are replaced)."""
    d = data.config(ds)
    if d["kind"] != "pipeline":
        return {"error": "Only lists made by Find leads can be saved to the sheet."}
    with EXPORT_LOCK:
        keep, store.DIR = store.DIR, ROOT / d["dir"]
        try:
            tables = pipeline.local_tables()
        finally:
            store.DIR = keep
    sheet.push(sheet.open_book(), tables)
    return {"ok": True, "city": d["city"], "accounts": len(tables["Accounts"])}


def sheet_load(city: str) -> dict:
    """IMPORT one city from the sheet into this app (replaces this app's copy of that city's list)."""
    t = sheet.pull(sheet.open_book(), city)
    if not t["Accounts"]:
        return {"error": f"The sheet has no accounts for {city}."}
    folder = ROOT / f"data_{jobs.slug(city)}"
    with EXPORT_LOCK:
        keep, store.DIR = store.DIR, folder
        try:
            for name, tab, _ in sheet.TABLES:
                store.save(name, t[tab])
        finally:
            store.DIR = keep
    CACHE.pop(jobs.slug(city), None)
    return {"ok": True, "city": city, "accounts": len(t["Accounts"])}


def autoload() -> None:
    """On start, a server with an empty disk (a free host after a restart) fills itself from the sheet: the sheet is the database."""
    try:
        for city in sheet.cities(sheet.open_book()) if sheet.enabled() else []:
            if not (ROOT / f"data_{jobs.slug(city)}" / "accounts.json").exists():
                print(f"loaded {city} from the Google Sheet: {sheet_load(city)}", flush=True)
    except Exception as e:
        print(f"could not load from the sheet at start: {type(e).__name__}", flush=True)


def setup_status() -> dict:
    """Which keys are saved (never the keys themselves) and where results go."""
    names = {"GEMINI_API_KEY": "Gemini (AI)", "FIRECRAWL_API_KEY": "Firecrawl (web pages)", "HUNTER_API_KEY": "Hunter (emails)", "APIFY_TOKEN": "Apify (LinkedIn lists)"}
    return {"keys": [{"name": label, "set": bool(env(k)), "required": k == "GEMINI_API_KEY"} for k, label in names.items()],
            "sheet": "Google Sheet" if sheet.enabled() else "Local Excel file"}


def leads(ds: str, refresh: bool = False) -> list[dict]:
    if refresh or ds not in CACHE:
        CACHE[ds] = data.load(ds)
    return CACHE[ds]


def find(ds: str, lead_id: str) -> dict:
    return next(l for l in leads(ds) if l["id"] == lead_id)


def styles() -> list[dict]:
    return [{"id": k, "name": v["name"], "best_when": v["best_when"], "for": v["for"]} for k, v in yml("templates")["styles"].items()]


def handle_post(path: str, body: dict) -> tuple[int, dict]:
    if path == "/api/lead":
        return record_lead(body)
    if path == "/api/event":
        return record_event(body)
    if path == "/api/run":
        return jobs.start(body.get("city", ""), body.get("size", ""))
    if path == "/api/sheet/save":
        return 200, sheet_save(body["dataset"])
    if path == "/api/sheet/load":
        return 200, sheet_load(body["city"])
    lead = find(body["dataset"], body["lead_id"])
    if path == "/api/draft":
        idx = body.get("contact", -1)
        contact = lead["contacts"][idx] if isinstance(idx, int) and 0 <= idx < len(lead["contacts"]) else None
        try:
            return 200, drafting.generate(lead, body["style"], contact, body.get("notes", ""))
        except Exception as e:  # never show keys; keep the message short and human
            msg = re.sub(r"(api_key|key|token)=[^&\s]+", r"\1=***", str(e))[:300]
            return 502, {"error": f"The writing assistant could not produce a safe draft this time. Try again, or pick another style. ({msg})"}
    if path == "/api/check":
        probs = drafting.problems(lead, body["subject"], body["body"], body.get("notes", ""), whole=True)
        return 200, {"problems": probs, "words": len(body["body"].split())}
    if path == "/api/save":
        saved = _read("drafts.json")
        saved[f"{body['dataset']}:{lead['id']}"] = {"subject": body["subject"], "body": body["body"], "style": body.get("style"),
                                                     "saved_at": datetime.now().isoformat(timespec="seconds")}
        _write("drafts.json", saved)
        return 200, {"ok": True}
    if path == "/api/send":
        probs = drafting.problems(lead, body["subject"], body["body"], body.get("notes", ""), whole=True)
        if probs:
            return 422, {"error": "Please fix these before sending:", "problems": probs}
        to = body.get("to", "").strip()
        rec = {"id": int(time.time() * 1000), "ts": datetime.now().isoformat(timespec="seconds"), "dataset": body["dataset"],
               "company": lead["company"], "to": to, "subject": body["subject"], "body": body["body"],
               "status": ""}
        rec["status"] = mailer.deliver(rec)["status"]
        out = _read("outbox.json")
        out.insert(0, rec)
        _write("outbox.json", out)
        return 200, {"record": rec, "gmail_url": drafting.gmail_url(to, body["subject"], body["body"])}
    return 404, {"error": "unknown endpoint"}


FAILS: dict[str, list[float]] = defaultdict(list)  # client address -> times of recent wrong access codes
PUBLIC_ONLY = ("/api/lead", "/api/event")  # written by the local copy of the public page; switched off on a hosted server


def access_check(path: str, given: str, client: str, now: float | None = None) -> tuple[int, str]:
    """(200, "") if allowed, else (status, message). Only /api paths need the code, and only when ACCESS_CODE is set."""
    code = os.getenv("ACCESS_CODE", "")
    if not code or not path.startswith("/api/"):
        return 200, ""
    now = now or time.time()
    FAILS[client] = [t for t in FAILS[client] if now - t < 60]
    if len(FAILS[client]) >= 20:  # a page load sends several requests at once, so one wrong code can count several times
        return 429, "Too many wrong codes. Wait a minute and try again."
    if path in PUBLIC_ONLY:
        return 404, "not found"
    if not hmac.compare_digest(given.encode(), code.encode()):
        if given:  # a request with no code at all (the page just opened) is not a guess
            FAILS[client].append(now)
        return 401, "A valid access code is needed."
    return 200, ""


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = os.getenv("ALLOWED_ORIGIN", "").rstrip("/")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Access-Code")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Vary", "Origin")

    def _gate(self, path: str) -> bool:
        code, msg = access_check(path, self.headers.get("X-Access-Code", ""), self.client_address[0])
        if code != 200:
            self._send(code, {"error": msg})
        return code == 200

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code: int, obj=None, raw: bytes | None = None, ctype="application/json", headers: dict | None = None):
        payload = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "xml" not in ctype and "sheet" not in ctype else ""))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/healthz":
            return self._send(200, {"ok": True})
        if not self._gate(u.path):
            return
        try:
            if u.path in ("/", "/dashboard", "/dashboard/"):
                return self._send(200, raw=(STATIC / "index.html").read_bytes(), ctype="text/html")
            if u.path == "/api/datasets":
                return self._send(200, data.available())
            if u.path == "/api/leads":
                return self._send(200, leads(q["dataset"], q.get("refresh") == "1"))
            if u.path == "/api/styles":
                return self._send(200, {"styles": styles(), "facts": drafting.facts(), "max_words": yml("playbook")["max_words"]})
            if u.path == "/api/saved":
                return self._send(200, _read("drafts.json").get(f"{q['dataset']}:{q['lead_id']}") or {})
            if u.path == "/api/job":
                return self._send(200, jobs.status())
            if u.path == "/api/run-options":
                return self._send(200, {"cities": jobs.cities(), "sizes": {k: {x: v[x] for x in ("label", "minutes", "cost")} for k, v in jobs.sizes().items()},
                                        "demo": os.getenv("BUDGET_PROFILE") == "demo"})
            if u.path == "/api/sheet":
                return self._send(200, sheet_status())
            if u.path == "/api/setup":
                return self._send(200, setup_status())
            if u.path == "/api/export":
                blob = workbook_bytes(q["dataset"])
                if blob is None:
                    return self._send(404, {"error": "There is no sheet for this list."})
                return self._send(200, raw=blob, ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  headers={"Content-Disposition": f'attachment; filename="leads_{q["dataset"]}.xlsx"', "Access-Control-Expose-Headers": "Content-Disposition"})
            if u.path == "/api/allowance":
                return self._send(200, budget.status())
            if u.path == "/api/quota":
                from src.run import quota_data
                return self._send(200, quota_data())
            if u.path == "/api/funnel":
                return self._send(200, funnel())
            if u.path == "/api/inbound":
                return self._send(200, inbound())
            if u.path == "/site" or u.path.startswith("/site/"):
                rel = u.path[len("/site"):].lstrip("/") or "index.html"
                f = (SITE / rel).resolve()
                if SITE.resolve() not in f.parents or not f.is_file() or f.name.endswith((".src.html", ".py", ".old.html")):
                    return self._send(404, {"error": "not found"})
                body = inject_script_url(f.read_bytes()) if f.name == "index.html" else f.read_bytes()
                return self._send(200, raw=body, ctype=TYPES.get(f.suffix, "application/octet-stream"))
            if u.path == "/api/outbox":
                return self._send(200, _read("outbox.json"))
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)[:200]})

    def do_POST(self):
        if not self._gate(urlparse(self.path).path):
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            code, obj = handle_post(urlparse(self.path).path, body)
            self._send(code, obj)
        except StopIteration:
            self._send(404, {"error": "lead not found"})
        except Exception as e:
            self._send(500, {"error": str(e)[:200]})

    def log_message(self, *a):  # quiet
        pass


def serve(port: int = 8765) -> None:
    host, port = os.getenv("HOST", "127.0.0.1"), int(os.getenv("PORT", port))
    srv = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=autoload, daemon=True).start()
    print(f"InfinityBox Leads app: http://{host}:{port}   public page: http://{host}:{port}/site/   (Ctrl+C to stop)", flush=True)
    srv.serve_forever()
