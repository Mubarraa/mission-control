"""Matcher unit tests: pure domain, no database (specs/crew-matching)."""

import uuid
from datetime import UTC, date, datetime, timedelta

from mission_control.domain.matching import eligibility, engine, scoring, solver
from mission_control.domain.matching.model import (
    Candidate,
    Commitment,
    MatchInput,
    MissionWindow,
    Position,
    Requirement,
    SkillRecord,
    UnavailableWindow,
)

START = datetime(2027, 3, 1, tzinfo=UTC)
END = datetime(2027, 3, 21, tzinfo=UTC)
WINDOW = MissionWindow(START, END, buffer_days=14)

PILOTING, GEOLOGY, EVA, MEDICINE = (uuid.uuid4() for _ in range(4))
NAMES = {PILOTING: "Piloting", GEOLOGY: "Geology", EVA: "EVA", MEDICINE: "Medicine"}


def req(skill, level, cert=False):
    return Requirement(skill, NAMES[skill], level, cert)


def pos(role, *reqs, ordinal=1, index=1, headcount=1):
    return Position(uuid.uuid5(uuid.NAMESPACE_DNS, role), role, ordinal, index, headcount, tuple(reqs))


def crew(name, verified=None, claimed=None, certs=None, **kw):
    skills = {}
    for skill, level in (verified or {}).items():
        skills[skill] = SkillRecord(level, level, True, (certs or {}).get(skill))
    for skill, level in (claimed or {}).items():
        prev = skills.get(skill)
        skills[skill] = SkillRecord(prev.verified_level if prev else None, level, False, None)
    cid = uuid.uuid5(uuid.NAMESPACE_URL, name)
    return Candidate(cid, name, skills=skills, **kw)


def rules(c, p, window=WINDOW):
    return {r.rule for r in eligibility.evaluate(c, p, window)}


def match(positions, candidates, **kw):
    return engine.run(MatchInput("ART-12", WINDOW, tuple(positions), tuple(candidates), kw.pop("barred", {})), **kw)


# ------------------------------------------------------------------ eligibility (5.1)


def test_unverified_claim_excluded_and_flagged():
    bob = crew("Bob", claimed={GEOLOGY: 4})
    results = eligibility.evaluate(bob, pos("Geologist", req(GEOLOGY, 3)), WINDOW)
    assert {r.rule for r in results} == {"SKILL_MISSING", "UNVERIFIED_WOULD_QUALIFY"}
    assert eligibility.tier(results) == 0


def test_certification_expiring_mid_mission():
    carol = crew("Carol", verified={EVA: 4}, certs={EVA: date(2027, 3, 10)})
    assert "CERT_EXPIRED" in rules(carol, pos("EVA Lead", req(EVA, 3, cert=True)))
    valid = crew("Val", verified={EVA: 4}, certs={EVA: date(2027, 3, 21)})
    assert rules(valid, pos("EVA Lead", req(EVA, 3, cert=True))) == set()


def test_missing_certification():
    assert "CERT_MISSING" in rules(crew("NoCert", verified={EVA: 4}), pos("EVA Lead", req(EVA, 3, cert=True)))


def test_recovery_buffer_respected():
    dana = crew(
        "Dana",
        verified={GEOLOGY: 4},
        commitments=(Commitment("ART-9", START - timedelta(days=30), START + timedelta(days=4)),),
    )
    results = eligibility.evaluate(dana, pos("Geologist", req(GEOLOGY, 3)), WINDOW)
    assert any(r.rule == "COMMITTED" and "ART-9 until 2027-03-05" in r.detail for r in results)


def test_new_mission_blocked_period_includes_its_own_buffer():
    starts_during_buffer = crew(
        "Late",
        verified={GEOLOGY: 4},
        commitments=(Commitment("ART-20", END + timedelta(days=5), END + timedelta(days=9)),),
    )
    assert "COMMITTED" in rules(starts_during_buffer, pos("Geologist", req(GEOLOGY, 3)))


def test_pending_offers_do_not_exclude():
    eve = crew("Eve", verified={GEOLOGY: 4}, pending_offers=(Commitment("ART-15", START, END),))
    assert rules(eve, pos("Geologist", req(GEOLOGY, 3))) == set()


def test_declined_crew_barred():
    eve = crew("Eve", verified={GEOLOGY: 5})
    result = match([pos("Geologist", req(GEOLOGY, 3))], [eve], barred={eve.crew_id: "DECLINED"})
    assert result.positions[0].suggestion is None
    assert result.positions[0].unfilled_reasons[0].rules[0].detail == "declined this mission"


def test_unavailability_uses_public_label_only():
    medic = crew(
        "Mo",
        verified={GEOLOGY: 4},
        unavailability=(UnavailableWindow(START, START + timedelta(days=3), "unavailable"),),
    )
    results = eligibility.evaluate(medic, pos("Geologist", req(GEOLOGY, 3)), WINDOW)
    assert [r.detail for r in results] == ["unavailable 2027-03-01 to 2027-03-04"]


def test_why_not_closest_first():
    slot = pos("Geologist", req(GEOLOGY, 3))
    frank = crew("Frank")
    dana = crew("Dana", verified={GEOLOGY: 2})
    bob = crew("Bob", claimed={GEOLOGY: 4})
    busy = crew("Busy", verified={GEOLOGY: 5}, commitments=(Commitment("ART-9", START, END),))
    result = match([slot], [frank, dana, bob, busy])
    assert [e.name for e in result.positions[0].unfilled_reasons] == ["Bob", "Dana", "Busy", "Frank"]
    assert [e.tier for e in result.positions[0].unfilled_reasons] == [0, 1, 2, 3]


