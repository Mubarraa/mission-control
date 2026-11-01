# Spec Delta

## Purpose

Suggests the best crew for a mission as a whole, explains every suggestion and every gap, and lets a lead turn the suggestions into offers. The engine never commits crew on its own.

## ADDED Requirements

### Requirement: Run the matcher
The mission owner or a Director SHALL be able to run the matcher on a DRAFT mission. It considers only the slot positions not already covered by PROPOSED or ACCEPTED assignments. Running the matcher SHALL NOT change any data.

#### Scenario: Matcher on a draft
- **WHEN** a Lead runs the matcher on their DRAFT mission with 3 open positions
- **THEN** the system returns a suggestion or an explicit gap for each of the 3 positions, and no assignments are created

#### Scenario: Matcher on a non-draft mission
- **WHEN** the matcher is run on a mission that is PENDING_APPROVAL or later
- **THEN** the system responds 409 Conflict

### Requirement: Hard eligibility rules
A crew member SHALL be eligible for a slot only if all of the following hold. They have an active crew profile in the organisation. Every requirement of the slot is met by a VERIFIED level at or above the minimum. Any required certification is valid until the mission end. They have no unavailability window or ACCEPTED assignment overlapping the mission's blocked period. They are not on the mission already. They have not declined or withdrawn from this mission.

#### Scenario: Unverified skill does not qualify
- **WHEN** Bob claims Geology 4 but has no verified Geology level
- **THEN** Bob is not eligible for a slot requiring Geology 3 or above

#### Scenario: Certification expiring mid-mission
- **WHEN** Carol's EVA certification expires on 2027-03-10 and the mission runs 2027-03-01 to 2027-03-21 with EVA certification required
- **THEN** Carol is not eligible for that slot

#### Scenario: Recovery buffer respected
- **WHEN** Dana's accepted mission ends 2027-02-20, the buffer is 14 days, and the new mission starts 2027-03-01
- **THEN** Dana is not eligible

#### Scenario: Pending offers do not exclude
- **WHEN** Eve has only a PROPOSED (not accepted) assignment on another overlapping mission
- **THEN** Eve remains eligible, with a lower score and a note about the competing offer

### Requirement: Soft scoring
For each eligible crew-slot pair, the matcher SHALL compute a score from 0 to 1 that combines skill fit, workload balance, relevant experience, an over-qualification penalty, and a penalty for competing pending offers. The weights SHALL be documented. Each score SHALL come with a breakdown by factor.

#### Scenario: Workload balance
- **WHEN** two crew members are equally qualified and one has 60 assigned mission-days in the trailing 90 days while the other has 0
- **THEN** the crew member with less recent workload scores higher

#### Scenario: Over-qualification penalty
- **WHEN** a slot requires Medicine 2 and both a level-5 and a level-2 medic are eligible and otherwise equal
- **THEN** the level-2 medic scores higher, keeping the expert free for missions that need one

### Requirement: Mission-wide optimal assignment
The matcher SHALL choose suggestions across all open positions together to maximise the total score, filling as many positions as possible. It SHALL NOT fill slots one at a time greedily. Results SHALL be deterministic for the same data.

#### Scenario: Greedy trap avoided
- **WHEN** a mission needs a Commander (Piloting 4+) and a Geologist (Geology 3+), Alice is the only pilot and the best geologist, and Bob is a qualified geologist
- **THEN** the matcher suggests Alice as Commander and Bob as Geologist

#### Scenario: Deterministic output
- **WHEN** the matcher runs twice on unchanged data, including ties in score
- **THEN** both runs return identical suggestions

### Requirement: Explanations and alternatives
Each suggestion SHALL include its score breakdown, a short explanation of why the crew member fits (e.g. "piloting 5 (needs 4+), cert valid to 2028-06, light workload") and up to three ranked alternative candidates for that position.

#### Scenario: Suggestion explanation
- **WHEN** the matcher suggests Alice as Commander
- **THEN** the response includes her score, the factor breakdown, a short explanation and alternatives

### Requirement: Why-not diagnostics
For each position the matcher cannot fill, the result SHALL say so and list the candidates that were excluded, each with every hard rule they failed in plain language. A candidate whose unverified claim would meet a requirement SHALL be flagged as worth verifying. The matcher SHALL NOT fill an unfillable position with a candidate who fails any hard rule.

#### Scenario: Unfillable slot explained
- **WHEN** no crew member is eligible for the Commander slot
- **THEN** the result marks the slot unfilled and lists reasons such as "Dana: piloting 3 < 4 required" and "Eve: on ART-9 until 2027-03-04 incl. recovery"

#### Scenario: Verification hint
- **WHEN** Bob's unverified Geology 4 claim would have met an unfilled Geologist requirement
- **THEN** the why-not entry for Bob says that verifying his Geology skill would make him eligible

#### Scenario: Privacy preserved in reasons
- **WHEN** a candidate is excluded because of a MEDICAL unavailability window
- **THEN** the reason says "unavailable" with the dates and no medical detail

#### Scenario: No under-qualified fallback
- **WHEN** a Geologist slot requires Geology 3 and the only crew with Geology have verified level 2
- **THEN** the position is reported unfilled and no level-2 crew member is suggested, even though doing so would complete the mission

### Requirement: Closest candidates first
Why-not entries SHALL be ordered by closeness to eligibility: first candidates whose only issue is an unverified claim, then those one level below the minimum, then those blocked only by availability or commitments, then the rest. Ties are broken by name. Only the five closest are returned by default, and all of them on request.

#### Scenario: Near-miss ordering
- **WHEN** a slot needs Geology 3 and the excluded crew are Frank (no geology), Dana (geology 2) and Bob (unverified claim of 4)
- **THEN** the why-not list is ordered Bob, Dana, Frank

#### Scenario: Truncated list
- **WHEN** 40 crew members are excluded from a position
- **THEN** the five closest are returned along with the total excluded count, and requesting all returns all 40

### Requirement: Apply suggestions
The mission owner or a Director SHALL be able to apply all suggestions, or only chosen ones, from a match run. Each applied suggestion becomes a PROPOSED assignment. Applying SHALL re-check eligibility and reject any suggestion that is no longer valid, without affecting the others.

#### Scenario: Apply all
- **WHEN** a Lead applies all suggestions from a match
- **THEN** a PROPOSED assignment is created for each suggested crew member, and each appears in that crew member's inbox

#### Scenario: Stale suggestion
- **WHEN** a suggested crew member accepted a conflicting mission after the match ran and the Lead applies the suggestions
- **THEN** that one suggestion is reported as no longer eligible with its reason, and the others are applied
