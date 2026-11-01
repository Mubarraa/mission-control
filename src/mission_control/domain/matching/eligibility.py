"""Hard eligibility rules (design.md section 7.2) and closeness tiers for why-not ordering."""

from datetime import datetime

from mission_control.domain.matching.model import Candidate, MissionWindow, Position, RuleResult

UNVERIFIED_FLAG = "UNVERIFIED_WOULD_QUALIFY"
AVAILABILITY_RULES = {"COMMITTED", "UNAVAILABLE", "ASSIGNED_ELSEWHERE"}
SKILL_RULES = {"SKILL_MISSING", "SKILL_BELOW_MIN"}

BARRED_DETAIL = {
    "ALREADY_ON_MISSION": "already on this mission",
    "DECLINED": "declined this mission",
    "WITHDRAWN": "withdrew from this mission",
}


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end  # half-open intervals


def evaluate(candidate: Candidate, position: Position, window: MissionWindow) -> list[RuleResult]:
    """Every rule the candidate fails for this position (all failures, not just the first).

    Advisory flags (blocking=False) are included so explanations can point at fixable gaps.
    """
    results: list[RuleResult] = []
    if not candidate.active:
        results.append(RuleResult("INACTIVE", "profile inactive"))

    for req in position.requirements:
        rec = candidate.skills.get(req.skill_id)
        skill = req.skill_name.lower()
        verified = rec.verified_level if rec else None
        if verified is None:
            results.append(RuleResult("SKILL_MISSING", f"no verified {skill}"))
        elif verified < req.min_level:
            results.append(RuleResult("SKILL_BELOW_MIN", f"{skill} {verified} < {req.min_level} required"))
        if (
            rec
            and (verified is None or verified < req.min_level)
            and not rec.verified
            and rec.claimed_level >= req.min_level
        ):
            results.append(
                RuleResult(
                    UNVERIFIED_FLAG,
                    f"claims {skill} {rec.claimed_level} (unverified); verifying would qualify",
                    False,
                )
            )
        if req.cert_required:
            if rec is None or rec.cert_expires_on is None:
                results.append(RuleResult("CERT_MISSING", f"no {skill} certification on file"))
            elif rec.cert_expires_on < window.end.date():
                results.append(
                    RuleResult(
                        "CERT_EXPIRED",
                        f"{skill} cert expires {rec.cert_expires_on:%Y-%m-%d}, "
                        f"before mission end {window.end:%Y-%m-%d}",
                    )
                )

    for c in candidate.commitments:
        if _overlaps(c.start, c.end, window.start, window.blocked_end):
            results.append(RuleResult("COMMITTED", f"on {c.mission_code} until {c.end:%Y-%m-%d} incl. recovery"))
    for u in candidate.unavailability:
        if _overlaps(u.start, u.end, window.start, window.blocked_end):
            results.append(RuleResult("UNAVAILABLE", f"{u.public_label} {u.start:%Y-%m-%d} to {u.end:%Y-%m-%d}"))
    return results


def blocking(results: list[RuleResult]) -> list[RuleResult]:
    return [r for r in results if r.blocking]


def tier(results: list[RuleResult]) -> int:
    """0: only an unverified claim stands in the way; 1: one level short on one requirement;
    2: qualified but blocked by availability/commitments; 3: everything else."""
    hard = blocking(results)
    flags = [r for r in results if not r.blocking]
    rules = {r.rule for r in hard}
    if hard and rules <= SKILL_RULES and len(flags) >= len(hard):
        return 0
    if len(hard) == 1 and hard[0].rule == "SKILL_BELOW_MIN" and _gap(hard[0].detail) == 1:
        return 1
    if hard and rules <= AVAILABILITY_RULES:
        return 2
    return 3


def _gap(detail: str) -> int:
    # detail format: "<skill> <have> < <need> required"
    try:
        left, right = detail.split(" < ")
        return int(right.split()[0]) - int(left.split()[-1])
    except (ValueError, IndexError):
        return 99
