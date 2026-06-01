"""Human-style Sudoku solver and difficulty rater.

Rather than brute-force backtracking (that's in sudoku.py), this module solves
a puzzle the way a person would: it maintains pencil-mark candidates for every
cell and repeatedly applies logical techniques, from easiest to hardest, until
the puzzle is solved or no technique makes progress.

Difficulty is rated by the HARDEST technique that was required. A puzzle solved
with only singles is easy; one that needs an X-Wing or chain is hard. This
gives a far truer difficulty measure than counting starting clues.

Public API:
    rate(grid) -> (tier_name, hardest_technique, log)
    solve_human(grid) -> (solved_grid_or_None, hardest_level, log)
    grade_to_tier(level) -> tier name
"""

from copy import deepcopy

SIZE = 9
BOX = 3
DIGITS = set(range(1, 10))

# ---- technique difficulty levels -------------------------------------------
# Each technique is tagged with a numeric difficulty. The puzzle's rating is the
# maximum level used across the whole solve. Levels are grouped into tiers.
L_SINGLE = 1          # naked single, hidden single
L_LOCKED = 2          # locked candidates (pointing / claiming)
L_PAIR = 3            # naked/hidden pairs
L_TRIPLE = 4          # naked/hidden triples (and quads)
L_XWING = 5           # X-Wing
L_XYWING = 6          # XY-Wing
L_SWORDFISH = 7       # Swordfish
L_GUESS = 99          # needed trial-and-error (beyond implemented logic)

TIER_BANDS = [
    ("Beginner", 1, 1),       # only singles
    ("Easy", 2, 2),           # up to locked candidates
    ("Intermediate", 3, 4),   # pairs / triples
    ("Expert", 5, 98),        # X-Wing and beyond (true advanced logic)
]


def grade_to_tier(level):
    """Map a max-technique level to a tier name."""
    if level <= 0:
        return "Beginner"
    if level == L_GUESS:
        return "Expert"       # required guessing -> treat as hardest
    for name, lo, hi in TIER_BANDS:
        if lo <= level <= hi:
            return name
    return "Expert"


# ---- unit helpers -----------------------------------------------------------

def _rows():
    return [[(r, c) for c in range(SIZE)] for r in range(SIZE)]


def _cols():
    return [[(r, c) for r in range(SIZE)] for c in range(SIZE)]


def _boxes():
    units = []
    for br in range(0, SIZE, BOX):
        for bc in range(0, SIZE, BOX):
            units.append([(br + i, bc + j) for i in range(BOX) for j in range(BOX)])
    return units


ROWS, COLS, BOXES = _rows(), _cols(), _boxes()
ALL_UNITS = ROWS + COLS + BOXES

# peers[(r,c)] = set of cells sharing a row, column, or box with (r,c)
PEERS = {}
for r in range(SIZE):
    for c in range(SIZE):
        peers = set()
        for u in ALL_UNITS:
            if (r, c) in u:
                peers.update(u)
        peers.discard((r, c))
        PEERS[(r, c)] = peers


class Board:
    """Candidate grid: each cell holds either a solved digit or a set of
    candidate digits."""

    def __init__(self, grid):
        # values[(r,c)] = digit (1-9) or 0; cand[(r,c)] = set of candidates
        self.values = {}
        self.cand = {}
        for r in range(SIZE):
            for c in range(SIZE):
                v = grid[r][c]
                self.values[(r, c)] = v
                self.cand[(r, c)] = set() if v else set(DIGITS)
        # propagate initial clues
        for r in range(SIZE):
            for c in range(SIZE):
                if self.values[(r, c)]:
                    self._eliminate_peers((r, c), self.values[(r, c)])

    def _eliminate_peers(self, cell, digit):
        for p in PEERS[cell]:
            self.cand[p].discard(digit)

    def place(self, cell, digit):
        """Assign a digit to a cell and clear it from peers' candidates."""
        self.values[cell] = digit
        self.cand[cell] = set()
        self._eliminate_peers(cell, digit)

    def solved(self):
        return all(self.values[(r, c)] for r in range(SIZE) for c in range(SIZE))

    def contradiction(self):
        """True if any empty cell has no candidates (dead end)."""
        for r in range(SIZE):
            for c in range(SIZE):
                if not self.values[(r, c)] and not self.cand[(r, c)]:
                    return True
        return False

    def to_grid(self):
        return [[self.values[(r, c)] for c in range(SIZE)] for r in range(SIZE)]


# ---- techniques -------------------------------------------------------------
# Each technique function takes a Board and returns True if it made progress
# (placed a digit or eliminated a candidate). They never guess.

