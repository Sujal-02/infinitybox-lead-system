"""Contacts published on an organisation's own website, via Firecrawl. Cheapest source: good for universities,
hospitals and small firms. Only addresses literally present on the page are kept (never generated), on the org's own
domain, free-mail skipped (DPDP: business data only). Each contact is scored with the hierarchy (src/hierarchy.py), so
a registrar@ ranks as a gatekeeper, and estate@ / hostel@ / purchase@ as targets."""
import re
from urllib.parse import urlparse

from . import hierarchy
from .cfg import env
from .discover import web
from .models import Account, Person

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
FREEMAIL = ("gmail.", "yahoo.", "hotmail.", "outlook.", "rediffmail.", "proton", "icloud.", "live.com", "aol.")
PAGE_SKIP = ("press", "news", "tender", "notice", "circular", "event", "gallery", "career", "admission",
             "lottery", "apk", "casino", "slot", "betting", "game", "review")  # last row: spam on hacked subdomains
SPAM = ("lottery", "apk", "casino", "slot", "betting", "game", "review")
TITLE_PREFIX = re.compile(r"^((dr|prof|mr|mrs|ms|shri|smt|er)[.()\s]*)+", re.I)


def _clean(s: str) -> str:
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # markdown links -> text
    s = re.sub(r"<[^>]*>?", " ", s)  # html tags (also an unterminated "<br")
    s = re.sub(r"[-=_]{3,}|!\[[^\]]*\]", " ", s)  # rules and image markers
    return " ".join(re.sub(r"[*#>|_`]", " ", s).split())


def _lines(md: str) -> list[str]:
    md = re.sub(r"<\s*br[^>]*>?", "\n", md, flags=re.I)  # a <br> starts a new line, so role/name/email stay separate
    return [_clean(x) for x in md.splitlines()]


def _no_phones(s: str) -> str:
    return re.sub(r"(?:tel|ph|phone|fax|mob)[^\w@]*[\d /,+-]{6,}|\d[\d /-]{6,}\d", "", s, flags=re.I)  # evidence carries no phone numbers


def _deobfuscate(text: str) -> str:
    return re.sub(r"\s*[\[(]\s*(at)\s*[\])]\s*", "@", re.sub(r"\s*[\[(]\s*dot\s*[\])]\s*", ".", text, flags=re.I), flags=re.I)


def _looks_like_name(s: str) -> bool:
    words = s.split()
    return 2 <= len(words) <= 5 and all(w[:1].isupper() or w.lower().rstrip(".") in ("dr", "prof") for w in words) \
        and not any(ch.isdigit() or ch == "@" for ch in s)


def extract_contacts(md: str, page_url: str, a: Account, triggers=()) -> list[Person]:
    """Emails found in page markdown. The role comes from the lines just above (a blank line ends the block), else
    from the mailbox name; relevance comes from the hierarchy for this kind of organisation."""
    kind = a.org_kind or hierarchy.classify(a.segment, a.name)
    site = (a.domain or urlparse(page_url).netloc).lower().removeprefix("www.")
    root = ".".join(site.split(".")[-3:]) if site.endswith((".ac.in", ".co.in", ".org.in", ".edu.in", ".gov.in", ".res.in")) \
        else ".".join(site.split(".")[-2:])
    lines = _lines(_deobfuscate(md))
    out, seen = [], set()
    for i, line in enumerate(lines):
        for em in EMAIL.findall(line):
            em = em.lower().strip(".")
            dom = em.split("@")[1]
            if em in seen or any(f in dom for f in FREEMAIL) or not (dom == root or dom.endswith("." + root)):
                continue
            seen.add(em)
            near, j = [], i  # this line plus the contiguous lines above it
            while j >= 0 and lines[j] and len(near) < 4:
                near.insert(0, lines[j])
                j -= 1
            role, rel = "", hierarchy.Rel(0.0, "none", "")
            for x in near:
                if "@" in x:  # the address line itself must not decide the role ("regis@" is not proof of "Registrar")
                    continue
                r = hierarchy.relevance(x[:90], kind, triggers)
                if r.score > rel.score:
                    role, rel = x[:90], r
            name = next((x for x in reversed(near) if "@" not in x and _looks_like_name(TITLE_PREFIX.sub("", x)) and len(x) < 60), "")
            if not rel.score:  # no role text nearby: judge by the mailbox name (estate@, registrar@, info@ ...)
                local = em.split("@")[0]
                rel, role = hierarchy.mailbox_relevance(local, kind, triggers), f"Published mailbox: {local}@"
            out.append(Person(account_id=a.id, role=role, name=name, email=em, email_status="published", source="website",
                              source_url=page_url, evidence=_no_phones(" | ".join(near))[:250], role_match=rel.score,
                              tier=rel.tier, why=rel.why))
    return out


