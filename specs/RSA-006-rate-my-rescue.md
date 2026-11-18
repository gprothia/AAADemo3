---
id: RSA-006
title: Rate My Rescue
status: approved
owner: "@gprothia"
issue: "#11"
---

# RSA-006: Rate My Rescue

## Why
Members currently have no way to share feedback after a roadside rescue, and Marketing/operations want to recognize top-performing drivers and highlight great service.

## Scope
- In: rating a member's own `completed` rescue once (1–5 stars, optional quick tags `"On time"`, `"Friendly driver"`, `"Explained the fix"`, optional comment), thank-you confirmation screen, and a `"Top drivers this month"` leaderboard showing driver full names, photos, average stars, and top praise tags.
- Out: rating rescues that are still `en_route` or not yet `completed`, editing/deleting a rating after submission, comment moderation queue, and driver tipping/payments.

## Acceptance criteria

### RSA-006-AC1 [api]
- **Given** member Alice has a rescue in status `completed` that has not been rated yet
- **When** she sends `POST /v1/requests/{id}/rating` with `{"stars": 5, "tags": ["On time", "Explained the fix"], "comment": "Super quick and helpful!"}`
- **Then** the response is `201` with `request_id`, `driver_name`, `stars` (`5`), `tags` (`["On time", "Explained the fix"]`), `comment` (`"Super quick and helpful!"`), and `created_at`

### RSA-006-AC2 [api]
- **Given** member Alice has a `completed` rescue
- **When** she sends `POST /v1/requests/{id}/rating` with `stars: 0` (or `6`), an unsupported tag, or a `comment` longer than `500` characters
- **Then** the response is `422` with code `VALIDATION_ERROR` and `errors` naming `stars`, `tags`, or `comment` (`SEC-3`, `API-2`); empty or whitespace-only `comment` values are stored as `null`

### RSA-006-AC3 [api]
- **Given** member Alice has a rescue in status `received`, `assigned`, `en_route`, `arrived`, or `cancelled`
- **When** she sends `POST /v1/requests/{id}/rating`
- **Then** the response is `409` with code `RATING_NOT_ALLOWED`

### RSA-006-AC4 [api]
- **Given** member Alice has already submitted a rating for her `completed` rescue
- **When** she sends `POST /v1/requests/{id}/rating` again for the same rescue
- **Then** the response is `409` with code `ALREADY_RATED`

### RSA-006-AC5 [api]
- **Given** a caller without a valid `Authorization: Bearer <token>` header
- **When** they send `POST /v1/requests/{id}/rating`
- **Then** the response is `401` with code `UNAUTHENTICATED` (`AAA-1`)

### RSA-006-AC6 [api]
- **Given** a signed-in dispatcher
- **When** they send `POST /v1/requests/{id}/rating`
- **Then** the response is `403` with code `FORBIDDEN` (`AAA-5`)