def naked_single(b):
    for r in range(SIZE):
        for c in range(SIZE):
            if not b.values[(r, c)] and len(b.cand[(r, c)]) == 1:
                d = next(iter(b.cand[(r, c)]))
                b.place((r, c), d)
                return True
    return False


def hidden_single(b):
    for unit in ALL_UNITS:
        for d in DIGITS:
            spots = [cell for cell in unit
                     if not b.values[cell] and d in b.cand[cell]]
            if len(spots) == 1:
                b.place(spots[0], d)
                return True
    return False


def locked_candidates(b):
    """Pointing & claiming: if a digit in a box is confined to one row/col, it
    can be removed from the rest of that row/col (and vice versa)."""
    progressed = False
    for box in BOXES:
        for d in DIGITS:
            spots = [cell for cell in box
                     if not b.values[cell] and d in b.cand[cell]]
            if not spots:
                continue
            rows = {r for r, _ in spots}
            cols = {c for _, c in spots}
            if len(rows) == 1:
                r = next(iter(rows))
                for c in range(SIZE):
                    if (r, c) not in box and d in b.cand[(r, c)]:
                        b.cand[(r, c)].discard(d); progressed = True
            if len(cols) == 1:
                c = next(iter(cols))
                for r in range(SIZE):
                    if (r, c) not in box and d in b.cand[(r, c)]:
                        b.cand[(r, c)].discard(d); progressed = True
    # claiming: digit in a row/col confined to one box -> clear rest of box
    for unit in ROWS + COLS:
        for d in DIGITS:
            spots = [cell for cell in unit
                     if not b.values[cell] and d in b.cand[cell]]
            if not spots:
                continue
            box_ids = {(r // BOX, c // BOX) for r, c in spots}
            if len(box_ids) == 1:
                br, bc = next(iter(box_ids))
                for i in range(BOX):
                    for j in range(BOX):
                        cell = (br * BOX + i, bc * BOX + j)
                        if cell not in unit and d in b.cand[cell]:
                            b.cand[cell].discard(d); progressed = True
    return progressed


def naked_subset(b, n):
    """Naked pair (n=2), triple (3), quad (4): n cells in a unit whose combined
    candidates are exactly n digits -> those digits leave the rest of the unit."""
    from itertools import combinations
    progressed = False
    for unit in ALL_UNITS:
        empties = [cell for cell in unit if not b.values[cell]]
        for combo in combinations(empties, n):
            union = set()
            for cell in combo:
                union |= b.cand[cell]
            if len(union) == n:
                for cell in empties:
                    if cell not in combo:
                        before = len(b.cand[cell])
                        b.cand[cell] -= union
                        if len(b.cand[cell]) != before:
                            progressed = True
    return progressed


def hidden_subset(b, n):
    """Hidden pair/triple/quad: n digits confined to exactly n cells in a unit
    -> those cells lose all other candidates."""
    from itertools import combinations
    progressed = False
    for unit in ALL_UNITS:
        empties = [cell for cell in unit if not b.values[cell]]
        digit_spots = {d: [cell for cell in empties if d in b.cand[cell]]
                       for d in DIGITS}
        present = [d for d in DIGITS if digit_spots[d]]
        for combo in combinations(present, n):
            cells = set()
            for d in combo:
                cells |= set(digit_spots[d])
            if len(cells) == n:
                keep = set(combo)
                for cell in cells:
                    if b.cand[cell] - keep:
                        b.cand[cell] &= keep
                        progressed = True
    return progressed


def x_wing(b):
    """X-Wing: a digit forms a rectangle across two rows (or cols) with exactly
    two candidate positions each -> eliminate from the crossing cols (or rows)."""
    from itertools import combinations
    progressed = False
    for d in DIGITS:
        # row-based
        rowspots = {}
        for r in range(SIZE):
            cs = [c for c in range(SIZE)
                  if not b.values[(r, c)] and d in b.cand[(r, c)]]
            if len(cs) == 2:
                rowspots[r] = cs
        for r1, r2 in combinations(rowspots, 2):
            if rowspots[r1] == rowspots[r2]:
                for c in rowspots[r1]:
                    for r in range(SIZE):
                        if r not in (r1, r2) and d in b.cand[(r, c)]:
                            b.cand[(r, c)].discard(d); progressed = True
        # col-based
        colspots = {}
        for c in range(SIZE):
            rs = [r for r in range(SIZE)
                  if not b.values[(r, c)] and d in b.cand[(r, c)]]
            if len(rs) == 2:
                colspots[c] = rs
        for c1, c2 in combinations(colspots, 2):
            if colspots[c1] == colspots[c2]:
                for r in colspots[c1]:
                    for c in range(SIZE):
                        if c not in (c1, c2) and d in b.cand[(r, c)]:
                            b.cand[(r, c)].discard(d); progressed = True
    return progressed


def xy_wing(b):
    """XY-Wing: a pivot cell {X,Y} sees two pincers {X,Z} and {Y,Z}; any cell
    seeing both pincers can't be Z."""
    progressed = False
    bivalue = [cell for cell in b.cand
               if not b.values[cell] and len(b.cand[cell]) == 2]
    bivalue_set = set(bivalue)
    for pivot in bivalue:
        if len(b.cand[pivot]) != 2:
            continue
        x, y = tuple(b.cand[pivot])
        wings = [c for c in bivalue if c != pivot and c in PEERS[pivot]]
        for i in range(len(wings)):
            for j in range(i + 1, len(wings)):
                w1, w2 = wings[i], wings[j]
                s1, s2 = set(b.cand[w1]), set(b.cand[w2])
                shared = s1 & s2
                if len(shared) != 1:
                    continue
                z = next(iter(shared))
                if z in (x, y):
                    continue
                # The two wings must be exactly {x,z} and {y,z} (in either order).
                if (s1 == {x, z} and s2 == {y, z}) or \
                   (s1 == {y, z} and s2 == {x, z}):
                    for cell in PEERS[w1] & PEERS[w2]:
                        if not b.values[cell] and z in b.cand[cell]:
                            b.cand[cell].discard(z)
                            progressed = True
    return progressed


def swordfish(b):
    """Swordfish: 3 rows where a digit appears in 2-3 cols, all within the same
    3 cols -> eliminate that digit from those cols in other rows (and the col
    transpose)."""
    from itertools import combinations
    progressed = False
    for d in DIGITS:
        # row-based
        rowspots = {}
        for r in range(SIZE):
            cs = [c for c in range(SIZE)
                  if not b.values[(r, c)] and d in b.cand[(r, c)]]
            if 2 <= len(cs) <= 3:
                rowspots[r] = set(cs)
        for combo in combinations(rowspots, 3):
            colset = set()
            for r in combo:
                colset |= rowspots[r]
            if len(colset) == 3:
                for c in colset:
                    for r in range(SIZE):
                        if r not in combo and d in b.cand[(r, c)]:
                            b.cand[(r, c)].discard(d); progressed = True
        # col-based
        colspots = {}
        for c in range(SIZE):
            rs = [r for r in range(SIZE)
                  if not b.values[(r, c)] and d in b.cand[(r, c)]]
            if 2 <= len(rs) <= 3:
                colspots[c] = set(rs)
        for combo in combinations(colspots, 3):
            rowset = set()
            for c in combo:
                rowset |= colspots[c]
            if len(rowset) == 3:
                for r in rowset:
                    for c in range(SIZE):
                        if c not in combo and d in b.cand[(r, c)]:
                            b.cand[(r, c)].discard(d); progressed = True
    return progressed


# Ordered easiest -> hardest. Each entry: (level, name, function).
TECHNIQUES = [
    (L_SINGLE, "Naked Single", naked_single),
    (L_SINGLE, "Hidden Single", hidden_single),
    (L_LOCKED, "Locked Candidates", locked_candidates),
    (L_PAIR, "Naked Pair", lambda b: naked_subset(b, 2)),
    (L_PAIR, "Hidden Pair", lambda b: hidden_subset(b, 2)),
    (L_TRIPLE, "Naked Triple", lambda b: naked_subset(b, 3)),
    (L_TRIPLE, "Hidden Triple", lambda b: hidden_subset(b, 3)),
    (L_TRIPLE, "Naked Quad", lambda b: naked_subset(b, 4)),
    (L_TRIPLE, "Hidden Quad", lambda b: hidden_subset(b, 4)),
    (L_XWING, "X-Wing", x_wing),
    (L_XYWING, "XY-Wing", xy_wing),
    (L_SWORDFISH, "Swordfish", swordfish),
]


def solve_human(grid):
    """Solve using human techniques only (no guessing). Returns
    (solved_grid_or_None, max_level_used, log_of_technique_names)."""
    b = Board(grid)
    max_level = 0
    log = []
    while not b.solved():
        if b.contradiction():
            return None, max_level, log
        progressed = False
        # Always try techniques from easiest; only escalate when easier ones stall.
        for level, name, fn in TECHNIQUES:
            if fn(b):
                max_level = max(max_level, level)
                log.append(name)
                progressed = True
                break
        if not progressed:
            # No implemented technique helps -> beyond our logic (needs guessing).
            return None, L_GUESS, log
    return b.to_grid(), max_level, log


def rate(grid):
    """Rate a puzzle's difficulty. Returns (tier_name, max_level, log)."""
    solved, level, log = solve_human(grid)
    if solved is None and level != L_GUESS:
        # contradiction / unsolvable by logic for another reason
        return "Expert", level, log
    return grade_to_tier(level), level, log