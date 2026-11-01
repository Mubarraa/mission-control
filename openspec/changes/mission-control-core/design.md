# Design: Mission Control Core

> The motivation and scope are in `proposal.md`. Behaviour contracts are in `specs/*/spec.md`.
> This document covers **how** the system is built and **why** it is built that way. It is written
> for an engineering team and for an AI coding agent working through `tasks.md`.

## 1. Context

- This is a greenfield repository. Nothing exists yet except OpenSpec scaffolding.
- Design plus implementation has a budget of 3-4 hours, built serially by one agent. That forces a hard line
  between what is **built** and what is **designed for but deferred** (see section 12).
- The reviewer has to be able to run everything locally with `docker` and `uv` and nothing else.
- The CLI goes through a usability review. It is a first-class product surface, not a test harness.

The system's difficulty sits in three places, and the structure of this design follows them:

```
  +--------------------+     +---------------------+     +----------------------+
  |  TENANT ISOLATION  |     |  COMMITMENT LOGIC   |     |  MATCHING            |
  |  enforced by       |     |  who is committed   |     |  who *should* go,    |
  |  structure + DB,   |     |  to what and who    |     |  as a crew, and why  |
  |  not by habit      |     |  signed off; race-  |     |  (incl. why not)     |
  |                    |     |  safe at the DB     |     |                      |
  +--------------------+     +---------------------+     +----------------------+
```

## 2. Goals / Non-Goals

**Goals**
- Make cross-tenant leakage structurally hard: an org filter that is forgotten in one query must not be enough to leak data.
- Make double-booking impossible at the storage layer, including under concurrent requests.
- Keep the lifecycle rules and the matcher in **pure, framework-free code** so they are trivial to test and to read in review.
- Make the matcher **explainable** first and clever second. A lead must be able to trust or override every suggestion.
- Make the CLI coherent: consistent nouns and verbs, readable defaults, `--json` everywhere, and next-step hints.

**Non-Goals (design-level)**
- Horizontal scaling, HA, and multi-region deployment. The target is up to about 500 crew per org and about 20 slots per mission.
- A general workflow engine. The approval policy is deliberately a small set of parameters, not a DSL.
- Team-level (non-separable) matching constraints. The design leaves room for them (section 7.6).

## 3. Architecture

```
  +---------------------+         HTTP/JSON (bearer token)          +----------------------------------+
  |  mc  (cli/ package) |  -------------------------------------->  |  FastAPI app  (api/)             |
  |  Typer + Rich +     |                                           |  routers, Pydantic schemas,      |
  |  httpx              |  <--------------------------------------  |  auth dep -> TenantContext,      |
  |  no server imports  |        problem+json errors                |  error -> RFC 7807 mapping       |
  +---------------------+                                           +----------------+-----------------+
                                                                                     |
                                                                    +----------------v-----------------+
                                                                    |  services/                       |
                                                                    |  load -> call domain -> persist  |
                                                                    |  -> audit, one transaction/req   |
                                                                    +-------+------------------+-------+
                                                                            |                  |
                                                         +------------------v---+     +--------v-----------------+
                                                         |  domain/  (PURE)     |     |  db/                     |
                                                         |  lifecycle rules,    |     |  SQLAlchemy models,      |
                                                         |  matcher, scoring,   |     |  TenantRepository(ctx),  |
                                                         |  explanations        |     |  Alembic migrations      |
                                                         |  no DB, no HTTP      |     +------------+-------------+
                                                         +----------------------+                  |
                                                                                          +--------v--------+
                                                                                          | Postgres 16     |
                                                                                          | btree_gist      |
                                                                                          +-----------------+
```

### 3.1 Repository layout

```
mission-control/
  pyproject.toml              # uv workspace: server package + cli package
  docker-compose.yml          # postgres:16 with healthcheck
  Makefile                    # up, migrate, seed, run, test, test-unit, demo, lint
  src/mission_control/
    config.py                 # settings from env (DATABASE_URL, JWT_SECRET, TOKEN_TTL)
    domain/
      enums.py                # Role, MissionState, AssignmentState, SkillStatus, UnavailCategory
      errors.py               # DomainError hierarchy (NotFound, Forbidden, Conflict, Validation)
      lifecycle.py            # transition table + guards (pure)
      matching/
        model.py              # dataclasses: Position, Candidate, Commitment, MatchResult, ...
        eligibility.py        # hard rules -> list[Exclusion]
        scoring.py            # factor functions + weights
        solver.py             # cost matrix + linear_sum_assignment
        explain.py            # human-readable reasons
    db/
      base.py, session.py     # engine, session per request
      models.py               # ORM models
      repositories.py         # TenantRepository + per-aggregate repos
      migrations/             # Alembic (hand-edited where needed)
    services/                 # auth, members, skills, crew, missions, assignments, matching, inbox, notifications, audit
    api/
      app.py, deps.py         # app factory, get_db, get_ctx, require_role
      errors.py               # DomainError -> problem+json
      schemas/                # Pydantic request/response models
      routers/                # auth, org, members, skills, crew, missions, assignments, inbox
    seed.py                   # demo data (two orgs)
  cli/
    pyproject.toml            # package "mission-control-cli", entry point `mc`
    src/mc/
      main.py                 # Typer app, command groups
      client.py               # httpx wrapper, auth header, error -> exit code
      session.py              # ~/.config/mc/session.json (0600)
      output.py               # Rich tables, --json, next-step hints
      commands/               # auth, inbox, org, members, skills, crew, profile, missions, match, assignments
  tests/
    unit/                     # domain: lifecycle, eligibility, scoring, solver, explain
    api/                      # real Postgres; tenancy, roles, SoD, lifecycle, booking races
    e2e/                      # CLI journey against a live test server
  scripts/demo.sh             # full narrated journey via `mc`
```

**Dependency rule**: `domain` imports nothing from the project. `services` imports `domain` and `db`. `api` imports `services`. `cli` imports nothing from `src/`. This rule is what lets the matcher be reviewed and tested without any infrastructure.

## 4. Data model

