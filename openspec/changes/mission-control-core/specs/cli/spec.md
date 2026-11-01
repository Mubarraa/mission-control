# Spec Delta

## Purpose

Defines the `mc` command-line experience, the primary interface through which directors, mission leads and crew members carry out every core workflow against the Mission Control API.

## ADDED Requirements

### Requirement: Login and context
`mc login` SHALL authenticate against a configurable API URL for a named organisation, store the session locally, and confirm who the user is, their role and the organisation. `mc logout` SHALL clear the session. `mc whoami` SHALL show the current context.

#### Scenario: Successful login
- **WHEN** a user runs `mc login --org artemis-labs` and enters valid credentials at the prompts
- **THEN** the CLI prints the user's email, role and organisation and saves the session for later commands

#### Scenario: Password never echoed or stored
- **WHEN** a user logs in interactively
- **THEN** the password is not echoed and not written to disk; only the token is stored, in a file readable only by the user

#### Scenario: Not logged in
- **WHEN** a user runs any command that needs authentication without a session, or with an expired one
- **THEN** the CLI exits with a non-zero status and tells them to run `mc login`

### Requirement: Primary workflow coverage
The CLI SHALL cover every primary workflow through the API alone. That includes organisation settings and members, the skill taxonomy, crew profiles, skills, verification and availability, mission creation and slots, matching with explanations and applying suggestions, offers, assignment responses and withdrawals, notifications, every lifecycle transition, approvals and rejections, and mission history.

#### Scenario: End-to-end journey through the CLI
- **WHEN** a lead creates a mission, adds slots, runs `mc match` and applies the suggestions, the crew accept via `mc assignment accept`, the lead runs `mc mission submit`, and a different director runs `mc mission approve`
- **THEN** the mission ends APPROVED without any direct API or database access

### Requirement: Role-aware inbox
`mc inbox` SHALL show what needs the current user's attention for their role, starting with any unread notifications for every role. Directors see missions awaiting their approval. Leads see their missions with unfilled positions, declined offers, rejections, and PROPOSED offers with their age, flagged once older than the organisation's stale offer threshold. Offers never expire automatically. Crew see pending assignment offers and skills awaiting verification.

#### Scenario: Director inbox
- **WHEN** a Director runs `mc inbox` while two missions are PENDING_APPROVAL, one of which they submitted
- **THEN** both are listed, and the one they submitted is marked as needing another approver

#### Scenario: Crew inbox
- **WHEN** a Crew Member with one PROPOSED assignment runs `mc inbox`
- **THEN** the offer is listed with mission code, slot and dates, along with the command to accept or decline it

#### Scenario: Lead sees stale offers
- **WHEN** a Lead's mission has an offer to Bob that has been PROPOSED for 4 days and the stale threshold is 3 days
- **THEN** `mc inbox` lists it as stale with its age and suggests `mc assignment release <id>` or following up with the crew member

#### Scenario: Fresh offers are not flagged
- **WHEN** an offer has been PROPOSED for 2 days and the stale threshold is 3 days
- **THEN** `mc inbox` lists it with its age but does not flag it as stale

#### Scenario: Lead sees who has accepted
- **WHEN** a Lead's DRAFT mission has five positions and one crew member has accepted
- **THEN** `mc inbox` shows every slot in order with who has accepted and who is still offered, a "1 of 5 accepted" count, and a next step explaining that it is waiting for crew

#### Scenario: Lead sees a withdrawal notification
- **WHEN** Bob has withdrawn from the Lead's approved mission ART-12
- **THEN** `mc inbox` shows the notification first, with the mission now in DRAFT, Bob's slot and reason, and suggests `mc match ART-12` and `mc inbox dismiss <id>`

#### Scenario: Dismissing from the CLI
- **WHEN** the Lead runs `mc inbox dismiss <id>`
- **THEN** the CLI confirms the dismissal and the notification no longer appears in `mc inbox`

### Requirement: Crew withdrawal command
`mc assignment withdraw ID --reason TEXT` SHALL withdraw the current crew member from their accepted assignment. The CLI SHALL prompt for a reason if none is given and refuse to send an empty one.

#### Scenario: Withdraw with a reason
- **WHEN** Bob runs `mc assignment withdraw 17 --reason "knee injury"`
- **THEN** the CLI confirms the withdrawal and notes that the mission lead has been notified, along with any change to the mission's state

