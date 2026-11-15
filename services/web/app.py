"""Roadside Assistance member and dispatcher portal (demo for AAA).

Pages
  /signin             demo sign-in: pick a member or the dispatcher (stands in for company SSO)
  /requests/new       RSA-001  a member asks for help
  /requests           RSA-002  members see their own requests; dispatchers see all
  /requests/{id}      RSA-002/003  details; dispatchers update status, ETA and driver

The browser only talks to this server. It calls the API server-side, passing the signed-in
user's token. On Cloud Run the API is private: calls also carry a Google identity token for
the API's audience in X-Serverless-Authorization, leaving Authorization for the app's token.
"""

from __future__ import annotations

import asyncio
import html
import os
import time

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

API_URL = os.environ.get("API_URL", "http://localhost:8080")
API_AUDIENCE = os.environ.get("API_AUDIENCE", "")
COOKIE = "session"


class GoogleIdTokenAuth(httpx.Auth):
    """Cloud Run IAM for the private API: an identity token in X-Serverless-Authorization."""

    def __init__(self, audience: str):
        self.audience, self._token, self._expires = audience, "", 0.0

    async def _get(self) -> str:
        if time.time() > self._expires:
            from google.auth.transport.requests import Request as GoogleRequest
            from google.oauth2 import id_token

            self._token = await asyncio.to_thread(id_token.fetch_id_token, GoogleRequest(), self.audience)
            self._expires = time.time() + 45 * 60
        return self._token

    async def async_auth_flow(self, request):
        request.headers["X-Serverless-Authorization"] = f"Bearer {await self._get()}"
        yield request


app = FastAPI(title="Roadside Assistance")
client = httpx.AsyncClient(base_url=API_URL, timeout=10, auth=GoogleIdTokenAuth(API_AUDIENCE) if API_AUDIENCE else None)

HELP_TYPES = {
    "tow": "Tow",
    "battery": "Battery jump-start",
    "flat_tyre": "Flat tyre",
    "lockout": "Locked out",
    "fuel": "Out of fuel",
}
STATUS_LABEL = {
    "received": "Received",
    "assigned": "Truck assigned",
    "en_route": "On the way",
    "arrived": "Arrived",
    "completed": "Completed",
}
NEXT_STATUS = {"received": "assigned", "assigned": "en_route", "en_route": "arrived", "arrived": "completed"}

CSS = """
*{box-sizing:border-box}
body{font-family:Roboto,Arial,sans-serif;margin:0;color:#202124;background:#F8F9FA}
header{background:#0B3D91;color:#fff;padding:14px 32px;display:flex;align-items:center;gap:24px}
header .brand{font-weight:700;font-size:18px;margin-right:auto}
header a{color:#fff;text-decoration:none}
header .who{font-size:14px;opacity:.9}
main{max-width:860px;margin:32px auto;padding:0 16px}
.card{background:#fff;border:1px solid #DADCE0;border-radius:12px;padding:24px;margin-bottom:16px}
h1{font-size:28px;font-weight:500;margin:0 0 16px}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #E8EAED}
label{display:flex;flex-direction:column;gap:6px;font-size:14px;margin-bottom:14px}
input,select{padding:9px;border:1px solid #DADCE0;border-radius:8px;font-size:15px}
button{padding:10px 18px;border-radius:8px;border:0;background:#0B3D91;color:#fff;font-size:15px;cursor:pointer}
.users{display:flex;gap:12px;flex-wrap:wrap}
.badge{display:inline-block;padding:3px 12px;border-radius:12px;background:#E8F0FE;color:#174EA6;font-size:14px}
.error{color:#C5221F}
.muted{color:#5F6368;font-size:14px}
.demo{font-size:12px;color:#5F6368;text-align:center;margin:24px}
"""


