# AGENTS.md: the one rulebook for coding agents

Antigravity, Claude Code, Gemini CLI and other agents read this file first. The saved commands
in `.agents/workflows/` only list steps; when they say "follow the rules", they mean this file
and the standards it points to.

**The app:** Roadside Assistance, a demo member and dispatcher portal for AAA. Members ask
for help (tow, battery, flat tyre, lockout, fuel); dispatchers move each request along.

## The cycle

```
feature request (GitHub issue, plain language)  or  a vibe-coded prototype
  → enterprise spec (specs/*.md, approved by a person)   /write-spec #<issue>
  → tests → code → style checks → local run
  → GKE sandbox: app as pods, ALL tests run (new + regression)
  → evidence posted to GitHub → pull request              /build-spec specs/<file>
  → CI re-checks independently → a person reviews and merges
  → merge deploys to UAT on Cloud Run, smoke-tested, rolled back on failure
```

## Never
- Commit to `main`, merge, approve, force-push, or delete branches you didn't create.
- Change a spec's acceptance criteria, or weaken a test, to make something pass.
- Take a business decision the issue doesn't contain. Ask, or list it as an open question.
- Overwrite a GitHub issue's description. Add a comment instead.
- Post an issue, comment or PR before showing the user its text.
- Open a PR without a green GKE sandbox run for the exact commit being proposed.
- Change anything in `standards/` as part of a feature. Standards change in their own PR.

---

## 0. Standards come first

Read `standards/README.md` and the files it lists before writing a spec or code:
`aaa.md` (sign-in, roles, audit), `api.md`, `logging.md`, `slo.md`, `code-style.md`,
`security.md`. Every rule there applies to every feature. Quote rule IDs (e.g. AAA-7) in
specs and plans where they decide something.

## 1. Feature requests (GitHub issues)

A feature request says **what someone wants and why**, in plain words. It is not a spec.
- Use the "Feature request" form's sections (`.github/ISSUE_TEMPLATE/feature-request.yml`):
  `### Why`, `### Who`, `### What they want`, `### Example`, `### Open questions`.
- No Given/When/Then, no rule IDs, no status codes. Those belong in the spec.
- Title `[Request] <plain description>`, label `request`.
- Agents: draft to `.tmp/feature-request.md`, show the user, then
  `gh issue create --title ... --label request --body-file .tmp/feature-request.md`.

## 2. Specs

The spec is the agreement and the source of truth. `scripts/check_spec.py` enforces the
mechanical rules, including the enterprise sections; CI runs it on every PR.

**File and header**
- `specs/<ID>-<short-kebab-name>.md`, e.g. `specs/RSA-004-track-my-rescue.md`. Copy
  `specs/_TEMPLATE.md` and keep every section.
- IDs: area prefix + 3 digits (`RSA-` features, `STD-` shared standards). Next free number;
  never reuse one.
- Front matter `id` (matches the file name), `title`, `status`, `owner` (`@handle`),
  `issue` (`"#<n>"`). Heading `# <ID>: <title>`.

**Status**
- `draft` while questions are open. `approved` only when a person says so.
  `implemented` in the PR that ships it.
- `approved`/`implemented` specs have no unticked `- [ ]` questions. A ticked question
  carries its answer: `- [x] Show the driver's phone? → No (#6)`.

**Acceptance criteria**
- `### <ID>-AC<n> [api]`, `[ui]` or `[api,ui]`. Numbered from 1, unique, never renumbered;
  retire with `### ~~<ID>-AC<n> [tag]~~`.