#### Scenario: Missing reason
- **WHEN** Bob runs `mc assignment withdraw 17` without `--reason`
- **THEN** the CLI prompts for a reason and does not send the request until a non-empty reason is entered

### Requirement: Human-friendly references
Commands SHALL accept mission codes (e.g. ART-12) instead of internal identifiers, and readable names or emails for crew and skills where they are unambiguous.

#### Scenario: Mission by code
- **WHEN** a user runs `mc mission show ART-12`
- **THEN** the mission is shown without the user needing its internal identifier

#### Scenario: Ambiguous name
- **WHEN** a crew name matches more than one crew member
- **THEN** the CLI lists the matches and asks the user to use the email

### Requirement: Readable output and next steps
By default, commands SHALL print readable tables and summaries. Commands that change state SHALL confirm what changed and suggest the logical next command.

#### Scenario: Next-step hint
- **WHEN** a lead creates a mission
- **THEN** the CLI prints the new mission code and state, followed by a suggested `mc mission slot add` command

#### Scenario: Match output
- **WHEN** a lead runs `mc match ART-12`
- **THEN** the CLI shows a table of positions with the suggested crew member, score and a short reason, highlights unfilled positions, and suggests `--explain` and `--apply`

### Requirement: Machine-readable output
Every command SHALL support `--json` to print the API result as JSON on stdout, with no decoration.

#### Scenario: JSON output
- **WHEN** a user runs `mc mission list --json`
- **THEN** stdout contains only valid JSON that can be piped to tools such as jq

### Requirement: Clear errors and exit codes
Errors SHALL be shown as one readable message explaining the rule that was violated and, where possible, how to resolve it. Commands SHALL exit 0 on success and non-zero on failure. Exit codes SHALL distinguish usage errors, authentication or permission errors, not found, conflicts, and server or connection errors.

#### Scenario: Business-rule error
- **WHEN** a director runs `mc mission approve` on a mission they submitted
- **THEN** the CLI prints that a different approver is required and exits with the permission-error code, with no stack trace

#### Scenario: API unreachable
- **WHEN** the API cannot be reached
- **THEN** the CLI names the URL it tried and exits with the connection-error code

### Requirement: Role-appropriate help
`mc --help` and each command group's help SHALL describe commands with examples. When a command needs a role the user lacks, the CLI SHALL say which role is required.

#### Scenario: Crew attempts approval
- **WHEN** a Crew Member runs `mc mission approve ART-12`
- **THEN** the CLI explains that approving missions requires the Director role

### Requirement: In-terminal workflow guides
`mc guide` SHALL list the available step-by-step guides, and `mc guide TOPIC` SHALL print one guide (onboarding crew, planning and staffing a mission, approval, handling changes), showing which role runs each step and commands that can be copied as-is. Every command shown in a guide SHALL be a real `mc` command.

#### Scenario: List guides
- **WHEN** a user runs `mc guide`
- **THEN** the CLI lists each topic with a one-line description and how to open it

#### Scenario: Open a guide
- **WHEN** a user runs `mc guide onboard`
- **THEN** the CLI prints the onboarding steps grouped by role (Director, crew member, Director or Lead), with runnable commands

### Requirement: Getting-started screen
Running `mc` with no arguments SHALL show a short getting-started screen based on the local session, without calling the API. It SHALL suggest `mc login` when not logged in, and show the current user, role and organisation with `mc inbox` as the next step when logged in, plus pointers to `mc guide` and `mc --help` in both cases.

#### Scenario: Not logged in
- **WHEN** a user with no session runs `mc`
- **THEN** the CLI suggests `mc login --org <slug>`, `mc guide` and `mc --help`

#### Scenario: Logged in
- **WHEN** a logged-in Mission Lead runs `mc`
- **THEN** the CLI shows their email, role and organisation and suggests `mc inbox`

### Requirement: Confirmation before irreversible actions
Cancelling or aborting a mission, releasing a crew member and deactivating a member SHALL ask for confirmation, describing the consequence, unless `--yes` is given. Declining the confirmation SHALL send no request.

#### Scenario: Cancel declined
- **WHEN** a lead runs `mc mission cancel ART-4` and answers no
- **THEN** no request is sent and the mission is unchanged

#### Scenario: Scripted cancel
- **WHEN** a lead runs `mc mission cancel ART-4 --yes`
- **THEN** the mission is cancelled without a prompt
