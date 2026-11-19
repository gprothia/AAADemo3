"""API tests generated from specs/RSA-007-sample-seed-data.md."""

import pytest


@pytest.mark.ac("RSA-007-AC1")
def test_alice_sees_own_seeded_requests(as_user):
    r = as_user("alice").get("/v1/requests")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert {"RSA-1002", "RSA-1003", "RSA-1005"} <= ids
    assert ids.isdisjoint({"RSA-1001", "RSA-1004", "RSA-1006", "RSA-1007"})


@pytest.mark.ac("RSA-007-AC2")
def test_dana_sees_all_seeded_requests_types_and_statuses(as_user):
    r = as_user("dana").get("/v1/requests")
    assert r.status_code == 200
    rows = {row["id"]: row for row in r.json()}
    expected_ids = {"RSA-1001", "RSA-1002", "RSA-1003", "RSA-1004", "RSA-1005", "RSA-1006", "RSA-1007"}
    assert expected_ids <= set(rows)
    seeded = [rows[rid] for rid in expected_ids]
    assert {"alice", "bob"} <= {row["member"] for row in seeded}
    assert {"tow", "battery", "flat_tyre", "lockout", "fuel"} <= {row["type"] for row in seeded}
    assert {"received", "assigned", "en_route", "arrived", "completed", "cancelled"} <= {
        row["status"] for row in seeded
    }


@pytest.mark.ac("RSA-007-AC3")
def test_seeded_completed_requests_include_ratings(as_user):
    for member, request_id in [("alice", "RSA-1003"), ("bob", "RSA-1006")]:
        r = as_user(member).get(f"/v1/requests/{request_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "completed"
        rating = body.get("rating")
        assert isinstance(rating, dict)
        assert rating["request_id"] == request_id
        assert isinstance(rating["driver_name"], str) and rating["driver_name"]
        assert 1 <= rating["stars"] <= 5
        assert isinstance(rating["tags"], list)
        assert "comment" in rating
        assert isinstance(rating["created_at"], str) and rating["created_at"]


@pytest.mark.ac("RSA-007-AC4")
def test_seeded_requests_auth_and_isolation(api, as_user):
    unauth = api.get("/v1/requests")
    assert unauth.status_code == 401
    assert unauth.json()["code"] == "UNAUTHENTICATED"

    other = as_user("bob").get("/v1/requests/RSA-1002")
    assert other.status_code == 404
    assert other.json()["code"] == "REQUEST_NOT_FOUND"
