"""One-time setup for running the lead desk on your own computer.

It explains each service, asks you to paste your own free key, checks that the key works, and saves them in a private `.env`
file next to this script (never uploaded: it is git-ignored). Results go to a local Excel file, so no Google account is needed.

    python setup_local.py              # ask for every key (press Enter to skip an optional one)
    python setup_local.py --if-needed  # ask only if the required key is missing (start.bat / start.sh use this)
    python setup_local.py --check      # test the keys already saved, change nothing

Standard library only, so it runs before anything is installed."""
import getpass
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".env"

# name, label, required?, what it does, what happens without it, where to get it, how to test it (url builder, header)
SERVICES = [
    {"key": "GEMINI_API_KEY", "label": "Gemini (Google AI)", "required": True,
     "does": "The AI. It reads news headlines and pages and turns them into leads, and writes the draft emails.",
     "without": "REQUIRED. Without it nothing can be extracted or drafted.",
     "free": "Free tier, no card. Create a key at https://aistudio.google.com/app/apikey",
     "test": lambda k: ("https://generativelanguage.googleapis.com/v1beta/models?key=" + urllib.parse.quote(k), {})},
    {"key": "FIRECRAWL_API_KEY", "label": "Firecrawl", "required": False,
     "does": "Searches the web and reads pages: company websites, tender portals, GCC trackers, contact pages.",
     "without": "Recommended. Without it only free news search is used, so fewer leads and no website contacts.",
     "free": "1,000 free credits. Sign up at https://www.firecrawl.dev and copy the key from the dashboard.",
     "test": lambda k: ("https://api.firecrawl.dev/v2/team/credit-usage", {"Authorization": "Bearer " + k})},
    {"key": "HUNTER_API_KEY", "label": "Hunter", "required": False,
     "does": "Finds a person's work email and says whether it is verified. Emails are never guessed: only what Hunter or a website returns is used.",
     "without": "Optional. Without it, contacts have names and roles but emails only when a company website publishes them.",
     "free": "50 free searches a month. Get a key at https://hunter.io/api-keys",
     "test": lambda k: ("https://api.hunter.io/v2/account?api_key=" + urllib.parse.quote(k), {})},
    {"key": "APIFY_TOKEN", "label": "Apify", "required": False,
     "does": "Reads PUBLIC LinkedIn company pages to list who works in facilities or admin, with no login or cookies.",
     "without": "Optional. Without it, contacts come only from company websites and Hunter. Skip it if you do not want LinkedIn data used.",
     "free": "About US$5 of free credit a month. Token at https://console.apify.com/account/integrations",
     "test": lambda k: ("https://api.apify.com/v2/users/me?token=" + urllib.parse.quote(k), {})},
]


def read_env(path: Path = ENV) -> dict:
    """KEY=value lines of a .env file (comments and blank lines ignored)."""
    out = {}
    for line in path.read_text("utf-8").splitlines() if path.exists() else []:
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def write_env(updates: dict, path: Path = ENV, template: Path = ROOT / ".env.example") -> None:
    """Set keys in the .env file, keeping every other line (comments, other settings) exactly as it was."""
    source = path if path.exists() else template
    lines = source.read_text("utf-8").splitlines() if source.exists() else []
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=", line)
        if m and m.group(1) in updates:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"
            done.add(m.group(1))
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    path.write_text("\n".join(lines) + "\n", "utf-8")


def mask(value: str) -> str:
    return "(not set)" if not value else "..." + value[-4:] if len(value) > 8 else "(set)"


def check_key(service: dict, value: str) -> tuple[bool, str]:
    """Ask the provider's own free 'who am I' endpoint. The key is never printed, even in an error."""
    url, headers = service["test"](value)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            return (200 <= r.status < 300), "works"
    except urllib.error.HTTPError as e:
        return False, "the service said the key is not valid" if e.code in (400, 401, 403) else f"the service answered {e.code}"
    except Exception as e:  # offline, blocked network, timeout
        return False, f"could not reach the service ({type(e).__name__}); check your internet connection"


def ask_one(service: dict, current: str) -> str:
    print(f"\n{'-' * 70}\n{service['label']}  [{'REQUIRED' if service['required'] else 'optional'}]")
    print(f"  What it does : {service['does']}")
    print(f"  Without it   : {service['without']}")
    print(f"  Cost         : {service['free']}")
    if current:
        print(f"  Currently    : {mask(current)}  (press Enter to keep it)")
    while True:
        value = getpass.getpass("  Paste your key (hidden), or press Enter to " + ("keep" if current else "skip") + ": ").strip()
        if not value:
            if service["required"] and not current:
                print("  This key is required. Paste it to continue.")
                continue
            return current
        ok, why = check_key(service, value)
        print(f"  Checking... {'OK, ' if ok else 'PROBLEM: '}{why}")
        if ok:
            return value
        if input("  Save it anyway? [y/N] ").strip().lower() == "y":
            return value


def main(argv: list[str]) -> int:
    env = read_env()
    if "--check" in argv:
        bad = 0
        for s in SERVICES:
            v = env.get(s["key"], "")
            ok, why = check_key(s, v) if v else (not s["required"], "not set" + (" (REQUIRED)" if s["required"] else " (optional)"))
            bad += not ok
            print(f"{s['label']:<20} {mask(v):<12} {'OK' if ok else 'PROBLEM'}: {why}")
        return 1 if bad else 0
    if "--if-needed" in argv and env.get("GEMINI_API_KEY"):
        return 0
    if not sys.stdin.isatty():
        print("No keys saved yet. Run `python setup_local.py` in a terminal to add them.")
        return 0
    print("InfinityBox lead desk: local setup")
    print("You will paste up to four keys. Each is free to create and stays on this computer in the file .env (it is never uploaded).")
    print("Results are saved in a local Excel file per city (open it in Excel or Google Sheets), so no Google account or sheet is needed.")
    updates = {s["key"]: ask_one(s, env.get(s["key"], "")) for s in SERVICES}
    updates.update({"DRY_RUN": "0", "GSHEET_ID": "", "SHEET_WEBHOOK_URL": "", "SHEET_API_TOKEN": ""})  # no Google Sheet: results go to a local workbook
    write_env(updates)
    print(f"\nSaved to {ENV.name}. Summary:")
    for s in SERVICES:
        print(f"  {s['label']:<20} {mask(updates[s['key']])}")
    print("\nNext: start the desk (start.bat on Windows, ./start.sh on Mac/Linux), open Find leads, pick a city and press the button.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
