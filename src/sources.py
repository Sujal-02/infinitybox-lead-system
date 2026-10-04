"""Walk config/sources.yaml and check every URL is alive. Status: ok | blocked (alive, bot-walled) | dead | template."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urlparse

import requests

from .cfg import env, yml
from .models import Source


def collect() -> list[Source]:
    out = []

    def walk(node, path):
        if isinstance(node, dict):
            if "u" in node and "n" in node:
                u = node["u"]
                u = u if u.startswith("http") else f"https://{u}"
                out.append(Source(name=node["n"], url=u, group=".".join(path), access=node.get("a", ""),
                                  priority=node.get("p", ""), seen_live=node.get("v", 0), note=node.get("x", "")))
            else:
                for k, v in node.items():
                    walk(v, path + [k])
        elif isinstance(node, list):
            for v in node:
                walk(v, path)

    walk({k: v for k, v in yml("sources").items() if k not in ("rules", "people")}, [])
    return out


def _once(s: Source, timeout: int) -> Source:
    ua = f"InfinityBoxLeadBot/1.0 (status check only; contact {env('TEAM_EMAIL') or 'n/a'})"
    try:
        r = requests.get(s.url, headers={"User-Agent": ua}, timeout=timeout, stream=True, allow_redirects=True)
        r.close()
        s.http = r.status_code
        s.status = ("ok" if r.status_code < 400 else "blocked" if r.status_code in (401, 403, 429)
                    else "dead" if r.status_code in (404, 410) else "error")
        old, new = urlparse(s.url).netloc.removeprefix("www."), urlparse(r.url).netloc.removeprefix("www.")
        if new and new != old:
            s.note = f"{s.note} [redirects to {new}]".strip()
    except requests.RequestException as e:
        dns = any(k in str(e) for k in ("NameResolution", "getaddrinfo", "Name or service", "nodename"))
        s.status, s.note = ("dead" if dns else "unreachable"), f"{s.note} [{type(e).__name__}]".strip()
    return s


def _check(s: Source) -> Source:
    """ok | blocked (alive, bot-walled) | dead (404/410/DNS) | error (5xx) | unreachable (timeout/SSL/connection: retry from a browser) | template."""
    s.checked = date.today().isoformat()
    if "{" in s.url:
        s.status = "template"
        return s
    s = _once(s, 12)
    if s.status == "unreachable":  # one slower retry before giving up: many Indian sites are slow, not down
        s.note = s.note.rsplit(" [", 1)[0] if s.note.endswith("]") else s.note
        s = _once(s, 30)
    return s


def check_all() -> list[Source]:
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(_check, collect()))


DOMAIN = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s)]*)?", re.I)


def collect_city() -> list[Source]:
    """Every URL in config/city_sources.yaml: entries with `u`, REIT entries (named by their key) and media listed as plain
    domains ("thehindu.com (Bengaluru)"). Group = '<city>.<category>'."""
    out = []

    def walk(node, path, key=""):
        if isinstance(node, dict):
            if "u" in node:
                u = node["u"] if node["u"].startswith("http") else f"https://{node['u']}"
                out.append(Source(name=node.get("n") or key, url=u, group=".".join(path), access=node.get("a", ""), priority=node.get("p", ""),
                                  seen_live=node.get("v", 0), note=node.get("x", "")))
            else:
                for k, v in node.items():
                    walk(v, path + [k], k)
        elif isinstance(node, list):
            for v in node:
                walk(v, path)
        elif isinstance(node, str) and path and path[-1] == "local_media":
            m = DOMAIN.search(node)
            if m:
                out.append(Source(name=node, url="https://" + m.group(0), group=".".join(path), access="media", priority="m"))

    walk({k: v for k, v in yml("city_sources").items() if k != "usage"}, [])
    return out


def check_city() -> list[Source]:
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(_check, collect_city()))


CITY_ORDER = ["shared", "bengaluru", "pune", "mumbai", "gurugram"]
CITY_LABEL = {"shared": "All cities (national / cross-city)", "bengaluru": "Bengaluru", "pune": "Pune", "mumbai": "Mumbai", "gurugram": "Gurugram / NCR"}
CATEGORY_LABEL = {"govt_bodies": "Government, tenders and regulators", "chambers_assoc": "Industry bodies and events", "local_media": "Local media",
                  "gcc_trackers": "GCC trackers", "lease_transaction_data": "Lease data", "reits": "REITs / landlords"}
CAT_ORDER = list(CATEGORY_LABEL)
STATUS_ORDER = {"ok": 0, "blocked": 1, "error": 2, "unreachable": 3, "dead": 4, "template": 5}
PRI_ORDER = {"h": 0, "m": 1, "l": 2, "": 3}
FIX = {"dead": "hostname or page does not exist from here: find the current site",
       "unreachable": "timeout or SSL problem from this machine: open it in a browser before dropping it",
       "error": "server error: try again, or use the redirect target if one is shown",
       "blocked": "alive but refuses bots: treat as manual"}


def city_report(rows: list[Source], today: str) -> str:
    """Markdown report: city -> category, sorted by priority then status, plus a city x status matrix and a fix list."""
    from collections import Counter
    key = lambda r: (PRI_ORDER.get(r.priority, 3), STATUS_ORDER.get(r.status, 9), r.name)
    city_of = lambda r: r.group.split(".")[0]
    cat_of = lambda r: r.group.split(".")[1] if "." in r.group else ""
    statuses = ["ok", "blocked", "error", "unreachable", "dead"]
    L = [f"# City sources: reachability, by city and category (checked {today})", "",
         "Each row is one source from `config/city_sources.yaml`. Within a category, sorted by priority (h, m, l) then status. "
         "`unreachable` = timeout or SSL problem from this machine; `blocked` = alive but refuses bots; `dead` = 404 or the hostname does not exist. "
         "A source that is not `ok` here may still work in a normal browser or from an Indian network: check before dropping it.", "",
         "## Summary by city", "", "| city | sources | " + " | ".join(statuses) + " |", "|---|---|" + "---|" * len(statuses)]
    for c in CITY_ORDER:
        mine = [r for r in rows if city_of(r) == c]
        if mine:
            cnt = Counter(r.status for r in mine)
            L.append(f"| {CITY_LABEL[c]} | {len(mine)} | " + " | ".join(str(cnt.get(x, 0)) for x in statuses) + " |")
    cnt = Counter(r.status for r in rows)
    L += [f"| **All** | **{len(rows)}** | " + " | ".join(f"**{cnt.get(x, 0)}**" for x in statuses) + " |", ""]
    for c in CITY_ORDER:
        mine = [r for r in rows if city_of(r) == c]
        if not mine:
            continue
        L += [f"## {CITY_LABEL[c]}", ""]
        for cat in CAT_ORDER:
            sub = sorted([r for r in mine if cat_of(r) == cat or (cat == "reits" and cat_of(r) == "reits")], key=key)
            if not sub:
                continue
            L += [f"### {CATEGORY_LABEL[cat]} ({', '.join(f'{k} {v}' for k, v in Counter(r.status for r in sub).most_common())})", "",
                  "| status | pri | source | url | note |", "|---|---|---|---|---|"]
            L += [f"| {r.status}{' ' + str(r.http) if r.http and r.status != 'ok' else ''} | {r.priority or '-'} | {r.name[:58]} | {r.url} | {r.note[:90]} |" for r in sub]
            L.append("")
    bad = sorted([r for r in rows if r.status != "ok"], key=lambda r: (CITY_ORDER.index(city_of(r)), STATUS_ORDER.get(r.status, 9), r.name))
    L += ["## Fix list (everything that is not ok)", "", "| city | source | status | what to do |", "|---|---|---|---|"]
    L += [f"| {CITY_LABEL[city_of(r)]} | {r.name[:50]} ({r.url}) | {r.status} | {FIX.get(r.status, '')} {r.note[-70:] if 'redirects' in r.note else ''} |" for r in bad]
    redirects = [r for r in rows if "redirects to" in r.note and r.status == "ok"]
    if redirects:
        L += ["", "## Reachable, but the site has moved (update the URL)", ""]
        L += [f"- {r.name}: {r.url} -> {r.note.split('redirects to ')[1].rstrip(']')}" for r in redirects]
    seen = [r for r in rows if r.seen_live == 1 and r.status != "ok"]
    L += ["", "## Marked v:1 (seen live) but not reachable now", ""] + ([f"- {r.name} ({r.url}): {r.status}" for r in seen] or ["- none"])
    return "\n".join(L)
