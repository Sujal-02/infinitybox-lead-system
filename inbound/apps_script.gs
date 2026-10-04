/**
 * Google Apps Script web app: receives the calculator form, appends to the Leads tab,
 * and routes by segment. Also the sheet gateway for the pipeline (sheetOp).
 * Setup: create it from the sheet itself (Extensions -> Apps Script) so it is bound to that sheet. Script properties -> API_TOKEN
 * (a long random string; the same value goes in the pipeline's .env as SHEET_API_TOKEN). Deploy as Web app (execute as me, access: anyone).
 * Permissions: appsscript.json asks for ONE scope, spreadsheets.currentonly (this sheet only). It cannot open other files or send email.
 * To be told about new enquiries, use the sheet's Tools -> Notification rules ("any changes are made" -> email).
 */
var QUEUES = { corporate: "warewashing", institution: "warewashing", fitout: "kitchen design", caterer: "partner" };
var SEGMENTS = Object.keys(QUEUES);

function route(segment) {
  return QUEUES[segment] || "unrouted";
}

// Column order must match the Leads tab: ts, company, role, city, segment, seats, meals, inputs_json, queue, owner
function buildLead(d, now) {
  var clip = function (v) { return String(v == null ? "" : v).slice(0, 200); };
  if (!clip(d.company) || SEGMENTS.indexOf(d.segment) < 0) throw new Error("company and valid segment required");
  var inputs = { contact: clip(d.contact), setup: clip(d.setup), assumptions: "estimate, see calculator" };
  if (d.inputs) inputs.calc = d.inputs;
  return [now, clip(d.company), clip(d.role), clip(d.city), d.segment,
          Number(d.seats) || 0, Number(d.meals) || 0, JSON.stringify(inputs), route(d.segment), ""];
}

function doPost(e) {
  try {
    var d = JSON.parse(e.postData.contents);
    if (d.op) return sheetOp(d);                  // the pipeline writing to the sheet (needs API_TOKEN); see src/sheet.py ScriptBook
    if (d.type === "event") return logEvent(d);  // anonymous funnel event from the page (no personal data)
    if (d.website) return reply({ ok: true });  // honeypot: bots fill this hidden field
    var row = buildLead(d, new Date().toISOString());
    SpreadsheetApp.getActive().getSheetByName("Leads").appendRow(row);
    return reply({ ok: true, queue: row[8] });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  }
}

function logEvent(d) {
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName("Events");
  if (!sh) { sh = ss.insertSheet("Events"); sh.appendRow(["ts", "sid", "event", "utm_source", "utm_medium", "utm_campaign", "ref", "path"]); }
  var clip = function (v) { return String(v == null ? "" : v).slice(0, 100); };
  sh.appendRow([clip(d.ts), clip(d.sid), clip(d.event), clip(d.utm_source), clip(d.utm_medium), clip(d.utm_campaign), clip(d.ref), clip(d.path)]);
  return reply({ ok: true });
}

// Sheet gateway for the pipeline when a Google Cloud service-account key is not allowed. Every call needs the API_TOKEN.
function sheetOp(d) {
  var props = PropertiesService.getScriptProperties(), token = props.getProperty("API_TOKEN");
  if (!token || d.token !== token) return reply({ ok: false, error: "bad token" });
  var ss = SpreadsheetApp.getActive(), sh = d.title ? ss.getSheetByName(d.title) : null;
  if (d.op === "list") return reply({ ok: true, title: ss.getName(), titles: ss.getSheets().map(function (x) { return x.getName(); }) });
  if (d.op === "add") { if (!sh) ss.insertSheet(String(d.title)); return reply({ ok: true }); }
  if (!sh) return reply({ ok: false, error: "no tab " + d.title });
  if (d.op === "values") return reply({ ok: true, values: sh.getLastRow() ? sh.getDataRange().getDisplayValues() : [] });
  if (d.op === "clear") { sh.clear(); return reply({ ok: true }); }
  if (d.op === "append") {
    var rows = d.rows || [], w = rows.reduce(function (m, r) { return Math.max(m, r.length); }, 0);
    if (!rows.length) return reply({ ok: true });
    var range = sh.getRange(sh.getLastRow() + 1, 1, rows.length, w);
    range.setNumberFormat("@");                    // keep text as text (no auto-converted dates or numbers)
    range.setValues(rows.map(function (r) { while (r.length < w) r.push(""); return r; }));
    return reply({ ok: true });
  }
  return reply({ ok: false, error: "unknown op" });
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
