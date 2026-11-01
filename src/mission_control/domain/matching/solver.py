"""Crew-level optimisation (design.md section 7.4).

Rectangular min-cost assignment over positions x (candidates + one "unfilled" dummy per position):
  cost = -(M + score) for eligible pairs, INFEASIBLE otherwise; dummy column p costs 0 for position p only.
With M = |positions| + 1, filling one more position always outweighs any total-score gain, so the result
fills as many positions as possible and, among those, maximises total score. Never greedy.
"""

from scipy.optimize import linear_sum_assignment

INFEASIBLE = 1e9  # finite on purpose: scipy rejects infeasible matrices containing inf


def solve(scores: list[list[float | None]]) -> list[int | None]:
    """scores[p][c] is the score of candidate c for position p, or None if ineligible.
    Returns, for each position, the chosen candidate index or None (unfilled)."""
    n_pos = len(scores)
    if n_pos == 0:
        return []
    n_cand = len(scores[0])
    big_m = n_pos + 1
    cost = [[INFEASIBLE] * (n_cand + n_pos) for _ in range(n_pos)]
    for p in range(n_pos):
        for c in range(n_cand):
            if scores[p][c] is not None:
                cost[p][c] = -(big_m + scores[p][c])
        cost[p][n_cand + p] = 0.0
    rows, cols = linear_sum_assignment(cost)
    chosen: list[int | None] = [None] * n_pos
    for p, c in zip(rows, cols, strict=True):
        if c < n_cand and scores[p][c] is not None:
            chosen[p] = int(c)
    return chosen
