# Tasks

> Serial, one agent. Timeboxes are agent-execution estimates and total **210 min (3.5 h)**.
> A task is done only when its stated verification passes. References: `design.md` §N, `specs/<capability>`.
>
> **Cut line**: after group 5, the core is complete and demoable through the API.
> **If behind schedule, drop in this order**: (1) why-not depth: keep rule codes, drop the verification hint and prose polish,
> (2) match alternatives and `--explain` detail, (3) `mission history` endpoint and command,
> (4) admin CLI commands for org, member and skill (seed covers them). **Never cut** tenant-isolation or separation-of-duties tests.

## 1. Scaffolding (15 min)

- [x] 1.1 Create the uv workspace (server package `mission_control`, cli package `mc` with its own light dependencies), ruff config, `docker-compose.yml` (postgres:16 with healthcheck), and a `Makefile` (up, migrate, seed, run, test, test-unit, demo, lint) following design §3.1. Verify that `make up` reports Postgres healthy, `uv run mc --help` prints help, and `uv run ruff check` passes.
- [x] 1.2 Add `config.py`, an injectable `Clock` (real by default, fixed in tests), the FastAPI app factory with `GET /healthz`, a per-request session dependency, and the pytest harness (test database, connection-level transaction rollback through a dependency override, base factories). Verify that `make test` runs a passing `/healthz` API test against real Postgres.

## 2. Data model, auth and tenancy (45 min)

- [x] 2.1 Implement all ORM models from design §4 (including `notifications` and the WITHDRAWN assignment state), with `UNIQUE(org_id, id)` on parents and composite tenant FKs (§4.1), plus Alembic migration 0001 with a hand-written `btree_gist` extension and the `no_double_booking` exclusion constraint, carrying a do-not-remove comment (§8). Verify that `make migrate` succeeds, and DB tests show (a) overlapping ACCEPTED assignments for one crew member raise SQLSTATE 23P01 while touching half-open periods do not, and (b) an assignment referencing another org's crew member fails the FK.
- [x] 2.2 Implement the domain error hierarchy and problem+json mapping (§9), argon2 password hashing, `POST /v1/auth/login` (org-scoped JWT), `GET /v1/me`, `get_ctx` (which loads an active membership on every request) and `require_role`. Verify with API tests: login succeeds; a wrong password and a non-member org return the identical error; missing, expired or tampered tokens get 401; a deactivated membership is refused (specs/tenancy-and-access).
- [x] 2.3 Implement `TenantRepository(session, ctx)`, the append-only audit service, and the endpoints for org settings (`approvals_required`, `recovery_buffer_days`, `stale_offer_days`) and members (§5). Verify with API tests: a Lead or Crew member changing settings gets 403; a Director adds and deactivates members; a settings change writes an audit event; **an isolation test confirms Org A cannot list, read or modify Org B members (404)**.

## 3. Crew profiles (25 min)

- [x] 3.1 Implement the skill taxonomy (Director-only, case-insensitive unique per org, deactivate) and crew profile endpoints with crew visibility limits. Verify with API tests: a duplicate name gets 409; the same name in another org succeeds; a Crew member reading another profile gets 404; **an isolation test covers skills and crew profiles**.
- [x] 3.2 Implement crew skills: self-declare (UNVERIFIED), verify by a Director or Lead with an optional level adjustment and cert expiry, **no self-verification**, and editing a verified skill sets it back to UNVERIFIED while keeping the last verified level (specs/crew-profiles). Verify with API tests for each scenario, including a Lead with a crew profile getting 403 when verifying themselves.
- [x] 3.3 Implement unavailability windows (crew for self, Director for anyone, validation) and the privacy view: Leads see LEAVE and TRAINING categories, MEDICAL and OTHER as "Unavailable", and never the note. Verify with API tests for the Lead view and the Director view, and the invalid-window rejection.

## 4. Missions, lifecycle and assignments (45 min)

