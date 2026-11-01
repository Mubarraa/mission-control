# Spec Delta

## Purpose

Describes what each crew member can do and when they can do it: the organisation's skill taxonomy, each crew member's proficiency and certifications, how self-declared skills become trusted, and when a crew member is unavailable.

## ADDED Requirements

### Requirement: Organisation skill taxonomy
Each organisation SHALL define its own skills, each with a unique name in that organisation, an optional category and a description. Only Directors SHALL create or change skills. Skills SHALL be deactivated, not deleted.

#### Scenario: Director defines a skill
- **WHEN** a Director creates the skill "EVA" in category "Operations"
- **THEN** the skill is available to that organisation only

#### Scenario: Duplicate skill name
- **WHEN** a Director creates a skill whose name already exists in their organisation, ignoring case
- **THEN** the system rejects it with a conflict error

#### Scenario: Same name in another organisation
- **WHEN** Org B creates a skill named "EVA" that Org A already has
- **THEN** the skill is created, because taxonomies are independent

### Requirement: Crew profile
A crew profile SHALL be linked to one membership and hold a display name, a short bio and an active flag. Any member, including a Director or Lead, MAY have a crew profile. Only members with a crew profile SHALL be considered for assignments.

#### Scenario: Director creates a crew profile for a member
- **WHEN** a Director creates a crew profile for a member
- **THEN** that member can be matched and assigned to missions

#### Scenario: Deactivated crew is not assignable
- **WHEN** a crew profile is deactivated
- **THEN** it is excluded from matching and new offers, and its past assignments are preserved

### Requirement: Proficiency levels
A crew skill SHALL record a proficiency level from 1 to 5 (1 Awareness, 2 Novice, 3 Competent, 4 Proficient, 5 Expert) and MAY record a certification expiry date.

#### Scenario: Invalid level rejected
- **WHEN** a crew skill is submitted with level 0 or 6
- **THEN** the system rejects it with a validation error

### Requirement: Self-declared skills
Crew Members SHALL be able to add, change and remove skills on their own profile. A newly declared skill SHALL be UNVERIFIED.

#### Scenario: Crew declares a skill
- **WHEN** a Crew Member adds "Geology" at level 4 to their own profile
- **THEN** the skill is stored as UNVERIFIED with a claimed level of 4

#### Scenario: Crew cannot edit another profile's skills
- **WHEN** a Crew Member tries to add a skill to another crew member's profile
- **THEN** the system responds 404 Not Found

### Requirement: Skill verification
Directors and Mission Leads SHALL be able to verify a crew skill. They may adjust the level and set the certification expiry. Verification records who verified it and when. Nobody SHALL verify a skill on their own crew profile.

#### Scenario: Lead verifies with an adjusted level
- **WHEN** a Lead verifies Bob's claimed Geology level 4 as level 3
- **THEN** the skill becomes VERIFIED at level 3 and records the Lead and time

#### Scenario: Self-verification forbidden
- **WHEN** a Lead who also has a crew profile tries to verify a skill on their own profile
- **THEN** the system responds 403 Forbidden and explains that someone else must verify it

### Requirement: Re-verification after edits
When a crew member changes the level of a VERIFIED skill, the skill SHALL become UNVERIFIED with the new claimed level. The last verified level SHALL remain the level used for matching until the skill is verified again.

#### Scenario: Edit after verification
- **WHEN** Alice, verified at Piloting 3, changes her claimed level to 5
- **THEN** the skill shows claimed level 5 as UNVERIFIED, and matching keeps using verified level 3

#### Scenario: Removing a skill
- **WHEN** a crew member removes a skill from their profile
- **THEN** the skill no longer counts toward matching

### Requirement: Unavailability windows
Crew SHALL be able to record unavailability windows on their own profile, and Directors may do so for any crew member. Each window has a start and end (half-open interval), a category (LEAVE, TRAINING, MEDICAL, OTHER) and an optional private note. The end SHALL be after the start.

#### Scenario: Crew records leave
- **WHEN** a Crew Member records LEAVE from 2027-03-01 to 2027-03-08
- **THEN** they are treated as unavailable for any part of that interval

#### Scenario: Invalid window
- **WHEN** a window is submitted with an end at or before its start
- **THEN** the system rejects it with a validation error

### Requirement: Unavailability privacy
Mission Leads SHALL see every unavailability window. LEAVE and TRAINING windows show their category. MEDICAL and OTHER windows show only "Unavailable". Leads SHALL never see the private note. The crew member and Directors SHALL see the full category and note.

#### Scenario: Lead sees a medical window
- **WHEN** a Lead views the availability of a crew member who has a MEDICAL window
- **THEN** the window is shown as "Unavailable" with no category detail or note

#### Scenario: Director sees full detail
- **WHEN** a Director views the same crew member's availability
- **THEN** the window shows category MEDICAL and the note

### Requirement: Assignment history
Directors and Mission Leads SHALL be able to view a crew member's assignment history with missions, slots, dates and outcomes. Crew Members SHALL be able to view their own.

#### Scenario: Crew views own history
- **WHEN** a Crew Member requests their assignments
- **THEN** they see their past, current and pending assignments with mission code, slot, window and state
