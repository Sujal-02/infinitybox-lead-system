import pytest

from src import hierarchy
from src.hierarchy import classify, mailbox_relevance, relevance
from src.models import Account, Person
from src.people import _map_item, merge, select


def test_classify_organisation_kind():
    assert classify("institution", "Savitribai Phule Pune University") == "education"
    assert classify("institution", "Sassoon Hospital") == "hospital"
    assert classify("institution", "PMRDA") == "government"
    assert classify("corporate", "RUCKUS Networks", "Starts Local Manufacturing in Pune") == "manufacturing"
    assert classify("corporate", "TCS", "new campus") == "corporate"
    assert classify("caterer", "Sodexo") == "caterer"


def test_university_hierarchy_registrar_is_gatekeeper_not_buyer():
    reg = relevance("Registrar", "education")
    assert reg.tier == "tier3" and reg.score < hierarchy.TARGET
    for t in ("Estate Officer", "Chief Rector", "Dean Student Welfare"):
        assert relevance(t, "education").tier == "tier1" and relevance(t, "education").score >= hierarchy.TARGET
    assert relevance("Hostel Warden", "education").tier == "tier2"
    assert relevance("Purchase Officer", "education").tier == "tier2"
    for t in ("Professor of Physics", "Examination Controller", "Head of Department, Chemistry"):
        assert relevance(t, "education").score == 0


def test_other_kinds():
    assert relevance("Head of Facilities", "corporate").tier == "tier1"
    assert relevance("Facility Manager", "corporate").tier == "tier2"       # facility = facilities
    assert relevance("Senior Software Engineer", "corporate").score == 0
    assert relevance("Chief Dietitian", "hospital").tier == "tier1"
    assert relevance("Consultant Surgeon", "hospital").score == 0
    assert relevance("Medical Superintendent", "hospital").tier == "tier3"
    assert relevance("Canteen Manager", "manufacturing").tier == "tier2"
    assert relevance("Production Manager", "manufacturing").score == 0
    assert relevance("Executive Engineer", "government").tier == "tier1"


def test_trigger_boost_and_seniority():
    base = relevance("Purchase Officer", "education").score
    assert relevance("Purchase Officer", "education", ["tender"]).score == pytest.approx(base + 0.1)
    assert relevance("Head of Facilities", "corporate").score > relevance("Facilities Manager", "corporate").score
    assert relevance("Assistant Estate Officer", "education").score < relevance("Estate Officer", "education").score  # junior


def test_mailbox_relevance():
    assert mailbox_relevance("estate", "education").tier == "tier1"
    assert mailbox_relevance("registrar", "education").tier == "tier3"
    assert mailbox_relevance("info", "education").tier == "generic"
    assert mailbox_relevance("hostel.office", "education").tier in ("tier1", "tier2")


def test_map_item_tolerates_field_variants():
    a = _map_item({"firstName": "Asha", "lastName": "Rao", "headline": "Head of Facilities at X",
                   "linkedinUrl": "https://linkedin.com/in/asha"})
    assert a == {"name": "Asha Rao", "title": "Head of Facilities at X", "url": "https://linkedin.com/in/asha"}
    b = _map_item({"fullName": "B C", "currentPositions": [{"position": "Admin Head"}], "profileUrl": "u"})
    assert b["title"] == "Admin Head" and b["url"] == "u"


def P(**kw):
    return Person(**{**dict(account_id="a", role="r", source="website"), **kw})


def test_merge_dedupes_and_fills_blanks():
    p1 = P(name="Asha Rao", profile_url="li", source="apify:x", role_match=0.9, tier="tier1")
    p2 = P(name="asha rao", email="a@x.com", email_status="valid", source="hunter", role_match=0.8, tier="tier1")
    out = merge([p2, p1])
    assert len(out) == 1 and out[0].email == "a@x.com" and out[0].profile_url == "li" and "hunter" in out[0].source