- [x] 4.1 Implement `domain/lifecycle.py`: the transition table, guards (`can_submit`, `can_approve` with SoD for both submitter and owner, ownership), `allowed_actions` and the approval-count rule (§6). Verify with table-driven unit tests covering every legal and illegal transition and the SoD guards for a Lead and a Director.
- [x] 4.2 Implement mission create, read, update and list (codes from `mission_seq`, window validation, Crew see only their assigned missions), slots and requirements CRUD, and revision increments on material change (§6). Verify with API tests: the code format is ART-N and accepted wherever a mission is referenced; an invalid window gets 422; an unknown or other-org skill is rejected; **isolation tests cover missions and slots**.
- [x] 4.3 Implement assignments: manual offer (DRAFT only, headcount and one-per-mission checks under the mission row lock), accept (unavailability check, `blocked_period` including the buffer, 23P01 mapped to 409 naming the conflicting mission), decline (reason required), release, crew withdrawal (§6.1: reason required, DRAFT/PENDING/APPROVED only, back to DRAFT through the material-change path, `crew.withdrew` notification to the owner in the same transaction), and rejecting new unavailability that overlaps an ACCEPTED assignment. Verify with API tests including a **concurrent double-accept using two committing connections** where exactly one succeeds; a Crew member accepting someone else's offer getting 404; an empty decline or withdraw reason getting 422; withdrawing from an APPROVED mission returning it to DRAFT with approvals voided and the owner notified; withdrawing from an ACTIVE mission getting 409; withdrawn crew freeing their blocked period.
- [x] 4.4 Implement the transition endpoints: submit gate (lists unfilled slots), the started-window guard on submit and approve (`starts_at > clock.now()`), approve and reject with `revision` (stale gets 409), N-of-M using the snapshot policy, auto-withdraw on material change, released crew sending the mission back to DRAFT, cancel releasing assignments, and audit events plus `GET /missions/{ref}/history`. Verify with API tests: **a Lead and a Director each fail to approve their own mission (403)**; two approvals required; a policy change doesn't affect pending missions; an edit while pending voids approvals; a rejection requires a reason; submitting or approving after the start date gets 409 (fixed clock).

## 5. Matching engine (35 min)

- [x] 5.1 Implement `domain/matching/model.py` and `eligibility.py` (every rule in §7.2, collecting all failures, the `UNVERIFIED_WOULD_QUALIFY` flag, the buffer-aware overlap, privacy-safe details, closeness tiers 0-3 with top-5 truncation plus `excluded_total`) with `explain.py` reason strings. Verify with unit tests: unverified claim excluded and flagged; cert expiring mid-mission; recovery buffer; PROPOSED elsewhere doesn't exclude; declined crew excluded; MEDICAL detail hidden; why-not ordered Bob (unverified) then Dana (one level short) then Frank (no skill).
- [x] 5.2 Implement `scoring.py` (the five factors and weights in §7.3, workload measured relative to mission start). Verify with unit tests for workload ordering, right-sizing preferring the level-2 medic over the level-5 one, the pending-offer penalty, and scores bounded to [0,1].
- [x] 5.3 Implement `solver.py` (the `|P| x (|C|+|P|)` cost matrix, finite INFEASIBLE value, dummy columns, fill-first M), alternatives (top 3), and assembly of `MatchResult`. Verify with unit tests: **greedy trap gives Alice=Commander, Bob=Geologist**; no eligible crew gives every position unfilled without an error; **only level-2 crew for a level-3 slot leaves it unfilled (no under-qualified fallback)**; partial fill; identical output across repeated runs with tied scores.
- [x] 5.4 Implement the matching service (bulk loading without N+1), `GET /missions/{ref}/match` (DRAFT only, open positions only, read-only) and `POST /match/apply` (explicit pairs, re-validated, each pair independent). Verify with API tests: the match creates no rows; apply creates PROPOSED assignments; a stale pair is reported while the others apply; a non-DRAFT mission gets 409.

> ---------------- **CUT LINE**: everything above is the demoable core ----------------

## 6. CLI (30 min)

