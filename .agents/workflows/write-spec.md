---
description: Turn a feature-request issue into an approved spec (rules in AGENTS.md section 2)
---

# /write-spec

Usage: `/write-spec #<issue number>`. Follow `AGENTS.md`, section 2 (Specs).

// turbo
1. Read the request and every comment: `gh issue view <n> --comments`.
2. Read `standards/README.md` and the standards it lists, `specs/_TEMPLATE.md`, and the existing specs in the same area (e.g. all `RSA-*`).
// turbo
3. `git checkout main && git pull`, then `git checkout -b feat/<id-lower>-<short-name>`.
4. Write `specs/<ID>-<short-name>.md` from the template, `status: draft`, filling every enterprise section (AAA, Logging, API contract, SLO). Turn the request
   into exact acceptance criteria. Every decision not in the issue or its comments goes under
   Open questions as `- [ ]`.
// turbo
5. `python scripts/check_spec.py specs/<file>`. Fix every error; review every warning.
6. Show the user the spec and the open questions. Wait.
7. Apply the answers (tick each question with its answer), re-run step 5. When the user says
   the spec is agreed, set `status: approved` and commit `<ID>: add spec`.
8. Draft a comment for the issue: link to the spec file on the branch and a short list of the
   decisions. Show it, and post it with `gh issue comment <n> --body-file ...` when the user
   agrees. Never edit the issue description.
9. Next step: `/build-spec specs/<file>`.
