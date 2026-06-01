"""Tkinter GUI for the Sudoku generator/solver.

Requires sudoku.py in the same directory. Run: python sudoku_gui.py

Modes:
  - Play:  fill in cells yourself; "Check" flags mistakes, "Solve" reveals all.
  - New:   generates a fresh puzzle (difficulty hook is ready, see DIFFICULTIES).

Settings (background / highlight / error colors) are editable via the Settings
button and persist to a JSON file next to this script.
"""

import json
import os
import tkinter as tk
from tkinter import messagebox, colorchooser

import sudoku

SIZE = 9
BOX = 3

# Difficulty hook: maps a label to how many cells to remove. No selector is
# exposed yet (by request); wiring one later is just binding a control to these
# values and passing the choice to new_game(). DEFAULT picks the starting level.
DIFFICULTIES = {
    "Easy": 40,
    "Medium": 50,
    "Hard": 56,
}
DEFAULT_DIFFICULTY = "Medium"

# Fixed colors (not user-configurable, by request)
GIVEN_FG = "#1a1a1a"       # original clues (locked)
USER_FG = "#1565c0"        # player-entered values
SOLVED_FG = "#2e7d32"      # auto-solve fills
NORMAL_BG = "#ffffff"      # blank/filled cell background

# User-configurable settings and their defaults. Anything in here is what gets
# saved to / loaded from the settings file, so adding a new option later is a
# one-line addition plus a row in the settings dialog.
DEFAULT_SETTINGS = {
    "window_bg": "#f0f0f0",    # window background (behind board + buttons)
    "highlight_bg": "#e3f2fd",  # selected cell
    "error_bg": "#ffcdd2",     # cells flagged wrong by Check
}

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "sudoku_settings.json")


def load_settings():
    """Load settings from disk, falling back to defaults for any missing keys."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r") as f:
            saved = json.load(f)
        # Only accept known keys with string values; ignore anything unexpected.
        for k in DEFAULT_SETTINGS:
            if isinstance(saved.get(k), str):
                settings[k] = saved[k]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass  # first run or unreadable file -> defaults
    return settings


def save_settings(settings):
    """Persist settings to disk. Failure is non-fatal (just reported)."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        return True
    except OSError:
        return False


class SudokuGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Sudoku")
        self.root.resizable(False, False)

        self.settings = load_settings()

        self.puzzle = None      # starting grid (0 = blank); clues are locked
        self.solution = None    # the known full solution
        self.cells = {}         # (r, c) -> Entry widget
        self.selected = None

        self._build_grid()
        self._build_controls()
        self._apply_settings()
        self.new_game(DEFAULT_DIFFICULTY)

    # ---- UI construction -------------------------------------------------

    def _build_grid(self):
        self.board = tk.Frame(self.root, bg="#1a1a1a", padx=2, pady=2)
        self.board.grid(row=0, column=0, padx=12, pady=12)

        # Nine 3x3 box frames give us the heavy interior borders for free.
        boxes = {}
        for br in range(BOX):
            for bc in range(BOX):
                f = tk.Frame(self.board, bg="#1a1a1a", padx=1, pady=1)
                f.grid(row=br, column=bc, padx=(0, 2 if bc < 2 else 0),
                       pady=(0, 2 if br < 2 else 0))
                boxes[(br, bc)] = f

        vcmd = (self.root.register(self._validate_entry), "%P")
        for r in range(SIZE):
            for c in range(SIZE):
                box = boxes[(r // BOX, c // BOX)]
                e = tk.Entry(box, width=2, font=("Helvetica", 20, "bold"),
                             justify="center", bd=0, relief="flat",
                             disabledbackground=NORMAL_BG,
                             disabledforeground=GIVEN_FG,
                             validate="key", validatecommand=vcmd)
                e.grid(row=r % BOX, column=c % BOX, padx=1, pady=1, ipady=6)
                e.bind("<FocusIn>", lambda ev, rc=(r, c): self._on_focus(rc))
                e.bind("<KeyRelease>", lambda ev, rc=(r, c): self._on_type(rc))
                self.cells[(r, c)] = e

    def _build_controls(self):
        self.bar = tk.Frame(self.root)
        self.bar.grid(row=1, column=0, pady=(0, 12))

        tk.Button(self.bar, text="New Game", width=9,
                  command=lambda: self.new_game(DEFAULT_DIFFICULTY)
                  ).grid(row=0, column=0, padx=3)
        tk.Button(self.bar, text="Check", width=9, command=self.check
                  ).grid(row=0, column=1, padx=3)
        tk.Button(self.bar, text="Solve", width=9, command=self.solve
                  ).grid(row=0, column=2, padx=3)
        tk.Button(self.bar, text="Settings", width=9, command=self.open_settings
                  ).grid(row=0, column=3, padx=3)

        self.status = tk.Label(self.root, text="", font=("Helvetica", 11))
        self.status.grid(row=2, column=0, pady=(0, 10))

    # ---- settings --------------------------------------------------------

    def _apply_settings(self):
        """Push current settings onto the live widgets."""
        bg = self.settings["window_bg"]
        self.root.config(bg=bg)
        self.bar.config(bg=bg)
        self.status.config(bg=bg)
        # Re-highlight the selected cell with the (possibly new) highlight color.
        if self.selected and self.cells[self.selected]["state"] != "disabled":
            self.cells[self.selected].config(bg=self.settings["highlight_bg"])

    def open_settings(self):
        SettingsDialog(self.root, self.settings, on_save=self._on_settings_saved)

    def _on_settings_saved(self, new_settings):
        self.settings.update(new_settings)
        ok = save_settings(self.settings)
        self._apply_settings()
        self.status.config(
            text="Settings saved." if ok else "Settings applied (couldn't write file).")

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
        self.selected = None
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
            cell.config(bg=self.settings["highlight_bg"])

    def _on_type(self, rc):
        cell = self.cells[rc]
        if cell["state"] != "disabled":
            cell.config(bg=self.settings["highlight_bg"], fg=USER_FG)
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
                e.config(bg=self.settings["error_bg"])
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


class SettingsDialog(tk.Toplevel):
    """Modal dialog for editing colors. Calls on_save(dict) when saved."""

    LABELS = [
        ("window_bg", "Window background"),
        ("highlight_bg", "Selected cell"),
        ("error_bg", "Error highlight"),
    ]

    def __init__(self, parent, current, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.on_save = on_save
        self.draft = dict(current)   # edited copy; only committed on Save
        self.swatches = {}

        for i, (key, label) in enumerate(self.LABELS):
            tk.Label(self, text=label, anchor="w", width=18).grid(
                row=i, column=0, padx=(14, 6), pady=8, sticky="w")
            sw = tk.Label(self, width=6, relief="solid", bd=1,
                          bg=self.draft[key])
            sw.grid(row=i, column=1, padx=6, pady=8)
            self.swatches[key] = sw
            tk.Button(self, text="Choose...",
                      command=lambda k=key: self._pick(k)
                      ).grid(row=i, column=2, padx=(6, 14), pady=8)

        btns = tk.Frame(self)
        btns.grid(row=len(self.LABELS), column=0, columnspan=3, pady=(6, 12))
        tk.Button(btns, text="Restore Defaults", command=self._restore
                  ).grid(row=0, column=0, padx=5)
        tk.Button(btns, text="Cancel", command=self.destroy
                  ).grid(row=0, column=1, padx=5)
        tk.Button(btns, text="Save", command=self._save
                  ).grid(row=0, column=2, padx=5)

        self.transient(parent)
        self.grab_set()          # modal
        self.update_idletasks()
        self._center_on(parent)

    def _center_on(self, parent):
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 3}")

    def _pick(self, key):
        chosen = colorchooser.askcolor(color=self.draft[key],
                                       parent=self, title="Pick a color")
        if chosen and chosen[1]:
            self.draft[key] = chosen[1]
            self.swatches[key].config(bg=chosen[1])

    def _restore(self):
        for key, _ in self.LABELS:
            self.draft[key] = DEFAULT_SETTINGS[key]
            self.swatches[key].config(bg=self.draft[key])

    def _save(self):
        self.on_save(self.draft)
        self.destroy()


def main():
    root = tk.Tk()
    SudokuGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()