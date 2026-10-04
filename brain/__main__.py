"""python -m brain --city Bangalore [--max-steps 70] [--out data_brain]
Runs the Gemini-only agent once, then writes REPORT.md. Nothing is edited by hand between the run and the report."""
import argparse
import json
from collections import Counter
from pathlib import Path

from . import agent


def report(out: Path) -> str:
    leads = sorted(json.loads((out / "leads.json").read_text("utf-8")), key=lambda x: -float(x["score"]["total"]))
    meta = json.loads((out / "meta.json").read_text("utf-8"))
    trace = [json.loads(line) for line in (out / "trace.jsonl").read_text("utf-8").splitlines()]
    calls = Counter(t["tool"] for t in trace)
    errs = Counter(t["tool"] for t in trace if t["error"])
    lines = [f"# Gemini-only run: {meta['city']} (autonomous, no human edits)\n",
             f"Leads saved by Gemini: **{meta['leads_saved']}** | steps used: {meta['steps_used']}/{meta['max_steps']}\n",
             f"**Gemini's own summary:** {meta['finish_summary'] or '(none: it did not call finish)'}\n",
             "## Audit: what the agent did\n",
             "| tool | calls | errors/rejections |", "|---|---|---|"]
    lines += [f"| {k} | {v} | {errs.get(k, 0)} |" for k, v in calls.most_common()]
    rejected = [t for t in trace if t["tool"] == "save_lead" and t["error"]]
    if rejected:
        lines.append("\nRejected saves (validator caught these):")
        lines += [f"- {t['args'].get('company', '?')}: {t['result_head'][:200]}" for t in rejected]
    lines += [f"\nFree-trial spend: {meta['spend']}\n", "## Leads (ranked by the code-computed score; Gemini does not score)\n"]
    for i, l in enumerate(leads, 1):
        sc = l["score"]
        lines.append(f"### {i}. {l['company']} ({l['segment']}/{sc['org_kind']}) | score {sc['total']} [fit {sc['fit']} / trigger {sc['trigger']} / reach {sc['reach']}] | {l['trigger_type']} {l['event_date']}")
        lines.append(f"**Score reason (code):** {sc['reason']}  \n**Why now (Gemini):** {l['why_now']}  \n**Summary:** {l['summary']}  \n**Evidence:** \"{l['evidence']}\" ([source]({l['source_url']}))")
        lines.append(f"**Buyer logic (Gemini):** {l['buyer_logic']}")
        if l.get("website"):
            lines.append(f"**Website:** {l['website']}")
        if l.get("linkedin_company_url"):
            lines.append(f"**Company LinkedIn:** {l['linkedin_company_url']}")
        lines.append("**Contacts (relevance scored by the code hierarchy):**" if sc["contacts"] else "**Contacts:** none found")
        for c in sc["contacts"]:
            lines.append(f"- [{c['tier']} {c['relevance']}] {c.get('name') or '(mailbox)'} | {c.get('title', '')} | email: {c.get('email') or '-'} ({c.get('email_status') or '-'}) | "
                         f"{c.get('linkedin_url') or '-'} | {c.get('note', '')}")
        d = l["draft"]
        o = l["outreach"]
        lines.append(f"\n**Playbook draft to {d.get('to_role', '?')}:** *{d['subject']}*  \n(ids: value={o['value_id']}, condition={o.get('condition_id', 'none')}, cta={o['cta_id']})\n\n> {d['body']}  \n({len(d['body'].split())} words)\n")
    text = "\n".join(lines)
    (out / "REPORT.md").write_text(text, "utf-8")
    return text


def main():
    p = argparse.ArgumentParser(prog="brain")
    p.add_argument("--city", default="Bangalore")
    p.add_argument("--max-steps", type=int, default=70)
    p.add_argument("--out", default="data_brain")
    a = p.parse_args()
    out = Path(a.out)
    meta = agent.run(a.city, a.max_steps, out)
    print(json.dumps(meta, indent=1, ensure_ascii=False))
    report(out)
    print(f"\nreport: {out / 'REPORT.md'}")


if __name__ == "__main__":
    main()
