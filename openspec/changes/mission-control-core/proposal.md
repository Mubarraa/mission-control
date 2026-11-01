# Proposal: Mission Control Core

## Why

Space organisations staff missions by hand. Mission leads spend hours checking skill profiles, availability calendars and existing commitments against each other, and the results are error-prone: double-booked crew, lapsed certifications, and specialists burned out on back-to-back missions. Mission Control is a multi-tenant B2B platform that turns this into a governed workflow. Missions are defined as crew slots with explicit requirements. A matching engine proposes the best crew for the whole mission and explains its choices. An approval workflow makes sure nothing goes active without independent sign-off.

## What Changes

This is a greenfield build of the platform core:

- **Multi-tenant HTTP API** (FastAPI + Postgres) where every tenant-owned record is scoped to an organisation, enforced through tenant-scoped repositories and org-scoped auth tokens. Cross-tenant access is indistinguishable from "not found".
- **Three roles per organisation**: Director, Mission Lead and Crew Member. A user can belong to several organisations with one role in each. **Separation of duties**: nobody can approve a mission they submitted, or verify their own skills.
- **Crew profiles**: an org-defined skill taxonomy, proficiency levels 1-5, optional certification expiry, self-declared skills that a Director or Lead verifies, and unavailability windows with private reasons.
- **Mission lifecycle**: DRAFT -> PENDING_APPROVAL -> APPROVED -> ACTIVE -> COMPLETED, plus CANCELLED and ABORTED. Missions are made of crew slots with per-slot skill requirements. Approval is tied to a mission revision, any material edit invalidates it, and each org sets its own approval policy (number of approvals required).
- **Assignments**: crew are offered slots (PROPOSED) and accept or decline, with a reason required for declining. Before a mission goes active, crew can withdraw from an accepted assignment with a mandatory reason. A pending or approved mission then returns to DRAFT and the lead is notified. Accepted assignments block the crew member's time, including an org-configurable post-mission recovery buffer. A database exclusion constraint makes double-booking impossible.
- **Auto-matching engine**: hard eligibility filters, then weighted soft scoring (skill fit, workload balance, experience, over-qualification penalty), then a globally optimal crew assignment (Hungarian algorithm). Every suggestion is explained, and unfillable slots come with "why not" reasons for each excluded candidate. The matcher only suggests. A lead applies the suggestions.
- **Append-only audit trail** of lifecycle transitions, approvals, verifications and assignment responses and withdrawals.
- **Notifications**: stored per recipient, kept separate from the audit trail, shown in the inbox and dismissed individually. Crew withdrawals are the first event type.
- **`mc` CLI** (Typer + Rich) covering every primary workflow through the API: login and org context, a role-aware inbox, mission and slot management, matching with explanations, approvals, and assignment responses. It prints next-step hints and supports `--json` on every command.
- **Seed and demo tooling**: two organisations with realistic crew, so the full journey and tenant isolation can be shown in minutes.

## Capabilities

### New Capabilities

- `tenancy-and-access`: organisations, users, memberships and roles; authentication with org-scoped tokens; tenant isolation guarantees; role-based authorisation; the audit trail; per-member notifications.
- `crew-profiles`: crew profiles, the org skill taxonomy, proficiency and certifications, the self-declare/verify flow, and unavailability windows with privacy rules.
- `mission-lifecycle`: missions, crew slots and requirements, lifecycle state transitions, the approval policy and separation of duties, and assignments with their offer/accept/decline/withdraw flow and double-booking prevention.
- `crew-matching`: eligibility rules, scoring, optimal crew-level assignment, explanations and why-not diagnostics, and applying suggestions as offers.
- `cli`: the `mc` command-line experience covering authentication and context, the role-aware inbox, command coverage of the primary workflows, output modes and error presentation.

### Modified Capabilities

None. This is a greenfield project with no existing specs.

## Impact

- **New code**: `src/mission_control/` (domain, db, services, api), a separate `cli/` package (`mc`), Alembic migrations, `tests/` (unit, api, e2e), `docker-compose.yml`, `Makefile`, and README.
- **Dependencies**: Python 3.12 (uv), FastAPI, SQLAlchemy 2, Alembic, psycopg, pyjwt, pwdlib, scipy, Typer, Rich, httpx, pytest and ruff.
- **Infrastructure**: Postgres 16 with the `btree_gist` extension, run via docker-compose. Developers and reviewers need Docker.
- **Out of scope** (described in the design as extension points): a web UI, Postgres row-level security, team-level matching constraints, multi-stage approval chains, scheduled automatic transitions, notifications, SSO/API keys, and self-serve org signup.
