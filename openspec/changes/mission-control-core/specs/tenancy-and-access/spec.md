# Spec Delta

## Purpose

Defines organisations as isolated tenants, how users authenticate into exactly one organisation at a time, what each role may do, and the append-only audit trail of consequential actions.

## ADDED Requirements

### Requirement: Organisation-scoped data
Every mission, crew profile, skill, assignment, approval and audit event SHALL belong to exactly one organisation. A request SHALL only read or change records of the organisation its token is scoped to.

#### Scenario: Listing returns only own-tenant records
- **WHEN** a Director of Org A lists missions
- **THEN** the response contains only Org A missions and no Org B missions

#### Scenario: Cross-tenant read is not found
- **WHEN** a user authenticated to Org A requests an Org B mission by its identifier
- **THEN** the system responds 404 Not Found, the same as for an identifier that does not exist

#### Scenario: Cross-tenant write is not found
- **WHEN** a user authenticated to Org A tries to update, transition or assign crew on an Org B mission
- **THEN** the system responds 404 Not Found and changes nothing

#### Scenario: Cross-tenant references are rejected
- **WHEN** an Org A lead adds an Org B skill to an Org A mission slot, or offers an Org B crew member an Org A slot
- **THEN** the system rejects the request as referencing a resource that was not found

### Requirement: Memberships and roles
A user SHALL be able to hold memberships in several organisations, with exactly one role per organisation: Director, Mission Lead or Crew Member. A membership SHALL be deactivatable but never deleted.

#### Scenario: User with two memberships
- **WHEN** a user is a Mission Lead in Org A and a Crew Member in Org B
- **THEN** they act with Mission Lead permissions when authenticated to Org A and Crew Member permissions when authenticated to Org B

#### Scenario: Deactivated membership cannot authenticate
- **WHEN** a Director deactivates a member and that member then tries to log in to the organisation
- **THEN** authentication fails and the member's history is preserved

### Requirement: Org-scoped authentication
The system SHALL authenticate users by email and password for a named organisation and issue a bearer token scoped to that one organisation and membership. Requests without a valid token SHALL be rejected.

#### Scenario: Successful login
- **WHEN** a user submits valid credentials and an organisation where they hold an active membership
- **THEN** the system returns a bearer token that carries the organisation and role, and an expiry time

#### Scenario: Login to an organisation without membership
- **WHEN** a user submits valid credentials for an organisation where they hold no membership
- **THEN** authentication fails with the same error as for invalid credentials

#### Scenario: Missing or invalid token
- **WHEN** a request to a protected endpoint has no token, or an expired or tampered one
- **THEN** the system responds 401 Unauthorized

### Requirement: Role-based permissions
The system SHALL enforce the permissions of each role. Directors manage organisation settings, members, the skill taxonomy and approvals, and see everything in the organisation. Mission Leads create and manage missions, run the matcher and verify skills. Crew Members manage their own profile, skills and availability and respond to their own assignments.

#### Scenario: Crew member cannot create missions
- **WHEN** a Crew Member tries to create a mission
- **THEN** the system responds 403 Forbidden

#### Scenario: Mission lead cannot change organisation settings
- **WHEN** a Mission Lead tries to change the approval policy
- **THEN** the system responds 403 Forbidden

#### Scenario: Director manages members
- **WHEN** a Director adds a member with an email, name and role
- **THEN** the member is created in the Director's organisation and can log in with the initial credentials

### Requirement: Crew member visibility limits
Crew Members SHALL only see their own profile, the missions they hold an assignment on, and the organisation's skill taxonomy. They SHALL NOT see other crew profiles, availability or missions they are not assigned to.

#### Scenario: Crew member lists missions
- **WHEN** a Crew Member lists missions
- **THEN** only missions where they have an assignment are returned

#### Scenario: Crew member reads another profile
- **WHEN** a Crew Member requests another crew member's profile
- **THEN** the system responds 404 Not Found

### Requirement: Organisation settings
Each organisation SHALL have settings that only a Director can change: the number of approvals a mission needs (default 1), the post-mission recovery buffer in days (default 14), and the stale offer threshold in days (default 3).

#### Scenario: Director updates settings
- **WHEN** a Director sets approvals required to 2
- **THEN** missions submitted afterwards need two approvals from distinct eligible approvers

#### Scenario: Director sets stale offer threshold
- **WHEN** a Director sets the stale offer threshold to 5 days
- **THEN** leads' inboxes flag PROPOSED offers only once they are older than 5 days

### Requirement: Append-only audit trail
The system SHALL record an audit event for each mission state transition, approval or rejection, assignment offer, response and withdrawal, skill verification, membership change and settings change. Each event records the actor, time, entity, action and relevant details. Audit events SHALL NOT be modifiable or deletable through any interface.

#### Scenario: Transition is audited
- **WHEN** a lead submits a mission for approval
- **THEN** an audit event records the lead, the time, the mission, and the transition from DRAFT to PENDING_APPROVAL

#### Scenario: Viewing a mission's history
- **WHEN** a Director or the mission's lead requests the history of a mission
- **THEN** the system returns that mission's audit events in time order

### Requirement: Notifications
The system SHALL deliver notifications to individual members for events that need their attention: a crew withdrawal, and a mission becoming fully crewed, each notify the mission owner. A notification belongs to one organisation and one recipient. Only the recipient SHALL see it. It stays unread until the recipient dismisses it. Notifications are separate from the audit trail, and dismissing one SHALL NOT affect audit events.

#### Scenario: Owner notified of withdrawal
- **WHEN** a crew member withdraws from a mission owned by a Lead
- **THEN** the Lead has an unread notification naming the mission, the crew member, the slot, the reason, and whether the mission returned to DRAFT

#### Scenario: Owner notified when fully crewed
- **WHEN** the last open position on a DRAFT mission is accepted
- **THEN** the owner receives one notification that the mission is fully crewed and ready to submit; earlier acceptances create no notification

#### Scenario: Only the recipient sees a notification
- **WHEN** another member of the same organisation, or a member of another organisation, lists their notifications
- **THEN** the Lead's notification does not appear, and trying to dismiss it by identifier gives 404 Not Found

#### Scenario: Dismissing a notification
- **WHEN** the Lead dismisses the notification
- **THEN** it no longer appears among their unread notifications, and the withdrawal's audit event is unchanged
