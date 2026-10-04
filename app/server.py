"""Local web app (standard library only). Bound to 127.0.0.1: it is a prototype for one person on one machine.
"Send" is a placeholder (app/mailer.py): it records the message in an outbox and offers a pre-filled Gmail compose link."""
import json
import re
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.cfg import ROOT, yml
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


def funnel() -> dict:
    """Unique visitors reaching each step, overall and per outreach campaign (utm_campaign)."""
    ev = _read("events.json") or []
    def count(rows):
        seen = {s: {e["sid"] for e in rows if e["event"] == s} for s in FUNNEL}
        return [{"step": s, "label": FUNNEL_LABEL[s], "visitors": len(seen[s])} for s in FUNNEL]
    camps = sorted({e["utm_campaign"] for e in ev if e["utm_campaign"]})
    return {"overall": count(ev), "campaigns": [{"campaign": c, "steps": count([e for e in ev if e["utm_campaign"] == c])} for c in camps]}


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
    STATE.mkdir(exist_ok=True)
    (STATE / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False), "utf-8")


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


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj=None, raw: bytes | None = None, ctype="application/json"):
        payload = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
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
                return self._send(200, {"cities": jobs.cities(), "sizes": {k: {x: v[x] for x in ("label", "minutes", "cost")} for k, v in jobs.SIZES.items()}})
            if u.path == "/api/quota":
                from src.run import quota_data
                return self._send(200, quota_data())
            if u.path == "/api/funnel":
                return self._send(200, funnel())
            if u.path == "/api/inbound":
                return self._send(200, _read("inbound_leads.json") or [])
            if u.path == "/site" or u.path.startswith("/site/"):
                rel = u.path[len("/site"):].lstrip("/") or "index.html"
                f = (SITE / rel).resolve()
                if SITE.resolve() not in f.parents or not f.is_file() or f.name.endswith((".src.html", ".py", ".old.html")):
                    return self._send(404, {"error": "not found"})
                return self._send(200, raw=f.read_bytes(), ctype=TYPES.get(f.suffix, "application/octet-stream"))
            if u.path == "/api/outbox":
                return self._send(200, _read("outbox.json"))
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)[:200]})

    def do_POST(self):
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
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"InfinityBox Leads app: http://127.0.0.1:{port}   public page: http://127.0.0.1:{port}/site/   (Ctrl+C to stop)")
    srv.serve_forever()
