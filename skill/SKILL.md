---
name: dreamdata-health-check
description: Run a read-only setup health check on a Dreamdata workspace through the Dreamdata MCP and write a handoff report in two versions, one for an engineer and one for an executive. Use when onboarding a new Dreamdata customer, before a kickoff or training call, or when a customer says "the numbers look off".
---

# Dreamdata Setup Health Check

Purpose: before an onboarding handoff, confirm that a customer's Dreamdata workspace is actually producing usable data, and give both the technical owner and the exec sponsor a clear list of what to fix.

This skill is **read-only**. Never call `save_audience`, `report_builder_save_report` or `create_dashboard`. If a fix needs a write, put it in the checklist for a human.

## Inputs
- The workspace to check. If the user doesn't name one, call `list_my_accounts`; if there's exactly one, use it.
- Optional: the customer's production website domain (needed for checks 3 and 5).

## Checks (run in this order)

| # | Check | How | Status rules |
|---|---|---|---|
| 1 | Workspace access and identity | `list_my_accounts` | FIX if the slug or name doesn't match the customer (e.g. a slug taken from a personal or .edu email domain) |
| 2 | Currency set | `get_account_currency` | FIX if `currency` is null; revenue and ROI figures will be unlabeled |
| 3 | Tracker live on the production site | If a browser tool is available: load the domain, confirm the Dreamdata script loads and a page call is sent. Otherwise mark SKIPPED and ask the customer to check the Tracking Debugger | FIX if the script is missing or no call is sent |
| 4 | Events reaching the model | Report builder, Analyze Engagement, last 7 days, metrics Events / Sessions / Visitors / Contacts / Companies / Page Views, segmented by Host and Event Name | WAITING if 0 and setup is under 24h old (modeling delay); FIX if 0 after 24h while check 3 passed |
| 5 | Non-production traffic | From check 4's Host breakdown, flag any host that isn't the production domain (`*.netlify.app`, `*.vercel.app`, `localhost`, `staging.*`, `preview.*`, `dev.*`) | FIX if any non-production host has events; it inflates visitor and engagement numbers |
| 6 | Visitors becoming known contacts | From check 4: Contacts vs Visitors, plus any form or identify-type events in the Event Name breakdown | FIX if Visitors > 0 but Contacts = 0 after a week; form tracking or identify calls likely missing |
| 7 | Ad platform data | Analyze Engagement, last 30 days, segmented by Channel, metrics Events / Sessions / Impressions | CHECK if an ad platform is connected but Impressions = 0: confirm the account has live campaigns, then check the connection |
| 8 | Companies resolving | `search_companies` with a broad query | WAITING if empty during the first 24h; FIX after |
| 9 | Pipeline stages | `report_builder_list_subjects(analysis_type="stage_reporting")` | BLOCKER if no subjects come back: with no stages, attribution has no outcome to credit. Check that the CRM has deals and that stages are configured |
| 10 | Signals configured | `report_builder_get_components` on Analyze Engagement and look at the Signal Metrics group | TODO if there are no signals; suggest one high-intent signal (pricing, booking or demo page) |
| 11 | Audiences and saved reports | `list_audiences`, `list_saved_reports` | TODO if empty; expected for a new workspace, but list the first audience and first report to build |

Build every report config only from ids that `report_builder_get_components` returns. Never invent ids, and never show ids to the reader.

## Output

Write three sections:

1. **Status table**: one row per check, with Status (PASS / WAITING / CHECK / TODO / FIX / BLOCKER), the actual result, and a one-line next step. Include the date and time of the run, and state results exactly as returned. Never estimate numbers.
2. **Engineer version**: what's broken, where, and the exact fix (e.g. "No identify events: confirm form tracking is enabled and the form submit fires `identify` with the email").
3. **Exec version**: three to five plain-English sentences. What's working, what's blocking "which marketing drives revenue," what happens next, and by when. No jargon.

End with a **handoff checklist** of open items, each with an owner (customer or Dreamdata) and a re-run date for this check.