```
 organisations 1---* memberships *---1 users
      |                  |
      |                  1
      |                  |
      |               0..1
      +---* skills    crew_profiles 1---* crew_skills *---1 skills
      |                  |    1
      |                  |    +---* unavailability
      |                  *
      +---* missions 1---* mission_slots 1---* slot_requirements *---1 skills
      |        1               1
      |        |               |
      |        +-----* assignments *---1 crew_profiles
      |        +-----* approvals
      +---* audit_events
      +---* notifications *---1 memberships (recipient)
```

| Table | Key columns | Notes |
|---|---|---|
| `organisations` | `id`, `slug` (unique), `name`, `mission_prefix` (e.g. `ART`), `mission_seq`, `approvals_required` (default 1), `recovery_buffer_days` (default 14), `stale_offer_days` (default 3) | `mission_seq` is incremented with `UPDATE ... RETURNING` to generate codes. |
| `users` | `id`, `email` (unique, lower-cased), `name`, `password_hash` | Global identity. Holds no tenant data. |
| `memberships` | `id`, `org_id`, `user_id`, `role`, `active` | `UNIQUE(org_id, user_id)`. **The principal is the membership**, not the user. |
| `skills` | `id`, `org_id`, `name`, `category`, `description`, `active` | Unique index on `(org_id, lower(name))`. |
| `crew_profiles` | `id`, `org_id`, `membership_id` (unique), `display_name`, `bio`, `active` | Optional per membership. |
| `crew_skills` | `id`, `org_id`, `crew_id`, `skill_id`, `claimed_level`, `verified_level` (nullable), `status` (UNVERIFIED/VERIFIED), `cert_expires_on` (nullable), `verified_by`, `verified_at` | `UNIQUE(crew_id, skill_id)`. Matching reads only `verified_level`. |
| `unavailability` | `id`, `org_id`, `crew_id`, `period tstzrange`, `category`, `note` | Half-open `[start, end)`. GiST index on `(crew_id, period)`. |
| `missions` | `id`, `org_id`, `code`, `name`, `description`, `starts_at`, `ends_at`, `state`, `revision`, `owner_id` (membership), `submitted_by`, `submitted_revision`, `approvals_required_snapshot` | `UNIQUE(org_id, code)`. The snapshot implements "policy in force at submission". |
| `mission_slots` | `id`, `org_id`, `mission_id`, `role_name`, `headcount`, `ordinal` | |
| `slot_requirements` | `id`, `org_id`, `slot_id`, `skill_id`, `min_level`, `cert_required` | `UNIQUE(slot_id, skill_id)`. |
| `assignments` | `id`, `org_id`, `mission_id`, `slot_id`, `crew_id`, `state` (PROPOSED/ACCEPTED/DECLINED/WITHDRAWN/RELEASED), `source` (MATCHER/MANUAL), `blocked_period tstzrange`, `offered_by`, `offered_at`, `responded_at`, `exit_reason` (required for DECLINED and WITHDRAWN) | **Exclusion constraint** (section 8). Partial unique index on `(mission_id, crew_id) WHERE state IN ('PROPOSED','ACCEPTED')`. |
| `approvals` | `id`, `org_id`, `mission_id`, `revision`, `approver_id`, `decision` (APPROVE/REJECT), `reason`, `created_at` | `UNIQUE(mission_id, revision, approver_id)`. Approvals for old revisions stay as history and are ignored for counting. |
| `audit_events` | `id`, `org_id`, `actor_id`, `entity_type`, `entity_id`, `action`, `data jsonb`, `created_at` | Insert-only. There is no update or delete path in code. |
| `notifications` | `id`, `org_id`, `recipient_id` (membership), `kind` (e.g. `crew.withdrew`), `mission_id` (nullable), `data jsonb`, `created_at`, `read_at` (nullable) | Index on `(recipient_id) WHERE read_at IS NULL`. Written in the same transaction as the triggering event. Kept separate from the audit log (D19). |

### 4.1 Tenant integrity in the schema itself

Every tenant-owned table has `org_id NOT NULL` **and** references its parents through **composite foreign keys**
(`(org_id, crew_id) REFERENCES crew_profiles(org_id, id)`, etc.). Each parent has a `UNIQUE(org_id, id)`.
As a result the database itself refuses an Org A assignment that points at an Org B crew member, even if a service bug tried to create one.
It costs one extra unique index per parent table and almost no code.

### 4.2 Time

All timestamps are `timestamptz` in UTC and all intervals are half-open `[start, end)`. Python uses only timezone-aware
datetimes; a test asserts that naive datetimes are rejected at the schema boundary. The CLI accepts `YYYY-MM-DD`
(interpreted as 00:00 UTC) or full ISO-8601, and displays dates in UTC.

## 5. Tenancy, authentication and authorisation

```
  Authorization: Bearer <jwt{sub: membership_id, org: org_id, role, exp}>
        |
        v
  get_ctx():  decode + verify signature/exp
              -> load membership (active?) -> TenantContext(org_id, membership_id, user_id, role, crew_id?)
        |
        v
  require_role(...)  (route-level coarse check)
        |
        v
  service(ctx, ...)  (fine-grained checks: ownership, SoD, crew self-only)
        |
        v
  TenantRepository(session, ctx)  -> every query: WHERE org_id = :ctx.org_id
```

- **Login** (`POST /v1/auth/login {email, password, org}`) verifies the password (argon2 via pwdlib) and an active membership in `org`.
  It returns a JWT signed with HS256, with an 8-hour TTL. A bad password and a missing membership return the **same** error, so the endpoint does not reveal which organisations an email belongs to.
- **Defence in depth** for isolation:
  1. Tokens carry exactly one org, so a request cannot even express "another tenant".
  2. Repositories require a `TenantContext` at construction and add the org predicate. There is no unscoped query helper outside `auth` and `seed`.
  3. Composite foreign keys (section 4.1) make cross-tenant references impossible in the database.
  4. A cross-tenant lookup returns **404** (the same as a missing record), so existence never leaks.
  5. The `tests/api/test_tenant_isolation.py` suite tries every resource type across tenants.
