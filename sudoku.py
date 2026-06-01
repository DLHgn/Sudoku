"""A Sudoku generator and solver.

Generation: fill a grid with a backtracking solver seeded with randomness,
then remove cells symmetrically while verifying the puzzle stays uniquely
solvable. Solving: constraint-propagation-free backtracking with a
most-constrained-cell heuristic for speed.
"""

import random
from copy import deepcopy

SIZE = 9
BOX = 3
DIGITS = range(1, 10)


def _candidates(grid, row, col):
    """Return the set of digits that can legally go in (row, col)."""
    used = set(grid[row])                      # row
    used |= {grid[r][col] for r in range(SIZE)}  # column
    br, bc = (row // BOX) * BOX, (col // BOX) * BOX
    used |= {grid[br + i][bc + j] for i in range(BOX) for j in range(BOX)}  # box
    return [d for d in DIGITS if d not in used]


def _find_best_cell(grid):
    """Find the empty cell with the fewest candidates (fail-fast heuristic)."""
    best, best_cands = None, None
    for r in range(SIZE):
        for c in range(SIZE):
            if grid[r][c] == 0:
                cands = _candidates(grid, r, c)
                if best_cands is None or len(cands) < len(best_cands):
                    best, best_cands = (r, c), cands
                    if len(cands) <= 1:        # can't do better
                        return best, best_cands
    return best, best_cands


def solve(grid, randomize=False, count_limit=None, _count=None):
    """Solve in place via backtracking.

    randomize    : shuffle candidate order (used for generation).
    count_limit  : if set, count solutions up to this limit instead of
                   stopping at the first; returns the number found.
    Returns True/False when counting is off, else the solution count.
    """
    if count_limit is not None:
        _count = _count if _count is not None else [0]
        cell, cands = _find_best_cell(grid)
        if cell is None:                       # full grid = one solution
            _count[0] += 1
            return _count[0]
        r, c = cell
        for d in cands:
            grid[r][c] = d
            if solve(grid, randomize, count_limit, _count) >= count_limit:
                grid[r][c] = 0
                return _count[0]
            grid[r][c] = 0
        return _count[0]

    cell, cands = _find_best_cell(grid)
    if cell is None:
        return True                            # solved
    r, c = cell
    if randomize:
        random.shuffle(cands)
    for d in cands:
        grid[r][c] = d
        if solve(grid, randomize):
            return True
        grid[r][c] = 0
    return False                               # dead end, backtrack


def count_solutions(grid, limit=2):
    """Count solutions up to `limit` (default 2 = 'is it unique?')."""
    return solve(deepcopy(grid), count_limit=limit)


def generate_full_grid():
    """Produce a complete, valid, randomized solution grid."""
    grid = [[0] * SIZE for _ in range(SIZE)]
    solve(grid, randomize=True)
    return grid


def make_puzzle(clues_removed=50):
    """Generate a puzzle with a unique solution.

    clues_removed : how many cells to attempt to blank out (symmetrically).
    Returns (puzzle, solution).
    """
    solution = generate_full_grid()
    puzzle = deepcopy(solution)

    # Visit cell positions in random order; remove in mirrored pairs.
    cells = [(r, c) for r in range(SIZE) for c in range(SIZE)]
    random.shuffle(cells)

    removed = 0
    for r, c in cells:
        if removed >= clues_removed:
            break
        if puzzle[r][c] == 0:
            continue
        mr, mc = SIZE - 1 - r, SIZE - 1 - c
        backup = [(r, c, puzzle[r][c]), (mr, mc, puzzle[mr][mc])]
        puzzle[r][c] = 0
        puzzle[mr][mc] = 0
        # Keep the removal only if the puzzle is still uniquely solvable.
        if count_solutions(puzzle) == 1:
            removed += sum(1 for _, _, v in backup if v != 0)
        else:
            for br, bc, v in backup:
                puzzle[br][bc] = v
    return puzzle, solution


# Removal targets to bias generation toward a tier. Harder tiers strip more
# clues, which tends to demand harder techniques; the rater then confirms.
_TIER_REMOVAL = {
    "Beginner": 40,
    "Easy": 46,
    "Intermediate": 52,
    "Expert": 58,
}


def make_rated_puzzle(tier, max_attempts=120, rater=None, cache=None):
    """Generate a uniquely-solvable puzzle whose human-solving difficulty
    matches `tier`. Returns (puzzle, solution, actual_tier, source) where source
    is "fresh" (generated this call), "cache" (served from the cache), or
    "fallback" (closest tier generated when nothing matched).

    If a `cache` (puzzle_cache.PuzzleCache) is given:
      - every rated candidate is banked under its actual tier (free variety,
        especially for the rare middle tiers), and
      - when live generation can't hit the target within max_attempts, a cached
        puzzle of the target tier is served instead of a wrong-tier fallback.

    rater: callable(grid) -> (tier_name, level, log). Injected to avoid an
    import cycle; callers pass solver.rate.
    """
    if rater is None:
        import solver
        rater = solver.rate

    target_removed = _TIER_REMOVAL.get(tier, 50)
    order = ["Beginner", "Easy", "Intermediate", "Expert"]
    target_idx = order.index(tier) if tier in order else 1
    best = None  # (distance, puzzle, solution, actual_tier)

    for _ in range(max_attempts):
        puzzle, solution = make_puzzle(clues_removed=target_removed)
        actual, _level, _log = rater(puzzle)
        if cache is not None:
            cache.add(actual, puzzle, solution)   # bank as we go (your idea)
        if actual == tier:
            return puzzle, solution, actual, "fresh"
        dist = abs(order.index(actual) - target_idx) if actual in order else 9
        if best is None or dist < best[0]:
            best = (dist, puzzle, solution, actual)

    # Live generation missed the target. Prefer a cached puzzle of the right
    # tier over serving the wrong difficulty.
    if cache is not None:
        cached = cache.take(tier)
        if cached is not None:
            return cached[0], cached[1], tier, "cache"

    # Last resort: if we somehow have no candidate at all (e.g. zero attempts
    # and an empty cache), generate one plain puzzle so the caller always gets
    # a playable board.
    if best is None:
        puzzle, solution = make_puzzle(clues_removed=target_removed)
        actual, _level, _log = rater(puzzle)
        if cache is not None:
            cache.add(actual, puzzle, solution)
        return puzzle, solution, actual, "fallback"

    return best[1], best[2], best[3], "fallback"


def format_grid(grid):
    """Pretty-print a grid with box separators; 0 shown as '.'."""
    lines = []
    for r in range(SIZE):
        if r % BOX == 0 and r != 0:
            lines.append("------+-------+------")
        cells = []
        for c in range(SIZE):
            if c % BOX == 0 and c != 0:
                cells.append("|")
            cells.append(str(grid[r][c]) if grid[r][c] else ".")
        lines.append(" ".join(cells))
    return "\n".join(lines)


if __name__ == "__main__":
    puzzle, solution = make_puzzle(clues_removed=50)
    print("Puzzle:\n")
    print(format_grid(puzzle))

    solved = deepcopy(puzzle)
    solve(solved)
    print("\nSolved:\n")
    print(format_grid(solved))

    assert solved == solution
    print("\nVerified: solver result matches the generated solution.")