def office_lead(a: Account, title: str, url: str, kind: str, triggers=()) -> Person | None:
    """A page of a relevant office (e.g. 'Hostel Office') that publishes no contact: still worth knowing, but never a target."""
    if any(w in title.lower() for w in ("notice", "announcement", "news", "regarding", "circular", "share", "price", "stock", "investor", "limited", "ltd")):  # an item, not an office
        return None
    r = hierarchy.mailbox_relevance(re.sub(r"[^A-Za-z ]", " ", title.split("-")[0].split("|")[0]), kind, triggers)
    if r.tier not in ("tier1", "tier2"):
        return None
    return Person(account_id=a.id, role=f"Office: {title[:70]}", source="website", source_url=url, tier="office",
                  role_match=min(r.score, 0.5), why=f"relevant office found on the site but no contact published ({r.why}): "
                  "reach it through the switchboard or the gatekeeper")


def candidate_pages(home_url: str, links: list[str], kind: str = "corporate") -> list[str]:
    """Same-site pages most likely to list the right people: contact first, then offices named in the kind's hierarchy."""
    host = urlparse(home_url).netloc.lower().removeprefix("www.")
    hints = hierarchy.page_hints(kind)
    ranked = []
    for u in links:
        low = u.lower()
        if urlparse(u).netloc.lower().removeprefix("www.").endswith(host) and not any(s in low for s in PAGE_SKIP):
            score = min((rank for word, rank in hints if word in low), default=None)
            if score is not None:
                ranked.append((score, u))
    return [u for _, u in sorted(ranked)][:3]


def from_website(a: Account, titles: list[str], stats: dict, triggers=()) -> list[Person]:
    if not env("FIRECRAWL_API_KEY"):
        return []
    a.domain = a.domain or web.domain_for(a)
    if not a.domain:
        return []
    kind = a.org_kind or hierarchy.classify(a.segment, a.name)
    home = f"https://{a.domain}"
    page = web.scrape(home)
    out = extract_contacts(page["markdown"], home, a, triggers)
    for u in candidate_pages(home, page["links"], kind):
        out += extract_contacts(web.scrape(u)["markdown"], u, a, triggers)
    if kind != "corporate" and not any(p.role_match >= hierarchy.TARGET for p in out):  # institutions publish office pages; big corporate sites return junk
        # homepage links did not lead to a target: search the site itself
        found = {}  # url -> page title. Short queries work; long multi-word site: queries return nothing.
        for term in hierarchy.search_terms(kind).split()[:4]:
            for r in web._search(f"site:{a.domain} {term}", 3, scrape=False):
                u, t = r["url"], r.get("title", "")
                if u not in found and not u.lower().endswith(".pdf") and not any(s in (u + t).lower() for s in SPAM):
                    found[u] = t
        rank = lambda t: hierarchy.mailbox_relevance(re.sub(r"[^A-Za-z ]", " ", t.split("-")[0].split("|")[0]), kind, triggers).score
        for u, t in sorted(found.items(), key=lambda kv: -rank(kv[1]))[:3]:  # pages of relevant offices first
            got = extract_contacts(web.scrape(u)["markdown"], u, a, triggers)
            out += got
            lead = office_lead(a, t, u, kind, triggers) if not got else None
            if lead:
                out.append(lead)
    stats["website_contacts"] = stats.get("website_contacts", 0) + len(out)
    return out
