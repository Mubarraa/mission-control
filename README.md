# Mission Control

Multi-tenant platform for space organisations to plan missions, staff them with the right crew, and get them
independently approved. It consists of an HTTP API (FastAPI + Postgres) and the `mc` command-line client.

- **Design document:** [`openspec/changes/mission-control-core/design.md`](openspec/changes/mission-control-core/design.md)
  (architecture, data model, lifecycle, matching algorithm, decisions, risks, built vs deferred)
- **Behaviour specs:** [`openspec/changes/mission-control-core/specs/`](openspec/changes/mission-control-core/specs/)
- **Proposal / task plan:** [`proposal.md`](openspec/changes/mission-control-core/proposal.md),
  [`tasks.md`](openspec/changes/mission-control-core/tasks.md)

## Prerequisites

- **Docker** (Docker Desktop, OrbStack or Colima) for Postgres 16
- **[uv](https://docs.astral.sh/uv/)**, which downloads Python 3.12 automatically

## Quick start

```bash
make up        # start Postgres (waits until healthy)
make migrate   # create the schema
make seed      # two demo organisations; prints the logins (password: mission-control-demo)
make run       # API on http://localhost:8000  (OpenAPI docs at /docs)
```

In a second terminal:

```bash
uv run mc login --org artemis-labs --email priya@artemis.io   # password: mission-control-demo
uv run mc inbox
uv run mc match ART-3
```

To see the whole journey narrated in about a minute (it uses its own throwaway session):

```bash
make demo
```

To reset everything: `make down && make up && make migrate && make seed`. Re-run this before replaying the demo,
because the demo verifies a skill and books crew.

## The demo organisations

`make seed` creates **Artemis Labs** (`artemis-labs`, missions `ART-n`) with scenarios designed to exercise the
matcher, and **Orion Dynamics** (`orion-dynamics`, `ORN-n`), which exists to demonstrate tenant isolation.

| Who | Role | Why they're interesting |
|---|---|---|
| amara@ / lena@artemis.io | Directors | two Directors, so a mission can be approved by someone other than its submitter |
| priya@ / marcus@artemis.io | Mission Leads | Priya owns the `ART-3` Lunar South Pole Survey |
| alice@artemis.io | Crew | the only available pilot *and* the best geologist (the greedy trap) |
| bob@artemis.io | Crew | qualified geologist with prior mission experience |
| dev@artemis.io | Crew | **unverified** Geology claim that would fill a gap |
| carol@artemis.io | Crew | EVA certification **expires mid-mission** |
| eve@artemis.io | Crew | committed to `ART-2`; still inside the 14-day **recovery buffer** |
| hana@artemis.io | Crew | on **leave** during the survey |
| ivan@artemis.io | Crew | private **MEDICAL** window (Leads only see "Unavailable") |
| farah@ / gabe@artemis.io | Crew | level-5 surgeon vs level-2 medic: **right-sizing** picks Gabe for a level-2 slot |
| oskar@orion.space | Director (Orion) | try `mc mission show ART-3`: not found |

## Using `mc`

```
mc login --org SLUG [--email E]       mc logout        mc whoami
mc inbox                              # role-aware home screen; notifications first
mc inbox dismiss ID

mc mission create NAME --start YYYY-MM-DD --end YYYY-MM-DD
mc mission slot add REF --role R [--count N] --skill SKILL:LEVEL[:cert] ...
mc mission show|list|edit|history ...
mc match REF [ROLE] [--explain] [--all] [--apply [--only ROLE]]
mc mission offer REF CREW --slot ROLE
mc mission submit|approve|reject|withdraw|start|complete|abort|cancel REF

mc assignment list|accept|decline|withdraw|release ID       # short ids are fine
mc profile show | skill set SKILL LEVEL | unavailable add START END --category C
mc crew list|show|availability|verify|create ...
mc org settings [--approvals N] [--recovery-days D] [--stale-offer-days D]
mc member list|add|deactivate      mc skill list|add|deactivate
```

- Add `--json` anywhere for machine-readable output (`mc mission list --json | jq`).
- After every state change, `mc` prints a **Next:** hint.
- Exit codes: `0` ok, `2` usage, `3` auth/permission, `4` not found, `5` conflict/validation, `6` server/connection.
- Configuration: `--api URL` or `MC_API_URL`; the session lives in `~/.config/mc/session.json` (mode 0600, token
  only); `MC_PASSWORD` allows non-interactive login (used by the demo).

## Development

```bash
make test        # unit + API (real Postgres) + CLI + end-to-end, ~15s
make test-unit   # pure domain tests (lifecycle, matcher), no database
make lint        # ruff
```

Layout (see design.md §3.1): `src/mission_control/domain` holds pure business rules (lifecycle, matcher),
`services` orchestrates, `db` holds models, tenant-scoped repositories and migrations, and `api` holds the FastAPI
routers. `cli/` is a separate lightweight package that talks to the API over HTTP only.

> Docker Desktop installs `docker` in `~/.docker/bin`. The Makefile handles this, but if `docker` isn't found in
> your own shell, add that directory to your `PATH`.
