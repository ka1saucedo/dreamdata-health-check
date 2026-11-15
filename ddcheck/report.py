"""Render a health check Report as Markdown, HTML or JSON, with engineer and exec versions."""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta

from .checks import BLOCKER, CHECK, FIX, PASS, SEVERITY, SKIPPED, TODO, WAITING, Report  # noqa: F401

COLORS = {
    PASS: "#1f7a4d", WAITING: "#8a6d1f", CHECK: "#7a4d1f", TODO: "#4d5b7a",
    FIX: "#a8321f", BLOCKER: "#7a1f3d", SKIPPED: "#666666",
}


def _check(report: Report, cid: int):
    return next((c for c in report.checks if c.id == cid), None)


def _run_date(report: Report) -> datetime:
    return datetime.fromisoformat(report.run_at)


def exec_summary(report: Report) -> list[str]:
    """Three to five plain-English sentences for the exec sponsor. No jargon, no ids."""
    s: list[str] = []
    site, events, stages = _check(report, 3), _check(report, 4), _check(report, 9)
    if events and events.status == PASS:
        s.append("Website data is flowing into Dreamdata.")
    elif site and site.status == PASS:
        s.append("Your website tracking is installed.")
    if any(c.status == WAITING for c in report.checks):
        s.append("Some data is still processing, so parts of this report will fill in within a day.")
    if stages and stages.status == BLOCKER:
        s.append("One thing blocks the main question, which marketing drives revenue: "
                 "your deal stages aren't set up in Dreamdata yet.")
    fixes = [c for c in report.checks if c.status == FIX]
    if fixes:
        s.append(f"There {'is' if len(fixes) == 1 else 'are'} {len(fixes)} setup "
                 f"fix{'es' if len(fixes) != 1 else ''} to make before handoff.")
    if report.verdict == "Ready for handoff":
        s.append("Setup looks healthy and is ready for training and handoff.")
    nxt = (_run_date(report) + timedelta(days=2)).strftime("%b %-d")
    s.append(f"Next check: {nxt}.")
    return s


def engineer_items(report: Report) -> list[str]:
    items = []
    for c in sorted(report.checks, key=lambda c: (SEVERITY[c.status], c.id)):
        if c.status == PASS:
            continue
        detail = f" {c.engineer}" if c.engineer else ""
        items.append(f"[{c.status}] {c.name}: {c.result}.{detail} Next: {c.next_step}.")
    return items


def checklist(report: Report) -> list[tuple[str, str, str]]:
    nxt = (_run_date(report) + timedelta(days=2)).strftime("%Y-%m-%d")
    out, waiting = [], []
    for c in sorted(report.checks, key=lambda c: (SEVERITY[c.status], c.id)):
        if c.status == PASS:
            continue
        if c.status == WAITING:
            waiting.append(str(c.id))
            continue
        out.append((c.next_step, c.owner or "Dreamdata", nxt))
    if waiting:
        out.append((f"Re-run ddcheck once data is modeled (checks {', '.join(waiting)})", "Dreamdata", nxt))
    return out


def _md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(report: Report) -> str:
    when = _run_date(report).strftime("%b %-d, %Y %H:%M %Z").strip()
    lines = [
        f"# Dreamdata health check: {report.name}",
        "",
        f"**Verdict: {report.verdict}** · workspace `{report.slug}` · run {when}"
        + (f" · site {report.domain}" if report.domain else ""),
        "",
        "| # | Check | Status | Result | Next step |",
        "|---|---|---|---|---|",
    ]
    for c in report.checks:
        lines.append(f"| {c.id} | {_md_cell(c.name)} | **{c.status}** | {_md_cell(c.result)} | {_md_cell(c.next_step or '-')} |")
    lines += ["", "## For the exec", "", " ".join(exec_summary(report)), "", "## For the engineer", ""]
    lines += [f"- {i}" for i in engineer_items(report)] or ["- Nothing to fix."]
    lines += ["", "## Handoff checklist", "", "| Item | Owner | Re-run by |", "|---|---|---|"]
    lines += [f"| {_md_cell(a)} | {b} | {d} |" for a, b, d in checklist(report)]
    lines += ["", "_Read-only check via the Dreamdata MCP. Results are exactly as returned; nothing is estimated._", ""]
    return "\n".join(lines)


