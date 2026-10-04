"""Data shapes shared by every step (pydantic). Each model is also a Google Sheet tab: field order = column order."""
from datetime import date
from typing import Literal

from pydantic import BaseModel

Segment = Literal["corporate", "caterer", "fitout", "institution"]
TriggerType = Literal[
    "new_campus", "lease", "cafeteria_revamp", "tender",
    "caterer_renewal", "esg_plastic", "facilities_hiring",
]


class Doc(BaseModel):
    """A fetched page or news item. Evidence must be a substring of `text`."""
    url: str
    title: str = ""
    text: str
    date: date
    source: str  # news | web


class Account(BaseModel):
    id: str
    name: str
    domain: str = ""
    city: str
    segment: Segment
    size_est: int | None = None
    caterer: str = ""  # blank when unknown; never guess
    linkedin_url: str = ""  # company page, from web search or config/overrides.yaml
    org_kind: str = ""  # corporate | manufacturing | education | hospital | government | caterer | fitout (picks the contact hierarchy)
    first_seen: date
    status: str = "new"


class Signal(BaseModel):
    id: str
    account_id: str
    type: TriggerType
    date: date
    summary: str
    source_url: str
    evidence: str  # verbatim substring of the fetched text
    conf: float = 0.5
    city: str = ""  # filled when saved to the sheet: rows are keyed by (account, city)


class Person(BaseModel):
    account_id: str
    role: str
    name: str = ""
    profile_url: str = ""
    email: str = ""  # only ever what Hunter or the org's own website returned; never generated
    email_status: str = ""  # Hunter verification status, or "published" for a site-listed address
    source: str  # website | apify:<actor> | hunter | linkedin-search-link (joined with + after a merge)
    source_url: str = ""  # page that backs this contact (the site page, or Hunter's source for the address)
    evidence: str = ""  # snippet from that page
    role_match: float = 0.0  # 0-1 relevance from config/hierarchy.yaml (>= 0.6 = a real target)
    tier: str = ""  # tier1 decision maker | tier2 day-to-day owner | tier3 gatekeeper | generic | none
    why: str = ""  # why this person is (not) the right contact
    purpose: str = "B2B outreach to business role"  # DPDP: why we hold this
    city: str = ""  # filled when saved to the sheet: rows are keyed by (account, city)


class Score(BaseModel):
    account_id: str
    fit: float
    trigger: float
    reach: float
    total: float
    reason: str
    rank: int = 0
    updated: str = ""
    city: str = ""  # filled when saved to the sheet: rows are keyed by (account, city)


class Draft(BaseModel):
    account_id: str
    role: str
    subject: str
    body: str
    trigger_used: str
    status: str = "draft"
    city: str = ""  # filled when saved to the sheet: rows are keyed by (account, city)


class Lead(BaseModel):
    ts: str
    company: str
    role: str
    city: str
    segment: Segment
    seats: int
    meals: int
    inputs_json: str
    queue: str
    owner: str = ""


class LeadRow(BaseModel):
    """Flat, filterable view of one lead: account + score + best contact + every link that backs it."""
    rank: int
    account: str
    city: str
    segment: str
    total: float
    fit: float
    trigger: float
    reach: float
    reason: str
    triggers: str  # comma-separated trigger types
    source_kinds: str = ""  # news, tender
    newest_signal: str  # ISO date
    website: str = ""
    linkedin_company: str = ""
    contact_name: str = ""
    contact_title: str = ""
    contact_linkedin: str = ""  # profile URL, or the manual search link when no person was found
    contact_email: str = ""
    email_status: str = ""
    contact_source: str = ""
    contact_tier: str = ""
    contact_why: str = ""
    second_contact: str = ""  # runner-up: name, title, email
    contact_page: str = ""  # page that backs the contact
    n_sources: int = 0
    evidence_links: str = ""  # one line per signal: type | date | headline | url


class Source(BaseModel):
    name: str
    url: str
    group: str
    access: str = ""
    priority: str = ""
    seen_live: int = 0  # v in sources.yaml: 1 = seen live while researching
    status: str = ""    # ok | blocked | dead | template
    http: int | None = None
    checked: str = ""
    note: str = ""
