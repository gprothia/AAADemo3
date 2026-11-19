"""Roadside Assistance API (demo for AAA).

Features (see specs/):
  STD-001  Enterprise baseline: AAA, logging, API standards
  RSA-001  Request roadside help
  RSA-002  View requests (members: their own; dispatchers: all)
  RSA-003  Dispatcher updates a request
  RSA-005  Verified driver badge (partner Driver Directory)

Standards applied (see standards/):
  aaa.md      Bearer token on every /v1 endpoint; roles; deny by default; audit events
  api.md      /v1 paths; error body {"code", "message", "request_id"}; X-Request-ID
  logging.md  one JSON log line per request; request_id; phone numbers masked

Storage is in memory and seeded at start, so every sandbox begins clean.
"""

from __future__ import annotations

import asyncio
import base64
import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import uuid
from collections import Counter, deque
from datetime import UTC, datetime
from enum import StrEnum

import driver_directory
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

# --------------------------------------------------------------------------- config

SEED = os.environ.get("SEED_TEST_DATA", "true").lower() == "true"
# Test-only endpoints are registered only when this is on. Off by default; the GKE sandbox
# deployment turns it on. Never on in UAT or production.
TEST_HOOKS = os.environ.get("ENABLE_TEST_HOOKS", "false").lower() == "true"
# Demo sign-in only (standards/aaa.md): production uses the company identity provider.
SECRET = os.environ.get("DEMO_AUTH_SECRET", "demo-only-not-a-secret").encode()
TOKEN_TTL_S = 8 * 3600
# Release identity (deploy/prod): which build answered, and whether it is the stable or the
# canary copy. Sent on every response so a canary can be measured on its own (standards/slo.md).
APP_VERSION = os.environ.get("APP_VERSION", "dev")
APP_TRACK = os.environ.get("APP_TRACK", "")

app = FastAPI(title="Roadside Assistance API", version="1.0.0")

# --------------------------------------------------------------------------- logging

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
# Phone-shaped values: "+1 555 010 2233", "(555) 014-8392", "555-010-2233", "5550102233". Not dates or IDs.
PHONE = re.compile(r"\+\d[\d\s-]{8,}\d|(?:\(\d{3}\)|\b\d{3})[\s-]?\d{3}[\s-]?\d{4}\b")
RECENT_LOGS: deque[dict] = deque(maxlen=200)  # exposed only through a test hook

log = logging.getLogger("roadside")
log.setLevel(logging.INFO)
log.addHandler(logging.StreamHandler(sys.stdout))
log.propagate = False


def mask(value: str) -> str:
    """Keep the last 2 digits of a phone number: +1 555 010 1234 -> ********34."""
    digits = re.sub(r"\D", "", value)
    return "*" * max(len(digits) - 2, 0) + digits[-2:]


