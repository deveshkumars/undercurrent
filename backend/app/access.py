"""Who may call what.

Every /api request is classified once, by an ASGI middleware, as:
- "full": no ACCESS_CODE is configured (and public demo mode is off), or the request carries it;
- "visitor": PUBLIC_DEMO is on, the request has no valid code, and it is a GET on a read-only route
  that shows saved demo runs or validation results. Visitors only ever see documents flagged
  ``demo: True``; nothing they can reach calls a model or writes;
- "deny": everything else (401).

Public demo mode never grants full access without a code: with PUBLIC_DEMO on and no ACCESS_CODE set,
every caller is at most a visitor, so endpoints that spend API credits stay closed.
"""

from __future__ import annotations

import hmac
import json
import re
from contextvars import ContextVar
from typing import Literal

from .config import get_settings

Level = Literal["full", "visitor", "deny"]
LEVEL: ContextVar[Level] = ContextVar("access_level", default="full")

# Always reachable: liveness, app metadata (tells the UI whether a code is needed), API docs.
OPEN_PATHS = {"/api/health", "/api/meta", "/api/docs", "/api/openapi.json", "/api/docs/oauth2-redirect"}

# Read-only routes a visitor may GET in public demo mode.
_ID = r"[A-Za-z0-9_-]+"
VISITOR_GET = [re.compile(p) for p in (
    r"^/api/validation$",
    r"^/api/sim/(meta|demos)$",
    r"^/api/sim/populations$",
    rf"^/api/sim/populations/{_ID}$",
    rf"^/api/sim/populations/{_ID}/agents$",
    rf"^/api/sim/agents/{_ID}$",
    r"^/api/sim/runs$",
    rf"^/api/sim/runs/{_ID}$",
    rf"^/api/sim/runs/{_ID}/(ticks|posts|network|responses|compare|export\.csv)$",
)]


def classify(method: str, path: str, code: str | None) -> Level:
    s = get_settings()
    if path in OPEN_PATHS or not path.startswith("/api"):
        return "full"
    if s.access_code and hmac.compare_digest(code or "", s.access_code):
        return "full"
    if not s.access_code and not s.public_demo:
        return "full"  # private local use with no code configured
    if s.public_demo and method in ("GET", "HEAD") and any(p.match(path) for p in VISITOR_GET):
        return "visitor"
    return "deny"


def is_visitor() -> bool:
    return LEVEL.get() == "visitor"


class AccessMiddleware:
    """Pure ASGI middleware, so the level set here is visible to sync endpoints in the threadpool."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        level = classify(scope["method"], scope["path"], headers.get("x-access-code"))
        if level == "deny":
            body = json.dumps({"detail": "Access code required"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        token = LEVEL.set(level)
        try:
            await self.app(scope, receive, send)
        finally:
            LEVEL.reset(token)
