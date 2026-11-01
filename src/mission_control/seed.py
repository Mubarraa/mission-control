"""Demo data: two organisations with deliberately designed scenarios (design.md section 16).

Artemis Labs exercises every interesting matcher path:
  * Alice/Bob greedy trap      - Alice is the only available pilot AND the best geologist
  * Carol                      - EVA certification expires mid-mission
  * Dev                        - unverified Geology claim that would fill a gap
  * Eve                        - committed to ART-2, still inside the 14-day recovery buffer
  * Hana                       - on leave during the survey
  * Ivan                       - private MEDICAL window (Leads only see "Unavailable")
  * Farah vs Gabe              - right-sizing: a level-2 medic beats the level-5 expert for a level-2 slot
Orion Dynamics exists to demonstrate tenant isolation.

Safe to re-run: organisations that already exist are left untouched.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.security import hash_password

DEMO_PASSWORD = "mission-control-demo"


def _dt(y: int, mo: int, d: int) -> datetime:
    return datetime(y, mo, d, tzinfo=UTC)


class _Builder:
    def __init__(self, db: Session, org: m.Organisation, pw_hash: str) -> None:
        self.db, self.org, self.pw_hash = db, org, pw_hash
        self.skills: dict[str, m.Skill] = {}
        self.logins: list[tuple[str, str, str]] = []

    def member(self, name: str, email: str, role: str) -> m.Membership:
        user = self.db.scalar(select(m.User).where(m.User.email == email))
        if user is None:
            user = m.User(email=email, name=name, password_hash=self.pw_hash)
            self.db.add(user)
            self.db.flush()
        mem = m.Membership(org_id=self.org.id, user_id=user.id, role=role)
        self.db.add(mem)
        self.db.flush()
        self.logins.append((self.org.slug, email, role))
        return mem

    def skill(self, name: str, category: str, description: str) -> None:
        s = m.Skill(org_id=self.org.id, name=name, category=category, description=description)
        self.db.add(s)
        self.db.flush()
        self.skills[name] = s

    def crew(
        self,
        name: str,
        email: str,
        bio: str,
        verified: dict | None = None,
        claimed: dict | None = None,
        certs: dict | None = None,
        role: str = "CREW",
        member: m.Membership | None = None,
    ) -> m.CrewProfile:
        mem = member or self.member(name, email, role)
        c = m.CrewProfile(org_id=self.org.id, membership_id=mem.id, display_name=name, bio=bio)
        self.db.add(c)
        self.db.flush()
        for skill, level in (verified or {}).items():
            self.db.add(
                m.CrewSkill(
                    org_id=self.org.id,
                    crew_id=c.id,
                    skill_id=self.skills[skill].id,
                    claimed_level=level,
                    verified_level=level,
                    status="VERIFIED",
                    cert_expires_on=(certs or {}).get(skill),
                )
            )
        for skill, level in (claimed or {}).items():
            self.db.add(
                m.CrewSkill(
                    org_id=self.org.id,
                    crew_id=c.id,
                    skill_id=self.skills[skill].id,
                    claimed_level=level,
                    status="UNVERIFIED",
                )
            )
        self.db.flush()
        return c

    def mission(
        self,
        name: str,
        start: datetime,
        end: datetime,
        owner: m.Membership,
        state: str = "DRAFT",
        description: str | None = None,
    ) -> m.Mission:
        self.org.mission_seq += 1
        mi = m.Mission(
            org_id=self.org.id,
            code=f"{self.org.mission_prefix}-{self.org.mission_seq}",
            name=name,
            description=description,
            starts_at=start,
            ends_at=end,
            state=state,
            owner_id=owner.id,
            revision=1,
        )
        self.db.add(mi)
        self.db.flush()
        return mi

    def slot(self, mission: m.Mission, role: str, reqs: dict, headcount: int = 1, certs: set | None = None):
        s = m.MissionSlot(
            org_id=self.org.id,
            mission_id=mission.id,
            role_name=role,
            headcount=headcount,
            ordinal=len(mission.slots) + 1,
        )
        self.db.add(s)
        self.db.flush()
        for skill, level in reqs.items():
            self.db.add(
                m.SlotRequirement(
                    org_id=self.org.id,
                    slot_id=s.id,
                    skill_id=self.skills[skill].id,
                    min_level=level,
                    cert_required=skill in (certs or set()),
                )
            )
        self.db.flush()
        self.db.refresh(mission)
        return s

    def accepted(self, mission: m.Mission, slot: m.MissionSlot, crew: m.CrewProfile, offered_at: datetime):
        a = m.Assignment(
            org_id=self.org.id,
            mission_id=mission.id,
            slot_id=slot.id,
            crew_id=crew.id,
            state="ACCEPTED",
            source="MANUAL",
            offered_by=mission.owner_id,
            offered_at=offered_at,
            responded_at=offered_at,
            blocked_period=Range(
                mission.starts_at,
                mission.ends_at + timedelta(days=self.org.recovery_buffer_days),
                bounds="[)",
            ),
        )
        self.db.add(a)
        self.db.flush()


SKILLS = [
    ("Piloting", "Flight", "Spacecraft and lander piloting"),
    ("EVA", "Operations", "Extravehicular activity; certification required for spacewalks"),
    ("Geology", "Science", "Field and planetary geology"),
    ("Medicine", "Medical", "Flight surgery and crew medical care"),
    ("Engineering", "Systems", "Spacecraft systems and repair"),
    ("Communications", "Operations", "Deep-space communications"),
]


def seed_artemis(db: Session, pw_hash: str) -> list[tuple[str, str, str]]:
    org = m.Organisation(
        slug="artemis-labs",
        name="Artemis Labs",
        mission_prefix="ART",
        approvals_required=1,
        recovery_buffer_days=14,
        stale_offer_days=3,
    )
    db.add(org)
    db.flush()
    b = _Builder(db, org, pw_hash)
    for skill in SKILLS:
        b.skill(*skill)

    b.member("Amara Osei", "amara@artemis.io", "DIRECTOR")
    b.member("Lena Park", "lena@artemis.io", "DIRECTOR")
    priya = b.member("Priya Raman", "priya@artemis.io", "LEAD")
    marcus = b.member("Marcus Cole", "marcus@artemis.io", "LEAD")

    b.crew(
        "Alice Okafor",
        "alice@artemis.io",
        "Commander, 3 lunar sorties",
        verified={"Piloting": 5, "Geology": 5, "EVA": 4},
        certs={"EVA": date(2028, 6, 30)},
    )
    bob = b.crew("Bob Lindqvist", "bob@artemis.io", "Planetary geologist", verified={"Geology": 4, "Piloting": 2})
    b.crew(
        "Carol Mendes",
        "carol@artemis.io",
        "EVA specialist",
        verified={"EVA": 4, "Engineering": 3},
        certs={"EVA": date(2027, 3, 10)},
    )
    b.crew(
        "Dev Patel",
        "dev@artemis.io",
        "Recently transferred from the Mars analogue programme",
        verified={"Engineering": 4},
        claimed={"Geology": 4},
    )
    eve = b.crew("Eve Marsh", "eve@artemis.io", "Test pilot", verified={"Piloting": 4, "Engineering": 3})
    b.crew("Farah Haddad", "farah@artemis.io", "Senior flight surgeon", verified={"Medicine": 5})
    gabe = b.crew("Gabe Ito", "gabe@artemis.io", "Flight medic", verified={"Medicine": 2, "Communications": 3})
    hana = b.crew("Hana Kim", "hana@artemis.io", "Geochemist", verified={"Geology": 3})
    ivan = b.crew(
        "Ivan Petrov",
        "ivan@artemis.io",
        "EVA and systems",
        verified={"EVA": 3, "Engineering": 4},
        certs={"EVA": date(2029, 1, 31)},
    )
    b.crew("Jo Burke", "jo@artemis.io", "Communications lead", verified={"Communications": 4, "Engineering": 3})

    # History that feeds experience scores.
    shakedown = b.mission("Orbital Shakedown", _dt(2026, 8, 3), _dt(2026, 8, 17), marcus, state="COMPLETED")
    geo = b.slot(shakedown, "Geologist", {"Geology": 3})
    surgeon = b.slot(shakedown, "Flight Surgeon", {"Medicine": 2})
    b.accepted(shakedown, geo, bob, _dt(2026, 6, 1))
    b.accepted(shakedown, surgeon, gabe, _dt(2026, 6, 1))

    # Eve is committed to this one; its recovery buffer runs into the survey window.
    resupply = b.mission("Gateway Resupply", _dt(2027, 2, 1), _dt(2027, 2, 20), marcus, state="APPROVED")
    b.accepted(resupply, b.slot(resupply, "Pilot", {"Piloting": 4}), eve, _dt(2026, 10, 1))

    db.add(
        m.Unavailability(
            org_id=org.id,
            crew_id=hana.id,
            category="LEAVE",
            note="Family visit",
            period=Range(_dt(2027, 2, 25), _dt(2027, 3, 15), bounds="[)"),
        )
    )
    db.add(
        m.Unavailability(
            org_id=org.id,
            crew_id=ivan.id,
            category="MEDICAL",
            note="Knee surgery recovery",
            period=Range(_dt(2027, 5, 1), _dt(2027, 5, 29), bounds="[)"),
        )
    )

    survey = b.mission(
        "Lunar South Pole Survey",
        _dt(2027, 3, 1),
        _dt(2027, 3, 21),
        priya,
        description="Map volatile deposits in permanently shadowed craters.",
    )
    b.slot(survey, "Commander", {"Piloting": 4})
    b.slot(survey, "Geologist", {"Geology": 3}, headcount=2)
    b.slot(survey, "EVA Specialist", {"EVA": 3}, certs={"EVA"})
    b.slot(survey, "Flight Surgeon", {"Medicine": 2})
    return b.logins


def seed_orion(db: Session, pw_hash: str) -> list[tuple[str, str, str]]:
    org = m.Organisation(
        slug="orion-dynamics",
        name="Orion Dynamics",
        mission_prefix="ORN",
        approvals_required=2,
        recovery_buffer_days=7,
    )
    db.add(org)
    db.flush()
    b = _Builder(db, org, pw_hash)
    for skill in SKILLS[:3]:
        b.skill(*skill)
    b.member("Oskar Nilsson", "oskar@orion.space", "DIRECTOR")
    b.member("Mei Chen", "mei@orion.space", "DIRECTOR")
    lead = b.member("Tomas Varga", "tomas@orion.space", "LEAD")
    b.crew(
        "Rhea Solberg",
        "rhea@orion.space",
        "Prospecting pilot",
        verified={"Piloting": 4, "EVA": 3},
        certs={"EVA": date(2028, 1, 1)},
    )
    b.crew("Kai Mensah", "kai@orion.space", "Asteroid geologist", verified={"Geology": 5})
    mission = b.mission("Asteroid Prospecting", _dt(2027, 6, 1), _dt(2027, 6, 30), lead)
    b.slot(mission, "Pilot", {"Piloting": 3})
    return b.logins


def seed(db: Session) -> list[tuple[str, str, str]]:
    pw_hash = hash_password(DEMO_PASSWORD)
    logins = []
    for slug, builder in (("artemis-labs", seed_artemis), ("orion-dynamics", seed_orion)):
        if db.scalar(select(m.Organisation).where(m.Organisation.slug == slug)) is None:
            logins += builder(db, pw_hash)
    db.flush()
    return logins


def main() -> None:
    from mission_control.db.session import get_engine

    with Session(get_engine()) as db:
        created = seed(db)
        db.commit()
    if created:
        print(f"Seeded {len({s for s, _, _ in created})} organisation(s).")
    else:
        print("Demo organisations already exist - nothing to do.")
    print(f"\nDemo logins (password for everyone: {DEMO_PASSWORD})\n")
    print(f"  {'ORG':<16} {'ROLE':<9} EMAIL")
    for slug, email, role in [
        ("artemis-labs", "amara@artemis.io", "DIRECTOR"),
        ("artemis-labs", "lena@artemis.io", "DIRECTOR"),
        ("artemis-labs", "priya@artemis.io", "LEAD"),
        ("artemis-labs", "marcus@artemis.io", "LEAD"),
        ("artemis-labs", "alice@artemis.io", "CREW"),
        ("artemis-labs", "bob@artemis.io", "CREW"),
        ("artemis-labs", "dev@artemis.io", "CREW"),
        ("artemis-labs", "ivan@artemis.io", "CREW"),
        ("artemis-labs", "gabe@artemis.io", "CREW"),
        ("orion-dynamics", "oskar@orion.space", "DIRECTOR"),
    ]:
        print(f"  {slug:<16} {role:<9} {email}")
    print("\n  ...plus more crew: carol, eve, farah, hana, jo @artemis.io; tomas, mei, rhea, kai @orion.space")
    print("\nTry:  mc login --org artemis-labs --email priya@artemis.io   then   mc match ART-3")
