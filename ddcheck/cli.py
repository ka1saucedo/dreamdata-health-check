"""ddcheck: onboarding health checks for Dreamdata workspaces.

    ddcheck login                         sign in to the Dreamdata MCP (opens your browser once)
    ddcheck run --domain example.com      check one workspace and write a report
    ddcheck fleet                         check every workspace you can access, one summary table
    ddcheck demo                          run on a recorded real workspace, no sign-in needed
    ddcheck logout                        delete cached tokens
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .checks import SEVERITY, Report, run_checks
from .client import FixtureClient, MCPClient, ToolError
from .report import fleet_markdown, to_html, to_json, to_markdown
from .site import SiteResult

USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
ANSI = {"PASS": "32", "WAITING": "33", "CHECK": "33", "TODO": "36", "FIX": "31", "BLOCKER": "35", "SKIPPED": "90"}


def _c(status: str) -> str:
    label = f"{status:<8}"
    return f"\033[{ANSI[status]}m{label}\033[0m" if USE_COLOR else label


def print_summary(report: Report) -> None:
    print(f"\n{report.name} ({report.slug})  ->  {report.verdict}\n")
    for c in report.checks:
        print(f"  {c.id:>2}  {_c(c.status)} {c.name}: {c.result}")
    print()


def write_outputs(report: Report, out_dir: Path, fmt: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.run_at[:10]
    base = out_dir / f"{report.slug}-{stamp}"
    written = []
    renderers = {"md": to_markdown, "html": to_html, "json": to_json}
    for ext in (renderers if fmt == "all" else [fmt]):
        p = base.with_suffix(f".{ext}")
        p.write_text(renderers[ext](report))
        written.append(p)
    return written


def _demo_fixture() -> Path:
    return Path(str(resources.files("ddcheck") / "data" / "iwa_media_2026-11-14.json"))


def _fixture_site_checker(client: FixtureClient):
    recorded = client.meta.get("site", {})

    async def checker(domain: str) -> SiteResult:
        d = recorded.get(domain)
        if d is None:
            return SiteResult(domain=domain, error="not recorded in this fixture")
        return SiteResult(domain=domain, **d)

    return checker


async def _run(args) -> int:
    fixture = Path(args.fixture) if getattr(args, "fixture", None) else None
    if args.command == "demo":
        fixture = _demo_fixture()
        args.domain = args.domain or "iwamedia.com"
    client = FixtureClient(fixture) if fixture else MCPClient()
    kwargs = {}
    if fixture:
        kwargs["site_checker"] = _fixture_site_checker(client)
        from datetime import datetime
        kwargs["now"] = datetime.fromisoformat(client.meta["recorded_at"])

    async with client:
        if args.command == "login":
            accounts = (await client.call("list_my_accounts")).get("accounts", [])
            print(f"Signed in. {len(accounts)} workspace(s):")
            for a in accounts:
                print(f"  {a['slug']:<30} {a['name']}")
            return 0

        if args.command in ("run", "demo"):
            report = await run_checks(client, slug=args.workspace, domain=args.domain,
                                      setup_hours=args.setup_hours, **kwargs)
            print_summary(report)
            for p in write_outputs(report, Path(args.out), args.format):
                print(f"  wrote {p}")
            return 0 if report.verdict == "Ready for handoff" else 2

        if args.command == "fleet":
            accounts = (await client.call("list_my_accounts")).get("accounts", [])
            reports, errors = [], {}
            for a in accounts:
                print(f"checking {a['slug']}...", file=sys.stderr)
                try:
                    r = await run_checks(client, slug=a["slug"], **kwargs)
                    reports.append(r)
                    write_outputs(r, Path(args.out), args.format)
                except Exception as exc:
                    errors[a["slug"]] = f"{type(exc).__name__}: {exc}"
            table = fleet_markdown(reports, errors)
            Path(args.out).mkdir(parents=True, exist_ok=True)
            (Path(args.out) / "fleet.md").write_text(table)
            print(table)
            print(f"  wrote {Path(args.out) / 'fleet.md'} and one report per workspace")
            worst = min((SEVERITY[c.status] for r in reports for c in r.checks), default=6)
            return 2 if errors or worst <= SEVERITY["FIX"] else 0
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ddcheck", description="Onboarding health checks for Dreamdata workspaces.")
    p.add_argument("--version", action="version", version=f"ddcheck {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, fixture=True):
        sp.add_argument("--out", default="reports", help="output folder (default: reports/)")
        sp.add_argument("--format", choices=["md", "html", "json", "all"], default="all")
        if fixture:
            sp.add_argument("--fixture", help="replay a recorded run instead of calling the live MCP")

    sub.add_parser("login", help="sign in to the Dreamdata MCP and list your workspaces")
    sub.add_parser("logout", help="delete cached tokens")

    run = sub.add_parser("run", help="check one workspace")
    run.add_argument("--workspace", "-w", help="workspace slug (default: your only workspace)")
    run.add_argument("--domain", "-d", help="customer's production domain, e.g. example.com")
    run.add_argument("--setup-hours", type=float,
                     help="hours since setup; zero data after 24h becomes FIX instead of WAITING")
    common(run)

    fleet = sub.add_parser("fleet", help="check every workspace you can access")
    common(fleet)

    demo = sub.add_parser("demo", help="run on a recorded real workspace (no sign-in)")
    demo.add_argument("--domain", default=None)
    demo.set_defaults(workspace=None, setup_hours=None)
    common(demo, fixture=False)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "logout":
        from .auth import FileTokenStorage
        print("Signed out." if FileTokenStorage().clear() else "No cached tokens.")
        return 0
    try:
        return asyncio.run(_run(args))
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except BaseExceptionGroup as group:  # errors raised inside the MCP transport's task group
        leaf = group
        while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
            leaf = leaf.exceptions[0]
        print(f"error: {type(leaf).__name__}: {leaf}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # output piped into head/less that closed early
        return 0


if __name__ == "__main__":
    sys.exit(main())