def page(title: str, body: str, user: dict | None = None) -> HTMLResponse:
    who = ""
    if user:
        who = (
            f'<span class="who" data-testid="signed-in-as">Signed in as {html.escape(user["name"])} '
            f'({html.escape(user["role"])})</span><a href="/signout">Sign out</a>'
        )
    nav = ""
    if user and user["role"] == "member":
        nav = '<a href="/requests/new">Request help</a><a href="/requests">My requests</a>'
    elif user:
        nav = '<a href="/requests">All requests</a>'
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{CSS}</style></head><body>
<header><span class="brand">Roadside Assistance</span>{nav}{who}</header>
<main>{body}</main>
<p class="demo">Demo application. Not an AAA product. Sample data only.</p>
</body></html>"""
    )


def auth_headers(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    return {"Authorization": f"Bearer {token}"} if token else {}


async def signed_in(request: Request) -> dict | None:
    if not request.cookies.get(COOKIE):
        return None
    r = await client.get("/v1/me", headers=auth_headers(request))
    return r.json() if r.status_code == 200 else None


def to_signin() -> RedirectResponse:
    return RedirectResponse("/signin", status_code=303)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
async def home(request: Request):
    return RedirectResponse("/requests" if await signed_in(request) else "/signin", status_code=303)


# --------------------------------------------------------------------------- sign-in (demo SSO)


@app.get("/signin")
def signin_page():
    people = [("alice", "Alice Ng", "member"), ("bob", "Bob Ortiz", "member"), ("dana", "Dana Kim", "dispatcher")]
    buttons = "".join(
        f'<form method="post" action="/signin"><input type="hidden" name="user" value="{u}">'
        f'<button type="submit">Sign in as {n} ({r})</button></form>'
        for u, n, r in people
    )
    return page(
        "Sign in",
        f"""<div class="card"><h1>Sign in</h1>
<p class="muted">Demo sign-in. In production this is the company identity provider.</p>
<div class="users">{buttons}</div></div>""",
    )


@app.post("/signin")
async def signin(user: str = Form(...)):
    r = await client.post("/v1/auth/demo-login", json={"user": user})
    if r.status_code != 200:
        failed = page("Sign in", '<div class="card"><p class="error" role="alert">Sign-in failed</p></div>')
        failed.status_code = 502  # the API refused or couldn't be reached
        return failed
    resp = RedirectResponse("/requests", status_code=303)
    resp.set_cookie(COOKIE, r.json()["token"], httponly=True, samesite="lax")
    return resp


@app.get("/signout")
def signout():
    resp = RedirectResponse("/signin", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# --------------------------------------------------------------------------- RSA-001 request help


@app.get("/requests/new")
async def new_request(request: Request):
    user = await signed_in(request)
    if not user:
        return to_signin()
    options = "".join(f'<option value="{k}">{v}</option>' for k, v in HELP_TYPES.items())
    return page(
        "Request help",
        f"""<div class="card"><h1>Request roadside help</h1>
<form method="post" action="/requests">
<label>What do you need?<select name="type">{options}</select></label>
<label>Where are you?<input name="location" required></label>
<label>Phone number<input name="phone" required></label>
<button type="submit">Send request</button>
</form></div>""",
        user,
    )


@app.post("/requests")
async def submit_request(request: Request, type: str = Form(...), location: str = Form(...), phone: str = Form(...)):
    r = await client.post(
        "/v1/requests", json={"type": type, "location": location, "phone": phone}, headers=auth_headers(request)
    )
    if r.status_code == 401:
        return to_signin()
    if r.status_code != 201:
        user = await signed_in(request)
        detail = "; ".join(e["message"] for e in r.json().get("errors", [])) or r.json().get("message", "")
        return page(
            "Request help",
            f'<div class="card"><p class="error" role="alert">Could not send: {html.escape(detail)}</p>'
            '<a href="/requests/new">Try again</a></div>',
            user,
        )
    return RedirectResponse(f"/requests/{r.json()['id']}?created=1", status_code=303)


# --------------------------------------------------------------------------- RSA-002 view requests


@app.get("/requests")
async def list_requests(request: Request):
    user = await signed_in(request)
    if not user:
        return to_signin()
    rows = (await client.get("/v1/requests", headers=auth_headers(request))).json()
    title = "My requests" if user["role"] == "member" else "All requests"
    member_col = "<th>Member</th>" if user["role"] == "dispatcher" else ""
    body = "".join(
        f'<tr><td><a href="/requests/{r["id"]}">{r["id"]}</a></td>'
        + (f"<td>{html.escape(r['member'])}</td>" if user["role"] == "dispatcher" else "")
        + f"<td>{HELP_TYPES[r['type']]}</td><td>{html.escape(r['location'])}</td>"
        f"<td>{STATUS_LABEL[r['status']]}</td></tr>"
        for r in rows
    )
    empty = '<p class="muted">No requests yet.</p>' if not rows else ""
    return page(
        title,
        f"""<div class="card"><h1>{title}</h1>
