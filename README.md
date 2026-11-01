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
- Suggested commands are printed as `uv run mc ...` so you can copy them directly. If you install the CLI
  (`uv tool install ./cli`), set `MC_COMMAND=mc` to get plain `mc ...` suggestions.
- Examples in this README write `mc` for short; from the repo, run them as `uv run mc`.

## Common workflows

Each step shows who runs it. Switch users with `mc login --org <slug> --email <email>`; check who you are with
`mc whoami`.

### 1. Onboard a crew member

**Director:** create the account, and a crew profile if the person flies:

```bash
mc member add sam@artemis.io --name "Sam Rivera" --role CREW --crew   # prompts for an initial password
mc skill add "Robotics" --category Systems                             # only if the skill doesn't exist yet
```

(If someone is already a member but has no profile yet, use `mc crew create sam@artemis.io`. Leads and Directors
can have crew profiles too.)

**Crew member:** declare skills and availability:

```bash
mc profile skill set geology 4                 # levels 1-5; recorded as UNVERIFIED
mc profile unavailable add 2027-05-01 2027-05-15 --category LEAVE --note "Wedding"
mc profile show
```

**Director or Lead:** verify the claims. Only verified levels count for matching, and nobody can verify their
own skills.

```bash
mc crew show "Sam Rivera"
mc crew verify "Sam Rivera" geology
mc crew verify "Sam Rivera" eva --level 2 --cert-expires 2028-12-31   # adjust the level; set the cert expiry
```

If Sam later edits a verified skill, it becomes unverified again, and the previously verified level keeps counting
until someone verifies the new one. MEDICAL and OTHER unavailability show to Leads only as "Unavailable".

### 2. Plan and staff a mission

**Mission Lead:**

```bash
mc mission create "Shackleton Rim Traverse" --start 2027-03-02 --end 2027-03-20
mc mission slot add ART-4 --role Commander --skill piloting:4
mc mission slot add ART-4 --role Geologist --count 2 --skill geology:3
mc mission slot add ART-4 --role "EVA Specialist" --skill eva:3:cert   # :cert = valid certification required
mc match ART-4                       # best crew for the whole mission, with reasons
mc match ART-4 --explain Geologist   # score breakdown, alternatives, and why-not for gaps (closest first)
mc match ART-4 --apply               # offer the suggestions (or --only Commander)
mc mission offer ART-4 "Hana Kim" --slot Geologist   # or offer one person by hand (must be eligible)
```

The matcher never fills a slot with someone below its requirements. To close a gap, verify a pending claim
(`mc crew verify`), change the dates (`mc mission edit`), or lower the requirement; each of these is visible to
the approver.

**Crew members:** respond from their inbox (short ids are fine):

```bash
mc inbox
mc assignment accept 3d50
mc assignment decline 3d50 --reason "Family commitment"   # a reason is required
```

### 3. Get it approved

**Mission Lead:** once every position has an accepted crew member:

```bash
mc mission submit ART-4
```

**A different Director** (nobody approves a mission they submitted or own):

```bash
mc inbox                                   # missions awaiting approval
mc mission show ART-4
mc mission approve ART-4                   # or: mc mission reject ART-4 --reason "Need a backup EVA"
```

`mc org settings --approvals 2` makes missions need two Directors. Any edit to the dates, slots or crew sends a
pending or approved mission back to DRAFT for re-approval. After approval: `mc mission start ART-4`, then
`mc mission complete ART-4`.

### 4. When plans change

- **Crew can't go (before launch):** `mc assignment withdraw <id> --reason "..."`. The position reopens, a pending
  or approved mission returns to DRAFT, and the lead gets a notification in `mc inbox` (dismiss it with
  `mc inbox dismiss <id>`).
- **Mission already active:** crew can't withdraw themselves; the lead or a Director runs
  `mc assignment release <id>`.
- **Offer left unanswered:** the lead's inbox flags offers older than the org's threshold
  (`mc org settings --stale-offer-days 5`); follow up, or `mc assignment release <id>` and re-match.
- **Audit trail:** `mc mission history ART-4`.

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