- **Authorisation** has two layers. Route dependencies enforce the role matrix. Services enforce the relationship rules: ownership,
  "crew can act only on self", separation of duties (SoD), and visibility filters. SoD lives in `domain/lifecycle.py` guards
  (`can_approve(mission, actor)`), so it can be unit-tested.

**Role matrix (summary; the specs are authoritative)**

| Action | Director | Mission Lead | Crew |
|---|---|---|---|
| Org settings, members, skill taxonomy | yes | - | - |
| Create mission / manage own missions | yes | yes (own) | - |
| Run matcher, offer, release | yes | yes (own missions) | - |
| Approve / reject | yes (not own submission or owned mission) | - | - |
| Verify skills | yes (not self) | yes (not self) | - |
| Edit own profile, skills, availability | yes | yes | yes |
| Accept / decline / withdraw own assignment | yes | yes | yes |
| See and dismiss own notifications | yes | yes | yes |
| See all crew and missions | yes | yes | own only |

## 6. Mission lifecycle

```
                 edit freely (revision++)
                +----------+
                v          |
           +---------+-----+   submit [slots>=1, all positions ACCEPTED]   +-------------------+
 create -->|  DRAFT  |-------------------------------------------------> | PENDING_APPROVAL  |
           +----+----+                                                    +---+-------+-------+
              ^ ^  ^          reject(reason) / withdraw                       |       |
              | |  +----------------------------------------------------------+       | approve x N
              | |          material edit = auto-withdraw (revision++)                 | (distinct directors,
              | +---------------------------------------------------------+           |  not submitter/owner,
              |                                                           |           v  current revision)
              |                                                     +-----+---------------+
              |       material edit / release = back to DRAFT       |      APPROVED       |
              +-----------------------------------------------------+                     |
                                                                    +----------+----------+
   DRAFT / PENDING / APPROVED --cancel--> CANCELLED                            | start
                                                                    +----------v----------+
                                                                    |       ACTIVE        |--abort--> ABORTED
                                                                    +----------+----------+
                                                                               | complete
                                                                               v
                                                                           COMPLETED
```

- `domain/lifecycle.py` holds a single transition table: `{(state, action): next_state}`. It also holds guard functions that
  return a `Decision(allowed, reason)`. Services call `lifecycle.apply(mission_snapshot, action, actor)`.
  Illegal transitions raise `Conflict`, and the error includes `allowed_actions` so the CLI can suggest them.
- **Material changes** are changes to the window, slots, requirements or assignments. Each one increments `revision` in the same transaction.
  If the mission is PENDING_APPROVAL or APPROVED, it goes back to DRAFT and an `auto_withdrawn` audit event records which change caused it.
  Approvals are keyed by `(mission_id, revision)`, so they become irrelevant automatically. Nothing is deleted.
- **Approval counting**: `count(distinct approver) WHERE revision = mission.revision AND decision = APPROVE` is compared with
  `approvals_required_snapshot`, which is copied from org settings at submit time. Approve requests carry the `revision` the
  approver looked at, and a mismatch returns 409. This prevents approving something you have not seen.
- **Concurrency**: every transition and every material change starts with `SELECT ... FROM missions WHERE id=:id FOR UPDATE`.
  That serialises approve-versus-edit and approve-versus-approve races on the same mission.
- **Started-window guard**: submit and approve require `starts_at > now`, checked under the same row lock. A mission that sat in
  DRAFT or PENDING past its start date gets 409 and must have its window edited (a material change). Services take an
  **injectable clock** (`Clock.now()`), so tests control "now" instead of depending on the real date.
- **Side effects of terminal states**: on CANCELLED, PROPOSED and ACCEPTED assignments become RELEASED, which frees crew time.
  On COMPLETED or ABORTED, ACCEPTED assignments stay ACCEPTED. They are history, and the recovery buffer still applies.
- **Window edits with accepted crew** recompute `blocked_period` for ACCEPTED assignments. If that would create an overlap, the
  exclusion constraint rejects it and the edit fails with 409, naming the crew member and the conflicting mission.

### 6.1 Assignment lifecycle

```
  (offer / apply match)        accept [no overlap: exclusion constraint + unavailability check]
         |                    +------------------> ACCEPTED ---release (owner/Director)---> RELEASED
         v                    |                       |
     PROPOSED ----------------+                       +--withdraw(reason) (crew, mission DRAFT/PENDING/APPROVED)
         |                                            |      --> WITHDRAWN  + notify owner; PENDING/APPROVED -> DRAFT
         |   decline(reason)                          +-- mission COMPLETED/ABORTED: stays ACCEPTED (history)
         +------------------> DECLINED                +-- mission CANCELLED: RELEASED
         |   release / mission cancelled
         +------------------> RELEASED

     DECLINED and WITHDRAWN crew are never re-suggested or re-offered for that mission.
```

- **Crew withdrawal** (D18): one transaction that locks the mission row, requires the mission to be DRAFT, PENDING_APPROVAL or APPROVED
  (ACTIVE gets 409: "mission is under way; ask the lead to release you"), requires a non-empty reason, sets WITHDRAWN (which frees the
  blocked period, because the exclusion constraint covers only ACCEPTED), increments the revision (auto-withdrawing a pending or
  approved mission back to DRAFT through the usual material-change path), writes the audit event, and inserts a `crew.withdrew`
  notification for the mission owner. The notification records the mission, crew member, slot, reason and whether the mission returned to DRAFT.
  Emergencies during an ACTIVE mission go through the lead (release or abort), not crew self-service.

- Offers can only be made while the mission is DRAFT. Accepting a PROPOSED assignment on a mission that is no longer DRAFT returns 409.
  In practice that only happens if the mission was cancelled, and cancellation already releases its offers.
- `blocked_period = [mission.starts_at, mission.ends_at + org.recovery_buffer_days)`. It is computed when the assignment is accepted and
  recomputed when the window changes. Changing the buffer setting does not rewrite existing commitments.
