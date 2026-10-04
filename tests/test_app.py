import shutil
from datetime import date, timedelta

import pytest

from app import data, drafting, server
from app.explain import explain
from src import cfg, playbook
from src.models import Account, Person, Signal
from src.score import score_account

TODAY = date(2026, 10, 3)


def mk(size=None, caterer="", days=10, people=(), types=("new_campus",)):
    a = Account(id="a", name="Acme", city="Bangalore", segment="corporate", first_seen=TODAY, size_est=size, caterer=caterer)
    sigs = [Signal(id=str(i), account_id="a", type=t, date=TODAY - timedelta(days=days + i * 40), summary="s", source_url="u", evidence="e")
            for i, t in enumerate(types)]
    return a, sigs, list(people)


@pytest.mark.parametrize("kw", [dict(), dict(size=1500, caterer="FreshPlate"), dict(days=120), dict(types=("new_campus", "tender", "lease")),
                                dict(people=[Person(account_id="a", role="Head of Facilities", name="N", email="n@a.com", email_status="valid", source="hunter", role_match=0.9)]),
                                dict(people=[Person(account_id="a", role="Registrar", name="R", email="r@a.com", email_status="published", source="website", role_match=0.4)])])
def test_explanation_total_equals_the_real_score(kw):
    a, sigs, people = mk(**kw)
    ex = explain(a, sigs, people, TODAY)
    assert ex["total"] == pytest.approx(score_account(a, sigs, people, TODAY).total, abs=0.11)
    assert ex["total"] == pytest.approx(ex["fit"]["score"] + ex["trigger"]["score"] + ex["reach"]["score"], abs=0.11)


def test_tips_say_what_would_raise_the_score():
    ex = explain(*mk(), TODAY)
    text = " ".join(ex["tips"])
    assert "seats" in text and "named person" in text and "email" in text


LEAD = {"id": "acme", "company": "Acme", "segment": "corporate", "city": "Bangalore", "why_now": "Acme opened a campus",
        "sources": [{"quote": "Acme opens a 830,000 sq ft campus", "headline": "Acme campus", "date": "2026-09-01", "url": "u", "type": "new_campus"}],
        "contacts": [{"name": "Dr. Asha Rao", "title": "Head of Facilities", "email": "a@acme.com", "relevance": 0.9}]}


def test_guardrails():
    ok = drafting.problems(LEAD, "Cafeteria warewashing for Acme", "Saw that Acme opens a 830,000 sq ft campus. InfinityBox provides warewashing. Would a call help?")
    assert ok == []
    bad = drafting.problems(LEAD, "Hello", "InfinityBox is IoT-powered and certified, saving 40,000 rupees. Write to boss@acme.com. " + "word " * 200)
    joined = " ".join(bad)
    assert "IoT" in joined and "certified" in joined and "40,000" in joined and "email address" in joined and "words" in joined
    assert any("InfinityBox" in b for b in drafting.problems(LEAD, "Hello there", "Saw that Acme opens a campus."))


def test_greeting_uses_first_name_and_signoff_placeholder():
    subj, body = drafting.assemble("S", "Message.", LEAD["contacts"][0])
    assert body.startswith("Hi Asha,") and "[Your name]" in body
    assert drafting.assemble("S", "Message.", None)[1].startswith("Message.")