def test_select_prefers_targets_and_flags_gatekeeper():
    target = P(name="E O", role="Estate Officer", role_match=0.9, tier="tier1")
    target2 = P(name="W D", role="Hostel Warden", role_match=0.7, tier="tier2")
    gate = P(name="R G", role="Registrar", email="r@u.in", role_match=0.4, tier="tier3")
    assert [p.role for p in select([gate, target2, target])] == ["Estate Officer", "Hostel Warden"]  # gatekeeper left out
    only_gate = select([gate, P(role="info", role_match=0.15, tier="generic", email="i@u.in")])
    assert len(only_gate) == 1 and only_gate[0].tier == "tier3" and "introduction" in only_gate[0].why
    assert select([P(role="info", role_match=0.15, tier="generic")]) == []


def test_office_lead_for_relevant_office_without_contacts():
    from src.contacts import office_lead
    uni = Account(id="u", name="Example University", city="Pune", segment="institution", first_seen="2026-01-01")
    lead = office_lead(uni, "Hostel Office - Pune", "https://x.ac.in/hostel", "education")
    assert lead and lead.tier == "office" and lead.role_match <= 0.5 and not lead.email and "no contact published" in lead.why
    assert office_lead(uni, "NewsandAnnouncements: Tender Notice No. 5", "u", "education") is None   # a notice is not an office
    assert office_lead(uni, "Department of Physics", "u", "education") is None


def test_select_without_targets_returns_gatekeeper_plus_office_leads():
    gate = P(name="R G", role="Registrar", email="r@u.in", role_match=0.4, tier="tier3")
    office = P(role="Office: Hostel Office", role_match=0.5, tier="office")
    got = select([P(role="info", role_match=0.15, tier="generic"), office, gate])
    assert [p.tier for p in got] == ["tier3", "office"]
    assert select([office])[0].tier == "office"


def test_regressions_from_real_runs():
    assert classify("corporate", "TCS", "Opens 'Lights-Out' Factory Lab In Pune") == "corporate"      # "factory" alone is not a plant
    assert classify("corporate", "RUCKUS Networks", "Starts Local Manufacturing in Pune") == "manufacturing"
    assert mailbox_relevance("investor.service", "corporate").tier == "generic"                      # one shared word is not a match
    assert mailbox_relevance("facilities", "corporate").tier == "tier1"


def test_apify_limit_message_is_a_failure_not_zero_people():
    from types import SimpleNamespace as NS
    from src.people import ApifyError, check_run
    check_run(NS(status="SUCCEEDED", status_message="success"))
    for bad in (NS(status="SUCCEEDED", status_message="free user run limit exceeded"), NS(status="FAILED", status_message="boom")):
        with pytest.raises(ApifyError):
            check_run(bad)


def test_title_match_is_order_aware():
    assert relevance("AMS Delivery Manager with a Global Food Service Client", "corporate").score == 0   # real false positive
    assert relevance("Food Services Manager", "corporate").tier == "tier2"
    assert relevance("Head - Facilities", "corporate").tier == "tier1"                                   # "of" is optional
    assert relevance("Head Corporate Services, Real Estate and Facilities Management", "corporate").tier == "tier1"
    assert relevance("Dean (Student Welfare)", "education").tier == "tier1"


def test_resolve_merges_one_word_alias_and_kind_government():
    from src.resolve import resolve
    accs = []
    a = resolve(accs, "UNSW", "Bangalore", "institution")
    b = resolve(accs, "UNSW Sydney", "Bangalore", "institution")
    assert a is b and len(accs) == 1
    assert len([resolve(accs, "Bank of India", "B", "corporate"), resolve(accs, "State Bank of India", "B", "corporate")]) == 2 and len(accs) == 3  # multi-word names stay separate
    assert classify("institution", "Karnataka Government") == "government"


