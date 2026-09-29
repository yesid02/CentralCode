"""Utilidades de seguridad para Central Code."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

ENC_PREFIX = "enc:v1:"
SESSION_COOKIE = "admin_session"
CSRF_COOKIE = "csrf_token"
HOST_SESSION_COOKIE = "__Host-admin_session"
HOST_CSRF_COOKIE = "__Host-csrf_token"

_BLOCKED_PATH_PREFIXES = (
    "/.env",
    "/data/",
    "/.git",
    "/app/",
    "/requirements",
    "/readme",
)


def derive_fernet(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(fernet: Fernet, value: str) -> str:
    token = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{ENC_PREFIX}{token}"


def decrypt_secret(fernet: Fernet, value: str) -> str:
    if not value:
        return value
    if not value.startswith(ENC_PREFIX):
        return value
    token = value[len(ENC_PREFIX) :].encode("utf-8")
    try:
        return fernet.decrypt(token).decode("utf-8")
    except InvalidToken as error:
        raise ValueError("No se pudo descifrar una credencial almacenada.") from error


def secure_equals(left: str, right: str) -> bool:
    """Comparación resistente a timing para strings de distinta longitud."""
    left_digest = hashlib.sha256(left.encode("utf-8")).digest()
    right_digest = hashlib.sha256(right.encode("utf-8")).digest()
    return hmac.compare_digest(left_digest, right_digest)


def create_admin_session(session_secret: str, lifetime_seconds: int = 28800) -> tuple[str, str]:
    """Devuelve (session_cookie, csrf_token)."""
    now = int(time.time())
    csrf = secrets.token_urlsafe(32)
    payload = {
        "admin": True,
        "iat": now,
        "exp": now + lifetime_seconds,
        "jti": secrets.token_urlsafe(16),
        "csrf": csrf,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    signature = hmac.new(session_secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}", csrf


def verify_admin_session(session_secret: str, session: str | None) -> dict[str, Any] | None:
    if not session or "." not in session:
        return None
    encoded, signature = session.rsplit(".", 1)
    expected = hmac.new(session_secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode()).decode())
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not payload.get("admin"):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None
    return payload


def read_session_cookie(request: Request, *, prefer_host: bool) -> str | None:
    if prefer_host:
        return request.cookies.get(HOST_SESSION_COOKIE) or request.cookies.get(SESSION_COOKIE)
    return request.cookies.get(SESSION_COOKIE) or request.cookies.get(HOST_SESSION_COOKIE)


def read_csrf_cookie(request: Request, *, prefer_host: bool) -> str:
    if prefer_host:
        return request.cookies.get(HOST_CSRF_COOKIE) or request.cookies.get(CSRF_COOKIE) or ""
    return request.cookies.get(CSRF_COOKIE) or request.cookies.get(HOST_CSRF_COOKIE) or ""


class RateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lockouts: dict[str, float] = {}

    def hit(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets[key]
            while bucket and now - bucket[0] >= window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Demasiadas solicitudes. Intenta de nuevo en unos segundos.",
                )
            bucket.append(now)

    def assert_not_locked(self, key: str) -> None:
        with self._lock:
            until = self._lockouts.get(key)
            if until and until > time.monotonic():
                remaining = int(until - time.monotonic())
                raise HTTPException(
                    status_code=429,
                    detail=f"Demasiados intentos fallidos. Espera {remaining} segundos.",
                )
            if until and until <= time.monotonic():
                self._lockouts.pop(key, None)

    def register_failure(self, key: str, limit: int, window_seconds: int, lockout_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            failures = self._failures[key]
            while failures and now - failures[0] >= window_seconds:
                failures.popleft()
            failures.append(now)
            if len(failures) >= limit:
                self._lockouts[key] = now + lockout_seconds
                failures.clear()

    def clear_failures(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._lockouts.pop(key, None)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, app_env: str = "development"):
        super().__init__(app)
        self.app_env = app_env
        self.is_production = app_env.casefold() == "production"

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.casefold()
        if any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in _BLOCKED_PATH_PREFIXES):
            return Response(status_code=404, content="Not Found")

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "object-src 'none'"
        )
        if "server" in response.headers:
            del response.headers["server"]

        if path.startswith("/api/") or path in {"/admin", "/"}:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
        if path.startswith("/admin") or path.startswith("/api/admin"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"

        if self.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def set_auth_cookies(
    response: Response,
    session_value: str,
    csrf_token: str,
    *,
    secure: bool,
    max_age: int = 28800,
) -> None:
    session_name = HOST_SESSION_COOKIE if secure else SESSION_COOKIE
    csrf_name = HOST_CSRF_COOKIE if secure else CSRF_COOKIE
    common = {
        "samesite": "strict",
        "secure": secure,
        "max_age": max_age,
        "path": "/",
    }
    response.set_cookie(session_name, session_value, httponly=True, **common)
    response.set_cookie(csrf_name, csrf_token, httponly=False, **common)


def clear_auth_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE, HOST_SESSION_COOKIE, HOST_CSRF_COOKIE):
        response.delete_cookie(name, path="/")


def request_origin_ok(request: Request) -> bool:
    """Exige Origin/Referer del mismo host en mutaciones (anti-CSRF extra)."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True
    host = request.headers.get("host", "").strip().casefold()
    if not host:
        return False
    origin = request.headers.get("origin", "").strip()
    referer = request.headers.get("referer", "").strip()
    candidates = [value for value in (origin, referer) if value]
    if not candidates:
        # fetch same-origin a veces omite Origin; si hay cookie CSRF lo validamos aparte
        return True
    for candidate in candidates:
        parsed = urlparse(candidate)
        candidate_host = parsed.netloc.casefold()
        if candidate_host == host:
            return True
    return False


def require_csrf(request: Request, session_payload: dict[str, Any], *, prefer_host: bool = False) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if not request_origin_ok(request):
        raise HTTPException(status_code=403, detail="Origen no permitido.")
    header = request.headers.get("x-csrf-token", "")
    cookie = read_csrf_cookie(request, prefer_host=prefer_host)
    expected = session_payload.get("csrf", "")
    if not header or not cookie or not expected:
        raise HTTPException(status_code=403, detail="Token CSRF ausente.")
    if not hmac.compare_digest(header, cookie) or not hmac.compare_digest(header, expected):
        raise HTTPException(status_code=403, detail="Token CSRF inválido.")
