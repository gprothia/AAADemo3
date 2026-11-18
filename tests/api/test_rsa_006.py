"""API tests generated from specs/RSA-006-rate-my-rescue.md."""

import pytest


def _complete_request(as_user, req_id: str, driver_name: str = "Marcus Vance") -> None:
    dana = as_user("dana")
    r = dana.patch(
        f"/v1/requests/{req_id}",
        json={"status": "assigned", "driver_name": driver_name, "driver_truck": "Flatbed #14"},
    )
    assert r.status_code == 200
    for nxt in ("en_route", "arrived", "completed"):
        r = dana.patch(f"/v1/requests/{req_id}", json={"status": nxt})
        assert r.status_code == 200


@pytest.mark.ac("RSA-006-AC1")
def test_submit_rating(as_user, new_request):
    req = new_request("alice")
    _complete_request(as_user, req["id"])

    r = as_user("alice").post(
        f"/v1/requests/{req['id']}/rating",
        json={"stars": 5, "tags": ["On time", "Explained the fix"], "comment": "Super quick and helpful!"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["request_id"] == req["id"]
    assert body["driver_name"] == "Marcus Vance"
    assert body["stars"] == 5
    assert body["tags"] == ["On time", "Explained the fix"]
    assert body["comment"] == "Super quick and helpful!"
    assert body["created_at"]

    # Empty/whitespace-only comment is stored as null
    req2 = new_request("alice")
    _complete_request(as_user, req2["id"])
    r2 = as_user("alice").post(
        f"/v1/requests/{req2['id']}/rating",
        json={"stars": 4, "tags": [], "comment": "   "},
    )
    assert r2.status_code == 201
    assert r2.json()["comment"] is None


@pytest.mark.ac("RSA-006-AC2")
def test_rating_validation(as_user, new_request):
    req = new_request("alice")
    _complete_request(as_user, req["id"])

    r_stars = as_user("alice").post(f"/v1/requests/{req['id']}/rating", json={"stars": 0})
    assert r_stars.status_code == 422
    assert r_stars.json()["code"] == "VALIDATION_ERROR"
    assert any(e["field"] == "stars" for e in r_stars.json()["errors"])

    r_tag = as_user("alice").post(
        f"/v1/requests/{req['id']}/rating",
        json={"stars": 5, "tags": ["Unknown tag"]},
    )
    assert r_tag.status_code == 422
    assert r_tag.json()["code"] == "VALIDATION_ERROR"
    assert any("tags" in e["field"] for e in r_tag.json()["errors"])

    r_comment = as_user("alice").post(
        f"/v1/requests/{req['id']}/rating",
        json={"stars": 5, "comment": "x" * 501},
    )
    assert r_comment.status_code == 422
    assert r_comment.json()["code"] == "VALIDATION_ERROR"
    assert any(e["field"] == "comment" for e in r_comment.json()["errors"])


@pytest.mark.ac("RSA-006-AC3")
@pytest.mark.parametrize("status", ["received", "assigned", "en_route", "arrived", "cancelled"])
def test_rating_requires_completed(as_user, new_request, status):
    req = new_request("alice")
    dana = as_user("dana")
    if status in ("assigned", "en_route", "arrived"):
        dana.patch(f"/v1/requests/{req['id']}", json={"status": "assigned", "driver_name": "Marcus Vance"})
        if status in ("en_route", "arrived"):
            dana.patch(f"/v1/requests/{req['id']}", json={"status": "en_route"})
        if status == "arrived":
            dana.patch(f"/v1/requests/{req['id']}", json={"status": "arrived"})
    elif status == "cancelled":
        as_user("alice").post(f"/v1/requests/{req['id']}/cancel")

    r = as_user("alice").post(f"/v1/requests/{req['id']}/rating", json={"stars": 5})
    assert r.status_code == 409
    assert r.json()["code"] == "RATING_NOT_ALLOWED"


@pytest.mark.ac("RSA-006-AC4")
def test_rating_once_only(as_user, new_request):
    req = new_request("alice")
    _complete_request(as_user, req["id"])

    first = as_user("alice").post(f"/v1/requests/{req['id']}/rating", json={"stars": 5})
    assert first.status_code == 201

    second = as_user("alice").post(f"/v1/requests/{req['id']}/rating", json={"stars": 3})
    assert second.status_code == 409
    assert second.json()["code"] == "ALREADY_RATED"


@pytest.mark.ac("RSA-006-AC5")
def test_rating_unauthenticated(api, as_user, new_request):
    req = new_request("alice")
    _complete_request(as_user, req["id"])

    r = api.post(f"/v1/requests/{req['id']}/rating", json={"stars": 5})
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.ac("RSA-006-AC6")
def test_rating_forbidden_for_dispatcher(as_user, new_request):
    req = new_request("alice")
    _complete_request(as_user, req["id"])

    r = as_user("dana").post(f"/v1/requests/{req['id']}/rating", json={"stars": 5})
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"


@pytest.mark.ac("RSA-006-AC7")
def test_rating_other_member_returns_404(as_user):
    r = as_user("alice").post("/v1/requests/RSA-1001/rating", json={"stars": 5})
    assert r.status_code == 404
    assert r.json()["code"] == "REQUEST_NOT_FOUND"

    r_missing = as_user("alice").post("/v1/requests/RSA-9999/rating", json={"stars": 5})
    assert r_missing.status_code == 404
    assert r_missing.json()["code"] == "REQUEST_NOT_FOUND"


@pytest.mark.ac("RSA-006-AC8")
def test_rating_audit_event(as_user, new_request):
    req = new_request("alice")
    _complete_request(as_user, req["id"])

    r = as_user("alice").post(
        f"/v1/requests/{req['id']}/rating",
        json={"stars": 5, "tags": ["Friendly driver"]},
    )
    assert r.status_code == 201

    audit = as_user("dana").get("/v1/audit", params={"event": "rating.created", "target": req["id"]})
    assert audit.status_code == 200
    rows = audit.json()
    assert rows
    assert rows[0]["actor"] == "alice"
    assert rows[0]["target"] == req["id"]
    assert rows[0]["stars"] == 5
    assert rows[0]["tags"] == ["Friendly driver"]


@pytest.mark.ac("RSA-006-AC8")
@pytest.mark.needs_test_hooks
def test_rating_audit_includes_tags_and_excludes_comment(api, as_user, new_request):
    req = new_request("alice")
    _complete_request(as_user, req["id"])
    private_comment = "Confidential feedback text"
    r = as_user("alice").post(
        f"/v1/requests/{req['id']}/rating",
        json={"stars": 5, "tags": ["On time"], "comment": private_comment},
    )
    assert r.status_code == 201

    events = as_user("dana").get("/v1/audit", params={"event": "rating.created", "target": req["id"]}).json()
    assert events and events[0]["tags"] == ["On time"]
    assert "comment" not in events[0]

    logs = api.get("/test/logs", params={"limit": 50}).json()
    assert all(private_comment not in str(line) for line in logs)


@pytest.mark.ac("RSA-006-AC9")
def test_leaderboard_public(api, as_user):
    for client in (api, as_user("alice"), as_user("dana")):
        r = client.get("/v1/drivers/leaderboard")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        assert 1 <= len(rows) <= 10
        scores = [row["avg_stars"] for row in rows]
        assert scores == sorted(scores, reverse=True)
        for row in rows:
            assert row["driver_name"]
            assert row["photo_url"]
            assert isinstance(row["ratings_count"], int) and row["ratings_count"] > 0
            assert isinstance(row["top_tags"], list)