def test_llm_domain_is_ignored():
    from datetime import date
    from src.extract import Extraction, Item, extract
    from src.models import Doc
    import src.llm as llm
    d = Doc(url="u", title="t", text="Acme opens campus in Bengaluru", date=date(2026, 9, 1), source="web")
    item = Item(company="Acme", segment="corporate", type="new_campus", summary="s", evidence="Acme opens campus", domain="newspublisher.com")
    orig = llm.ask
    llm.ask = lambda *a, **k: Extraction(items=[item])
    try:
        accs = []
        extract([d], "Bangalore", accs, [], {})
    finally:
        llm.ask = orig
    assert accs[0].domain == ""            # never the publisher's domain


def test_mailbox_needs_whole_words():
    assert mailbox_relevance("corporatehr.services", "corporate").tier == "generic"   # real false positive (Target HR mailbox)
    assert mailbox_relevance("facilities", "corporate").tier == "tier1"
    assert mailbox_relevance("facility", "corporate").tier == "tier1"                  # plural/-y still match
    assert mailbox_relevance("estate", "education").tier == "tier1"


def test_apimaestro_headline_and_city_handling():
    from src.people import _in_city, _title_from_headline
    assert _title_from_headline("Facility Manager at Tata Consultancy Services") == "Facility Manager"
    assert _title_from_headline("Deputy Area Manager | Administration - Infrastructure & Facilities @ Bajaj") == "Deputy Area Manager | Administration - Infrastructure & Facilities"
    # the company name must not leak into role matching ("Consultancy" would hit the 'consultant' exclusion)
    assert relevance(_title_from_headline("Facility Manager at Tata Consultancy Services"), "corporate").tier == "tier2"
    assert _in_city({"location": {"full": "Pune District, Maharashtra, India"}}, "Pune")
    assert _in_city({"location": {"full": "Bengaluru, Karnataka, India"}}, "Bangalore")
    assert not _in_city({"location": {"full": "Hyderabad, Telangana, India"}}, "Pune")


def test_query_words_and_actor_fallback(monkeypatch):
    from src import people
    from src.hierarchy import query_words
    w = query_words("education")
    assert "estate" in w and any("hostel" in t for t in w) and "head" not in w
    assert "real estate" in query_words("corporate", 20) and "real" not in query_words("corporate", 20)   # phrases, not noise words
    a = Account(id="a", name="Acme", city="Pune", segment="corporate", first_seen="2026-01-01", linkedin_url="https://linkedin.com/company/acme")
    monkeypatch.setattr(people, "_refused", set())
    monkeypatch.setattr(people.cfg, "env", lambda k, d="": "x", raising=False)
    monkeypatch.setattr(people, "env", lambda k, d="": "x")
    calls = []
    def fake(a_, key, titles, triggers):
        calls.append(key)
        if key == "people":
            raise people.ApifyError("free user run limit exceeded")
        return [Person(account_id="a", role="Facility Manager", name="N", source="apify:alt", role_match=0.7, tier="tier2")]
    monkeypatch.setattr(people, "_apify_people", fake)
    st = {}
    assert people.from_apify(a, [], st)[0].name == "N" and calls == ["people", "people_alt"]
    people.from_apify(a, [], st)
    assert calls == ["people", "people_alt", "people_alt"]      # the refused actor is not retried within the run


def test_real_titles_found_by_the_agent_are_relevant():
    # contacts Gemini found in run 2 that the first hierarchy scored 0
    for t in ("Senior Manager - Corporate Real Estate", "Manager, Workplace Services & Real Estate PM", "Senior Manager Property, Real Estate and Facilities Management"):
        r = relevance(t, "corporate")
        assert r.tier == "tier2" and r.score >= hierarchy.TARGET - 0.15, (t, r)
    assert relevance("Head – Facilities & Administration", "corporate").tier == "tier1"
    assert relevance("MD & CCE, Ingram Micro India", "corporate").tier == "none"      # "MD" alone is not "managing director"
    assert relevance("Managing Director", "corporate").tier == "tier3"
    assert relevance("Software Engineer, Real Estate Platform", "corporate").score == 0   # exclusion still wins
