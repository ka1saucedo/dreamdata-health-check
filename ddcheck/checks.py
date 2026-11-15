"""The 11 onboarding checks.

Every check is read-only. Report configs are built only from metric/property ids that
``report_builder_get_components`` returns for the workspace, looked up by label.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from .client import DreamdataClient, ToolError
from .site import SiteResult, check_site

PASS, WAITING, CHECK, TODO, FIX, BLOCKER, SKIPPED = (
    "PASS", "WAITING", "CHECK", "TODO", "FIX", "BLOCKER", "SKIPPED",
)
SEVERITY = {BLOCKER: 0, FIX: 1, CHECK: 2, WAITING: 3, TODO: 4, SKIPPED: 5, PASS: 6}

ENGAGEMENT = "touchpoint_activity_performance"
NON_PROD_HOST = re.compile(
    r"(\.netlify\.app$|\.vercel\.app$|\.pages\.dev$|\.herokuapp\.com$|^localhost|^127\.0\.0\.1"
    r"|^(staging|stage|preview|dev|test|qa)[.-])",
    re.I,
)
EMAIL_DOMAIN_SLUG = re.compile(r"_(edu|com|net|org|io|co|ac_[a-z]{2})$|gmail|outlook|hotmail|yahoo", re.I)


@dataclass
class Check:
    id: int
    name: str
    status: str
    result: str
    next_step: str = ""
    engineer: str = ""
    owner: str = ""


@dataclass
class Report:
    slug: str
    name: str
    run_at: str
    domain: str | None
    checks: list[Check] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        statuses = {c.status for c in self.checks}
        if BLOCKER in statuses:
            return "Blocked"
        if FIX in statuses:
            return "Needs fixes"
        if WAITING in statuses:
            return "Waiting on data"
        return "Ready for handoff"

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.checks:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["verdict"] = self.verdict
        return d


# ---------------------------------------------------------------- helpers

def _section_items(resp: dict, section_id: str) -> list[dict]:
    for s in resp.get("sections", []):
        if s.get("id") == section_id:
            return s.get("items", [])
    return []


class Components:
    """Label -> id lookup built from a report_builder_get_components response."""

    def __init__(self, *responses: dict):
        self.metrics: dict[str, tuple[str, str]] = {}
        self.properties: dict[str, tuple[str, str]] = {}
        self.metric_groups: list[dict] = []
        for resp in responses:
            self.metric_groups = resp.get("metric_groups", self.metric_groups)
            for m in _section_items(resp, "metrics"):
                self.metrics.setdefault(m["label"], (m["internal"]["id"], m["internal"]["group_key"]))
            for p in _section_items(resp, "properties"):
                self.properties.setdefault(p["label"], (p["internal"]["id"], p["internal"]["scope_key"]))

    def metric_block(self, *labels: str) -> dict:
        block: dict[str, dict] = {}
        for label in labels:
            if label in self.metrics:
                mid, group = self.metrics[label]
                block.setdefault(group, {"metricIds": []})["metricIds"].append(mid)
        return block

    def segment(self, label: str) -> dict | None:
        if label not in self.properties:
            return None
        pid, scope = self.properties[label]
        return {"scope": scope, "propertyId": pid}

    def stage_groups(self) -> list[dict]:
        return [g for g in self.metric_groups if str(g.get("metric_group", "")).startswith("stageMetrics.")]


def records(resp: dict) -> list[dict]:
    """Normalise report rows to dicts keyed by column label (handles dict or list rows)."""
    cols = resp.get("columns", [])
    ids = [c["id"] for c in cols]
    labels = [c["label"] for c in cols]
    out = []
    for row in resp.get("data", []) or []:
        if isinstance(row, dict):
            source = row.get("values") if isinstance(row.get("values"), dict) else row
            out.append({lab: source.get(cid, source.get(lab)) for cid, lab in zip(ids, labels)})
        elif isinstance(row, (list, tuple)):
            out.append(dict(zip(labels, row)))
    return out


def total(rows: list[dict], label: str) -> float:
    s = 0.0
    for r in rows:
        v = r.get(label)
        if isinstance(v, dict):
            v = v.get("value")
        try:
            s += float(v or 0)
        except (TypeError, ValueError):
            pass
    return s


def _n(x: float) -> str:
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.1f}"


def _zero_status(setup_hours: float | None) -> tuple[str, str]:
    if setup_hours is not None and setup_hours >= 24:
        return FIX, "Setup is over 24h old, so this is no longer a modeling delay."
    return WAITING, "Expected inside the first 24h while Dreamdata models new data."


def _engagement_config(components: Components, time_value: str, segments: list[str], metrics: list[str]) -> dict:
    segs = [s for s in (components.segment(l) for l in segments) if s]
    block = components.metric_block(*metrics)
    first_metric = next(iter(block.values()))["metricIds"][0] if block else None
    cfg = {
        "report": {"analysisType": ENGAGEMENT, "analysisSubjectType": "touchpoint", "analysisSubjectId": "touchpoint"},
        "time": {"value": time_value, "timeAggregation": "day"},
        "segmentBy": segs,
        "metrics": block,
    }
    if first_metric:
        cfg["orderBy"] = {"metricId": first_metric, "orderingType": "descending"}
    return cfg


async def _safe(coro: Awaitable[dict]) -> tuple[dict | None, str | None]:
    try:
        return await coro, None
    except ToolError as exc:
        return None, str(exc)
    except Exception as exc:  # network or protocol errors: report, don't crash the whole run
        return None, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- main entry

SiteChecker = Callable[[str], Awaitable[SiteResult]]


async def run_checks(
    client: DreamdataClient,
    slug: str | None = None,
    domain: str | None = None,
    setup_hours: float | None = None,
    site_checker: SiteChecker = check_site,
    now: datetime | None = None,
) -> Report:
    now = now or datetime.now().astimezone()

    accounts_resp = await client.call("list_my_accounts")
    accounts = accounts_resp.get("accounts", [])
    if slug is None:
        if len(accounts) != 1:
            raise ToolError(f"{len(accounts)} workspaces available; pass --workspace (one of: "
                            + ", ".join(a["slug"] for a in accounts) + ")")
        slug = accounts[0]["slug"]
    account = next((a for a in accounts if a["slug"] == slug), None)
    name = account["name"] if account else slug
    report = Report(slug=slug, name=name, run_at=now.isoformat(timespec="minutes"), domain=domain)
    add = report.checks.append

    # 1 identity ----------------------------------------------------------
    if account is None:
        add(Check(1, "Workspace access and identity", FIX, f"No access to workspace '{slug}'",
                  "Get access to the workspace, or check the slug", owner="Dreamdata"))
    elif EMAIL_DOMAIN_SLUG.search(slug):
        add(Check(1, "Workspace access and identity", FIX,
                  f'Reachable as "{name}", but the slug "{slug}" looks like it came from a signup email domain',
                  "Rename the workspace slug and confirm company size and industry in settings",
                  f'Slug "{slug}" doesn\'t match the customer name "{name}". It shows up in MCP calls and URLs.',
                  owner="Dreamdata"))
    else:
        add(Check(1, "Workspace access and identity", PASS, f'Reachable as "{name}" ({slug})'))

    # 2 currency ------------------------------------------------------------
    cur, err = await _safe(client.call("get_account_currency", slug=slug))
    currency = (cur or {}).get("currency")
    if err:
        add(Check(2, "Currency", CHECK, f"Couldn't read currency: {err}", "Re-run", owner="Dreamdata"))
    elif not currency:
        add(Check(2, "Currency", FIX, "No currency set", "Set the account currency",
                  "Revenue and ROI figures will have no currency label.", owner="Customer"))
    else:
        add(Check(2, "Currency", PASS, str(currency.get("code", "")).upper()))

    # components (ids looked up by label, never hard-coded) ----------------
    comp_a, err_a = await _safe(client.call("report_builder_get_components", slug=slug, analysis_type=ENGAGEMENT,
                                            analysis_subject_id="touchpoint", metric_group="activityCountMetrics"))
    comp_s, _ = await _safe(client.call("report_builder_get_components", slug=slug, analysis_type=ENGAGEMENT,
                                        analysis_subject_id="touchpoint", metric_group="signalCountMetrics"))
    comps = Components(*(c for c in (comp_a, comp_s) if c))

    activity_rows: list[dict] = []
    activity_err = err_a
    if comp_a:
        cfg = _engagement_config(comps, "last_7_days", ["Host", "Event Name"],
                                 ["Events", "Sessions", "Visitors", "Contacts", "Companies", "Page Views"])
        resp, activity_err = await _safe(client.call("report_builder_run_config", slug=slug, config=cfg,
                                                     output_type="summary_table"))
        activity_rows = records(resp) if resp else []
    events = total(activity_rows, "Events")
    visitors = total(activity_rows, "Visitors")
    contacts = total(activity_rows, "Contacts")
    report.totals.update(events_7d=events, visitors_7d=visitors, contacts_7d=contacts)

    # 3 tracker on site -----------------------------------------------------
    site: SiteResult | None = None
    if not domain:
        add(Check(3, "Tracker on live site", SKIPPED, "No domain given",
                  "Re-run with --domain, or check the Tracking Debugger", owner="Dreamdata"))
    else:
        site = await site_checker(domain)
        if site.error:
            add(Check(3, "Tracker on live site", CHECK, f"Couldn't load {domain}: {site.error}",
                      "Check the domain, then the Tracking Debugger", owner="Dreamdata"))
        elif site.dreamdata_found:
            add(Check(3, "Tracker on live site", PASS, f"Dreamdata script found in the page HTML of {site.final_url}"))
        elif site.gtm_found:
            add(Check(3, "Tracker on live site", CHECK,
                      f"No Dreamdata script in the HTML of {domain}, but Google Tag Manager is present",
                      "Confirm the Dreamdata tag fires in GTM preview and the Tracking Debugger",
                      "The tracker may load through GTM, which a plain HTML fetch can't see.", owner="Customer"))
        else:
            add(Check(3, "Tracker on live site", CHECK,
                      f"No Dreamdata script or GTM found in the HTML of {domain}",
                      "Confirm the install in the Tracking Debugger",
                      "Not in the server-rendered HTML. It may be injected client-side; if the debugger shows "
                      "nothing, the tracker isn't installed.", owner="Customer"))

    # 4 events in the model -------------------------------------------------
    if activity_err:
        add(Check(4, "Events in the model (7 days)", CHECK, f"Report failed: {activity_err}", "Re-run", owner="Dreamdata"))
    elif events == 0:
        status, why = _zero_status(setup_hours)
        hint = " The tracker is on the site, so this points to a modeling delay, not a broken install." \
            if (site and site.dreamdata_found and status == WAITING) else ""
        add(Check(4, "Events in the model (7 days)", status, "0 events, 0 sessions, 0 visitors",
                  "Re-run after the 24h modeling window" if status == WAITING else "Open a ticket: tracker live but no events",
                  why + hint, owner="Dreamdata"))
    else:
        add(Check(4, "Events in the model (7 days)", PASS,
                  f"{_n(events)} events, {_n(total(activity_rows, 'Sessions'))} sessions, {_n(visitors)} visitors"))

    # 5 non-production hosts -----------------------------------------------
    if events == 0:
        add(Check(5, "Non-production traffic", WAITING, "No events yet, so hosts can't be checked",
                  "Re-run once events land", owner="Dreamdata"))
    else:
        host_events: dict[str, float] = {}
        for r in activity_rows:
            h = str(r.get("Host") or "")
            host_events[h] = host_events.get(h, 0) + total([r], "Events")
        bad = {h: n for h, n in host_events.items() if h and NON_PROD_HOST.search(h)}
        if bad:
            share = sum(bad.values()) / events * 100
            listing = ", ".join(f"{h} ({_n(n)})" for h, n in sorted(bad.items(), key=lambda x: -x[1]))
            add(Check(5, "Non-production traffic", FIX, f"{share:.0f}% of events come from non-production hosts: {listing}",
                      "Exclude these hosts in tracking settings",
                      "Preview and staging traffic inflates visitor counts and can trigger signals.", owner="Customer"))
        else:
            add(Check(5, "Non-production traffic", PASS, f"{len(host_events)} host(s), none look like staging or previews"))

    # 6 visitors -> contacts -----------------------------------------------
    if visitors == 0:
        add(Check(6, "Visitors becoming known contacts", WAITING, "0 visitors, 0 contacts",
                  "Re-run; then confirm form submits fire identify calls", owner="Customer"))
    elif contacts == 0:
        add(Check(6, "Visitors becoming known contacts", FIX, f"{_n(visitors)} visitors, 0 known contacts",
                  "Check form tracking and identify calls",
                  "Every visitor is anonymous. Confirm form submits send identify with the email.", owner="Customer"))
    else:
        add(Check(6, "Visitors becoming known contacts", PASS,
                  f"{_n(contacts)} contacts from {_n(visitors)} visitors ({contacts / visitors * 100:.1f}%)"))

    # 7 ad platform data ------------------------------------------------------
    if comp_a:
        cfg = _engagement_config(comps, "last_30_days", ["Channel"],
                                 ["Events", "Sessions", "Visitors", "Companies", "Impressions"])
        resp, err = await _safe(client.call("report_builder_run_config", slug=slug, config=cfg, output_type="summary_table"))
        if err:
            add(Check(7, "Ad platform data (30 days)", CHECK, f"Report failed: {err}", "Re-run", owner="Dreamdata"))
        else:
            rows = records(resp)
            imps = total(rows, "Impressions")
            channels = [str(r.get("Channel")) for r in rows if r.get("Channel")]
            report.totals.update(impressions_30d=imps, channels_30d=channels)
            if imps == 0:
                add(Check(7, "Ad platform data (30 days)", CHECK, "0 ad impressions",
                          "If an ad platform is connected, confirm it has live campaigns, then check the connection",
                          "No impression data at all. Either no active campaigns or the ad connection isn't syncing.",
                          owner="Customer"))
            else:
                add(Check(7, "Ad platform data (30 days)", PASS,
                          f"{_n(imps)} impressions across {len(channels)} channel(s)"))
    else:
        add(Check(7, "Ad platform data (30 days)", CHECK, "Report components unavailable", "Re-run", owner="Dreamdata"))

    # 8 companies ---------------------------------------------------------------
    comp_resp, err = await _safe(client.call("search_companies", slug=slug, query="a"))
    companies = (comp_resp or {}).get("items", [])
    if err:
        add(Check(8, "Companies resolving", CHECK, f"Search failed: {err}", "Re-run", owner="Dreamdata"))
    elif not companies:
        status, why = _zero_status(setup_hours)
        add(Check(8, "Companies resolving", status, "0 companies", "Re-run after modeling", why, owner="Dreamdata"))
    else:
        add(Check(8, "Companies resolving", PASS, f"{len(companies)}+ companies found (first page)"))

    # 9 pipeline stages -------------------------------------------------------
    subj, err = await _safe(client.call("report_builder_list_subjects", slug=slug, analysis_type="stage_reporting"))
    stages = _section_items(subj or {}, "analysis_subjects")
    if err:
        add(Check(9, "Pipeline stages", CHECK, f"Couldn't list stages: {err}", "Re-run", owner="Dreamdata"))
    elif not stages:
        add(Check(9, "Pipeline stages", BLOCKER, "No pipeline stages available",
                  "Confirm the CRM has deals with stages, then map stages in Dreamdata",
                  "With no stages, attribution has no outcome to credit, so every attribution report is empty.",
                  owner="Customer + Dreamdata"))
    else:
        add(Check(9, "Pipeline stages", PASS, ", ".join(s.get("label", "?") for s in stages)))

    # 10 signals ----------------------------------------------------------------
    if "Signal Count" in comps.metrics and comps.segment("Signal Name"):
        cfg = _engagement_config(comps, "last_30_days", ["Signal Name"], ["Signal Count"])
        resp, err = await _safe(client.call("report_builder_run_config", slug=slug, config=cfg, output_type="summary_table"))
        rows = records(resp) if resp else []
        if err:
            add(Check(10, "Signals firing (30 days)", CHECK, f"Report failed: {err}", "Re-run", owner="Dreamdata"))
        elif rows:
            listing = ", ".join(f"{r.get('Signal Name')} ({_n(total([r], 'Signal Count'))})" for r in rows[:5])
            add(Check(10, "Signals firing (30 days)", PASS, listing))
        else:
            status = WAITING if events == 0 else TODO
            add(Check(10, "Signals firing (30 days)", status, "0 signal hits",
                      "Once events land, confirm at least one high-intent signal (pricing, booking or demo page) fires",
                      "The MCP shows signal hits, not signal definitions, so check the Signals page for what's set up.",
                      owner="Dreamdata"))
    else:
        add(Check(10, "Signals firing (30 days)", CHECK, "Signal metrics unavailable", "Re-run", owner="Dreamdata"))

    # 11 audiences and saved reports -------------------------------------------
    aud, err1 = await _safe(client.call("list_audiences", slug=slug))
    rep, err2 = await _safe(client.call("list_saved_reports", slug=slug))
    n_aud, n_rep = len((aud or {}).get("items", [])), len((rep or {}).get("items", []))
    if err1 or err2:
        add(Check(11, "Audiences and saved reports", CHECK, f"Couldn't list: {err1 or err2}", "Re-run", owner="Dreamdata"))
    elif n_aud == 0 or n_rep == 0:
        add(Check(11, "Audiences and saved reports", TODO, f"{n_aud} audiences, {n_rep} saved reports",
                  "Build a 'hot accounts' audience and a channel-to-pipeline report once data lands",
                  owner="Dreamdata"))
    else:
        add(Check(11, "Audiences and saved reports", PASS, f"{n_aud} audiences, {n_rep} saved reports"))

    report.checks.sort(key=lambda c: c.id)
    return report
