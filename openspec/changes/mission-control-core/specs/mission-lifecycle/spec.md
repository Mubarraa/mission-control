# Spec Delta

## Purpose

Governs how a mission goes from an idea to a completed, independently approved operation: its crew slots and requirements, its lifecycle states and transitions, the approval policy and separation of duties, and the assignments that commit crew to it.

## ADDED Requirements

### Requirement: Mission definition
A Director or Mission Lead SHALL be able to create a mission with a name, an optional description and a time window (half-open, start before end, start not in the past). The creator SHALL become the mission owner. Each mission SHALL receive a code unique within the organisation (e.g. ART-12), which is accepted wherever a mission is referenced.

#### Scenario: Lead creates a mission
- **WHEN** a Lead creates "Lunar South Pole Survey" from 2027-03-01 to 2027-03-21
- **THEN** the mission is created in DRAFT with revision 1, the Lead as owner, and a code such as ART-12

#### Scenario: Invalid window
- **WHEN** a mission is created with an end at or before its start, or a start in the past
- **THEN** the system rejects it with a validation error

### Requirement: Crew slots and requirements
A mission SHALL have one or more crew slots. Each slot has a role name, a headcount (at least 1) and one or more skill requirements. Each requirement names an organisation skill, a minimum proficiency level and whether a valid certification is required.

#### Scenario: Lead adds a slot
- **WHEN** a Lead adds slot "Geologist" with headcount 2 requiring Geology at level 3 or above
- **THEN** the mission has two Geologist positions to fill

#### Scenario: Unknown skill rejected
- **WHEN** a slot requirement references a skill that does not exist in the organisation or is deactivated
- **THEN** the system rejects the request

### Requirement: Lifecycle states and transitions
A mission SHALL be in one of DRAFT, PENDING_APPROVAL, APPROVED, ACTIVE, COMPLETED, CANCELLED or ABORTED. Only the following transitions SHALL be allowed: submit (DRAFT to PENDING_APPROVAL), approve (PENDING_APPROVAL to APPROVED), reject or withdraw (PENDING_APPROVAL to DRAFT), start (APPROVED to ACTIVE), complete (ACTIVE to COMPLETED), abort (ACTIVE to ABORTED), and cancel (DRAFT, PENDING_APPROVAL or APPROVED to CANCELLED).

#### Scenario: Illegal transition rejected
- **WHEN** a user tries to start a mission that is in DRAFT
- **THEN** the system responds 409 Conflict, naming the current state and the transitions allowed from it

#### Scenario: Terminal states are final
- **WHEN** a user tries any transition on a COMPLETED, CANCELLED or ABORTED mission
- **THEN** the system responds 409 Conflict

### Requirement: Transition permissions
The mission owner or a Director SHALL be able to submit, withdraw, start, complete, abort and cancel a mission. Only Directors SHALL approve or reject. Crew Members SHALL NOT perform mission transitions.

#### Scenario: Another lead cannot submit
- **WHEN** a Lead who does not own a mission tries to submit it
- **THEN** the system responds 403 Forbidden

### Requirement: Submission gate
A mission SHALL only be submitted when it has at least one slot and every slot position is filled by an ACCEPTED assignment.

#### Scenario: Unfilled slot blocks submission
- **WHEN** a lead submits a mission where one Geologist position has no accepted assignment
- **THEN** the system responds 409 Conflict and lists each unfilled slot

#### Scenario: Complete crew submits
- **WHEN** every slot position has an ACCEPTED assignment and the owner submits
- **THEN** the mission moves to PENDING_APPROVAL and records the submitter and the revision being submitted

### Requirement: Started window blocks submission and approval
A mission SHALL NOT be submitted or approved once its window has started (start at or before the current time). The owner must edit the window, which is a material change, before it can proceed.

#### Scenario: Submit after start date passed
- **WHEN** the owner submits a DRAFT mission whose start time has already passed
- **THEN** the system responds 409 Conflict explaining that the window has started and the dates must be edited

#### Scenario: Approve after start date passed
- **WHEN** a Director approves a PENDING_APPROVAL mission whose start time has passed since submission
- **THEN** the system responds 409 Conflict and the mission stays PENDING_APPROVAL

### Requirement: Separation of duties for approval
The user who submitted a mission, and the mission owner, SHALL NOT approve or reject it, whatever their role.

#### Scenario: Director cannot approve own submission
- **WHEN** a Director who created and submitted a mission tries to approve it
- **THEN** the system responds 403 Forbidden, explaining that a different approver is required

#### Scenario: Different director approves
- **WHEN** a Director other than the submitter and owner approves a pending mission and the policy requires one approval
- **THEN** the mission moves to APPROVED

### Requirement: Approval policy
A mission SHALL become APPROVED only after receiving the number of approvals required by the organisation policy in force when it was submitted, each from a distinct eligible Director. A single rejection with a reason SHALL return it to DRAFT.

#### Scenario: Two approvals required
- **WHEN** the policy requires 2 approvals and one eligible Director approves
- **THEN** the mission stays PENDING_APPROVAL with 1 of 2 approvals recorded

#### Scenario: Same approver twice
- **WHEN** a Director who already approved a mission approves it again
- **THEN** the system responds 409 Conflict and the count does not change

#### Scenario: Rejection requires a reason
- **WHEN** a Director rejects a mission
- **THEN** a reason is required, the mission returns to DRAFT, and the recorded approvals are cleared

