from datetime import date, timedelta

from src.contacts import candidate_pages, extract_contacts
from src.leads import apply_filters
from src.models import Account, LeadRow
from src.people import _hunter_person
from src.hierarchy import Rel

UNI = Account(id="u", name="Example University", domain="exampleuni.ac.in", city="Pune", segment="institution",
              first_seen=date(2026, 1, 1))

PAGE = """
## Administration
**Dr. Meera Kulkar**
Registrar
[registrar@exampleuni.ac.in](mailto:registrar@exampleuni.ac.in)

Estate Officer
Mr. Anil Joshi
anil.joshi [at] exampleuni [dot] ac.in

Write to us: info@exampleuni.ac.in, someone@gmail.com, vendor@otherdomain.com
Hostel office: hostel@exampleuni.ac.in
"""


def by_email(ps):
    return {p.email: p for p in ps}


def test_website_contacts_only_published_org_addresses():
    ps = extract_contacts(PAGE, "https://exampleuni.ac.in/contact", UNI)
    assert set(by_email(ps)) == {"registrar@exampleuni.ac.in", "anil.joshi@exampleuni.ac.in", "info@exampleuni.ac.in",
                                 "hostel@exampleuni.ac.in"}  # no gmail, no other domain
    reg = by_email(ps)["registrar@exampleuni.ac.in"]
    assert reg.name == "Dr. Meera Kulkar" and reg.role == "Registrar" and reg.email_status == "published"
    assert reg.tier == "tier3" and reg.role_match < 0.6                      # gatekeeper, not the buyer
    est = by_email(ps)["anil.joshi@exampleuni.ac.in"]
    assert est.role == "Estate Officer" and est.tier == "tier1" and est.role_match >= 0.6
    assert by_email(ps)["info@exampleuni.ac.in"].tier == "generic" and by_email(ps)["info@exampleuni.ac.in"].name == ""
    assert by_email(ps)["hostel@exampleuni.ac.in"].tier in ("tier1", "tier2")  # judged by the mailbox name
    assert est.source_url.endswith("/contact") and "anil.joshi@" in est.evidence


def test_trigger_boost_flows_into_contacts():
    plain = by_email(extract_contacts(PAGE, "u", UNI))["anil.joshi@exampleuni.ac.in"].role_match
    boosted = by_email(extract_contacts(PAGE, "u", UNI, ["cafeteria_revamp"]))["anil.joshi@exampleuni.ac.in"].role_match
    assert boosted >= plain


def test_candidate_pages_follow_the_hierarchy():
    links = ["https://exampleuni.ac.in/about", "https://exampleuni.ac.in/contact-us", "https://other.com/contact",
             "https://exampleuni.ac.in/news", "https://exampleuni.ac.in/hostel-mess", "https://exampleuni.ac.in/registrar_office.htm",
             "https://exampleuni.ac.in/press.htm"]
    got = candidate_pages("https://exampleuni.ac.in", links, "education")
    assert got[0].endswith("contact-us") and got[1].endswith("hostel-mess") and "other.com" not in " ".join(got) and "press" not in " ".join(got)


def test_hunter_email_stored_as_returned_with_status_and_source():
    e = {"value": "a.b@corp.com", "first_name": "A", "last_name": "B", "position": "Head of Facilities", "confidence": 91,
         "verification": {"status": "accept_all"}, "sources": [{"uri": "https://corp.com/team"}]}
    p = _hunter_person(UNI, e, Rel(0.9, "tier1", "w"))
    assert (p.email, p.email_status, p.source_url, p.tier) == ("a.b@corp.com", "accept_all", "https://corp.com/team", "tier1")
    assert _hunter_person(UNI, {**e, "verification": None}, Rel(0.9, "tier1", "w")).email_status == "unverified"


def row(**kw):
    base = dict(rank=1, account="A", city="Pune", segment="corporate", total=40, fit=20, trigger=20, reach=0, reason="r",
                triggers="new_campus", source_kinds="news", newest_signal=date.today().isoformat())
    return LeadRow(**{**base, **kw})


def test_filters():
    old = (date.today() - timedelta(days=200)).isoformat()
    rows = [row(account="a"), row(account="b", city="Hyderabad", total=20),
            row(account="c", segment="institution", triggers="tender,lease", source_kinds="tender", newest_signal=old,
                contact_name="X", contact_email="x@y.com", contact_tier="tier1")]
    names = lambda **k: [r.account for r in apply_filters(rows, **k)]
    assert names(city="pune") == ["a", "c"]
    assert names(segment="institution") == ["c"]
    assert names(trigger="lease") == ["c"]
    assert names(min_score=30) == ["a", "c"]
    assert names(has_contact=True) == ["c"] and names(has_email=True) == ["c"]
    assert names(since_days=90) == ["a", "b"]
    assert names(source_kind="tender") == ["c"]
    assert names(tier="tier1") == ["c"] and names(tier="tier2") == []
