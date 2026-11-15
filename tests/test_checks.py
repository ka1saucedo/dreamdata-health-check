import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from ddcheck.checks import BLOCKER, CHECK, FIX, PASS, TODO, WAITING, NON_PROD_HOST, records, run_checks
from ddcheck.client import FixtureClient, ToolError, fixture_key, parse_tool_result
from ddcheck.site import SiteResult, scan_html

FIXTURE = Path(__file__).parent / "fixtures" / "iwa_media_2026-11-14.json"
NOW = datetime.fromisoformat("2026-11-14T21:20:00-10:00")


async def site_ok(domain):
    return SiteResult(domain=domain, final_url=f"https://{domain}/", dreamdata_found=True)


def statuses(report):
    return {c.id: c.status for c in report.checks}


# ------------------------------------------------------------ recorded real run

@pytest.mark.anyio
async def test_recorded_iwa_media_run():
    report = await run_checks(FixtureClient(FIXTURE), domain="iwamedia.com", site_checker=site_ok, now=NOW)
    assert report.slug == "ucsd_edu"
    assert statuses(report) == {
        1: FIX, 2: PASS, 3: PASS, 4: WAITING, 5: WAITING, 6: WAITING,
        7: CHECK, 8: WAITING, 9: BLOCKER, 10: WAITING, 11: TODO,
    }
    assert report.verdict == "Blocked"
    four = next(c for c in report.checks if c.id == 4)
    assert "modeling delay, not a broken install" in four.engineer


@pytest.mark.anyio
async def test_zero_data_after_24h_becomes_fix():
    report = await run_checks(FixtureClient(FIXTURE), setup_hours=48, now=NOW)
    s = statuses(report)
    assert s[4] == FIX and s[8] == FIX and s[3] == "SKIPPED"


# ------------------------------------------------------------ populated workspace (synthetic test data)

class PopulatedClient(FixtureClient):
    """The recorded workspace, with synthetic rows added so the 'data present' branches get exercised."""

    def __init__(self, path, activity_rows, channel_rows, signal_rows):
        super().__init__(path)
        self.tools = copy.deepcopy(self.tools)
        self.tools["report_builder_run_config:last_7_days:p_xhnuvdkst4iyda4,p_xj5qpbq6pm8wzu5"]["data"] = activity_rows
        self.tools["report_builder_run_config:last_30_days:p_y54efhqz2gmhgdf"]["data"] = channel_rows
        self.tools["report_builder_run_config:last_30_days:p_v76webpv65pzquq"]["data"] = signal_rows
        self.tools["search_companies"] = {"items": [{"id": "c1"}, {"id": "c2"}]}
        self.tools["report_builder_list_subjects:stage_reporting"]["sections"][0]["items"] = [
            {"label": "SQL", "internal": {"analysis_subject_id": "s1"}}]


@pytest.mark.anyio
async def test_preview_traffic_and_missing_identify_are_flagged():
    # Host, Event Name, Events, Sessions, Visitors, Contacts, Companies, Page Views
    activity = [
        ["example.com", "page", 120, 40, 30, 0, 5, 120],
        ["deploy-preview-12--example.netlify.app", "page", 80, 10, 4, 0, 1, 80],
    ]
    channels = [{"p_y54efhqz2gmhgdf": "Paid Social", "m_y9avyqx9vwfcz6c": 5400}]
    signals = [["High Intent: Booking Page", 3]]
    client = PopulatedClient(FIXTURE, activity, channels, signals)
    report = await run_checks(client, now=NOW)
    s = statuses(report)
    assert s[4] == PASS and s[5] == FIX and s[6] == FIX
    assert s[7] == PASS and s[8] == PASS and s[9] == PASS and s[10] == PASS
    five = next(c for c in report.checks if c.id == 5)
    assert "40%" in five.result and "netlify.app" in five.result
    assert report.verdict == "Needs fixes"


# ------------------------------------------------------------ units

def test_records_handles_dict_and_list_rows():
    resp = {"columns": [{"id": "p1", "label": "Host"}, {"id": "m1", "label": "Events"}],
            "data": [{"p1": "a.com", "m1": 3}, ["b.com", 4], {"values": {"p1": "c.com", "m1": 5}}]}
    assert records(resp) == [{"Host": "a.com", "Events": 3}, {"Host": "b.com", "Events": 4},
                             {"Host": "c.com", "Events": 5}]


@pytest.mark.parametrize("host,bad", [
    ("site--abc.netlify.app", True), ("my-app.vercel.app", True), ("staging.acme.com", True),
    ("localhost:3000", True), ("acme.com", False), ("www.devonshire.com", False),
])
def test_non_prod_hosts(host, bad):
    assert bool(NON_PROD_HOST.search(host)) is bad


def test_scan_html():
    r = scan_html("x.com", '<script src="https://cdn.dreamdata.cloud/scripts/analytics/next/dreamdata.min.js">')
    assert r.dreamdata_found and not r.gtm_found
    assert scan_html("x.com", "<script>(function(w,d){})(window,'GTM-AB12CD')</script>").gtm_found


def test_fixture_key_is_stable():
    cfg = {"time": {"value": "last_30_days"}, "segmentBy": [{"propertyId": "p_a"}, {"propertyId": "p_b"}]}
    assert fixture_key("report_builder_run_config", {"config": cfg}) == "report_builder_run_config:last_30_days:p_a,p_b"


class _Block:
    def __init__(self, text):
        self.text = text


class _Result:
    def __init__(self, text=None, structured=None, error=False):
        self.content = [_Block(text)] if text else []
        self.structuredContent = structured
        self.isError = error


def test_parse_tool_result():
    assert parse_tool_result(_Result(text=json.dumps({"a": 1}))) == {"a": 1}
    assert parse_tool_result(_Result(structured={"b": 2}, text="ignored")) == {"b": 2}
    with pytest.raises(ToolError):
        parse_tool_result(_Result(text="boom", error=True))


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_parse_unwraps_result_envelope():
    assert parse_tool_result(_Result(structured={"result": json.dumps({"c": 3})})) == {"c": 3}


def test_oauth_provider_builds_without_network(tmp_path):
    from ddcheck.auth import FileTokenStorage, build_oauth_provider

    provider = build_oauth_provider("https://mcp.dreamdata.io/mcp", storage=FileTokenStorage(tmp_path))
    assert provider is not None
    assert not FileTokenStorage(tmp_path).clear()