def test_send_records_but_never_emails(monkeypatch):
    d = cfg.ROOT / "cache" / "_app_test"
    monkeypatch.setattr(server, "STATE", d)
    monkeypatch.setattr(server, "find", lambda ds, i: LEAD)
    try:
        body = {"dataset": "x", "lead_id": "acme", "to": "a@acme.com", "subject": "Cafeteria warewashing for Acme",
                "body": "Saw that Acme opens a 830,000 sq ft campus. InfinityBox provides warewashing. Would a call help?\n\n" + playbook.link_for("Acme", "corporate", "Bangalore")}
        code, out = server.handle_post("/api/send", body)
        assert code == 200 and "Not emailed" in out["record"]["status"] and "placeholder" in out["record"]["status"] and out["gmail_url"].startswith("https://mail.google.com/mail/?view=cm")
        assert server._read("outbox.json")[0]["company"] == "Acme"
        code, out = server.handle_post("/api/send", {**body, "body": "InfinityBox is IoT enabled."})
        assert code == 422 and out["problems"]                      # unsafe drafts cannot even be recorded
        assert len(server._read("outbox.json")) == 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_recommended_style_rules():
    t1 = [{"relevance": 0.9}]
    assert data.recommend("corporate", ["new_campus"], t1) == "planning_stage"
    assert data.recommend("corporate", ["tender"], t1) == "tender_response"
    assert data.recommend("caterer", [], t1) == "caterer_partner"
    assert data.recommend("corporate", ["new_campus"], [{"relevance": 0.4}]) == "gatekeeper_intro"   # only a gatekeeper found


def test_every_dataset_on_disk_loads():
    for d in data.available():
        leads = data.load(d["id"])
        assert leads and all(l["score"]["total"] >= 0 and l["sources"] for l in leads)


def test_pipeline_dataset_only_shows_its_own_city():
    for ds, city in (("pune", "Pune"), ("bengaluru", "Bangalore")):
        if any(d["id"] == ds for d in data.available()):
            assert {l["city"] for l in data.load(ds)} == {city}


def test_inbound_lead_is_validated_routed_and_stored(monkeypatch):
    d = cfg.ROOT / "cache" / "_app_test2"
    monkeypatch.setattr(server, "STATE", d)
    try:
        body = {"company": "Acme", "role": "Head of Admin", "city": "Pune", "segment": "fitout", "contact": "a@acme.com", "meals": 1500,
                "inputs": {"name": "Asha", "totalRs": 121000}, "website": ""}
        code, out = server.handle_post("/api/lead", body)
        assert code == 200 and out["queue"] == "kitchen design"
        rec = server._read("inbound_leads.json")[0]
        assert rec["company"] == "Acme" and rec["meals"] == 1500 and '"Asha"' in rec["inputs_json"] and rec["owner"] == ""
        assert server.handle_post("/api/lead", {**body, "segment": "caterer"})[1]["queue"] == "partner"
        assert server.handle_post("/api/lead", {**body, "segment": "corporate"})[1]["queue"] == "warewashing"
        assert server.handle_post("/api/lead", {**body, "contact": "not-an-email"})[0] == 422
        assert server.handle_post("/api/lead", {**body, "website": "http://spam"})[0] == 200          # honeypot: accepted silently...
        assert len(server._read("inbound_leads.json")) == 3                                          # ...but never stored
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_funnel_counts_unique_visitors_per_campaign(monkeypatch):
    d = cfg.ROOT / "cache" / "_app_test3"
    monkeypatch.setattr(server, "STATE", d)
    try:
        ev = lambda sid, e, camp="": server.handle_post("/api/event", {"event": e, "sid": sid, "ts": "t", "utm_campaign": camp})
        for sid, steps, camp in (("a", ["view", "calc_start", "items", "result", "form_open", "lead"], "batch1"), ("b", ["view", "calc_start"], "batch1"), ("c", ["view"], "")):
            for s in steps:
                assert ev(sid, s, camp)[0] == 200
        ev("a", "view", "batch1")                                            # a repeat view is not a new visitor
        assert server.handle_post("/api/event", {"event": "hack", "sid": "x"})[0] == 422
        f = server.funnel()
        assert [s["visitors"] for s in f["overall"]] == [3, 2, 1, 1, 1, 1]
        assert [s["visitors"] for s in f["campaigns"][0]["steps"]] == [2, 2, 1, 1, 1, 1] and f["campaigns"][0]["campaign"] == "batch1"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_find_leads_rejects_unknown_input_and_second_job(monkeypatch):
    from app import jobs
    assert jobs.start("Atlantis", "quick")[0] == 422
    assert jobs.start("Pune", "huge")[0] == 422

    class Running:
        def poll(self):
            return None
    monkeypatch.setitem(jobs.JOB, "proc", Running())
    monkeypatch.setitem(jobs.JOB, "city", "Pune")
    code, body = jobs.start("Mumbai", "quick")
    assert code == 409 and "Pune" in body["error"]