def _scrub(value):
    """Mask phone numbers anywhere inside a logged value."""
    if isinstance(value, str):
        return PHONE.sub(lambda m: mask(m.group(0)), value)
    if isinstance(value, dict):
        return {
            k: (mask(v) if k in ("phone", "driver_phone") and isinstance(v, str) else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def emit(event: str, **fields) -> None:
    """One JSON object per line (standards/logging.md). Phone numbers never appear in clear."""
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "severity": fields.pop("severity", "INFO"),
        "event": event,
        "request_id": request_id_var.get(),
        **_scrub(fields),
    }
    RECENT_LOGS.append(record)
    log.info(json.dumps(record, default=str))


# --------------------------------------------------------------------------- errors


def error(status: int, code: str, message: str, **extra) -> JSONResponse:
    body = {"code": code, "message": message, "request_id": request_id_var.get(), **extra}
    return JSONResponse(status_code=status, content=body)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


@app.exception_handler(ApiError)
async def api_error(_: Request, exc: ApiError):
    return error(exc.status, exc.code, exc.message)


def _field_path(loc: tuple) -> str:
    """('body', 'items', 0, 'qty') -> 'items[0].qty'"""
    out = ""
    for part in loc:
        if part == "body":
            continue
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errors = [{"field": _field_path(e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return error(422, "VALIDATION_ERROR", "Request is invalid", errors=errors)


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return error(exc.status_code, code, str(exc.detail))


# --------------------------------------------------------------------------- request middleware


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-App-Version"] = APP_VERSION
        if APP_TRACK:
            response.headers["X-App-Track"] = APP_TRACK
        if request.url.path != "/healthz":
            emit(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
                user=getattr(request.state, "user", None),
                role=getattr(request.state, "role", None),
                version=APP_VERSION,
                track=APP_TRACK or None,
            )
        return response
    finally:
        request_id_var.reset(token)


# --------------------------------------------------------------------------- authentication

USERS = {
    "alice": {"name": "Alice Ng", "role": "member"},
    "bob": {"name": "Bob Ortiz", "role": "member"},
    "dana": {"name": "Dana Kim", "role": "dispatcher"},
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def sign(sub: str, role: str) -> str:
    payload = _b64(json.dumps({"sub": sub, "role": role, "exp": int(time.time()) + TOKEN_TTL_S}).encode())
    sig = _b64(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify(token: str) -> dict | None:
    try:
        payload, sig = token.split(".")
        expected = _b64(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return claims if claims.get("exp", 0) > time.time() else None
    except (ValueError, json.JSONDecodeError):
        return None


async def current_user(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """Authentication: every /v1 endpoint (except sign-in) requires a valid bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "UNAUTHENTICATED", "Sign in required")
    claims = verify(authorization.split(" ", 1)[1].strip())
    if not claims:
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token")
    request.state.user, request.state.role = claims["sub"], claims["role"]
    return claims


def require(*roles: str):
    """Authorization: deny by default; only the listed roles may call the endpoint."""

    async def check(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise ApiError(403, "FORBIDDEN", "Your role may not do this")
        return user

    return check


class DemoLogin(BaseModel):
    user: str


@app.post("/v1/auth/demo-login")
def demo_login(body: DemoLogin):
    """Demo sign-in: pick a seeded user. Stands in for the company identity provider."""
    u = USERS.get(body.user)
    if not u:
        raise ApiError(404, "USER_NOT_FOUND", f"Unknown demo user {body.user}")
    audit("auth.signed_in", actor=body.user, target=body.user)
    return {"token": sign(body.user, u["role"]), "user": body.user, "name": u["name"], "role": u["role"]}


@app.get("/v1/me")
async def me(user: dict = Depends(current_user)):
    u = USERS[user["sub"]]
    return {"user": user["sub"], "name": u["name"], "role": user["role"]}


# --------------------------------------------------------------------------- accounting (audit)

AUDIT: list[dict] = []


def audit(event: str, actor: str, target: str, **details) -> None:
    """Accounting: who did what to which record, when. Also written to the log."""
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "event": event,
        "actor": actor,
        "target": target,
        "request_id": request_id_var.get(),
        **details,
    }
    AUDIT.append(entry)
    emit("audit", audit_event=event, actor=actor, target=target, **details)


@app.get("/v1/audit")
def audit_log(event: str | None = None, target: str | None = None, _: dict = Depends(require("dispatcher"))):
    rows = [a for a in AUDIT if (not event or a["event"] == event) and (not target or a["target"] == target)]
    return list(reversed(rows))[:200]


# --------------------------------------------------------------------------- domain


class HelpType(StrEnum):
    tow = "tow"
    battery = "battery"
    flat_tyre = "flat_tyre"
    lockout = "lockout"
    fuel = "fuel"


STATUSES = ["received", "assigned", "en_route", "arrived", "completed"]
REQUESTS: dict[str, dict] = {}
RATINGS: dict[str, dict] = {}


def _avatar_svg(bg_hex: str, shirt_hex: str, hair_hex: str, skin_hex: str) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
        f'<rect width="120" height="120" fill="{bg_hex}"/>'
        f'<path d="M22 120c4-24 20-34 38-34s34 10 38 34z" fill="{shirt_hex}"/>'
        f'<circle cx="60" cy="48" r="24" fill="{skin_hex}"/>'
        f'<path d="M36 45c2-18 14-26 24-26 14 0 23 9 24 26-4-8-12-12-24-12s-19 4-24 12z" fill="{hair_hex}"/>'
        f'<circle cx="51" cy="50" r="2.6" fill="#1F2937"/>'
        f'<circle cx="69" cy="50" r="2.6" fill="#1F2937"/>'
        f'<path d="M52 60c3 4 13 4 16 0" fill="none" stroke="#7C2D12" stroke-width="2.5" stroke-linecap="round"/>'
        f"</svg>"
    )
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)


SEEDED_DRIVERS = [
    {
        "driver_name": "Marcus Vance",
        "photo_url": _avatar_svg("#DBEAFE", "#0B3D91", "#1F2937", "#E0AC69"),
        "avg_stars": 4.96,
        "ratings_count": 84,
        "top_tags": ["On time", "Friendly driver", "Explained the fix"],
    },
    {
        "driver_name": "Elena Rostova",
        "photo_url": _avatar_svg("#FCE7F3", "#1E3A8A", "#78350F", "#F1C27D"),
        "avg_stars": 4.93,
        "ratings_count": 71,
        "top_tags": ["Explained the fix", "Friendly driver"],
    },
    {
        "driver_name": "Devon Brooks",
        "photo_url": _avatar_svg("#DCFCE7", "#0B3D91", "#111827", "#8D5524"),
        "avg_stars": 4.89,
        "ratings_count": 65,
        "top_tags": ["On time", "Friendly driver"],
    },
    {
        "driver_name": "Priya Nair",
        "photo_url": _avatar_svg("#FEF3C7", "#1D4ED8", "#1F2937", "#C68642"),
        "avg_stars": 4.85,
        "ratings_count": 59,
        "top_tags": ["Explained the fix", "On time"],
    },
    {
        "driver_name": "Carlos Mendez",
        "photo_url": _avatar_svg("#E0E7FF", "#0B3D91", "#27272A", "#D2996C"),
        "avg_stars": 4.81,
        "ratings_count": 52,
        "top_tags": ["Friendly driver", "On time"],
    },
]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def seed() -> None:
    REQUESTS.clear()
    RATINGS.clear()
    AUDIT.clear()
    ts = now()
    sample_requests = [
        {
            "id": "RSA-1001",
            "member": "bob",
            "type": "battery",
            "location": "I-80 eastbound, mile 42",
            "phone": "+1 555 010 2233",
            "status": "assigned",
            "eta_minutes": 25,
            "driver": "Sam (Truck 12)",
            "driver_name": "Sam",
            "driver_truck": "Truck 12",
            "driver_rating": 4.8,
            "driver_phone": "(555) 010-1212",
            "history": [{"status": "received", "at": ts}, {"status": "assigned", "at": ts}],
            "created_at": ts,
        },
        {
            "id": "RSA-1002",
            "member": "alice",
            "type": "flat_tyre",
            "location": "US-101 northbound, exit 412",
            "phone": "+1 555 014 8392",
            "status": "en_route",
            "eta_minutes": 12,
            "driver": "Maria (Truck 07)",
            "driver_name": "Maria",
            "driver_truck": "Truck 07",
            "driver_rating": 4.9,
            "driver_phone": "(555) 010-3434",
            "history": [
                {"status": "received", "at": ts},
                {"status": "assigned", "at": ts},
                {"status": "en_route", "at": ts},
            ],
            "created_at": ts,
        },
        {
            "id": "RSA-1003",
            "member": "alice",
            "type": "tow",
            "location": "450 Market St, San Francisco, CA",
            "phone": "+1 555 014 8392",
            "status": "completed",
            "eta_minutes": 0,
            "driver": "Sam (Truck 12)",
            "driver_name": "Sam",
            "driver_truck": "Truck 12",
            "driver_rating": 4.8,
            "driver_phone": "(555) 010-1212",
            "history": [
                {"status": "received", "at": ts},
                {"status": "assigned", "at": ts},
                {"status": "en_route", "at": ts},
                {"status": "arrived", "at": ts},
                {"status": "completed", "at": ts},
            ],
            "created_at": ts,
        },
        {
            "id": "RSA-1004",
            "member": "bob",
            "type": "lockout",
            "location": "789 Oak Ave, Oakland, CA",
            "phone": "+1 555 010 2233",
            "status": "received",
            "eta_minutes": None,
            "driver": None,
            "driver_name": None,
            "driver_truck": None,
            "driver_rating": None,
            "driver_phone": None,
            "history": [{"status": "received", "at": ts}],
            "created_at": ts,
        },
        {
            "id": "RSA-1005",
            "member": "alice",
            "type": "fuel",
            "location": "I-280 southbound, mile 18",
            "phone": "+1 555 014 8392",
            "status": "arrived",
            "eta_minutes": 0,
            "driver": "Maria (Truck 07)",
            "driver_name": "Maria",
            "driver_truck": "Truck 07",
            "driver_rating": 4.9,
            "driver_phone": "(555) 010-3434",
            "history": [
                {"status": "received", "at": ts},
                {"status": "assigned", "at": ts},
                {"status": "en_route", "at": ts},
                {"status": "arrived", "at": ts},
            ],
            "created_at": ts,
        },
        {
            "id": "RSA-1006",
            "member": "bob",
            "type": "tow",
            "location": "1200 Broadway, Redwood City, CA",
            "phone": "+1 555 010 2233",
            "status": "completed",
            "eta_minutes": 0,
            "driver": "Maria (Truck 07)",
            "driver_name": "Maria",
            "driver_truck": "Truck 07",
            "driver_rating": 4.9,
            "driver_phone": "(555) 010-3434",
            "history": [
                {"status": "received", "at": ts},
                {"status": "assigned", "at": ts},
                {"status": "en_route", "at": ts},
                {"status": "arrived", "at": ts},
                {"status": "completed", "at": ts},
            ],
            "created_at": ts,
        },
        {
            "id": "RSA-1007",
            "member": "bob",
            "type": "flat_tyre",
            "location": "CA-92 westbound, San Mateo Bridge",
            "phone": "+1 555 010 2233",
            "status": "cancelled",
            "eta_minutes": None,
            "driver": None,
            "driver_name": None,
            "driver_truck": None,
            "driver_rating": None,
            "driver_phone": None,
            "history": [{"status": "received", "at": ts}, {"status": "cancelled", "at": ts}],
            "created_at": ts,
        },
    ]
    for r in sample_requests:
        REQUESTS[r["id"]] = r

    sample_ratings = [
        {
            "request_id": "RSA-1003",
            "driver_name": "Sam",
            "stars": 5,
            "tags": ["On time", "Friendly driver"],
            "comment": "Arrived quickly and handled the tow smoothly.",
            "created_at": ts,
        },
        {
            "request_id": "RSA-1006",
            "driver_name": "Maria",
            "stars": 4,
            "tags": ["Explained the fix"],
            "comment": "Helpful driver and clear communication.",
            "created_at": ts,
        },
    ]
    for rating in sample_ratings:
        RATINGS[rating["request_id"]] = rating
        REQUESTS[rating["request_id"]]["rating"] = rating


if SEED:
    seed()


def new_id() -> str:
    return f"RSA-{uuid.uuid4().hex[:6].upper()}"


def visible(r: dict, user: dict) -> bool:
    return user["role"] == "dispatcher" or r["member"] == user["sub"]


# --------------------------------------------------------------------------- RSA-001 request help


class HelpRequestIn(BaseModel):
    type: HelpType
    location: str = Field(min_length=3, max_length=200)
    phone: str

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v: str) -> str:
        if not re.fullmatch(r"\+?[\d\s-]{10,20}", v) or len(re.sub(r"\D", "", v)) < 10:
            raise ValueError("phone must have 10 to 15 digits")
        return v


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.post("/v1/requests", status_code=201)
async def create_request(body: HelpRequestIn, user: dict = Depends(require("member"))):
    r = {
        "id": new_id(),
        "member": user["sub"],
        "type": body.type.value,
        "location": body.location,
        "phone": body.phone,
        "status": "received",
        "eta_minutes": None,
        "driver": None,
        "driver_name": None,
        "driver_truck": None,
        "driver_rating": None,
        "driver_phone": None,
        "history": [{"status": "received", "at": now()}],
        "created_at": now(),
    }
    REQUESTS[r["id"]] = r
    audit("request.created", actor=user["sub"], target=r["id"], type=r["type"])
    return r


# --------------------------------------------------------------------------- RSA-002 view requests


@app.get("/v1/requests")
async def list_requests(user: dict = Depends(require("member", "dispatcher"))):
    rows = [r for r in REQUESTS.values() if visible(r, user)]
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


# RSA-005: cache partner lookups (5 min TTL) so request details stays within SLO budget (≤ 300 ms).
_VERIFICATION_CACHE: dict[str, tuple[bool, float]] = {}
_VERIFICATION_TTL_S = 300.0


async def _is_driver_verified(driver_name: str) -> bool:
    now_mono = time.monotonic()
    cached = _VERIFICATION_CACHE.get(driver_name)
    if cached is not None and now_mono < cached[1]:
        return cached[0]
    profile = await asyncio.to_thread(driver_directory.lookup, driver_name)
    verified = profile["verified"] if profile else False
    _VERIFICATION_CACHE[driver_name] = (verified, now_mono + _VERIFICATION_TTL_S)
    return verified


@app.get("/v1/requests/{request_id}")
async def get_request(request_id: str, user: dict = Depends(require("member", "dispatcher"))):
    r = REQUESTS.get(request_id)
    if not r or not visible(r, user):  # never reveal that someone else's request exists
        raise ApiError(404, "REQUEST_NOT_FOUND", "Request not found")
    # RSA-005: is the assigned driver verified by the partner Driver Directory?
    name = r.get("driver_name")
    verified = await _is_driver_verified(name) if name else None
    return {**r, "driver_verified": verified}


# --------------------------------------------------------------------------- RSA-003 dispatcher update


class UpdateIn(BaseModel):
    status: str | None = None
    eta_minutes: int | None = Field(default=None, ge=0, le=600)
    driver: str | None = Field(default=None, max_length=80)
    driver_name: str | None = Field(default=None, max_length=80)
    driver_truck: str | None = Field(default=None, max_length=120)
    driver_rating: float | None = Field(default=None, ge=1.0, le=5.0)
    driver_phone: str | None = Field(default=None, max_length=30)


@app.patch("/v1/requests/{request_id}")
async def update_request(request_id: str, body: UpdateIn, user: dict = Depends(require("dispatcher"))):
    r = REQUESTS.get(request_id)
    if not r:
        raise ApiError(404, "REQUEST_NOT_FOUND", "Request not found")
    changes = body.model_dump(exclude_none=True)
    if "status" in changes:
        new, cur = changes["status"], r["status"]
        if new not in STATUSES or STATUSES.index(new) != STATUSES.index(cur) + 1:
            raise ApiError(409, "INVALID_TRANSITION", f"Cannot move from {cur} to {new}")
        r["history"].append({"status": new, "at": now()})
    r.update(changes)
    audit("request.updated", actor=user["sub"], target=request_id, changes=changes)
    return r


# --------------------------------------------------------------------------- RSA-004 member cancel


CANCELLABLE_STATUSES = {"received", "assigned", "en_route"}


@app.post("/v1/requests/{request_id}/cancel")
async def cancel_request(request_id: str, user: dict = Depends(require("member"))):
    r = REQUESTS.get(request_id)
    if not r or r["member"] != user["sub"]:
        raise ApiError(404, "REQUEST_NOT_FOUND", "Request not found")
    if r["status"] not in CANCELLABLE_STATUSES:
        raise ApiError(409, "INVALID_TRANSITION", f"Cannot cancel request in status {r['status']}")
    prev = r["status"]
    r["status"] = "cancelled"
    r["history"].append({"status": "cancelled", "at": now()})
    audit("request.cancelled", actor=user["sub"], target=request_id, previous_status=prev)
    return r


# --------------------------------------------------------------------------- RSA-006 rate my rescue


ALLOWED_RATING_TAGS = ("On time", "Friendly driver", "Explained the fix")


class RatingIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("tags")
    @classmethod
    def check_tags(cls, v: list[str]) -> list[str]:
        for tag in v:
            if tag not in ALLOWED_RATING_TAGS:
                raise ValueError(f"Unsupported tag: {tag}")
        return list(dict.fromkeys(v))

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


@app.post("/v1/requests/{request_id}/rating", status_code=201)
async def rate_request(request_id: str, body: RatingIn, user: dict = Depends(require("member"))):
    r = REQUESTS.get(request_id)
    if not r or r["member"] != user["sub"]:
        raise ApiError(404, "REQUEST_NOT_FOUND", "Request not found")
    if r["status"] != "completed":
        raise ApiError(409, "RATING_NOT_ALLOWED", f"Cannot rate request in status {r['status']}")
    if request_id in RATINGS:
        raise ApiError(409, "ALREADY_RATED", "This rescue has already been rated")

    rating = {
        "request_id": request_id,
        "driver_name": r.get("driver_name") or "Assigned Driver",
        "stars": body.stars,
        "tags": body.tags,
        "comment": body.comment,
        "created_at": now(),
    }
    RATINGS[request_id] = rating
    r["rating"] = rating
    # LOG-4: comment text is excluded from audit/application logs.
    audit("rating.created", actor=user["sub"], target=request_id, stars=body.stars, tags=body.tags)
    return rating


@app.get("/v1/drivers/leaderboard")
async def driver_leaderboard():
    """Public monthly leaderboard (explicit AAA-1 exception per RSA-006)."""
    by_driver: dict[str, dict] = {
        d["driver_name"]: {
            "driver_name": d["driver_name"],
            "photo_url": d["photo_url"],
            "total_stars": d["avg_stars"] * d["ratings_count"],
            "ratings_count": d["ratings_count"],
            "tag_counts": Counter({t: 1 for t in d["top_tags"]}),
        }
        for d in SEEDED_DRIVERS
    }
    for rating in RATINGS.values():
        name = rating["driver_name"]
        entry = by_driver.setdefault(
            name,
            {
                "driver_name": name,
                "photo_url": _avatar_svg("#E8F0FE", "#0B3D91", "#1F2937", "#E0AC69"),
                "total_stars": 0.0,
                "ratings_count": 0,
                "tag_counts": Counter(),
            },
        )
        entry["total_stars"] += rating["stars"]
        entry["ratings_count"] += 1
        entry["tag_counts"].update(rating["tags"])

    board = [
        {
            "driver_name": e["driver_name"],
            "photo_url": e["photo_url"],
            "avg_stars": round(e["total_stars"] / e["ratings_count"], 2),
            "ratings_count": e["ratings_count"],
            "top_tags": [tag for tag, _ in e["tag_counts"].most_common(3)],
        }
        for e in by_driver.values()
        if e["ratings_count"] > 0
    ]
    board.sort(key=lambda d: (-d["avg_stars"], -d["ratings_count"], d["driver_name"]))
    return board[:10]


# --------------------------------------------------------------------------- test hooks (sandbox only)

if TEST_HOOKS:

    @app.get("/test/logs", include_in_schema=False)
    def recent_logs(limit: int = 50):
        """Recent structured log lines, so acceptance tests can check standards/logging.md."""
        return list(RECENT_LOGS)[-limit:]
