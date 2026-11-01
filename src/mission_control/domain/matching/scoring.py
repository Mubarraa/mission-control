"""Soft scoring for an eligible (crew, position) pair (design.md section 7.3).

Qualification dominates, but cannot completely override fairness of workload.
"""

from mission_control.domain.matching.model import Candidate, MissionWindow, Position

WEIGHTS = {"fit": 0.40, "rightsizing": 0.15, "workload": 0.25, "experience": 0.20}
PENDING_PENALTY = 0.10
EXACT_FIT = 0.85  # meets the minimum exactly; one or more levels above scores 1.0
WORKLOAD_HORIZON_DAYS = 90
EXPERIENCE_SATURATION = 5


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def factors(candidate: Candidate, position: Position, window: MissionWindow) -> dict[str, float]:
    margins = []
    for req in position.requirements:
        level = candidate.skills[req.skill_id].verified_level or 0
        margins.append((req, level - req.min_level))
    # Fit saturates one level above the minimum: extra headroom beyond +1 earns nothing here,
    # and right-sizing then penalises it, so experts stay free for missions that need them.
    fit = _mean([EXACT_FIT if margin == 0 else 1.0 for _, margin in margins])
    rightsizing = 1 - _mean([max(0, margin - 1) / 3 for _, margin in margins])
    workload = 1 - min(1.0, candidate.workload_days / WORKLOAD_HORIZON_DAYS)
    experience = min(
        1.0,
        _mean([candidate.experience.get(r.skill_id, 0) for r in position.requirements]) / EXPERIENCE_SATURATION,
    )
    competing = sum(1 for o in candidate.pending_offers if o.start < window.blocked_end and window.start < o.end)
    penalty = PENDING_PENALTY * min(1.0, competing / 2)
    return {
        "fit": round(fit, 3),
        "rightsizing": round(rightsizing, 3),
        "workload": round(workload, 3),
        "experience": round(experience, 3),
        "penalty": round(penalty, 3),
    }


def score(breakdown: dict[str, float]) -> float:
    raw = sum(WEIGHTS[k] * breakdown[k] for k in WEIGHTS) - breakdown["penalty"]
    return round(min(1.0, max(0.0, raw)), 3)
