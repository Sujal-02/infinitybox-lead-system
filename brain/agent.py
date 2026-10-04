"""Gemini as the only brain: it plans, searches, reads, scores, picks contacts and writes drafts by calling tools.
This loop only relays tool calls, enforces the free-trial budget (via the tools) and stops at a step limit."""
import json
import time
from datetime import date
from pathlib import Path

from google import genai
from google.genai import types

from src import budget, cfg, llm, playbook
from . import tools

SYSTEM = """You are the lead-generation brain for InfinityBox, an Indian company that provides offsite and onsite warewashing
(commercial dishwashing so cafeterias can serve on reusable ware instead of single-use) and commercial kitchen design.
Buyers are organisations with cafeterias, canteens, messes or kitchens: companies opening or leasing offices and campuses,
institutions (colleges, hospitals, hostels, government bodies) with canteens, caterers, and interior fit-out firms.

Today is {today}. Your job: find the 25 most promising leads in {city} right now, with evidence, the right person to approach,
and a short outreach draft. You decide what to search, which pages to read, which events matter, and which roles to approach (think about who actually buys
cafeteria, kitchen or warewashing services at that kind of organisation, and which people are merely gatekeepers). You do NOT score
leads (code scores them from the evidence, recency and contacts) and you do NOT write email text: the outreach email is assembled
from an approved playbook, and you only give a short event_phrase and choose ids from the menu below. Nothing is ever sent.

Rules (hard):
- Public data only. Use only facts returned by your tools. Quotes must be verbatim from tool output; emails must come from Hunter
  or a page you read; never guess an email address or a LinkedIn URL. If no contact is found, save the lead without one.
- A lead needs a concrete, recent (within about 90 days) event that suggests a cafeteria / kitchen / warewashing need. Check that a
  web page or LinkedIn page really belongs to the company before using it.
- Aim for variety (not only office leases) and for leads in {city} or its immediate region.
- trigger_type must be the label the evidence really shows (a hire or appointment is not a lease; a report is not a tender). If no
  label fits honestly, skip the lead.
- outreach.event_phrase restates the trigger after "Saw that <company> ...", using only words and numbers from your evidence. No claims
  about InfinityBox, no predictions. Playbook menu by segment:
{menu}
- Free-trial budgets for this run, shared with other jobs: web credits {firecrawl}, Hunter searches {hunter}, Apify runs {apify}.
  News search is free. Spend scarce quotas on your strongest leads. Tool errors are returned to you: adapt.
- You have at most {steps} steps (each step = one of your turns, which may call several tools). Save leads as you go, and call
  finish when done. Be honest in the finish summary about what worked and what did not."""


def _remaining() -> dict:
    caps, led = budget.caps(), budget._ledger().get(date.today().strftime("%Y-%m"), {})
    return {s: int(min(caps["per_run"][s], caps["monthly"][s] - led.get(s, 0))) for s in ("firecrawl", "hunter", "apify")}


def _call(client, contents, conf):
    """One model turn: model chain, one short retry on transient errors, charged against the Gemini budget."""
    budget.charge("gemini", 1)
    err = None
    for m in llm.models():
        for attempt in range(2):
            try:
                return client.models.generate_content(model=m, contents=contents, config=conf)
            except Exception as e:
                err = e
                if not any(t in str(e) for t in llm.TRANSIENT) or attempt == 1:
                    break
                time.sleep(15)
    raise err


def run(city: str, max_steps: int, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tools.reset()
    rem = _remaining()
    tools.CITY['name'] = city
    menu = '\n'.join(f'[{seg}]\n' + '\n'.join('  ' + x for x in playbook.options(seg).splitlines()) for seg in tools.SEGMENTS)
    system = SYSTEM.format(today=date.today(), city=city, steps=max_steps, menu=menu, **rem)
    client = genai.Client(api_key=cfg.env("GEMINI_API_KEY"))
    conf = types.GenerateContentConfig(system_instruction=system, tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**d) for d in tools.DECLARATIONS])],
                                       automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = [types.Content(role="user", parts=[types.Part(text=f"Begin. City: {city}.")])]
    trace, summary, steps_used = [], "", 0
    log = (out / "trace.jsonl").open("w", encoding="utf-8")
    for step in range(1, max_steps + 1):
        steps_used = step
        try:
            resp = _call(client, contents, conf)
        except Exception as e:
            summary = f"stopped at step {step}: model call failed ({type(e).__name__}: {str(e)[:160]})"
            break
        cand = resp.candidates[0].content
        contents.append(cand)
        calls = resp.function_calls or []
        if not calls:  # text only: nudge once toward action or finishing
            contents.append(types.Content(role="user", parts=[types.Part(text="Continue with tool calls, or call finish if you are done.")]))
            continue
        parts, done = [], False
        for fc in calls:
            args = dict(fc.args or {})
            if fc.name == "finish":
                summary, done, result = args.get("summary", ""), True, '{"ok": true}'
            elif fc.name in tools.TOOLS:
                result = tools.TOOLS[fc.name](**args)
            else:
                result = json.dumps({"error": f"unknown tool {fc.name}"})
            rec = {"step": step, "tool": fc.name, "args": {k: (v if len(str(v)) < 300 else str(v)[:300] + "...") for k, v in args.items()},
                   "result_chars": len(result), "error": '"error"' in result[:200] or '"saved": false' in result[:40], "result_head": result[:300]}
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            trace.append(rec)
            parts.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
        if done:
            break
        if step >= max_steps - 2:
            parts.append(types.Part(text=f"{max_steps - step} steps left: save any finished leads now and call finish."))
        contents.append(types.Content(role="user", parts=parts))
        time.sleep(1.5)  # stay under the free-tier request rate
    log.close()
    leads = list(tools.LEADS.values())
    (out / "leads.json").write_text(json.dumps(leads, indent=1, ensure_ascii=False), "utf-8")
    meta = {"city": city, "steps_used": steps_used, "max_steps": max_steps, "finish_summary": summary, "leads_saved": len(leads),
            "spend": budget.summary()}
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), "utf-8")
    return meta
