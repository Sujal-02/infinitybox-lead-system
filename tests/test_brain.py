import pytest

from brain import tools


@pytest.fixture(autouse=True)
def fresh():
    tools.reset()
    yield
    tools.reset()


GOOD = dict(company="Acme", segment="corporate", trigger_type="new_campus", event_date="2026-09-01", summary="s",
            evidence="Acme opens a new campus", source_url="http://x/1", why_now="w", buyer_logic="b",
            outreach={"to_role": "Head of Facilities", "event_phrase": "opens a new campus", "value_id": "warewash_core",
                      "condition_id": "caterer_forward", "cta_id": "call_15"})


def seen():
    tools._register("http://x/1", "Acme opens  a new\ncampus in Bengaluru. Contact: facilities@acme.com")
    tools._register("https://linkedin.com/in/asha", "profile")


def test_valid_lead_saved_whitespace_insensitive():
    seen()
    assert '"saved": true' in tools.save_lead(**GOOD)
    assert "acme" in tools.LEADS


def test_rejects_unverified_quote_url_email_and_linkedin():
    seen()
    r = tools.save_lead(**{**GOOD, "evidence": "Acme opens a 5,000-seat campus"})
    assert "verbatim" in r
    assert "never returned" in tools.save_lead(**{**GOOD, "source_url": "http://made-up"})
    bad = tools.save_lead(**{**GOOD, "contacts": [{"name": "A", "email": "a.b@acme.com"}]})
    assert "never appeared" in bad and not tools.LEADS
    assert "never appeared" in tools.save_lead(**{**GOOD, "contacts": [{"name": "A", "linkedin_url": "https://linkedin.com/in/fake"}]})
    ok = tools.save_lead(**{**GOOD, "contacts": [{"name": "Asha", "email": "FACILITIES@acme.com", "linkedin_url": "https://linkedin.com/in/asha"}]})
    assert '"saved": true' in ok                  # emails/links that a tool returned are accepted


def test_draft_limit_enums_and_cap():
    seen()
    assert "not in the evidence" in tools.save_lead(**{**GOOD, "outreach": {**GOOD["outreach"], "event_phrase": "will triple its catering spend next year"}})
    assert "forbidden" in tools.save_lead(**{**GOOD, "outreach": {**GOOD["outreach"], "event_phrase": "opens an IoT campus"}})
    assert "not allowed" in tools.save_lead(**{**GOOD, "outreach": {**GOOD["outreach"], "value_id": "caterer_partner"}})
    assert "segment must" in tools.save_lead(**{**GOOD, "segment": "other"})
    for i in range(tools.MAX_LEADS):
        tools.LEADS[f"c{i}"] = {}
    assert "call finish" in tools.save_lead(**{**GOOD, "company": "NewCo"})
    assert '"saved": true' in tools.save_lead(**{**GOOD, "company": "c3"})   # replacing an existing lead is allowed


def test_error_strings_never_leak_keys():
    e = RuntimeError("400 for url: https://api.hunter.io/v2/x?domain=a.com&api_key=SECRET123&limit=10")
    assert "SECRET123" not in tools._clean_err(e)


def test_score_is_computed_by_code_and_draft_comes_from_playbook():
    seen()
    import datetime
    recent = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    tools.CITY["name"] = "Bangalore"
    assert '"saved": true' in tools.save_lead(**{**GOOD, "event_date": recent, "priority_score": 100})   # an LLM score is ignored
    lead = tools.LEADS["acme"]
    assert lead["score"]["total"] != 100 and lead["score"]["trigger"] > 20 and "campus" in lead["score"]["reason"]
    assert lead["draft"]["body"].startswith("Saw that Acme opens a new campus.") and "InfinityBox provides" in lead["draft"]["body"]


def test_old_event_and_unsupported_trigger_label_rejected():
    seen()
    assert "within 120 days" in tools.save_lead(**{**GOOD, "event_date": "2025-01-01"})
    tools._register("http://x/2", "Table Space appoints Naveen Raina as COO of DESYN")
    r = tools.save_lead(**{**GOOD, "company": "DESYN", "source_url": "http://x/2", "evidence": "Table Space appoints Naveen Raina as COO",
                           "trigger_type": "facilities_hiring", "outreach": {**GOOD["outreach"], "event_phrase": "appointed Naveen Raina as COO"}})
    assert "not supported by the evidence" in r        # the label the first run stretched


def test_contact_relevance_and_hunter_status_flow_into_score(monkeypatch):
    from brain import scoring
    lead = {**GOOD, "event_date": "2026-09-20", "contacts": [{"name": "A B", "title": "Head of Facilities", "email": "a.b@acme.com"}]}
    r = scoring.score_lead(lead, "Bangalore", {"a.b@acme.com": "accept_all"})
    c = r["contacts"][0]
    assert c["tier"] == "tier1" and c["email_status"] == "accept_all" and r["reach"] >= 9    # named target + unverified email
