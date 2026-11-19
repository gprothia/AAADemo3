---
id: RSA-007
title: Sample seed data
status: implemented
owner: "@gprothia"
issue: "#13"
---

# RSA-007: Sample seed data

## Why
When the app starts with `SEED_TEST_DATA=true`, only `RSA-1001` (for Bob) is seeded, leaving Alice with an empty list and dispatchers with a single request. Pre-loading realistic sample requests and ratings across all members, help types, and statuses makes the portal immediately useful for demos and exploratory testing.

## Scope
- In: Seeding in-memory sample requests covering all seeded members (`alice`, `bob`), all help types (`tow`, `battery`, `flat_tyre`, `lockout`, `fuel`), and all statuses (`received`, `assigned`, `en_route`, `arrived`, `completed`, `cancelled`), plus pre-populated ratings on a few completed requests, when `SEED_TEST_DATA=true`.
- Out: Persistent database storage; modifying `RSA-1001` (which existing tests depend on); adding new users or roles.

## Acceptance criteria

### RSA-007-AC1 [api]
- **Given** the API starts with `SEED_TEST_DATA=true`
- **When** member `alice` calls `GET /v1/requests`
- **Then** the response is `200`, includes her seeded requests (`RSA-1002`, `RSA-1003`, `RSA-1005`), and does not include `bob`'s seeded requests (`RSA-1001`, `RSA-1004`, `RSA-1006`, `RSA-1007`) (AAA-7)

### RSA-007-AC2 [api]
- **Given** the API starts with `SEED_TEST_DATA=true`
- **When** dispatcher `dana` calls `GET /v1/requests`
- **Then** the response is `200` and includes `RSA-1001` through `RSA-1007`, covering both members (`alice`, `bob`), all 5 help types (`tow`, `battery`, `flat_tyre`, `lockout`, `fuel`), and all 6 statuses (`received`, `assigned`, `en_route`, `arrived`, `completed`, `cancelled`)

### RSA-007-AC3 [api]
- **Given** the API starts with `SEED_TEST_DATA=true`
- **When** `alice` calls `GET /v1/requests/RSA-1003` and `bob` calls `GET /v1/requests/RSA-1006`
- **Then** each response is `200` and includes a pre-populated `rating` object (`request_id`, `driver_name`, `stars`, `tags`, `comment`, `created_at`)

### RSA-007-AC4 [api]
- **Given** seeded requests exist
- **When** an unauthenticated caller calls `GET /v1/requests`
- **Then** the response is `401` with code `UNAUTHENTICATED` (AAA-1)
- **When** member `bob` calls `GET /v1/requests/RSA-1002` (`alice`'s)
- **Then** the response is `404` with code `REQUEST_NOT_FOUND` (AAA-7)

### RSA-007-AC5 [ui]
- **Given** `alice` signs in
- **When** she opens **My requests**
- **Then** she sees her seeded requests (`RSA-1002`, `RSA-1003`, `RSA-1005`) across multiple statuses and none of `bob`'s requests

### RSA-007-AC6 [ui]
- **Given** `dana` (dispatcher) signs in
- **When** she opens **All requests**
- **Then** she sees seeded requests for both `alice` and `bob` across all statuses

## Security & access (AAA)

### Authentication
Every `/v1` endpoint requires `Authorization: Bearer <token>` (AAA-1). Unauthenticated callers receive `401` with code `UNAUTHENTICATED`.

### Authorization
| Action | Roles allowed |
|---|---|
| List and view own seeded requests | member |
| List and view all seeded requests | dispatcher |

Members requesting another member's seeded request receive `404` with code `REQUEST_NOT_FOUND` (AAA-7).

### Accounting
None: startup seeding and reading seeded data do not mutate state on behalf of a user.

## Logging
Standard `http.request` JSON log line per request (`standards/logging.md` LOG-1, LOG-2). Seeded phone numbers are fake `555` numbers and are masked if ever logged (LOG-4).

## API contract
| Method | Path | Success | Errors |
|---|---|---|---|
| GET | /v1/requests | 200 | 401 |
| GET | /v1/requests/{id} | 200 | 401, 404 REQUEST_NOT_FOUND |

## SLO
```slo
p95_latency_ms: 300
error_rate_pct: 1.0
```

## Edge cases & errors
- When `SEED_TEST_DATA=false`, no sample requests or ratings are pre-loaded on startup.
- `RSA-1001` keeps its exact existing attributes (`bob`, `battery`, `assigned`, ETA `25`, driver `Sam (Truck 12)`) so existing tests remain valid.
- Seeded `completed` requests that already have a `rating` reject duplicate rating submissions with `409` (`ALREADY_RATED`).

## Test data
| ID | Member | Type | Status | Driver | Rated |
|---|---|---|---|---|---|
| `RSA-1001` | `bob` | `battery` | `assigned` | `Sam (Truck 12)` | No |
| `RSA-1002` | `alice` | `flat_tyre` | `en_route` | `Maria (Truck 07)` | No |
| `RSA-1003` | `alice` | `tow` | `completed` | `Sam (Truck 12)` | Yes (5 stars) |
| `RSA-1004` | `bob` | `lockout` | `received` | — | No |
| `RSA-1005` | `alice` | `fuel` | `arrived` | `Maria (Truck 07)` | No |
| `RSA-1006` | `bob` | `tow` | `completed` | `Maria (Truck 07)` | Yes (4 stars) |
| `RSA-1007` | `bob` | `flat_tyre` | `cancelled` | — | No |

## Open questions
- [x] Which members, request types, and statuses should be included in the default sample data? → All members (`alice`, `bob`), all 5 request types (`tow`, `battery`, `flat_tyre`, `lockout`, `fuel`), and all 6 statuses (`received`, `assigned`, `en_route`, `arrived`, `completed`, `cancelled`) (#13)
- [x] Should any seeded completed requests also include a pre-populated rating? → Yes, a few (`RSA-1003` and `RSA-1006`) (#13)
- [x] Are there any existing expectations or demos that rely on Alice starting with zero requests? → No (#13)
