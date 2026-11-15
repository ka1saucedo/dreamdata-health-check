# Dreamdata health check: 'Iwa Media

**Verdict: Blocked** · workspace `ucsd_edu` · run Nov 14, 2026 21:20 UTC-10:00 · site iwamedia.com

| # | Check | Status | Result | Next step |
|---|---|---|---|---|
| 1 | Workspace access and identity | **FIX** | Reachable as "'Iwa Media", but the slug "ucsd_edu" looks like it came from a signup email domain | Rename the workspace slug and confirm company size and industry in settings |
| 2 | Currency | **PASS** | USD | - |
| 3 | Tracker on live site | **PASS** | Dreamdata script found in the page HTML of https://iwamedia.com/ | - |
| 4 | Events in the model (7 days) | **WAITING** | 0 events, 0 sessions, 0 visitors | Re-run after the 24h modeling window |
| 5 | Non-production traffic | **WAITING** | No events yet, so hosts can't be checked | Re-run once events land |
| 6 | Visitors becoming known contacts | **WAITING** | 0 visitors, 0 contacts | Re-run; then confirm form submits fire identify calls |
| 7 | Ad platform data (30 days) | **CHECK** | 0 ad impressions | If an ad platform is connected, confirm it has live campaigns, then check the connection |
| 8 | Companies resolving | **WAITING** | 0 companies | Re-run after modeling |
| 9 | Pipeline stages | **BLOCKER** | No pipeline stages available | Confirm the CRM has deals with stages, then map stages in Dreamdata |
| 10 | Signals firing (30 days) | **WAITING** | 0 signal hits | Once events land, confirm at least one high-intent signal (pricing, booking or demo page) fires |
| 11 | Audiences and saved reports | **TODO** | 0 audiences, 0 saved reports | Build a 'hot accounts' audience and a channel-to-pipeline report once data lands |

## For the exec

Your website tracking is installed. Some data is still processing, so parts of this report will fill in within a day. One thing blocks the main question, which marketing drives revenue: your deal stages aren't set up in Dreamdata yet. There is 1 setup fix to make before handoff. Next check: Nov 16.

## For the engineer

- [BLOCKER] Pipeline stages: No pipeline stages available. With no stages, attribution has no outcome to credit, so every attribution report is empty. Next: Confirm the CRM has deals with stages, then map stages in Dreamdata.
- [FIX] Workspace access and identity: Reachable as "'Iwa Media", but the slug "ucsd_edu" looks like it came from a signup email domain. Slug "ucsd_edu" doesn't match the customer name "'Iwa Media". It shows up in MCP calls and URLs. Next: Rename the workspace slug and confirm company size and industry in settings.
- [CHECK] Ad platform data (30 days): 0 ad impressions. No impression data at all. Either no active campaigns or the ad connection isn't syncing. Next: If an ad platform is connected, confirm it has live campaigns, then check the connection.
- [WAITING] Events in the model (7 days): 0 events, 0 sessions, 0 visitors. Expected inside the first 24h while Dreamdata models new data. The tracker is on the site, so this points to a modeling delay, not a broken install. Next: Re-run after the 24h modeling window.
- [WAITING] Non-production traffic: No events yet, so hosts can't be checked. Next: Re-run once events land.
- [WAITING] Visitors becoming known contacts: 0 visitors, 0 contacts. Next: Re-run; then confirm form submits fire identify calls.
- [WAITING] Companies resolving: 0 companies. Expected inside the first 24h while Dreamdata models new data. Next: Re-run after modeling.
- [WAITING] Signals firing (30 days): 0 signal hits. The MCP shows signal hits, not signal definitions, so check the Signals page for what's set up. Next: Once events land, confirm at least one high-intent signal (pricing, booking or demo page) fires.
- [TODO] Audiences and saved reports: 0 audiences, 0 saved reports. Next: Build a 'hot accounts' audience and a channel-to-pipeline report once data lands.

## Handoff checklist

| Item | Owner | Re-run by |
|---|---|---|
| Confirm the CRM has deals with stages, then map stages in Dreamdata | Customer + Dreamdata | 2026-11-16 |
| Rename the workspace slug and confirm company size and industry in settings | Dreamdata | 2026-11-16 |
| If an ad platform is connected, confirm it has live campaigns, then check the connection | Customer | 2026-11-16 |
| Build a 'hot accounts' audience and a channel-to-pipeline report once data lands | Dreamdata | 2026-11-16 |
| Re-run ddcheck once data is modeled (checks 4, 5, 6, 8, 10) | Dreamdata | 2026-11-16 |

_Read-only check via the Dreamdata MCP. Results are exactly as returned; nothing is estimated._