- **Given** and **Then** (and **When** if there's an action). Every Then is checkable:
  exact status codes, error codes, field names, visible text. Tolerances go in the spec.
- Include the **control criteria** the enterprise sections imply: a `403` for each role that
  is not allowed, a `404` for someone else's record (AAA-7), an audit event per change.

**Enterprise sections (required)**
- **Security & access (AAA)**: Authentication; Authorization as a table of action → roles;
  Accounting as a table of audit events (or "None" with the reason).
- **Logging**: what's logged; any personal data and how it's masked.
- **API contract**: a table of method, path, success code, error codes.
- **SLO**: a ```` ```slo ```` block with `p95_latency_ms` and `error_rate_pct`. It governs the
  production canary (`standards/slo.md`).

Decisions come from the issue and its comments only. When the spec is written, comment on the
issue with a summary of the decisions (never edit the issue description).

## 3. Tests

- API: `tests/api/test_<id-lower>.py`, pytest + httpx, each test `@pytest.mark.ac("<AC-ID>")`.
  Use the fixtures in `tests/api/conftest.py`: `api` (signed out), `as_user("alice")`,
  `token("dana")`, `new_request()`.
- UI: `tests/ui/<id-lower>.spec.ts`, Playwright, each test `{ tag: '@<AC-ID>' }`. Sign in
  with `signIn(page, 'alice')` from `tests/ui/helpers.ts`; set up data through the API with
  `API`, `apiToken()` and `apiHeaders()` from the same file.
- Every non-retired criterion has at least one test per tag. Given/When/Then maps to
  arrange/act/assert. Assert the exact values the spec names.
- Base URLs from `API_BASE_URL` / `WEB_BASE_URL` only. Tests create their own data, run in
  any order, and never call real third-party services.
- Playwright: `getByRole` / `getByLabel` / `getByTestId`; no CSS paths, no fixed sleeps.
- The **whole** suite is the regression suite: every run executes all tests, old and new.
- Tests that call `/test/...` endpoints are marked so UAT can skip them: pytest
  `@pytest.mark.needs_test_hooks`; Playwright `{ tag: ['@<AC-ID>', '@needs-test-hooks'] }`.

## 4. The app

- `services/api`: FastAPI, versioned `/v1` paths. In-memory storage, seeded at start
  (`SEED_TEST_DATA=true`): users `alice`, `bob` (members), `dana` (dispatcher); request
  `RSA-1001` (Bob's). Use `require("member", ...)` for authorization, `audit(...)` for every
  change, `ApiError(status, code, message)` for errors. Logging and request IDs are automatic.
- **Test-only endpoints** go under `/test/...`, are registered only `if TEST_HOOKS:` (env
  `ENABLE_TEST_HOOKS`, **off by default**), and are hidden from the API schema. Only
  `deploy/app/api.yaml` (sandboxes) turns them on.
- `services/web`: FastAPI-rendered pages. The browser only talks to the website; it calls
  the API server-side with the signed-in user's token (cookie `session`).

## 4b. Environments

| Environment | Where | Deployed by | Test hooks |
|---|---|---|---|
| Local | your machine | you / the agent | on (`ENABLE_TEST_HOOKS=true`) |
| Dev sandbox | GKE `dev-<branch>` | `scripts/sandbox.sh` before the PR | on |
| PR sandbox | GKE `pr-<N>` | CI on every PR | on |
| **UAT** | **Cloud Run** `aaademo3-uat-web` / `-api` | **CI on every merge to `main`** | **off** |

Agents never deploy to UAT themselves; merging is a person's decision and the pipeline does
the rest.

## 5. Delivery

**Branches and commits**
- `feat/<id-lower>-<short-name>` from an up-to-date `main`. Commit messages
  `<ID>: <what changed>`. Spec, tests and code for one spec travel together.

**Gates before a PR, in order**
1. `python scripts/check_spec.py` and `python scripts/check_traceability.py` pass.
2. Style: `ruff format . && ruff check .` and `cd tests/ui && npx eslint .` pass.
3. Local run: both suites green against the app on this machine.
4. Commit everything (the sandbox refuses uncommitted changes, so the evidence matches a commit).
5. `scripts/sandbox.sh all`: Cloud Build images → app staged as pods in `dev-<branch>` on
   GKE → test pod runs **all** tests → reports in `reports/<namespace>/`. Must be green.
6. `git push -u origin HEAD`, open the PR, then `scripts/sandbox.sh publish`: posts the
   result as a commit status and a PR comment listing every test with its criterion.
7. `scripts/sandbox.sh down`.

**Pull request**
- `gh pr create --base main` with a body following `.github/pull_request_template.md`:
  spec link, `Closes #<issue>`, criteria covered, the sandbox result line.
- Print the PR URL. A person reviews: spec diff, then tests, then code.
