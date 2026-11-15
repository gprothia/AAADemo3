---
id: RSA-004
title: Track my rescue
status: draft
owner: "@gprothia"
issue: "#4"
---

# RSA-004: Track my rescue

## Why
When members are stranded, the worst part is not knowing when help will arrive. One page
shows how far away help is and who is coming. (From the request and Marketing's prototype.)

## Scope
- In: a tracking page for one of the member's own requests: ETA, progress, driver's first
  name and truck; dispatchers can open it for any request.
- Out, pending open questions: live map, share link, calling the driver, cancelling.

## Acceptance criteria

### RSA-004-AC1 [api]
- **Given** Alice's request is `assigned` with `eta_minutes` 18 and driver "Maria Lopez (Truck 7)"
- **When** Alice calls `GET /v1/requests/{id}/tracking`
- **Then** the response is `200` with `status` `assigned`, `eta_minutes` 18, `driver` `{"first_name": "Maria", "truck": "Truck 7"}`, and `steps` listing `received`, `assigned`, `en_route`, `arrived` with `done` true for the first two

### RSA-004-AC2 [api]
- **Given** Alice's tracking response
- **Then** it contains no phone number: no `phone` field, and no driver surname

### RSA-004-AC3 [api]
- **Given** Bob's request `RSA-1001`
- **When** Alice calls `GET /v1/requests/RSA-1001/tracking`
- **Then** the response is `404` with code `REQUEST_NOT_FOUND` (standards/aaa.md AAA-7)

### RSA-004-AC4 [api]
- **Given** a signed-in dispatcher
- **When** they call `GET /v1/requests/RSA-1001/tracking`
- **Then** the response is `200`

### RSA-004-AC5 [api]
- **Given** a request in status `completed`
- **When** its member calls the tracking endpoint
- **Then** the response is `200` with `eta_minutes` `null` and every step `done`

### RSA-004-AC6 [ui]
- **Given** Alice is signed in and her request is `assigned` with ETA 18 and driver "Maria Lopez (Truck 7)"
- **When** she opens `/requests/{id}/track`
- **Then** she sees "Your rescue is on the way", "18 min", the step "Truck assigned" marked done and "Maria · Truck 7"

### RSA-004-AC7 [ui]
- **Given** Alice's request is `completed`
- **When** she opens its tracking page
- **Then** she sees "Your rescue is complete" and no ETA

## Security & access (AAA)

### Authentication
Sign-in required (AAA-1). The prototype's share link would open without sign-in: see open
questions; not included until decided.

### Authorization
| Action | Roles allowed |
|---|---|
| Track own request | member |
| Track any request | dispatcher |

### Accounting
| Audit event | When | Details recorded |
|---|---|---|
| `tracking.viewed` | Someone opens a tracking view | actor, target (request id). *Proposed; see open questions* |

## Logging
Standard `http.request` line. The driver's phone and any location coordinates are never
returned or logged (LOG-4). The location text of the request is not logged.

## API contract
| Method | Path | Success | Errors |
|---|---|---|---|
| GET | /v1/requests/{id}/tracking | 200 | 401, 404 REQUEST_NOT_FOUND |

## SLO
This page is polled while members wait, so it is held tighter than the default.
```slo
p95_latency_ms: 250
error_rate_pct: 0.5
```

## Prototype reference
Link: `prototypes/track-my-rescue/` (from branch `proto/track-my-rescue`). Screens:
`screens/1-tracking.png`, `screens/2-share-with-family.png`.

| Prototype element | What the member sees or does | Data behind it | Became |
|---|---|---|---|
| Big ETA, counting down | "18 min" | `eta_minutes` (set by dispatcher, RSA-003) | AC1, AC6 |
| "Refreshes every 5 seconds" | Page updates itself | Polling the API | SLO; open question (rate) |
| Progress tracker | Received → Truck assigned → On the way → Arrived | `status` + `history` | AC1, AC5, AC6, AC7 |
| Map with moving truck | Truck's live position | **No GPS data exists today**; location is personal data | Open question; out of scope |
| Driver card | Name, truck, rating, rescues, **phone number** | `driver` text; rating/rescues don't exist; phone is an employee's personal data | AC1, AC2 (first name + truck only); open questions |
| "Call driver" | Phones the driver directly | Driver's personal number | Open question |
| "Share with family" | **Link anyone can open, no sign-in** | Public, unauthenticated access to a member's rescue | Open question (conflicts with AAA-1) |
| "Cancel request" | Cancels the rescue | A new state change, not specified anywhere | Open question; separate request |

## Edge cases & errors
- Request with no driver yet: `driver` is `null`; the page says "Assigning a truck".

## Test data
Seeded: Bob's request `RSA-1001` (assigned, ETA 25, "Sam (Truck 12)").

## Open questions

**Business**
- [ ] Share with family: offer it? (If yes, see the security question below.)
- [ ] Show the driver's phone, or route calls through the dispatch centre?
- [ ] Live map: we have no truck GPS data today. Leave it out of this feature?
- [ ] Cancel from this page: a separate feature request (it changes data and needs its own rules)?
- [ ] How fresh must it be: every 5 seconds as in the prototype, or every 30 seconds?

**IT / security**
- [ ] AAA-1: the share link opens with no sign-in, which the standard forbids. Drop it, or change the standard to allow a read-only, expiring link (a separate standards PR)?
- [ ] LOG-4: the driver's phone and live location are personal data. Agree they are never shown or logged here?
- [ ] AAA-9: audit every view of a tracking page (`tracking.viewed`), given it shows where a member is stranded?
- [ ] SLO: polling every 5 seconds multiplies load about 6× versus 30 seconds. Agree p95 250 ms and 0.5% errors at the chosen rate?
