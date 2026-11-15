from datetime import datetime
from pathlib import Path

import pytest

from ddcheck.checks import run_checks
from ddcheck.cli import main
from ddcheck.client import FixtureClient
from ddcheck.report import exec_summary, fleet_markdown, to_html, to_markdown

FIXTURE = Path(__file__).parent / "fixtures" / "iwa_media_2026-11-14.json"
NOW = datetime.fromisoformat("2026-11-14T21:20:00-10:00")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_exec_summary_is_plain_english():
    report = await run_checks(FixtureClient(FIXTURE), now=NOW)
    text = " ".join(exec_summary(report))
    assert "deal stages aren't set up" in text
    assert "Next check: Nov 16." in text
    for jargon in ("MCP", "slug", "identify", "p_", "m_"):
        assert jargon not in text


@pytest.mark.anyio
async def test_markdown_and_html_render():
    report = await run_checks(FixtureClient(FIXTURE), now=NOW)
    md, page = to_markdown(report), to_html(report)
    assert "**Verdict: Blocked**" in md and "## Handoff checklist" in md
    assert md.count("\n| ") >= 11
    assert "<!DOCTYPE html>" in page and "BLOCKER" in page and "&#x27;Iwa Media" in page
    assert "Blocked" in fleet_markdown([report], {"other_ws": "timeout"})


def test_cli_demo_writes_reports(tmp_path):
    code = main(["demo", "--out", str(tmp_path)])
    assert code == 2  # not ready for handoff
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".html", ".json", ".md"]