- A headcount check (`PROPOSED + ACCEPTED <= headcount`) runs under the mission row lock.
- **Stale offers are flagged, never expired.** Assignments record `offered_at`. The lead's inbox shows the age of each PROPOSED offer
  and flags it once `now - offered_at > org.stale_offer_days`, suggesting a follow-up or `mc assignment release`. No scheduler
  is involved (D16). Automatic expiry is deferred (§12).

## 7. Matching engine

The matcher answers one question: *"for the open positions of this mission, which eligible crew make the best crew overall, and why?"*

```
 +------------+  +-----------------------+  +----------------------+  +---------------------+  +------------------+
 | Load (svc) |->| 1. HARD FILTERS       |->| 2. SOFT SCORING      |->| 3. CREW-LEVEL       |->| 4. EXPLAIN       |
 | 4-5 bulk   |  | per (crew, slot):     |  | per eligible pair:   |  |    OPTIMISATION     |  | per position:    |
 | queries,   |  | - active profile      |  | fit, workload,       |  | rectangular min-cost|  | reason string,   |
 | no N+1     |  | - verified >= min     |  | experience, right-   |  | assignment with     |  | breakdown, top-3 |
 |            |  | - cert valid to end   |  | sizing, pending-     |  | dummy "unfilled"    |  | alternatives;    |
 |            |  | - no overlap: unavail |  | offer penalty        |  | columns             |  | why-not for gaps |
 |            |  |   / ACCEPTED + buffer |  | -> score in [0,1]    |  | (Hungarian, scipy)  |  |                  |
 |            |  | - not on/declined     |  |                      |  |                     |  |                  |
 |            |  | -> Exclusion(reasons) |  |                      |  |                     |  |                  |
 +------------+  +-----------------------+  +----------------------+  +---------------------+  +------------------+
                          everything right of "Load" is pure code in domain/matching/
```

### 7.1 Inputs (pure dataclasses)

- `Position(slot_id, slot_ordinal, index, role_name, requirements[(skill_id, min_level, cert_required)])`. One per **open** headcount unit.
- `Candidate(crew_id, name, active, skills{skill_id: (verified_level|None, claimed_level, status, cert_expires_on)}, commitments[(mission_code, blocked_period)], unavailability[(period, public_label)], pending_offers[(mission_code, period)], workload_days, experience{skill_id: completed_mission_count})`.
- `MissionWindow(start, end, buffer_days)`, plus the set of crew already on the mission or who declined it.

### 7.2 Hard filters

Each failed rule produces an `Exclusion(crew_id, slot_id, rule, detail)`. All failures are collected rather than stopping at the first one, so
why-not output is complete. The rules are the same as in `specs/crew-matching`:

| Rule | Detail example |
|---|---|
| `INACTIVE` | "profile inactive" |
| `SKILL_MISSING` / `SKILL_BELOW_MIN` | "piloting 3 < 4 required" or "no verified piloting" |
| `UNVERIFIED_WOULD_QUALIFY` (flag only) | "claims geology 4 (unverified); verifying would qualify" |
| `CERT_EXPIRED` | "EVA cert expires 2027-03-10, before mission end 2027-03-21" |
| `COMMITTED` | "on ART-9 until 2027-03-04 incl. recovery" |
| `UNAVAILABLE` | "unavailable 2027-03-01 to 03-08 (leave)". MEDICAL and OTHER show only "unavailable". |
| `ALREADY_ON_MISSION` / `DECLINED` / `WITHDRAWN` | "already Commander on this mission" / "declined this mission" / "withdrew from this mission" |

The mission's blocked period (with its recovery buffer) is checked for overlap, not just its raw window, because accepting would block the extended period.

**No under-qualified fallback.** Hard rules are never relaxed to complete a crew. An ineligible pair gets the `INFEASIBLE` cost, and
the dummy "unfilled" column is always cheaper (§7.4), so the solver leaves a position empty rather than filling it below the minimum.
To override, a lead must do something the approver can see: verify a pending claim, move the window, or lower the slot requirement
(a revision the Director approves). Formal waivers are deferred (§12).

**Closest candidates first.** Each exclusion gets a closeness tier used to sort why-not output. Ties are broken by name.

| Tier | Meaning | Example |
|---|---|---|
| 0 | Only issue is an unverified claim that would qualify | "claims geology 4 (unverified)" |
| 1 | One level short on a single requirement, nothing else wrong | "geology 2 < 3" |
| 2 | Qualified, but blocked only by availability or commitments | "on ART-9 until 03-04" |
| 3 | Everything else (missing skill, several shortfalls, expired cert, inactive) | "no verified geology" |

By default the result returns the five closest plus `excluded_total`, and `--all` returns every exclusion.

### 7.3 Scoring

For an eligible pair (crew *c*, position *p*) with requirements *R*, where `margin_r = verified_level_r - min_level_r` (0..4):

