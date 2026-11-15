"""End-to-end over the real MCP protocol: a local stand-in server replays the recorded
Dreamdata responses over streamable HTTP, and the live MCPClient talks to it."""

import json
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from ddcheck.checks import run_checks
from ddcheck.client import MCPClient, fixture_key

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "iwa_media_2026-11-14.json").read_text())


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(port):
    import uvicorn
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("dreamdata-standin", host="127.0.0.1", port=port)
    tools = FIXTURE["tools"]

    def reply(tool, **args):
        return json.dumps(tools[fixture_key(tool, args)])

    @server.tool()
    def list_my_accounts() -> str:
        return reply("list_my_accounts")

    @server.tool()
    def get_account_currency(slug: str | None = None) -> str:
        return reply("get_account_currency")

    @server.tool()
    def search_companies(query: str, slug: str | None = None) -> str:
        return reply("search_companies")

    @server.tool()
    def list_audiences(slug: str | None = None) -> str:
        return reply("list_audiences")

    @server.tool()
    def list_saved_reports(slug: str | None = None) -> str:
        return reply("list_saved_reports")

    @server.tool()
    def report_builder_list_subjects(analysis_type: str, slug: str | None = None) -> str:
        return reply("report_builder_list_subjects", analysis_type=analysis_type)

    @server.tool()
    def report_builder_get_components(analysis_type: str, analysis_subject_id: str,
                                      metric_group: str | None = None, slug: str | None = None) -> str:
        return reply("report_builder_get_components", metric_group=metric_group)

    @server.tool()
    def report_builder_run_config(config: dict, output_type: str | None = None, slug: str | None = None) -> str:
        return reply("report_builder_run_config", config=config)

    uvicorn.run(server.streamable_http_app(), host="127.0.0.1", port=port, log_level="error")


@pytest.mark.anyio
async def test_live_client_against_standin_server():
    port = _free_port()
    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    async with MCPClient(url=f"http://127.0.0.1:{port}/mcp", auth=None) as client:
        report = await run_checks(client, now=datetime.fromisoformat(FIXTURE["recorded_at"]))

    assert report.verdict == "Blocked"
    assert {c.id: c.status for c in report.checks}[9] == "BLOCKER"
    assert len(report.checks) == 11


@pytest.fixture
def anyio_backend():
    return "asyncio"