#### Scenario: Policy change does not affect in-flight missions
- **WHEN** the policy changes from 1 to 2 approvals while a mission is PENDING_APPROVAL
- **THEN** that mission still needs only 1 approval

### Requirement: Revision-bound approval
Each material change to a mission (window, slots, requirements, or assignments) SHALL increment its revision. Approvals SHALL apply to a specific revision. A material change while PENDING_APPROVAL or APPROVED SHALL return the mission to DRAFT and void existing approvals.

#### Scenario: Edit while pending
- **WHEN** the owner changes the mission window while it is PENDING_APPROVAL
- **THEN** the revision increments, the mission returns to DRAFT, the approvals are voided, and an audit event records why

#### Scenario: Assignment released after approval
- **WHEN** an accepted crew member on an APPROVED mission is released
- **THEN** the mission returns to DRAFT and must be resubmitted

#### Scenario: Stale approval rejected
- **WHEN** an approval is submitted for revision 3 while the mission is at revision 4
- **THEN** the system responds 409 Conflict

#### Scenario: Locked after start
- **WHEN** someone tries to make a material change to an ACTIVE mission
- **THEN** the system responds 409 Conflict

### Requirement: Assignment offers
The mission owner or a Director SHALL be able to offer a slot position to an eligible crew member on a DRAFT mission, creating a PROPOSED assignment. A crew member SHALL hold at most one non-declined assignment per mission. The number of PROPOSED and ACCEPTED assignments in a slot SHALL NOT exceed its headcount.

#### Scenario: Offer created
- **WHEN** a Lead offers Alice the Commander slot on their DRAFT mission
- **THEN** a PROPOSED assignment is created and appears in Alice's inbox

#### Scenario: Duplicate crew on a mission
- **WHEN** a Lead offers Alice a second slot on a mission where she already has a PROPOSED or ACCEPTED assignment
- **THEN** the system responds 409 Conflict

#### Scenario: Slot over-filled
- **WHEN** a Lead offers a third Geologist position on a slot with headcount 2 that already has two active assignments
- **THEN** the system responds 409 Conflict

### Requirement: Assignment responses
The offered crew member SHALL be able to accept or decline a PROPOSED assignment. Declining SHALL require a non-empty reason. The mission owner or a Director SHALL be able to release a PROPOSED or ACCEPTED assignment before the mission is ACTIVE.

#### Scenario: Crew accepts
- **WHEN** Alice accepts her PROPOSED Commander assignment and has no conflicting commitment
- **THEN** the assignment becomes ACCEPTED and blocks her time for the mission window plus the recovery buffer

#### Scenario: Crew declines
- **WHEN** Bob declines with reason "family commitment"
- **THEN** the assignment becomes DECLINED, the position reopens, and Bob is not suggested again for that mission

#### Scenario: Decline without a reason
- **WHEN** a Crew Member declines an offer with an empty reason
- **THEN** the system rejects the request with a validation error and the offer stays PROPOSED

#### Scenario: Responding to someone else's offer
- **WHEN** a Crew Member tries to accept an assignment offered to someone else
- **THEN** the system responds 404 Not Found

### Requirement: Crew withdrawal
A crew member SHALL be able to withdraw from their own ACCEPTED assignment while the mission is DRAFT, PENDING_APPROVAL or APPROVED, giving a mandatory non-empty reason. The assignment becomes WITHDRAWN, the position reopens, the revision increments, and the mission owner is notified. Withdrawal SHALL NOT be possible once the mission is ACTIVE.

#### Scenario: Withdraw from a draft mission
- **WHEN** Bob withdraws from his ACCEPTED Geologist assignment on a DRAFT mission with reason "knee injury"
- **THEN** the assignment becomes WITHDRAWN, the position reopens, the mission stays DRAFT, and the owner receives a notification with Bob's reason

#### Scenario: Withdraw from an approved mission
- **WHEN** Bob withdraws from an APPROVED mission with a reason
- **THEN** the mission returns to DRAFT, its approvals are voided, and the owner receives a notification that the mission is back in DRAFT and why

#### Scenario: Reason required
- **WHEN** a crew member tries to withdraw with an empty reason
- **THEN** the system rejects the request with a validation error and the assignment stays ACCEPTED

#### Scenario: No withdrawal from an active mission
- **WHEN** a crew member tries to withdraw from an ACTIVE mission
- **THEN** the system responds 409 Conflict, explaining that the mission is under way and the lead must release them

#### Scenario: Withdrawn crew not re-suggested
- **WHEN** the matcher runs on a mission Bob withdrew from
- **THEN** Bob is excluded, with the reason "withdrew from this mission"

### Requirement: No double booking
A crew member SHALL NOT hold two ACCEPTED assignments whose blocked periods overlap. The blocked period is the mission window extended at the end by the organisation's recovery buffer. This SHALL hold even when two acceptances happen at the same moment.

#### Scenario: Overlapping acceptance rejected
- **WHEN** Alice, accepted on ART-9 (blocked until 2027-03-04 including the buffer), tries to accept an assignment on a mission starting 2027-03-01
- **THEN** the system responds 409 Conflict and names the conflicting mission

#### Scenario: Concurrent acceptance
- **WHEN** two overlapping offers to the same crew member are accepted at the same moment
- **THEN** exactly one becomes ACCEPTED and the other is rejected with a conflict

#### Scenario: Unavailability blocks acceptance
- **WHEN** a crew member accepts an assignment that overlaps one of their unavailability windows
- **THEN** the system responds 409 Conflict and names the overlapping window