def test_why_not_truncated_to_five_with_total():
    many = [crew(f"Crew {i:02d}") for i in range(40)]
    result = match([pos("Geologist", req(GEOLOGY, 3))], many)
    assert len(result.positions[0].unfilled_reasons) == 5 and result.positions[0].excluded_total == 40
    assert len(match([pos("Geologist", req(GEOLOGY, 3))], many, all_reasons=True).positions[0].unfilled_reasons) == 40


# ------------------------------------------------------------------ scoring (5.2)


def _score(c, p):
    return scoring.score(scoring.factors(c, p, WINDOW))


def test_workload_balance():
    p = pos("Geologist", req(GEOLOGY, 3))
    rested = crew("Rested", verified={GEOLOGY: 4}, workload_days=0)
    busy = crew("Busy", verified={GEOLOGY: 4}, workload_days=60)
    assert _score(rested, p) > _score(busy, p)


def test_rightsizing_prefers_level_two_medic_for_level_two_slot():
    p = pos("Medic", req(MEDICINE, 2))
    assert _score(crew("Junior", verified={MEDICINE: 2}), p) > _score(crew("Expert", verified={MEDICINE: 5}), p)


def test_pending_offer_penalty():
    p = pos("Geologist", req(GEOLOGY, 3))
    free = crew("Free", verified={GEOLOGY: 4})
    offered = crew("Offered", verified={GEOLOGY: 4}, pending_offers=(Commitment("ART-15", START, END),))
    assert scoring.factors(offered, p, WINDOW)["penalty"] == 0.05
    assert _score(free, p) > _score(offered, p)


def test_scores_bounded():
    p = pos("Geologist", req(GEOLOGY, 1))
    best = crew("Best", verified={GEOLOGY: 2}, experience={GEOLOGY: 10})
    worst = crew(
        "Worst",
        verified={GEOLOGY: 1},
        workload_days=500,
        pending_offers=(Commitment("A", START, END), Commitment("B", START, END)),
    )
    assert 0 <= _score(worst, p) <= _score(best, p) <= 1


# ------------------------------------------------------------------ solver (5.3)


def test_greedy_trap_avoided():
    commander = pos("Commander", req(PILOTING, 4), ordinal=1)
    geologist = pos("Geologist", req(GEOLOGY, 3), ordinal=2)
    alice = crew("Alice", verified={PILOTING: 5, GEOLOGY: 5})
    bob = crew("Bob", verified={PILOTING: 2, GEOLOGY: 4})
    result = match([geologist, commander], [alice, bob])
    picks = {r.position.role_name: r.suggestion.name for r in result.positions}
    assert picks == {"Commander": "Alice", "Geologist": "Bob"}


def test_no_eligible_crew_leaves_all_unfilled_without_error():
    result = match([pos("Commander", req(PILOTING, 4)), pos("Geologist", req(GEOLOGY, 3), ordinal=2)], [crew("Nobody")])
    assert result.filled == 0 and result.unfilled == 2


def test_no_under_qualified_fallback():
    result = match(
        [pos("Geologist", req(GEOLOGY, 3))],
        [crew("Dana", verified={GEOLOGY: 2}), crew("Dee", verified={GEOLOGY: 2})],
    )
    assert result.positions[0].suggestion is None


def test_partial_fill_and_assigned_elsewhere_reason():
    commander = pos("Commander", req(PILOTING, 3), ordinal=1)
    geologist = pos("Geologist", req(GEOLOGY, 3), ordinal=2)
    alice = crew("Alice", verified={PILOTING: 5, GEOLOGY: 5})
    result = match([commander, geologist], [alice])
    assert result.filled == 1
    gap = next(r for r in result.positions if r.suggestion is None)
    assert gap.unfilled_reasons[0].rules[0].rule == "ASSIGNED_ELSEWHERE"


def test_headcount_two_fills_two_distinct_people():
    positions = [pos("Geologist", req(GEOLOGY, 3), index=i, headcount=2) for i in (1, 2)]
    result = match(positions, [crew("A", verified={GEOLOGY: 4}), crew("B", verified={GEOLOGY: 4})])
    assert {r.suggestion.name for r in result.positions} == {"A", "B"}
    assert [r.position.label for r in result.positions] == ["Geologist #1", "Geologist #2"]


def test_deterministic_with_ties():
    positions = [pos("Geologist", req(GEOLOGY, 3), index=i, headcount=2) for i in (1, 2)]
    twins = [crew(f"Twin {i}", verified={GEOLOGY: 4}) for i in range(6)]
    first = [r.suggestion.crew_id for r in match(positions, twins).positions]
    for _ in range(5):
        assert [r.suggestion.crew_id for r in match(positions, list(reversed(twins))).positions] == first


def test_alternatives_ranked_and_explained():
    p = pos("Geologist", req(GEOLOGY, 3))
    team = [crew(n, verified={GEOLOGY: lvl}) for n, lvl in [("A", 4), ("B", 3), ("C", 5), ("D", 3), ("E", 4)]]
    result = match([p], team).positions[0]
    assert len(result.alternatives) == 3
    assert [a.score for a in result.alternatives] == sorted((a.score for a in result.alternatives), reverse=True)
    assert "geology" in result.suggestion.reason and "needs 3+" in result.suggestion.reason


def test_solver_handles_empty_inputs():
    assert solver.solve([]) == []
    assert solver.solve([[None, None]]) == [None]