def test_job_status_hides_secrets_and_reports_stages(monkeypatch):
    from app import jobs

    class Done:
        def poll(self):
            return 0
    log = jobs.ROOT / "cache" / "_test" / "job.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("calling https://x.test/api?api_key=SECRET123&a=1\n", "utf-8")
    monkeypatch.setattr(jobs, "STATE", log.parent)
    monkeypatch.setattr(jobs, "JOB", {"proc": Done(), "city": "Pune", "size": "quick", "folder": "cache/_test/none", "started": 0})
    s = jobs.status()
    assert s["state"] == "done" and s["dataset"] == "pune" and len(s["stages"]) == 5
    assert "SECRET123" not in " ".join(s["tail"])


def test_run_options_lists_the_six_cities():
    from app import jobs
    assert set(jobs.cities()) == {"Bangalore", "Hyderabad", "Pune", "NCR", "Mumbai", "Chennai"}
    assert all({"label", "minutes", "cost", "args"} <= set(v) for v in jobs.SIZES.values())


def test_draft_carries_a_tracked_link_the_model_cannot_write_or_remove():
    subj, body = drafting.assemble("S", "Message.", LEAD["contacts"][0], LEAD)
    link = playbook.link_for("Acme", "corporate", "Bangalore")
    assert link in body and body.rstrip().endswith("InfinityBox") and "c=Acme" in link and "s=corporate" in link and "utm_campaign=bangalore-" in link
    assert drafting.problems(LEAD, subj, body, whole=True) == []                      # the link's digits and tags are not flagged as claims
    assert any("link" in b for b in drafting.problems(LEAD, subj, body.replace(link, ""), whole=True))   # removing it is flagged


def test_public_snapshot_has_no_personal_details():
    from app import export_static
    lead = {"company": "Acme", "contacts": [{"name": "Asha Rao", "title": "Head of Facilities", "email": "asha@acme.com", "linkedin": "https://www.linkedin.com/in/x",
                                              "source_url": "https://www.linkedin.com/in/x", "why": "Asha Rao is the decision maker", "tier": "tier1", "relevance": 0.9}],
            "why_now": "Acme opened a campus; press contact press@acme.com", "sources": [{"quote": "Asha Rao said the campus opens soon"}]}
    out = export_static.scrub(lead)
    blob = str(out)
    assert "Asha" not in blob and "@acme.com" not in blob and "linkedin.com/in" not in blob
    assert out["contacts"][0]["title"] == "Head of Facilities" and out["contacts"][0]["hidden"] is True


def test_dashboard_page_is_the_desk_in_read_only_mode():
    from app import export_static
    page = export_static.html()
    assert 'window.STATIC_BASE = "data/"' in page and page.index("STATIC_BASE") < page.index("const STATIC")
    assert (export_static.OUT / "data" / "datasets.json").exists()


