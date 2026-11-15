"""OAuth login for the Dreamdata MCP server.

The first run opens your browser to sign in to Dreamdata. Tokens are cached in
``~/.config/ddcheck/`` (file mode 600) and refreshed automatically after that.
Nothing is ever written inside the repo.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CONFIG_DIR = Path(os.environ.get("DDCHECK_CONFIG_DIR", Path.home() / ".config" / "ddcheck"))
CALLBACK_PORT = int(os.environ.get("DDCHECK_CALLBACK_PORT", "8765"))
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"


class FileTokenStorage:
    """Implements the MCP SDK's TokenStorage protocol on two small JSON files."""

    def __init__(self, directory: Path = CONFIG_DIR):
        self.dir = directory
        self.tokens_path = directory / "tokens.json"
        self.client_path = directory / "client.json"

    def _write(self, path: Path, payload: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
        path.chmod(0o600)

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken

        if self.tokens_path.exists():
            return OAuthToken.model_validate_json(self.tokens_path.read_text())
        return None

    async def set_tokens(self, tokens) -> None:
        self._write(self.tokens_path, tokens.model_dump_json())

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull

        if self.client_path.exists():
            return OAuthClientInformationFull.model_validate_json(self.client_path.read_text())
        return None

    async def set_client_info(self, client_info) -> None:
        self._write(self.client_path, client_info.model_dump_json())

    def clear(self) -> bool:
        removed = False
        for p in (self.tokens_path, self.client_path):
            if p.exists():
                p.unlink()
                removed = True
        return removed


class _CallbackState:
    def __init__(self) -> None:
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None
        self.done = threading.Event()


def _make_handler(cb: _CallbackState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server API)
            query = parse_qs(urlparse(self.path).query)
            cb.code = (query.get("code") or [None])[0]
            cb.state = (query.get("state") or [None])[0]
            cb.error = (query.get("error") or [None])[0]
            ok = cb.code is not None
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            msg = "Signed in. You can close this tab and go back to the terminal." if ok else f"Sign-in failed: {cb.error}"
            self.wfile.write(f"<html><body style='font-family:sans-serif'><p>{msg}</p></body></html>".encode())
            cb.done.set()

        def log_message(self, *args):
            return

    return Handler


async def _redirect_handler(url: str) -> None:
    print("\nOpening your browser to sign in to Dreamdata...")
    print(f"If it doesn't open, paste this URL into your browser:\n{url}\n")
    webbrowser.open(url)


async def _callback_handler() -> tuple[str, str | None]:
    cb = _CallbackState()
    server = HTTPServer(("localhost", CALLBACK_PORT), _make_handler(cb))
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        await asyncio.to_thread(cb.done.wait, 300)
    finally:
        server.server_close()
    if not cb.code:
        raise RuntimeError(f"Dreamdata sign-in did not complete ({cb.error or 'timed out'})")
    return cb.code, cb.state


def build_oauth_provider(server_url: str, storage: FileTokenStorage | None = None):
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    metadata = OAuthClientMetadata(
        client_name="ddcheck (Dreamdata onboarding health check)",
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        scope="read",  # ddcheck never writes; Dreamdata also offers reports/audiences/dashboards:write
    )
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=metadata,
        storage=storage or FileTokenStorage(),
        redirect_handler=_redirect_handler,
        callback_handler=_callback_handler,
    )


def describe_storage() -> str:
    s = FileTokenStorage()
    return json.dumps({"config_dir": str(s.dir), "signed_in": s.tokens_path.exists()})