<table aria-label="Requests"><thead><tr>
<th>Request</th>{member_col}<th>Help</th><th>Location</th><th>Status</th></tr></thead>
<tbody>{body}</tbody></table>{empty}</div>""",
        user,
    )


@app.get("/requests/{request_id}")
async def show_request(request: Request, request_id: str, created: int = 0):
    user = await signed_in(request)
    if not user:
        return to_signin()
    resp = await client.get(f"/v1/requests/{request_id}", headers=auth_headers(request))
    if resp.status_code != 200:
        return page("Not found", '<div class="card"><h1>Request not found</h1></div>', user)
    r = resp.json()
    banner = '<p class="badge" role="status">Help is on the way. We received your request.</p>' if created else ""
    eta = f"{r['eta_minutes']} min" if r["eta_minutes"] is not None else "Not yet known"
    driver = html.escape(r["driver"]) if r["driver"] else "Not yet assigned"
    update = ""
    if user["role"] == "dispatcher" and r["status"] in NEXT_STATUS:
        nxt = NEXT_STATUS[r["status"]]
        update = f"""<div class="card"><h1>Update request</h1>
<form method="post" action="/requests/{r["id"]}/update">
<label>Next status<select name="status"><option value="{nxt}">{STATUS_LABEL[nxt]}</option></select></label>
<label>ETA (minutes)<input name="eta_minutes" type="number" min="0" max="600"></label>
<label>Driver<input name="driver"></label>
<button type="submit">Save update</button></form></div>"""
    return page(
        r["id"],
        f"""<div class="card">{banner}<h1>Request {r["id"]}</h1>
<table aria-label="Request details">
<tr><th>Help</th><td>{HELP_TYPES[r["type"]]}</td></tr>
<tr><th>Location</th><td>{html.escape(r["location"])}</td></tr>
<tr><th>Status</th><td data-testid="status">{STATUS_LABEL[r["status"]]}</td></tr>
<tr><th>ETA</th><td data-testid="eta">{eta}</td></tr>
<tr><th>Driver</th><td data-testid="driver">{driver}</td></tr>
</table></div>{update}""",
        user,
    )


# --------------------------------------------------------------------------- RSA-003 dispatcher update


@app.post("/requests/{request_id}/update")
async def update_request(
    request: Request, request_id: str, status: str = Form(...), eta_minutes: str = Form(""), driver: str = Form("")
):
    body: dict = {"status": status}
    if eta_minutes.strip():
        body["eta_minutes"] = int(eta_minutes)
    if driver.strip():
        body["driver"] = driver.strip()
    r = await client.patch(f"/v1/requests/{request_id}", json=body, headers=auth_headers(request))
    if r.status_code == 401:
        return to_signin()
    if r.status_code != 200:
        user = await signed_in(request)
        return page(
            "Update failed",
            f'<div class="card"><p class="error" role="alert">{html.escape(r.json().get("message", ""))}</p>'
            f'<a href="/requests/{request_id}">Back</a></div>',
            user,
        )
    return RedirectResponse(f"/requests/{request_id}", status_code=303)