def test_hosted_mode_needs_the_access_code_and_limits_wrong_guesses(monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret")
    server.FAILS.clear()
    assert server.access_check("/api/leads", "", "1.1.1.1")[0] == 401
    assert server.access_check("/api/leads", "s3cret", "1.1.1.1")[0] == 200
    assert server.access_check("/", "", "1.1.1.1")[0] == 200                      # the page itself is not secret, its data is
    assert server.access_check("/api/lead", "s3cret", "1.1.1.1")[0] == 404        # local-only endpoints are off on a hosted server
    for _ in range(20):
        server.access_check("/api/leads", "wrong", "2.2.2.2")
    server.FAILS["4.4.4.4"] = []
    for _ in range(50):
        server.access_check("/api/leads", "", "4.4.4.4")                          # no code at all never locks anyone out
    assert server.access_check("/api/leads", "s3cret", "4.4.4.4")[0] == 200
    assert server.access_check("/api/leads", "s3cret", "2.2.2.2")[0] == 429       # guessing is rate limited, even with the right code
    monkeypatch.delenv("ACCESS_CODE")
    assert server.access_check("/api/leads", "", "3.3.3.3")[0] == 200             # no code configured (local use): open


def test_demo_profile_caps_spend_and_offers_only_the_quick_run(monkeypatch):
    from app import jobs
    from src import budget
    monkeypatch.setenv("BUDGET_PROFILE", "demo")
    assert set(jobs.sizes()) == {"quick"} and jobs.start("Pune", "full")[0] == 422
    demo, main = budget.caps(), budget.yml("budgets")
    assert all(demo["monthly"][k] < main["monthly"][k] for k in ("firecrawl", "hunter", "gemini"))
    monkeypatch.delenv("BUDGET_PROFILE")
    assert set(jobs.sizes()) == {"quick", "standard", "full"}


def test_local_sheet_download_and_setup_status(monkeypatch):
    import io
    import openpyxl
    from app import data
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test-secret-123")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "")
    st = server.setup_status()
    assert [k["set"] for k in st["keys"]][:2] == [True, False] and "sk-test-secret-123" not in str(st)   # status only, never the key
    folder = cfg.ROOT / "cache" / "_app_test" / "ds"                                       # a tiny empty run, so this works on a clean checkout too
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "accounts.json").write_text("[]", "utf-8")
    monkeypatch.setitem(data.DATASETS, "t", {"label": "t", "kind": "pipeline", "dir": "cache/_app_test/ds", "city": "Pune"})
    try:
        ds, before = next(d for d in data.available() if d["id"] == "t"), server.store.DIR
        wb = openpyxl.load_workbook(io.BytesIO(server.workbook_bytes(ds["id"])))
        assert {"Accounts", "Scores", "Drafts", "Pipeline"} <= set(wb.sheetnames)
        assert server.store.DIR == before                                                  # the store is pointed back after the export
    finally:
        shutil.rmtree(cfg.ROOT / "cache" / "_app_test", ignore_errors=True)


def test_dashboard_shows_enquiries_and_visits_stored_in_the_google_sheet(monkeypatch):
    """The live public page writes to the sheet (Leads, Events); the dashboard reads them through the gateway next to its own."""
    tabs = {"Leads": [["ts", "company", "role", "city", "segment", "seats", "meals", "inputs_json", "queue", "owner"],
                      ["2026-10-04T10:00:00Z", "Acme Foods", "Facilities", "Pune", "corporate", "500", "900", '{"contact": "a@acme.com"}', "warewashing", ""]],
            "Events": [["ts", "sid", "event", "utm_source", "utm_medium", "utm_campaign", "ref", "path"],
                       ["t", "s1", "view", "email", "outreach", "pune-202610", "", "/"], ["t", "s1", "lead", "email", "outreach", "pune-202610", "", "/"],
                       ["t", "s2", "junk", "", "", "", "", "/"]]}

    class Book:
        def call(self, op, title="", **kw):
            return tabs[title]
    monkeypatch.setenv("SHEET_WEBHOOK_URL", "https://example.test/exec")
    monkeypatch.setattr(server.sheet, "open_book", lambda: Book())
    monkeypatch.setattr(server, "_read", lambda name: [])
    server._SHEET.clear()
    rows = server.inbound()
    assert rows[0]["company"] == "Acme Foods" and rows[0]["source"] == "sheet" and rows[0]["meals"] == 900 and rows[0]["queue"] == "warewashing"
    f = server.funnel()
    assert [s["visitors"] for s in f["overall"]][0] == 1 and f["overall"][-1]["visitors"] == 1   # visited 1, sent an enquiry 1; the unknown event is ignored
    assert f["campaigns"][0]["campaign"] == "pune-202610"
    monkeypatch.delenv("SHEET_WEBHOOK_URL")
    server._SHEET.clear()
    assert server.inbound() == [] and server.sheet_tab("Leads") == []                           # no gateway: nothing read, nothing broken
