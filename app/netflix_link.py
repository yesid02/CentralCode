"""Resuelve el enlace de acceso temporal de Netflix e intenta leer el PIN."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.imap_client import extract_otp

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class HouseholdResolveResult:
    code: str | None = None
    link_url: str | None = None
    source: str | None = None  # "page" | "link"


def resolve_household_code(url: str, *, timeout: float = 12.0) -> HouseholdResolveResult:
    """Intenta obtener el código desde la página del enlace; si falla, devuelve el link."""
    clean = (url or "").strip()
    if not clean:
        return HouseholdResolveResult()

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
            },
        ) as client:
            response = client.get(clean)
            text = response.text or ""
            normalized = re.sub(r"(?<=\d) (?=\d)", "", text)
            code = extract_otp(normalized)
            if code:
                return HouseholdResolveResult(code=code, link_url=clean, source="page")
    except (httpx.HTTPError, OSError):
        pass

    return HouseholdResolveResult(code=None, link_url=clean, source="link")
