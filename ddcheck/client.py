"""Clients that call Dreamdata MCP tools.

Two implementations share one interface, ``await client.call(tool, **args) -> dict``:

* ``MCPClient``     talks to the live Dreamdata MCP server over streamable HTTP with OAuth.
* ``FixtureClient`` replays responses recorded from a real run (used by tests and ``--fixture``).
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Protocol

DREAMDATA_MCP_URL = "https://mcp.dreamdata.io/mcp"


class ToolError(RuntimeError):
    """A Dreamdata MCP tool returned an error, or a fixture has no recording for a call."""


class DreamdataClient(Protocol):
    async def call(self, tool: str, **args: Any) -> dict: ...


def fixture_key(tool: str, args: dict[str, Any]) -> str:
    """Stable key for a tool call, used to record and replay responses."""
    if tool == "report_builder_get_components":
        return f"{tool}:{args.get('metric_group') or 'all'}"
    if tool == "report_builder_list_subjects":
        return f"{tool}:{args.get('analysis_type')}"
    if tool == "report_builder_run_config":
        cfg = args.get("config") or {}
        segs = ",".join(s["propertyId"] for s in cfg.get("segmentBy", []))
        return f"{tool}:{cfg.get('time', {}).get('value')}:{segs}"
    return tool


def parse_tool_result(result: Any) -> dict:
    """Turn an MCP CallToolResult into a dict. Prefers structured content, falls back to JSON text."""
    if getattr(result, "isError", False):
        text = " ".join(getattr(c, "text", "") for c in result.content)
        raise ToolError(text or "tool returned an error")
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and structured:
        # Some servers wrap a JSON string as {"result": "..."}; unwrap it.
        if set(structured) == {"result"} and isinstance(structured["result"], str):
            try:
                inner = json.loads(structured["result"])
                if isinstance(inner, dict):
                    return inner
            except json.JSONDecodeError:
                pass
        else:
            return structured
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ToolError(f"non-JSON tool output: {text[:200]}") from exc
            return parsed if isinstance(parsed, dict) else {"items": parsed}
    return {}


class MCPClient:
    """Live client. Use as ``async with MCPClient() as client: ...``."""

    def __init__(self, url: str = DREAMDATA_MCP_URL, auth: Any = "oauth", timeout: float = 60):
        """``auth=\"oauth\"`` (default) signs in with OAuth; pass ``None`` for servers without auth (tests)."""
        self.url = url
        self.auth = auth
        self.timeout = timeout
        self._stack: AsyncExitStack | None = None
        self._session = None

    async def __aenter__(self) -> "MCPClient":
        from mcp import ClientSession

        await self._preflight()
        if self.auth == "oauth":
            from .auth import build_oauth_provider

            self.auth = build_oauth_provider(self.url)

        self._stack = AsyncExitStack()
        try:  # newer mcp 1.x
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.shared._httpx_utils import create_mcp_http_client

            http = await self._stack.enter_async_context(
                create_mcp_http_client(timeout=httpx.Timeout(self.timeout, read=300), auth=self.auth)
            )
            transport = streamable_http_client(self.url, http_client=http)
        except ImportError:  # older mcp 1.x
            from mcp.client.streamable_http import streamablehttp_client

            transport = streamablehttp_client(self.url, auth=self.auth, timeout=self.timeout)
        read, write, _ = await self._stack.enter_async_context(transport)
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._stack:
            try:
                await self._stack.aclose()
            except Exception:
                pass

    async def _preflight(self) -> None:
        """Fail fast with a clear message if the server can't be reached at all."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as http:
                await http.get(self.url)
        except httpx.HTTPError as exc:
            raise ToolError(f"Couldn't reach {self.url} ({type(exc).__name__}: {exc}). "
                            "Check your internet connection or VPN.") from exc

    async def call(self, tool: str, **args: Any) -> dict:
        args = {k: v for k, v in args.items() if v is not None}
        result = await self._session.call_tool(tool, args)
        return parse_tool_result(result)


class FixtureClient:
    """Replays a recorded run. Unrecorded calls raise ToolError so checks degrade honestly."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        data = json.loads(self.path.read_text())
        self.meta = {k: v for k, v in data.items() if k != "tools"}
        self.tools: dict[str, dict] = data["tools"]

    async def __aenter__(self) -> "FixtureClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def call(self, tool: str, **args: Any) -> dict:
        key = fixture_key(tool, args)
        if key not in self.tools:
            raise ToolError(f"no recorded response for {key}")
        return self.tools[key]
