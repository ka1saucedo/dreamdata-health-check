"""Check a customer's live site for the Dreamdata tracker (plain HTTP fetch, no JavaScript)."""

from __future__ import annotations

import re
from dataclasses import dataclass

DREAMDATA_PATTERN = re.compile(r"cdn\.dreamdata\.cloud|dreamdata\.(min\.)?js|window\.dreamdata", re.I)
GTM_PATTERN = re.compile(r"googletagmanager\.com/gtm\.js|GTM-[A-Z0-9]{4,}", re.I)


@dataclass
class SiteResult:
    domain: str
    final_url: str = ""
    dreamdata_found: bool = False
    gtm_found: bool = False
    error: str | None = None


def scan_html(domain: str, html: str, final_url: str = "") -> SiteResult:
    return SiteResult(
        domain=domain,
        final_url=final_url or f"https://{domain}",
        dreamdata_found=bool(DREAMDATA_PATTERN.search(html)),
        gtm_found=bool(GTM_PATTERN.search(html)),
    )


async def check_site(domain: str) -> SiteResult:
    import httpx

    url = domain if domain.startswith("http") else f"https://{domain}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15,
                                     headers={"User-Agent": "ddcheck/0.1 (+onboarding health check)"}) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            return scan_html(domain, resp.text, str(resp.url))
    except Exception as exc:
        return SiteResult(domain=domain, error=f"{type(exc).__name__}: {exc}")
