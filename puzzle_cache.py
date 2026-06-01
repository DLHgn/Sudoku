"""A small on-disk cache of rated puzzles, keyed by difficulty tier.

Purpose: live generation reliably produces only some tiers (Beginner/Expert);
the middle tiers are rare. Rather than discard the puzzles that generation makes
along the way, we bank them under whatever tier they actually rate as. When live
generation can't quickly produce a requested tier, we serve a cached one.

Design:
  - Per tier we keep at most MAX_PER_TIER entries, newest first.
  - Adding to a full tier evicts the OLDEST entry (a rolling window, so the
    cache keeps refreshing with recent puzzles rather than going stale).
  - Each entry tracks whether it has been played; serving prefers unplayed
    entries so the player doesn't immediately repeat a board.
  - Stored compactly: puzzle/solution as 81-char strings (~200 bytes each).

This module is pure data + file I/O; it does no generation or rating itself.
"""

import json
import os

SIZE = 9
MAX_PER_TIER = 20      # rolling window size per difficulty tier
TIERS = ["Beginner", "Easy", "Intermediate", "Expert"]

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "sudoku_cache.json")


def _flat(grid):
    return "".join(str(grid[r][c]) for r in range(SIZE) for c in range(SIZE))


def _unflat(s):
    return [[int(s[r * SIZE + c]) for c in range(SIZE)] for r in range(SIZE)]


def _key(puzzle):
    """A puzzle's identity for dedup is its clue layout."""
    return _flat(puzzle)


class PuzzleCache:
    def __init__(self, path=CACHE_FILE):
        self.path = path
        # store[tier] = list of {puzzle, solution, played} dicts, newest first
        self.store = {t: [] for t in TIERS}
        self._load()

    # ---- persistence ----------------------------------------------------

    def _load(self):
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return
        for tier in TIERS:
            entries = data.get(tier)
            if not isinstance(entries, list):
                continue
            clean = []
            for e in entries:
                # Validate each entry defensively; skip anything malformed.
                if (isinstance(e, dict)
                        and isinstance(e.get("puzzle"), str) and len(e["puzzle"]) == 81
                        and isinstance(e.get("solution"), str) and len(e["solution"]) == 81
                        and e["puzzle"].isdigit() and e["solution"].isdigit()):
                    clean.append({"puzzle": e["puzzle"],
                                  "solution": e["solution"],
                                  "played": bool(e.get("played", False))})
            self.store[tier] = clean[:MAX_PER_TIER]

    def save(self):
        try:
            with open(self.path, "w") as f:
                json.dump(self.store, f)
            return True
        except OSError:
            return False

    # ---- operations -----------------------------------------------------

    def add(self, tier, puzzle, solution):
        """Bank a rated puzzle. No-op for unknown tiers or duplicates. Inserts
        newest-first and evicts the oldest when the tier is full."""
        if tier not in self.store:
            return False
        pk = _key(puzzle)
        if any(e["puzzle"] == pk for e in self.store[tier]):
            return False                      # already cached
        self.store[tier].insert(0, {"puzzle": pk,
                                    "solution": _flat(solution),
                                    "played": False})
        if len(self.store[tier]) > MAX_PER_TIER:
            self.store[tier] = self.store[tier][:MAX_PER_TIER]  # drop oldest
        return True

    def take(self, tier):
        """Return (puzzle, solution) for a cached puzzle of `tier`, preferring
        an unplayed one; marks it played. Returns None if the tier is empty."""
        entries = self.store.get(tier, [])
        if not entries:
            return None
        # Prefer the newest unplayed entry; else fall back to the newest overall.
        chosen = next((e for e in entries if not e["played"]), entries[0])
        chosen["played"] = True
        return _unflat(chosen["puzzle"]), _unflat(chosen["solution"])

    def count(self, tier):
        return len(self.store.get(tier, []))

    def counts(self):
        return {t: len(self.store[t]) for t in TIERS}