### RSA-006-AC7 [api]
- **Given** member Alice is signed in
- **When** she sends `POST /v1/requests/RSA-1001/rating` (Bob's request)
- **Then** the response is `404` with code `REQUEST_NOT_FOUND` (`AAA-7`)

### RSA-006-AC8 [api]
- **Given** member Alice submits a valid rating for her `completed` rescue
- **Then** the audit log (`GET /v1/audit`) has a `rating.created` event with `alice` as `actor`, the request id as `target`, and `stars` recorded (`AAA-9`, `AAA-11`)

### RSA-006-AC9 [api]
- **Given** completed rescues have ratings
- **When** a caller (including an unauthenticated visitor) sends `GET /v1/drivers/leaderboard`
- **Then** the response is `200` with up to the top `10` rated drivers for the current month sorted by `avg_stars` descending, each with `driver_name`, `photo_url`, `avg_stars`, `ratings_count`, and `top_tags`

### RSA-006-AC10 [ui]
- **Given** Alice is signed in and has both a `completed` rescue and an `en_route` rescue
- **When** she opens the Rate My Rescue page
- **Then** she can select the `completed` rescue and sees `"How did we do?"`, 5 star buttons, tags `"On time"`, `"Friendly driver"`, `"Explained the fix"`, and a comment box, while `en_route` rescues cannot be rated

### RSA-006-AC11 [ui]
- **Given** Alice selects 5 stars, toggles `"On time"` and `"Explained the fix"`, enters a comment, and submits
- **When** the rating succeeds
- **Then** she sees `"Thank you for your feedback!"` with a summary of her rescue, driver, stars, tags, and comment, plus actions to rate another rescue or view the leaderboard

### RSA-006-AC12 [ui]
- **Given** a visitor opens the `"Top drivers this month"` leaderboard page
- **Then** they see `"Top drivers this month"` with ranked drivers showing each driver's full name, photo, average stars, rating count, and top tags

## Security & access (AAA)

### Authentication
- `POST /v1/requests/{id}/rating` requires `Authorization: Bearer <token>` (`AAA-1`). Missing or invalid tokens receive `401` `UNAUTHENTICATED`.
- `GET /v1/drivers/leaderboard` and web `/leaderboard` are public (explicit public exception to `AAA-1`).

### Authorization
| Action | Roles allowed |
|---|---|
| Submit a rescue rating (`POST /v1/requests/{id}/rating`) | member (owner only; `404` for others per AAA-7; `403` for dispatcher per AAA-5) |
| View monthly driver leaderboard (`GET /v1/drivers/leaderboard`) | public (any caller, signed in or signed out) |

### Accounting
| Audit event | When | Details recorded |
|---|---|---|
| `rating.created` | A member submits a rating for a completed rescue | `actor`, `target` (request id), `stars`, `tags` |

## Logging
Standard `http.request` line (`LOG-2`) and `event: "audit"` line on `rating.created` (`LOG-5`). Member comments and request bodies are not logged (`LOG-4`).

## API contract
| Method | Path | Success | Errors |
|---|---|---|---|
| POST | /v1/requests/{id}/rating | 201 | 401 UNAUTHENTICATED, 403 FORBIDDEN, 404 REQUEST_NOT_FOUND, 409 RATING_NOT_ALLOWED, 409 ALREADY_RATED, 422 VALIDATION_ERROR |
| GET | /v1/drivers/leaderboard | 200 | — |

## SLO
```slo
p95_latency_ms: 300
error_rate_pct: 1.0
```

## Prototype reference
Link: `prototypes/rate-my-rescue/` (from branch `proto/rate-my-rescue`)

| Screen / element | What the user sees or does | Data behind it | Became |
|---|---|---|---|
| Rescue list sidebar | List of member rescues (`RSA-1042` Completed, `RSA-1045` En route, etc.) | Member's rescues (`id`, `service`, `status`, `driver_name`, `rating`) | RSA-006-AC10 (restricted to `completed` per Issue #11) |
| En-route notice & rating form | Prototype allowed rating `en_route` rescues | `status` check | Rejected per Issue #11 → RSA-006-AC3 (`409` `RATING_NOT_ALLOWED`) |
| `"How did we do?"` 5-star selector | Interactive 1–5 star buttons | `stars` (integer 1–5) | RSA-006-AC1, RSA-006-AC2, RSA-006-AC10 |
| Quick feedback tags | Toggle pills: `"On time"`, `"Friendly driver"`, `"Explained the fix"` | `tags` (validated enum list) | RSA-006-AC1, RSA-006-AC2, RSA-006-AC10 |
| Comment box | Optional free-text `<textarea>` | `comment` (not logged per LOG-4) | RSA-006-AC1, RSA-006-AC10 |
| Submit Rating button | Submits rating (prototype allowed re-rating) | `POST /v1/requests/{id}/rating` (`rating.created` audit) | RSA-006-AC1, RSA-006-AC4 (one-time only per Issue #11), RSA-006-AC8 |
| Thank-you screen | `"Thank you for your feedback!"`, summary card, action buttons | Submitted rating summary | RSA-006-AC11 |
| `"Top drivers this month"` leaderboard | Public ranked list with driver full name, photo, average stars, count, top tags | `GET /v1/drivers/leaderboard` | RSA-006-AC9, RSA-006-AC12; Open question on `AAA-1` |

## Edge cases & errors
- Rating a non-completed rescue (`received`, `assigned`, `en_route`, `arrived`, `cancelled`): `409` `RATING_NOT_ALLOWED`.
- Rating an already-rated rescue: `409` `ALREADY_RATED`.
- `stars` not an integer in `1..5`, or unknown tag in `tags`: `422` `VALIDATION_ERROR` (`SEC-3`).
- Unknown request id or another member's request: `404` `REQUEST_NOT_FOUND` (`AAA-7`).
- Dispatcher calling member rating endpoint: `403` `FORBIDDEN` (`AAA-5`).

## Test data
Seeded users `alice`, `bob` (members), `dana` (dispatcher); seeded request `RSA-1001` (Bob's). Tests create their own `completed` and `en_route` requests via API / `/test/...` hooks as needed.

## Open questions
- [x] (Business) What is the maximum length for a member `comment` (e.g. `500` characters) and should empty/whitespace-only comments be stored as `null`? → `500` characters max; empty/whitespace-only comments stored as `null`.
- [x] (Business) On the `"Top drivers this month"` leaderboard, how many drivers should be shown (e.g. top 5 or top 10), and should drivers with 0 ratings this month be excluded? → Show top `10` rated drivers.
- [x] (IT / Security — `AAA-1`) `AAA-1` requires `Authorization: Bearer <token>` on every `/v1` endpoint except sign-in, while Issue #11 says the leaderboard can be public. Should `GET /v1/drivers/leaderboard` be an explicit public exception to `AAA-1`, or should `/v1/drivers/leaderboard` require a token (with `services/web` rendering `/leaderboard` publicly using a server-side token)? → `GET /v1/drivers/leaderboard` is public (explicit exception to `AAA-1`).
- [x] (IT / Security — `LOG-4`) Confirm `driver_name` and `photo_url` on the public leaderboard are approved for public display and that member `comment` text is excluded from application logs. → Confirmed: `driver_name` and `photo_url` are approved for public display, and `comment` text is excluded from logs.