- [x] 6.1 Implement `mc` foundations: httpx client, session file (0600, `MC_API_URL`), problem+json mapped to one-line messages and exit codes (§10), global `--json`, Rich output helpers with `Next:` hints, and `login`/`logout`/`whoami` with a hidden password prompt. Verify with CliRunner tests using httpx `MockTransport`: exit codes for 401/403/404/409/connection errors; `--json` output parses; session file mode is 0600.
- [x] 6.2 Implement mission commands (`list`, `create`, `show`, `edit`, `slot add/remove`, `offer`, and every transition, including `reject --reason`), `assignment list/accept/decline/withdraw/release` (decline and withdraw prompt for a reason if `--reason` is missing and never send it empty), and `profile` (show, skill set/remove, unavailable add/list/remove), plus `crew verify`. Verify with CliRunner tests that commands send the right requests, that `create` prints the code and a `Next:` hint, and that `withdraw` without `--reason` prompts and rejects empty input.
- [x] 6.3 Implement `mc match` (table, unfilled highlighting, `--explain [ROLE]`, `--all`, `--apply [--only]`), `GET /v1/inbox` plus `mc inbox` (unread notifications first for every role, with `POST /notifications/{id}/dismiss` and `mc inbox dismiss ID`; role-shaped: a Director's own submissions marked as needing another approver; Leads see PROPOSED offers with their age, flagged stale past `stale_offer_days`), and the admin commands `org settings`, `member`, `skill` and `crew list/show/create`. Verify with an API test for each role's inbox, including a 4-day-old offer flagged and a 2-day-old one not flagged at threshold 3 (fixed clock); a withdrawal notification shown to the owner only, **not visible to another member or another org (404 on dismiss)**, and gone after dismissal while its audit event remains; and CliRunner tests for match output and `--apply`.

## 7. Seed, end-to-end and docs (15 min)

- [x] 7.1 Implement `seed.py` with the designed scenarios from design §16 (two orgs, two Directors in Artemis, the greedy-trap pair, an expired cert, an unverified claim, leave, a MEDICAL window, a crew member inside the recovery buffer) that can be re-run safely and prints logins. Verify that `make seed` runs twice without error, and that a match on the seeded demo mission shows the expected Commander and Geologist suggestions.
- [x] 7.2 Write the e2e test (live server and CliRunner) for the full journey in specs/cli: Lead creates and matches, Crew accept, Lead submits, a different Director approves; also cross-tenant `mc mission show` gets 404 with exit code 4. Then write `scripts/demo.sh` and the README (prerequisites, 3-command quick start, demo walkthrough, link to design.md). Verify that `make test` is fully green and that `make up && make migrate && make seed && make demo` works from a clean `docker compose down -v`.

## 8. CLI self-guidance (added after review, 15 min)

- [x] 8.1 Add `mc guide [TOPIC]` with the four workflow guides as data in the CLI package, rendered by role with the command prefix applied. Verify with CliRunner tests that the topic list and one guide render, and that every guide command resolves to a real `mc` command.
- [x] 8.2 Make bare `mc` show a getting-started screen from the local session (no API call). Verify with tests for the logged-out and logged-in screens.
- [x] 8.3 Add confirmation prompts with `--yes` to `mission cancel`, `mission abort`, `assignment release` and `member deactivate`, describing the consequence. Verify with tests that declining sends no request and `--yes` skips the prompt.

- [x] 8.4 Show every slot in the Lead's inbox with accepted and offered crew (slot order), an "N of M accepted" count, readable offer ages and a waiting/next-step hint. Verify with an API test of the inbox data and a CliRunner test of the layout.
- [x] 8.5 Notify the mission owner once when the last position is accepted (`mission.fully_crewed`). Verify with API tests that earlier acceptances create no notification and the last one creates exactly one.

## Workflow follow-up

- Export `design.md` (plus links to the specs) as the submitted design document, together with the implementation and session transcripts.
- Archive the change with `/opsx:archive` once the review is complete.