def to_json(report: Report) -> str:
    d = report.to_dict()
    d["exec_summary"] = exec_summary(report)
    return json.dumps(d, indent=2)


CSS = """
body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;color:#1d1d1f;max-width:1040px;margin:40px auto;padding:0 24px;background:#fbfaf7}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px}
.meta{color:#666;margin-bottom:20px}.verdict{display:inline-block;padding:4px 10px;border-radius:6px;color:#fff;font-weight:600}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e6e3dc;border-radius:8px;overflow:hidden}
th,td{padding:9px 12px;border-bottom:1px solid #eeebe4;text-align:left;vertical-align:top}th{background:#f4f2ec;font-size:13px;color:#555}
.pill{display:inline-block;min-width:68px;text-align:center;padding:2px 8px;border-radius:999px;color:#fff;font-size:12px;font-weight:600}
.exec{background:#fff;border:1px solid #e6e3dc;border-radius:8px;padding:14px 18px}
li{margin:4px 0}footer{color:#888;font-size:13px;margin:28px 0}
"""


def to_html(report: Report) -> str:
    e = html.escape
    verdict_color = {"Blocked": COLORS[BLOCKER], "Needs fixes": COLORS[FIX],
                     "Waiting on data": COLORS[WAITING]}.get(report.verdict, COLORS[PASS])
    rows = "".join(
        f"<tr><td>{c.id}</td><td>{e(c.name)}</td>"
        f"<td><span class='pill' style='background:{COLORS[c.status]}'>{c.status}</span></td>"
        f"<td>{e(c.result)}</td><td>{e(c.next_step or '-')}</td></tr>"
        for c in report.checks
    )
    eng = "".join(f"<li>{e(i)}</li>" for i in engineer_items(report)) or "<li>Nothing to fix.</li>"
    chk = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{d}</td></tr>" for a, b, d in checklist(report))
    when = _run_date(report).strftime("%b %-d, %Y %H:%M %Z").strip()
    site = f" · site {e(report.domain)}" if report.domain else ""
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Health check: {e(report.name)}</title>
<style>{CSS}</style></head><body>
<h1>Dreamdata health check: {e(report.name)}</h1>
<div class="meta"><span class="verdict" style="background:{verdict_color}">{report.verdict}</span>
&nbsp; workspace <code>{e(report.slug)}</code> · run {when}{site}</div>
<table><tr><th>#</th><th>Check</th><th>Status</th><th>Result</th><th>Next step</th></tr>{rows}</table>
<h2>For the exec</h2><div class="exec">{e(' '.join(exec_summary(report)))}</div>
<h2>For the engineer</h2><ul>{eng}</ul>
<h2>Handoff checklist</h2><table><tr><th>Item</th><th>Owner</th><th>Re-run by</th></tr>{chk}</table>
<footer>Read-only check via the Dreamdata MCP. Results are exactly as returned; nothing is estimated.</footer>
</body></html>"""


def fleet_markdown(reports: list[Report], errors: dict[str, str]) -> str:
    order = {"Blocked": 0, "Needs fixes": 1, "Waiting on data": 2, "Ready for handoff": 3}
    lines = ["# Dreamdata onboarding fleet view", "",
             "| Workspace | Verdict | Blockers | Fixes | Waiting | Top issue |", "|---|---|---|---|---|---|"]
    for r in sorted(reports, key=lambda r: (order[r.verdict], r.name.lower())):
        n = r.counts()
        top = next((c for c in sorted(r.checks, key=lambda c: (SEVERITY[c.status], c.id)) if c.status != PASS), None)
        top_txt = f"{top.name}: {top.result}" if top else "-"
        lines.append(f"| {_md_cell(r.name)} (`{r.slug}`) | **{r.verdict}** | {n.get(BLOCKER, 0)} | {n.get(FIX, 0)} "
                     f"| {n.get(WAITING, 0)} | {_md_cell(top_txt)} |")
    for slug, err in errors.items():
        lines.append(f"| `{slug}` | **Error** | - | - | - | {_md_cell(err)} |")
    lines.append("")
    return "\n".join(lines)
