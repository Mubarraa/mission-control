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
make logins    # show the logins again any time
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
mc                                    # getting started: who you are and what to do next
mc guide onboard|plan|approve|changes     # step-by-step workflows, by role
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
- `mission cancel`, `mission abort`, `assignment release` and `member deactivate` ask for confirmation; add
  `--yes` in scripts.
- Exit codes: `0` ok, `2` usage, `3` auth/permission, `4` not found, `5` conflict/validation, `6` server/connection.
- Configuration: `--api URL` or `MC_API_URL`; the session lives in `~/.config/mc/session.json` (mode 0600, token
  only); `MC_PASSWORD` allows non-interactive login (used by the demo).
- Suggested commands are printed as `uv run mc ...` so you can copy them directly. If you install the CLI
  (`uv tool install ./cli`), set `MC_COMMAND=mc` to get plain `mc ...` suggestions.
- Examples in this README write `mc` for short; from the repo, run them as `uv run mc`.

## Guide by role

Every command below is run as `uv run mc ...` from the repo (written `mc` here for short). Switch users with
`mc login --org <slug> --email <email>`, and check who you are with `mc` or `mc whoami`. The same workflows are
also available in the terminal: `mc guide onboard | plan | approve | changes`.

| Role | In one line |
|---|---|
| **Director** | Runs the organisation: settings, the skill list, people, verifying skills, and approving missions |
| **Mission Lead** | Plans missions: slots, matching, offers, verifying skills, and submitting for approval |
| **Crew Member** | Keeps their own profile current and responds to offers |

### Director

**Set up the organisation**
```bash
mc org settings                                   # view settings
mc org settings --approvals 2                     # missions need 2 Directors to approve
mc org settings --recovery-days 14 --stale-offer-days 3
mc skill add "Robotics" --category Systems        # only Directors manage the skill list
mc skill list
mc skill deactivate "Robotics"
```

**Manage people**
```bash
mc member add sam@artemis.io --name "Sam Rivera" --role CREW --crew   # --crew also creates a crew profile
mc member add lee@artemis.io --name "Lee Wong" --role LEAD
mc member list
mc member deactivate sam@artemis.io               # asks for confirmation; history is kept
mc crew create existing@artemis.io                # crew profile for someone who is already a member
```

**Verify crew skills** (never your own)
```bash
mc crew list                                      # "+1 unverified" marks pending claims
mc crew show "Sam Rivera"
mc crew verify "Sam Rivera" geology
mc crew verify "Sam Rivera" eva --level 2 --cert-expires 2028-12-31
```

**Approve missions** (never one you submitted or own)
```bash
mc inbox                                          # missions awaiting approval
mc mission show ART-4                             # review what you're approving
mc mission approve ART-4
mc mission reject ART-4 --reason "Need a backup EVA specialist"
mc mission history ART-4                          # audit trail
```

Directors can also do everything a Mission Lead can, on any mission.

### Mission Lead

**Plan a mission**
```bash
mc mission create "Shackleton Rim Traverse" --start 2027-03-02 --end 2027-03-20   # prints the code, e.g. ART-4
mc mission slot add ART-4 --role Commander --skill piloting:4
mc mission slot add ART-4 --role Geologist --count 2 --skill geology:3
mc mission slot add ART-4 --role "EVA Specialist" --skill eva:3:cert            # :cert = valid certification
mc mission edit ART-4 --end 2027-03-22            # date changes send a pending/approved mission back to DRAFT
mc mission show ART-4
```

**Staff it**
```bash
mc match ART-4                                    # best crew for the whole mission, with reasons
mc match ART-4 --explain Geologist                # score breakdown, alternatives, why-not (closest first)
mc match ART-4 --apply                            # offer the suggestions (or --only Commander)
mc mission offer ART-4 "Hana Kim" --slot Geologist   # offer one person by hand (must be eligible)
mc crew verify "Dev Patel" geology                # if a pending claim would fill a gap
mc inbox                                          # who has accepted, who is still pending
```

**Get it approved and run it**
```bash
mc mission submit ART-4                           # needs an accepted crew member in every position
mc mission start ART-4                            # after approval
mc mission complete ART-4
mc mission cancel ART-4                           # before it starts; asks for confirmation
```

**Handle changes**
```bash
mc inbox                                          # withdrawals, stale offers, fully-crewed notices
mc inbox dismiss <id>
mc assignment release <id>                        # remove someone (also for emergencies once ACTIVE)
mc assignment list --mission ART-4
```

You can't approve your own mission. A different Director has to.

### Crew Member

**Keep your profile current**
```bash
mc profile show
mc profile skill set geology 4                    # adds or changes a skill; it waits for verification
mc profile skill remove geology
mc profile unavailable add 2027-05-01 2027-05-15 --category LEAVE --note "Wedding"
mc profile unavailable list
mc profile unavailable remove <id>
```
Only skills already in the organisation's skill list can be declared. Ask a Director to add a new one.
MEDICAL and OTHER unavailability show to Leads only as "Unavailable", and your note is private.

**Respond to offers**
```bash
mc inbox                                          # your offers and skills awaiting verification
mc assignment accept <id>                         # short ids are fine
mc assignment decline <id> --reason "Family commitment"     # a reason is required
mc assignment withdraw <id> --reason "Knee injury"          # before launch; the lead is notified
mc assignment list
```

### How the roles hand off

| Workflow | Steps |
|---|---|
| Onboard crew | **Director** adds the member (`--crew`), then the **crew member** declares skills and availability, then a **Director or Lead** verifies the skills |
| Staff a mission | **Lead** creates it, adds slots, matches and offers, then each **crew member** accepts (the Lead gets a "fully crewed" notification) |
| Approval | **Lead** submits, then a **different Director** approves or rejects (rejection returns it to DRAFT for the Lead) |
| Withdrawal | **Crew member** withdraws with a reason, then the **Lead** is notified, the mission returns to DRAFT, and the Lead re-matches |

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
