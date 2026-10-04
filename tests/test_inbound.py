"""Runs inbound/apps_script.gs under node with mocked Google services: form POST -> Leads row (no email, no other Google service)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

GS = Path(__file__).resolve().parent.parent / "inbound" / "apps_script.gs"

HARNESS = """
const vm = require('vm'), fs = require('fs');
const rows = [], mails = [];
const ctx = { rows, mails,
  PropertiesService: { getScriptProperties: () => ({ getProperty: k => k + '_val' }) },
  SpreadsheetApp: { getActive: () => ({ getSheetByName: n => (n === 'Events' && !ctx.hasEvents) ? null : ({ appendRow: r => rows.push([n, r]) }),
    insertSheet: n => { ctx.hasEvents = true; return { appendRow: r => rows.push([n, r]) }; } }) },
  MailApp: { sendEmail: (...a) => mails.push(a) },
  ContentService: { MimeType: { JSON: 'json' }, createTextOutput: s => ({ s, setMimeType() { return this; } }) } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const post = o => JSON.parse(vm.runInContext('doPost', ctx)({ postData: { contents: JSON.stringify(o) } }).s);
const out = {
  ok: post({ company: 'Acme', role: 'Facilities', city: 'Pune', segment: 'fitout', seats: '500', meals: 900, contact: 'a@acme.com' }),
  bad: post({ company: 'Acme', segment: 'nonsense' }),
  bot: post({ company: 'Spam', segment: 'caterer', website: 'x' }),
  ev: post({ type: 'event', event: 'view', sid: 's1', ts: 't', utm_campaign: 'batch1' }),
  rows, mails };
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_form_to_leads_row_and_routing():
    r = subprocess.run(["node", "-e", HARNESS, str(GS)], capture_output=True, text=True, check=True)
    out = json.loads(r.stdout)
    assert out["ok"] == {"ok": True, "queue": "kitchen design"}
    assert out["bad"]["ok"] is False
    assert out["bot"] == {"ok": True}  # honeypot: silently accepted, nothing stored
    assert out["ev"] == {"ok": True}
    leads = [r for r in out["rows"] if r[0] == "Leads"]
    assert len(leads) == 1
    events = [r for r in out["rows"] if r[0] == "Events"]               # header row created on first event, then the event itself
    assert events[0][1][0] == "ts" and events[1][1][2] == "view" and events[1][1][5] == "batch1"
    row = leads[0][1]
    assert len(row) == 10 and row[1] == "Acme" and row[5] == 500 and row[8] == "kitchen design"
    assert out["mails"] == []                                         # the script cannot send email (narrow permissions)
    import json as _j
    manifest = _j.loads((GS.parent / "appsscript.json").read_text())
    assert manifest["oauthScopes"] == ["https://www.googleapis.com/auth/spreadsheets.currentonly"]
    assert "MailApp" not in GS.read_text() and "openById" not in GS.read_text()
