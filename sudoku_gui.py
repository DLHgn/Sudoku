"""Tkinter GUI for the Sudoku generator/solver.

Requires sudoku.py in the same directory. Run: python sudoku_gui.py

Modes:
  - Play:  fill in cells yourself; "Check" flags mistakes, "Solve" reveals all.
  - New:   generates a fresh puzzle (difficulty hook is ready, see DIFFICULTIES).
"""

import tkinter as tk
from tkinter import messagebox
from copy import deepcopy

import sudoku

SIZE = 9
BOX = 3

# Difficulty hook: maps a label to how many cells to remove. The UI doesn't
# expose a selector yet (by request), but adding one later is just wiring a
# dropdown to these values — no logic changes needed. DEFAULT picks the start.
DIFFICULTIES = {
    "Easy": 40,
    "Medium": 50,
    "Hard": 56,
}
DEFAULT_DIFFICULTY = "Medium"

# Colors
GIVEN_FG = "#1a1a1a"       # original clues (locked)
USER_FG = "#1565c0"        # player-entered values
ERROR_BG = "#ffcdd2"       # cells flagged wrong
SOLVED_FG = "#2e7d32"      # auto-solve fills
NORMAL_BG = "#ffffff"
HILITE_BG = "#e3f2fd"      # selected cell


class SudokuGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Sudoku")
        self.root.resizable(False, False)

        self.puzzle = None      # the starting grid (0 = blank); clues are locked
        self.solution = None    # the known full solution
        self.cells = {}         # (r, c) -> Entry widget
        self.selected = None

        self._build_grid()
        self._build_controls()
        self.new_game(DEFAULT_DIFFICULTY)

    # ---- UI construction -------------------------------------------------

    def _build_grid(self):
        board = tk.Frame(self.root, bg="#1a1a1a", padx=2, pady=2)
        board.grid(row=0, column=0, padx=12, pady=12)

        # Nine 3x3 box frames give us the heavy interior borders for free.
        boxes = {}
        for br in range(BOX):
            for bc in range(BOX):
                f = tk.Frame(board, bg="#1a1a1a", padx=1, pady=1)
                f.grid(row=br, column=bc, padx=(0, 2 if bc < 2 else 0),
                       pady=(0, 2 if br < 2 else 0))
                boxes[(br, bc)] = f

        vcmd = (self.root.register(self._validate_entry), "%P")
        for r in range(SIZE):
            for c in range(SIZE):
                box = boxes[(r // BOX, c // BOX)]
                e = tk.Entry(box, width=2, font=("Helvetica", 20, "bold"),
                             justify="center", bd=0, relief="flat",
                             disabledbackground=NORMAL_BG, disabledforeground=GIVEN_FG,
                             validate="key", validatecommand=vcmd)
                e.grid(row=r % BOX, column=c % BOX, padx=1, pady=1, ipady=6)
                e.bind("<FocusIn>", lambda ev, rc=(r, c): self._on_focus(rc))
                e.bind("<KeyRelease>", lambda ev, rc=(r, c): self._on_type(rc))
                self.cells[(r, c)] = e

    def _build_controls(self):
        bar = tk.Frame(self.root)
        bar.grid(row=1, column=0, pady=(0, 12))

        tk.Button(bar, text="New Game", width=10,
                  command=lambda: self.new_game(DEFAULT_DIFFICULTY)
                  ).grid(row=0, column=0, padx=4)
        tk.Button(bar, text="Check", width=10, command=self.check
                  ).grid(row=0, column=1, padx=4)
        tk.Button(bar, text="Solve", width=10, command=self.solve
                  ).grid(row=0, column=2, padx=4)

        self.status = tk.Label(self.root, text="", font=("Helvetica", 11))
        self.status.grid(row=2, column=0, pady=(0, 10))

    # ---- input validation ------------------------------------------------

    @staticmethod
    def _validate_entry(proposed):
        # Allow empty or a single digit 1-9; reject everything else (incl. 0).
        return proposed == "" or (len(proposed) == 1 and proposed in "123456789")

    # ---- game lifecycle --------------------------------------------------

    def new_game(self, difficulty):
        clues_removed = DIFFICULTIES.get(difficulty, 50)
        self.status.config(text="Generating...")
        self.root.update_idletasks()

        self.puzzle, self.solution = sudoku.make_puzzle(clues_removed=clues_removed)
        self._render_puzzle()
        self.status.config(text=f"New game ({difficulty}). Good luck!")

    def _render_puzzle(self):
        for (r, c), e in self.cells.items():
            e.config(state="normal")
            e.delete(0, tk.END)
            e.config(bg=NORMAL_BG, fg=USER_FG)
            val = self.puzzle[r][c]
            if val != 0:
                e.insert(0, str(val))
                e.config(state="disabled")   # lock the given clues

    # ---- interaction -----------------------------------------------------

    def _on_focus(self, rc):
        if self.selected and self.selected in self.cells:
            prev = self.cells[self.selected]
            if prev["state"] != "disabled":
                prev.config(bg=NORMAL_BG)
        self.selected = rc
        cell = self.cells[rc]
        if cell["state"] != "disabled":
            cell.config(bg=HILITE_BG)

    def _on_type(self, rc):
        # Clear any error highlight as soon as the player edits the cell.
        cell = self.cells[rc]
        if cell["state"] != "disabled":
            cell.config(bg=HILITE_BG, fg=USER_FG)
        if self._is_complete() and self._is_correct():
            self.status.config(text="Solved! Well done.")
            messagebox.showinfo("Sudoku", "You solved it!")

    # ---- actions ---------------------------------------------------------

    def _current_grid(self):
        grid = [[0] * SIZE for _ in range(SIZE)]
        for (r, c), e in self.cells.items():
            v = e.get()
            grid[r][c] = int(v) if v.isdigit() else 0
        return grid

    def _is_complete(self):
        return all(e.get().isdigit() for e in self.cells.values())

    def _is_correct(self):
        return self._current_grid() == self.solution

    def check(self):
        wrong = 0
        for (r, c), e in self.cells.items():
            if e["state"] == "disabled":
                continue
            v = e.get()
            if v.isdigit() and int(v) != self.solution[r][c]:
                e.config(bg=ERROR_BG)
                wrong += 1
        if wrong == 0:
            if self._is_complete():
                self.status.config(text="All correct — solved!")
            else:
                self.status.config(text="No mistakes so far. Keep going.")
        else:
            self.status.config(text=f"{wrong} incorrect cell(s) highlighted.")

    def solve(self):
        for (r, c), e in self.cells.items():
            if e["state"] == "disabled":
                continue
            e.delete(0, tk.END)
            e.insert(0, str(self.solution[r][c]))
            e.config(bg=NORMAL_BG, fg=SOLVED_FG)
        self.status.config(text="Solution revealed.")


def main():
    root = tk.Tk()
    SudokuGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()