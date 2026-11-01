"""Human-readable reasons for suggestions."""

from mission_control.domain.matching.model import Candidate, MissionWindow, Position


def suggestion_reason(candidate: Candidate, position: Position, window: MissionWindow) -> str:
    parts = []
    for req in position.requirements:
        rec = candidate.skills[req.skill_id]
        part = f"{req.skill_name.lower()} {rec.verified_level} (needs {req.min_level}+)"
        if req.cert_required and rec.cert_expires_on:
            part += f", cert to {rec.cert_expires_on:%Y-%m}"
        parts.append(part)
    days = round(candidate.workload_days)
    parts.append("no recent load" if days == 0 else f"{days} days load in prior 90")
    exp = max((candidate.experience.get(r.skill_id, 0) for r in position.requirements), default=0)
    if exp:
        parts.append(f"{exp} prior mission{'s' if exp != 1 else ''}")
    competing = [
        o.mission_code for o in candidate.pending_offers if o.start < window.blocked_end and window.start < o.end
    ]
    if competing:
        parts.append(f"competing offer on {', '.join(sorted(competing))}")
    return ", ".join(parts)