| Factor | Formula | Weight | Intent |
|---|---|---|---|
| Skill fit | `mean_r( 0.85 if margin_r == 0 else 1.0 )` | 0.40 | A comfortable margin (+1) is better than an exact fit; beyond +1 earns nothing more. *(Revised during implementation: the original linear formula `(margin+1)/(6-min)` let surplus outweigh right-sizing, contradicting the spec's level-2-medic scenario.)* |
| Right-sizing | `1 - mean_r( max(0, margin_r - 1) / 3 )` | 0.15 | Penalise surplus beyond +1 level, so experts stay available for missions that need them. |
| Workload | `1 - min(1, workload_days / 90)` | 0.25 | `workload_days` = days of ACCEPTED commitments in the 90 days before mission start. This spreads load. |
| Experience | `min(1, mean_r(completed_missions_using_skill_r) / 5)` | 0.20 | Proven track record on these skills. |
| Pending-offer penalty | `- 0.10 * min(1, overlapping_pending_offers / 2)` | - | Crew already offered a conflicting mission are less likely to accept. |

`score = clamp(0.40*fit + 0.15*rightsizing + 0.25*workload + 0.20*experience - penalty, 0, 1)`, rounded to 3 decimals.

The weights are module constants in `domain/matching/scoring.py`, chosen so that **qualification dominates** but cannot
completely override fairness of workload. Per-org tunable weights are deferred (section 12). Workload is measured relative to the
mission start, not to "now", so results don't drift with the clock and tests are deterministic.

### 7.4 Crew-level optimisation

Ranking each slot on its own fails on cases like this:

```
   Commander (piloting>=4)   Geologist (geology>=3)
   Alice: piloting 5, geology 5     Bob: piloting 2, geology 4

   greedy, Geologist first -> Alice=Geologist, Commander = nobody      x
   global optimum          -> Alice=Commander, Bob=Geologist           ok
```

The matcher builds a cost matrix of size `|P| x (|C| + |P|)`:

- `cost[p][c] = -(M + score[p][c])` if *c* is eligible for *p*, otherwise `INFEASIBLE = 1e9`. The value is finite on purpose, because scipy rejects infeasible `inf` matrices.
- Dummy column `|C| + p` has cost `0` for position *p* only, and `INFEASIBLE` for every other position. It means "leave *p* unfilled".
- `M = |P| + 1`. Filling one more position is always worth more than any possible total gain in score, so the result is
  **lexicographic**: as many positions as possible are filled, and among those fillings the total score is the highest.

`scipy.optimize.linear_sum_assignment` solves this exactly. With 20 positions and 500 crew it takes milliseconds. Positions are ordered by
`(slot_ordinal, index)` and candidates by `crew_id`, which makes ties resolve the same way every time (spec: deterministic output).
A crew member appears once as a column, so they can fill at most one position. This enforces "one slot per mission" without extra logic.

### 7.5 Output

```
MatchResult
  mission_code, revision
  positions[]:
    slot_id, role_name, index
    suggestion?: { crew_id, name, score, breakdown{fit, rightsizing, workload, experience, penalty}, reason }
    alternatives[<=3]: { crew_id, name, score, reason }      # next best eligible, excluding the suggestion
    unfilled_reasons[<=5 | all]: { crew_id, name, tier, rules[{rule, detail}] }   # only when unfilled; closest first
    excluded_total
  summary: { open, filled, unfilled }
```

`reason` strings are generated by `explain.py` from the breakdown, for example "piloting 5 (needs 4+), cert valid to 2028-06, 4 days load".
The matcher never writes. `POST /match/apply` takes an explicit list of `(slot_id, crew_id)` pairs, which is either the run the client
received or a subset of it, then **re-runs the eligibility rules** for each pair and creates PROPOSED assignments. Each pair
succeeds or fails on its own (spec: stale suggestion).

### 7.6 Extension point: team-level constraints

Constraints such as "at least one medic across the crew", "these two must not fly together" or "at most two rookies" cannot be
broken down into per-pair costs. The planned approach is to keep Hungarian for the initial solution and then run a bounded
**local search** (swap and replace moves, scored by `sum(score) - lambda * violations`). For orgs that need guarantees, the
alternative is a small **ILP** (OR-Tools CP-SAT). The `solver.py` interface (`solve(positions, candidates, scores) -> Assignment`)
is the seam where either would plug in.

## 8. Concurrency and double-booking

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE assignments ADD CONSTRAINT no_double_booking
  EXCLUDE USING gist (crew_id WITH =, blocked_period WITH &&) WHERE (state = 'ACCEPTED');
```

- This is written by hand in the first Alembic migration, because autogenerate does not understand it. A comment warns against removing it in later autogenerated revisions.
- Accepting runs in one transaction: lock the mission row, check state and headcount, check unavailability overlap
  (service-level query), compute `blocked_period`, and update to ACCEPTED. A constraint violation (SQLSTATE `23P01`) is turned into
  a 409 that names the conflicting mission, found by a follow-up query.
- Two concurrent acceptances: Postgres guarantees only one commits. This is covered by an API test that runs two
  connections in threads.
- Unavailability is checked in the service rather than by a constraint, because it lives in a different table. Adding an
  unavailability window that overlaps an existing ACCEPTED assignment is **rejected with 409**. The crew member must withdraw first
  (with a reason, notifying the lead), so commitments can't be silently broken.

## 9. API surface

The base path is `/v1`. Requests and responses are JSON. Errors are `application/problem+json`. `{ref}` is a mission code or UUID.

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login` - `GET /me` |
| Org | `GET/PATCH /org/settings` - `GET/POST /members` - `PATCH /members/{id}` (role, active) |
| Skills | `GET/POST /skills` - `PATCH /skills/{id}` |
| Crew | `GET/POST /crew` - `GET/PATCH /crew/{id}` (`me` alias) - `PUT/DELETE /crew/{id}/skills/{skill}` - `POST /crew/{id}/skills/{skill}/verify` - `GET/POST /crew/{id}/unavailability` - `DELETE /crew/{id}/unavailability/{uid}` - `GET /crew/{id}/assignments` |
| Missions | `GET/POST /missions` - `GET/PATCH /missions/{ref}` - `POST /missions/{ref}/slots` - `PATCH/DELETE /missions/{ref}/slots/{sid}` - `GET /missions/{ref}/history` |
| Transitions | `POST /missions/{ref}/{submit,withdraw,approve,reject,start,complete,abort,cancel}` (`approve` body: `{revision}`, `reject` body: `{revision, reason}`) |
| Matching | `GET /missions/{ref}/match` - `POST /missions/{ref}/match/apply {pairs:[{slot_id, crew_id}]}` |
| Assignments | `POST /missions/{ref}/assignments {slot_id, crew_id}` (manual offer) - `POST /assignments/{id}/{accept,decline,withdraw,release}` (`decline` and `withdraw` body: `{reason}`, required) |
| Inbox | `GET /inbox` (role-shaped payload, unread notifications first) - `POST /notifications/{id}/dismiss` |

Transitions are action endpoints rather than `PATCH state=...`. That keeps the intent explicit, keeps the audit trail readable, and gives each action its own permission rule.
List endpoints support `?state=`, `?limit=` and `?offset=`; cursor pagination is deferred.

**Error model**: `{type, title, status, detail, code, ...extensions}`. Examples are `code: "mission.unfilled_slots"` with `unfilled: [...]`,
`code: "mission.illegal_transition"` with `allowed_actions: [...]`, `code: "approval.self_approval"`, and `code: "assignment.double_booked"` with `conflict: {mission_code, until}`.
Statuses: 400/422 validation, 401 unauthenticated, 403 forbidden (role or SoD), 404 not found (including cross-tenant), 409 state conflict.

## 10. CLI design

**Principles**: noun-verb grammar (`mc mission submit`). Readable output by default and `--json` on every command. Every
state change prints *what changed* and a *Next:* hint. Mission codes are used everywhere. Errors are one line that explains the rule, with a
distinct exit code. The CLI never imports server code (fast startup, and it proves the API is complete).

```
mc login [--org SLUG] [--email E] [--api URL]     mc logout     mc whoami
mc inbox                                           # role-aware home screen, notifications first
mc inbox dismiss ID

mc org settings [--approvals N] [--recovery-days D] [--stale-offer-days D]
mc member list | add EMAIL --name N --role R | deactivate EMAIL
mc skill list | add NAME [--category C] | deactivate NAME

mc crew list [--skill S] | show CREW | create EMAIL | availability CREW
mc crew verify CREW SKILL [--level L] [--cert-expires DATE]
mc profile show | skill set SKILL LEVEL | skill remove SKILL
mc profile unavailable add START END --category C [--note N] | list | remove ID

mc mission list [--state S] | create NAME --start D --end D | show REF | edit REF ... | history REF
mc mission slot add REF --role R [--count N] --skill SKILL:LEVEL[:cert] ... | remove REF SLOT
mc mission offer REF --slot ROLE CREW
mc mission submit | withdraw | approve | reject --reason T | start | complete | abort | cancel   REF

mc match REF [--explain [ROLE]] [--all] [--apply [--only ROLE ...]]

mc assignment list | accept ID | decline ID --reason T | withdraw ID --reason T | release ID
                                                   # missing --reason on decline/withdraw: prompt, never send empty
```

Example session (what the usability review sees):

```
$ mc match ART-12
  ART-12  Lunar South Pole Survey   2027-03-01 -> 2027-03-21   DRAFT r4
  +----------------+----------------+-------+------------------------------------------+
  | Position       | Suggested      | Score | Why                                      |
  +----------------+----------------+-------+------------------------------------------+
  | Commander      | Alice Okafor   | 0.91  | piloting 5 (needs 4+), EVA cert to 2028  |
  | Geologist #1   | Bob Lindqvist  | 0.84  | geology 4 (needs 3+), 2 prior surveys    |
  | Geologist #2   | - unfilled -   |   -   | 0 eligible (4 excluded)                  |
  +----------------+----------------+-------+------------------------------------------+
  2 of 3 positions filled.
  Next: mc match ART-12 --apply      (offers the 2 suggestions)
        mc match ART-12 --explain Geologist
```

- **Session**: `~/.config/mc/session.json` (mode 0600) holds `api_url`, `token`, `org`, `email` and `role`. `MC_API_URL` overrides the URL.
  The password is read with a hidden prompt and never stored.
- **Exit codes**: `0` ok, `2` usage, `3` auth or permission (401/403), `4` not found, `5` conflict or validation (409/422), `6` server or connection.
- **Resolving names**: the CLI resolves crew names or emails and skill names to IDs through list endpoints. If a name is ambiguous it lists the matches and exits 2.

## 11. Testing strategy

| Layer | Scope | Key cases |
|---|---|---|
| `tests/unit` (pure, fast) | lifecycle, eligibility, scoring, solver, explain | table of all transitions; SoD guards; greedy trap; expired cert; buffer; unverified claim flagged; right-sizing; determinism with ties; unfilled positions via dummy columns |
| `tests/api` (real Postgres) | HTTP + DB | **tenant isolation across every resource**; 401/403 matrix; submit gate; self-approval for Lead and Director; N-of-M approvals; revision voiding; stale approval; concurrent accept (exclusion constraint); unavailability conflict; privacy of MEDICAL |
| `tests/e2e` | `mc` via Typer `CliRunner` against a live test server | full journey; `--json` parses; exit codes |

Each API test runs inside a connection-level transaction that is rolled back afterwards (session bound through FastAPI dependency
override). The concurrency test uses two real connections that commit. Factories (`make_org`, `make_member`, `make_crew`,
`make_mission`) keep a cross-tenant test to about two lines. There is no coverage target: every rule in the specs maps to a named test.

## 12. Built vs Deferred

| Area | Built now | Deferred (extension point) |
|---|---|---|
| Isolation | Org-scoped tokens, tenant repositories, composite FKs, 404 semantics, isolation suite | **Postgres RLS** as a fourth layer: `SET LOCAL app.org_id` in the session dependency plus a policy per table. The repository layer already centralises the hook. |
| Approval | N distinct approvers, snapshot at submit, SoD, revision binding | **Multi-stage chains** (e.g. safety then director). `approvals` would get a `stage` column and the policy would become an ordered list. |
| Matching | Filters, 5-factor scoring, optimal assignment, explanations, closest-first why-not, apply | **Requirement waivers**: a lead offers to a below-minimum candidate with a written justification, stored as `assignments.waiver_reason`; the approver sees a WAIVER warning, and approval of a waived crew may need the full Director quorum. **Team-level constraints** (section 7.6); **per-org weights** (move constants to `organisations.match_weights jsonb`); learning from accept/decline history. |
| Scheduling | Manual `start` and `complete` | A scheduler that starts APPROVED missions at `starts_at` (a worker calling the same service method). |
| Notifications | `notifications` table, written in the event's transaction; shown in `mc inbox`, dismissed per item. First event type: `crew.withdrew`. | **Delivery channels**: a worker reads undelivered notifications (the table doubles as an outbox) and sends email or webhooks. **More event types**: offer received, mission approved or rejected, skill verified. |
| Offers | Offer age and stale flag in the lead's inbox (`stale_offer_days`) | **Automatic offer expiry**: a scheduled job releases PROPOSED offers after N days, using the same service method as a manual release. |
| Identity | Email + password, JWT | SSO/OIDC, API keys for automation, refresh tokens, password reset. |
| Missions | One contiguous window | Mission phases with partial crew windows (assignment gets its own period, defaulting to the mission's). |
| Ops | docker-compose, single instance | Structured logging/metrics, cursor pagination, rate limits, org onboarding API, platform admin. |

## 13. Decisions (with alternatives)

| # | Decision | Why | Alternatives considered |
|---|---|---|---|
| D1 | **Python + FastAPI + sync SQLAlchemy** | Fastest path to a well-typed API in the time budget. Sync avoids async ORM pitfalls (lazy-load `MissingGreenlet`) at no real cost at this scale. | TypeScript/Nest (more CLI plumbing), Go (slower to a rich domain model), async SQLAlchemy (risk without benefit here). |
| D2 | **Postgres, not SQLite** | Exclusion constraints and `tstzrange` give race-proof double-booking prevention, and the RLS upgrade path exists. | SQLite: easier for reviewers to set up, but no exclusion constraints and only service-level checks, which can race. |
| D3 | **Membership is the principal**; token scoped to one org | Users in several orgs are realistic. A single-tenant token makes "which org?" impossible to get wrong per request. | `org_id` in the URL path (easy to mismatch with the token); global user role (breaks multi-org). **Revisit:** a separate account per organisation is the recommended direction; see section 18.1. |
| D4 | **Slots with headcount and per-slot requirements** | Matches how crews are actually organised, and turns matching into a well-defined assignment problem. | A flat list of mission skills (ambiguous: is it one person or two?). |
| D5 | **Self-declared, verified skills; matching on verified levels only** | Respects "crew manage their own profiles" without letting crew game the matcher. Unverified claims show up as "worth verifying". | Director-set skills only (goes against the brief); fully self-declared (gameable). |
| D6 | **Approval tied to a revision; edits auto-withdraw** | Closes the loophole of approving something and then changing it. Approvers explicitly sign off on what they saw. | Freezing edits while pending (frustrating for leads); approving without versioning (unsafe). |
| D7 | **Submit requires a fully accepted crew** | Directors approve a real, confirmed crew rather than a wish list. Fewer surprises after approval. | Two gates (approve plan, then crew): more realistic for large agencies, but doubles the workflow. Possible as a policy later. |
| D8 | **SoD as a rule (submitter or owner never approves)** rather than a role check | Covers Directors who create missions themselves. Testable as a pure guard. | "Leads can't approve" only, which leaves a Director self-approval hole. |
| D9 | **Only ACCEPTED blocks time; PROPOSED is a soft signal** | Otherwise outstanding offers would freeze the roster. The competing-offer penalty handles the soft case. | Hold offers with expiry (more state, more UX). |
| D10 | **Recovery buffer included in `blocked_period`** | The DB enforces the buffer too, not only the matcher. | Buffer checked only in the matcher (bypassed by manual offers). |
| D11 | **Hungarian with lexicographic fill-first cost and dummy columns** | Exact, fast, deterministic, and handles partial fills cleanly. | Greedy (provably wrong on easy cases); ILP (heavier dependency, unnecessary for separable scores). |
| D12 | **Matcher is stateless; apply takes explicit pairs and re-validates** | No stored "match runs" to expire. A lead can apply a subset. Stale suggestions fail one by one. | Persisted match runs with IDs (more tables, staleness handling). |
| D13 | **Action endpoints for transitions** | Explicit intent, one permission rule per action, readable audit trail. | `PATCH {state}` (overloaded, harder to authorise). |
| D14 | **CLI uses only the API, as a separate light package** | Fast startup, proves the API is complete, and the server could be deployed remotely. | Shared package (scipy/SQLAlchemy imports make `mc` start slowly). |
| D15 | **Composite tenant FKs** | Isolation enforced by the DB at almost no cost. | Relying only on application checks. |
| D16 | **Flag stale offers instead of expiring them automatically** | No scheduler is needed, and leads stay in control of their crew; an unanswered offer is a prompt to follow up, not a failure. | Automatic expiry (needs a worker, and can surprise crew mid-decision). Deferred. |
| D17 | **Never relax hard rules to fill a crew; sort why-not closest first** | Safety requirements are commitments the approver signs off on. Showing the nearest misses first gives leads the fastest legitimate path to a full crew. | Score-based fallback to under-qualified crew (silently weakens requirements); unsorted why-not (noise at 500 crew). |
| D18 | **Crew can withdraw themselves up to APPROVED, with a mandatory reason; not from ACTIVE** | Crew own their commitments, and a lead shouldn't be a bottleneck for someone who can't go. Approval can't be bypassed, because withdrawal sends a pending or approved mission back to DRAFT. The reason and notification mean the lead always knows why. ACTIVE missions are operational; emergencies go through the lead. | Lead-only release (no in-system way to ask, no recorded reason); a request-and-approve flow (more state, slower for genuine emergencies before launch); withdrawal including ACTIVE (crew could leave mid-mission with no decision made). |
| D19 | **Notifications in their own table, separate from the audit log** | Different jobs: notifications tell a person and get dismissed, while audit proves what happened and never changes. Keeping them apart means the audit log isn't shaped around the UI, and the notification table becomes the outbox for future email or webhooks. | Computing notifications from audit events with a per-member "seen" timestamp (no per-item dismiss, and it ties the inbox to the audit format). |

## 14. Assumptions

- No self-serve signup and no platform admin. Orgs and their first Directors are created by `seed` (or an admin script).
- Directors can create and lead missions. SoD still applies to them.
- A mission is one contiguous window, and every crew member is needed for all of it.
- A crew member fills at most one slot per mission. The mission owner is its creator, and changing ownership is deferred.
- Mission windows can't start in the past, and a mission can't be submitted or approved once its window has started. Dates are displayed in UTC.
- Unanswered offers never expire on their own. Leads see their age and release them by hand.
- Approval policy changes affect only missions submitted afterwards. Recovery buffer changes affect only commitments accepted afterwards.
- Unavailability is private: Leads see LEAVE and TRAINING by category, MEDICAL and OTHER only as "Unavailable", and never the note.
- Crew who decline or withdraw are not suggested or offered again for that mission. Declining and withdrawing both require a reason.
- Adding unavailability over an existing ACCEPTED assignment is rejected. The crew member must withdraw first, or be released by the lead.
- Records referenced by history are deactivated, never hard-deleted. The audit log is append-only.
- No email or push: notifications are stored and shown in `mc inbox`. Only crew withdrawals create notifications for now. Single instance, English only.
- Scale: up to about 500 crew per org and about 20 slots per mission. In-memory matching per request is fine.

## 15. Risks / Trade-offs

- [The time budget overruns in the matcher or CLI] -> Tasks have a cut line. Drop the depth of why-not output first, then `--json` polish, then the audit-history listing. Isolation and SoD tests are never cut.
- [Alembic autogenerate drops the exclusion constraint or extension] -> Write it by hand in migration 0001 with a warning comment. An API test asserts that the double-booking rejection works.
- [scipy errors on infeasible matrices] -> Use a finite `INFEASIBLE` cost plus dummy columns. A unit test covers "no eligible crew at all".
- [Reviewer machine lacks Docker or the right Python] -> uv pins Python 3.12. `make up` waits for the Postgres healthcheck. The README starts with prerequisites and a 3-command quick start.
- [Naive datetimes or closed intervals cause off-by-one overlaps] -> Use only aware UTC datetimes, reject naive ones at the schema boundary, use half-open ranges in Python and Postgres, and test the boundary case where one mission ends exactly when the next starts.
- [Scoring weights look arbitrary] -> They are documented with their intent, shown per suggestion as a breakdown, and confined to one module. Per-org tuning is a defined extension point.
- [Composite FKs complicate the ORM mapping] -> Use explicit `ForeignKeyConstraint` declarations on models, kept to the tables that reference crew, missions, slots and skills.
- [Single-director orgs can't approve their own missions] -> This is intentional, and the error says so clearly. The seed includes two Directors. The approver-of-last-resort question is documented as a policy choice for customers.
- [JWT has no revocation] -> 8-hour TTL. Deactivating a membership is checked on every request (`get_ctx` loads the membership), so access ends immediately anyway.

- [One login shared across organisations leaks a little and can't see cross-org bookings] -> Known limitation; see section 18.1. Recommended fix: a separate account per organisation.

## 16. Running and rollout

This is greenfield, so there is no data migration. Developer and reviewer flow:

```
make up        # docker compose up -d postgres (waits for healthy)
make migrate   # alembic upgrade head
make seed      # two orgs (Artemis Labs: ART, Orion Dynamics: ORN) with designed scenarios; prints logins
make run       # uvicorn on :8000
make demo      # scripts/demo.sh: full narrated journey via `mc`
make test      # unit + api + e2e
```

The seed data is **designed**, not random. Artemis has 2 Directors, 2 Leads and about 10 crew. They include the greedy-trap pair (Alice and Bob), an
expired EVA certification, an unverified claim that would fill a gap, a crew member on leave, a MEDICAL window, and a crew member committed to another
mission within the recovery buffer. Orion exists to demonstrate isolation. Rollback is `docker compose down -v`.

## 17. Open Questions

- Token TTL and whether `mc` should warn shortly before expiry. Either way the specs and tasks stay the same.
- Final wording of reason strings in explanations. This can be polished during the CLI phase.

## 18. Known limitations and recommended improvements

Issues found after implementation that are deliberately **not** fixed in this version. Each item records the problem,
its impact, and the recommended direction.

### 18.1 Identity is shared across organisations (recommended: a separate account per organisation)

**Current behaviour (D3).** A person has one global `User` (email + password). Each organisation gives them a
separate `Membership` (role) and, optionally, a separate `CrewProfile`, so skills, verification, unavailability and
assignment history are never shared between organisations. They log in with the **same email and password** for
every organisation, choosing the organisation at login. The token they receive is valid for that organisation only.

**Flaws.**

1. **Cross-tenant information leak when adding members.** When a Director adds an email that already belongs to a
   user in another organisation, `add_member` silently attaches the existing `User`:
   - the response shows the **name registered in the other organisation**, not the name the Director entered;
   - the **initial password the Director typed is ignored**, so the Director hands out credentials that do not work.

   Together these reveal that the email exists elsewhere, and what name it uses there. It's a small leak, but it is
   one, in a system whose core promise is that data never crosses tenants.
2. **No organisation fully controls its users' credentials.** Password policy, resets and (in future) SSO cannot be
   set per organisation, because one password serves every organisation the person belongs to. Deactivating a member
   in one organisation correctly ends their access there, but a password compromise affects all of their
   organisations.
3. **Bookings don't cross organisations.** Someone crewing for two organisations can be booked by both for the same
   dates, because (correctly) neither organisation's matcher can see the other's commitments. Today the only
   mitigation is for the crew member to record unavailability in each organisation themselves.

**Recommended improvement: a separate account per organisation.** Scope identity to the tenant:
`users.org_id NOT NULL` with `UNIQUE(org_id, email)`, and login resolves `(org, email)` to exactly one account
with its own password. The same email in two organisations is then two unrelated accounts that know nothing about
each other.
- Removes flaw 1 entirely: adding an email never touches another organisation's data.
- Removes flaw 2: each organisation owns its users' credentials, and per-organisation SSO/OIDC becomes
  straightforward.
- Flaw 3 stays by design (isolation wins). The extension point is an opt-in, crew-controlled "busy (other
  organisation)" status that shares only dates, never mission details.

**Migration sketch.** Make `Membership` the authenticated account (move `email`/`password_hash` onto it, or create
one user row per membership). Split any user with several memberships into one account per organisation, copying the
password hash so nobody is locked out. Change login to look up by `(org_slug, email)`. Tokens, `TenantContext` and
every repository stay unchanged, because they are already scoped to a single membership.

**Interim mitigation, if the shared model is kept for a while.** Store display names per membership instead of
reading `users.name`. When an added email already has an account, return a neutral message ("this person already
has an account and will log in with their existing password") without echoing any data from elsewhere.

