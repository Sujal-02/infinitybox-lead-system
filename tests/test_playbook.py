import pytest

from src import playbook
from src.playbook import Choice

EV = "Nike lays a big long-term bet on India with new Bengaluru campus to serve athletes and drive growth"


def C(**kw):
    return Choice(**{**dict(to_role="Head of Facilities", event_phrase="announced a new campus in Bengaluru",
                            value_id="warewash_core", condition_id="caterer_forward", cta_id="call_15"), **kw})


def test_valid_choice_renders_only_playbook_text():
    assert playbook.validate(C(), "corporate", EV) == []
    subject, body = playbook.render("Nike", "corporate", C())
    assert subject == "Cafeteria warewashing for Nike"
    assert body.startswith("Saw that Nike announced a new campus in Bengaluru.")
    assert "InfinityBox provides offsite and onsite warewashing" in body and len(body.split()) <= 90
    assert "IoT" not in body and "NABH" not in body        # claims the LLM invented last time cannot appear


def test_event_phrase_must_be_supported_by_evidence():
    bad = playbook.validate(C(event_phrase="launched an IoT-enabled zero-waste dining hub with 5,000 seats"), "corporate", EV)
    assert any("forbidden" in b for b in bad) and any("number" in b for b in bad)
    assert any("not in the evidence" in b for b in playbook.validate(C(event_phrase="plans to quadruple its catering spend next year"), "corporate", EV))
    assert playbook.validate(C(event_phrase="opened a new Bengaluru campus"), "corporate", EV) == []   # "opened" ~ "opens"? prefix 'opene' absent -> see below


def test_segment_restrictions_and_unknown_ids():
    assert any("not allowed" in b for b in playbook.validate(C(value_id="caterer_partner"), "corporate", EV))
    assert any("not allowed" in b for b in playbook.validate(C(condition_id="hostel_mess"), "corporate", EV))
    assert any("unknown" in b for b in playbook.validate(C(cta_id="free_money"), "corporate", EV))
    assert playbook.validate(C(value_id="caterer_partner", condition_id="none"), "caterer", EV) == []


def test_menu_lists_only_allowed_ids():
    m = playbook.options("caterer")
    assert "caterer_partner" in m and "warewash_core" in m and "hostel_mess" not in m
