"""The matcher: hard filters -> soft scoring -> crew-level optimisation -> explanations.

Pure function of its input; deterministic (positions ordered by slot/index, candidates by crew id).
"""

from mission_control.domain.matching import eligibility, explain, scoring, solver
from mission_control.domain.matching.model import (
    Exclusion,
    MatchInput,
    MatchResult,
    PositionResult,
    RuleResult,
    Suggestion,
)

WHY_NOT_DEFAULT = 5
MAX_ALTERNATIVES = 3


def run(data: MatchInput, *, all_reasons: bool = False) -> MatchResult:
    positions = sorted(data.positions, key=lambda p: (p.slot_ordinal, p.index))
    candidates = sorted(data.candidates, key=lambda c: str(c.crew_id))

    scores: list[list[float | None]] = []
    suggestions: list[list[Suggestion | None]] = []
    exclusions: list[list[Exclusion | None]] = []
    for pos in positions:
        row_s, row_sugg, row_ex = [], [], []
        for cand in candidates:
            barred = data.barred.get(cand.crew_id)
            results = (
                [RuleResult(barred, eligibility.BARRED_DETAIL[barred])]
                if barred
                else eligibility.evaluate(cand, pos, data.window)
            )
            if eligibility.blocking(results):
                row_s.append(None)
                row_sugg.append(None)
                row_ex.append(Exclusion(cand.crew_id, cand.name, eligibility.tier(results), tuple(results)))
            else:
                breakdown = scoring.factors(cand, pos, data.window)
                s = scoring.score(breakdown)
                row_s.append(s)
                row_sugg.append(
                    Suggestion(
                        cand.crew_id,
                        cand.name,
                        s,
                        breakdown,
                        explain.suggestion_reason(cand, pos, data.window),
                    )
                )
                row_ex.append(None)
        scores.append(row_s)
        suggestions.append(row_sugg)
        exclusions.append(row_ex)

    chosen = _fill_low_indices_first(positions, solver.solve(scores), scores)
    chosen_for = {c: p for p, c in enumerate(chosen) if c is not None}

    results = []
    for p, pos in enumerate(positions):
        pick = chosen[p]
        suggestion = suggestions[p][pick] if pick is not None else None
        eligible_others = sorted(
            (suggestions[p][c] for c in range(len(candidates)) if suggestions[p][c] and c != pick),
            key=lambda s: (-s.score, s.name),
        )
        alternatives = tuple(
            _annotate(s, positions[chosen_for[c]].label) if (c := _index(candidates, s)) in chosen_for else s
            for s in eligible_others[:MAX_ALTERNATIVES]
        )
        unfilled: list[Exclusion] = []
        if suggestion is None:
            unfilled = [e for e in exclusions[p] if e is not None]
            # Eligible people taken by another position also explain a gap.
            for c, other in chosen_for.items():
                if suggestions[p][c] is not None:
                    unfilled.append(
                        Exclusion(
                            candidates[c].crew_id,
                            candidates[c].name,
                            2,
                            (
                                RuleResult(
                                    "ASSIGNED_ELSEWHERE",
                                    f"suggested for {positions[other].label} (one position per mission)",
                                ),
                            ),
                        )
                    )
            unfilled.sort(key=lambda e: (e.tier, e.name.lower(), str(e.crew_id)))
        total = len(unfilled)
        shown = tuple(unfilled if all_reasons else unfilled[:WHY_NOT_DEFAULT])
        results.append(PositionResult(pos, suggestion, alternatives, shown, total))
    return MatchResult(data.mission_code, tuple(results))


def _fill_low_indices_first(positions, chosen: list[int | None], scores) -> list[int | None]:
    """Positions within a slot are interchangeable; show "Geologist #1" filled before "#2", best first."""
    by_slot: dict = {}
    for p, pos in enumerate(positions):
        by_slot.setdefault(pos.slot_id, []).append(p)
    result = list(chosen)
    for idxs in by_slot.values():
        picks = sorted((c for c in (chosen[p] for p in idxs) if c is not None), key=lambda c: -scores[idxs[0]][c])
        for slot_pos, p in enumerate(idxs):
            result[p] = picks[slot_pos] if slot_pos < len(picks) else None
    return result


def _index(candidates, suggestion: Suggestion) -> int:
    return next(i for i, c in enumerate(candidates) if c.crew_id == suggestion.crew_id)


def _annotate(s: Suggestion, label: str) -> Suggestion:
    return Suggestion(s.crew_id, s.name, s.score, s.breakdown, f"{s.reason} (suggested for {label})")
