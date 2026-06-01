"""CustomTkinter GUI for the Sudoku generator/solver.

Requires sudoku.py in the same directory, plus the CustomTkinter package:
    pip install customtkinter
Run: python sudoku_gui.py

Modes:
  - Play:  fill in cells yourself; "Check" flags mistakes, "Solve" reveals all.
  - New:   generates a fresh puzzle (difficulty hook is ready, see DIFFICULTIES).

Settings (theme, colors, line widths) are editable via the Settings button and
persist to a JSON file next to this script.
"""

import json
import os
import tkinter as tk

import customtkinter as ctk
from tkinter import colorchooser, messagebox

try:
    import darkdetect  # ships with CustomTkinter; reads the OS theme directly
except ImportError:
    darkdetect = None

import sudoku

SIZE = 9
BOX = 3

# Difficulty hook: label -> cells removed. No selector is exposed yet (by
# request); wiring one later just means passing a choice to new_game().
DIFFICULTIES = {"Easy": 40, "Medium": 50, "Hard": 56}
DEFAULT_DIFFICULTY = "Medium"

# Digit colors. These are tuples (light_mode, dark_mode) so they stay legible
# in either appearance; CustomTkinter picks the right one automatically.
GIVEN_FG = ("#1a1a1a", "#f0f0f0")   # original clues (locked)
USER_FG = ("#1565c0", "#5fa8ff")    # player-entered values
SOLVED_FG = ("#2e7d32", "#5fd36a")  # auto-solve fills

# Cell backgrounds (tuples for light/dark). Cells are plain tk widgets on the
# canvas, so these are resolved to a single color at render time.
CELL_BG = ("#ffffff", "#2b2b2b")

LINE_COLOR = ("#3a3a3a", "#888888")  # grid lines, per appearance mode

# User-configurable settings + defaults (what gets saved/loaded).
DEFAULT_SETTINGS = {
    "appearance": "System",     # "System" | "Light" | "Dark"
    "highlight_bg": "#3b6ea5",  # selected cell (single color, both modes)
    "error_bg": "#c0392b",      # cells flagged wrong by Check
    "cell_line": 1,             # px, lines between cells
    "box_line": 3,              # px, the 3x3 box borders
}

APPEARANCES = ["System", "Light", "Dark"]
LINE_MIN, LINE_MAX = 1, 8
CELL_PX = 46

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "sudoku_settings.json")


def load_settings():
    """Load settings, falling back to defaults for any missing/invalid keys."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r") as f:
            saved = json.load(f)
        for k, default in DEFAULT_SETTINGS.items():
            val = saved.get(k)
            if isinstance(val, type(default)) and not isinstance(val, bool):
                if k in ("cell_line", "box_line"):
                    val = max(LINE_MIN, min(LINE_MAX, int(val)))
                if k == "appearance" and val not in APPEARANCES:
                    continue
                settings[k] = val
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    """Persist settings to disk. Failure is non-fatal (reported, not raised)."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        return True
    except OSError:
        return False


def _effective_mode(appearance):
    """Map an appearance setting ('System'/'Light'/'Dark') to 'Light' or 'Dark'.

    For 'System' we read the OS theme directly via darkdetect rather than
    ctk.get_appearance_mode(). CustomTkinter caches its resolved value and
    updates it on a background poll, so right after toggling modes it can be
    momentarily stale — reading the OS directly makes every repaint agree."""
    if appearance == "System":
        if darkdetect is not None:
            theme = darkdetect.theme()   # "Dark", "Light", or None
            if theme in ("Dark", "Light"):
                return theme
        # Fallback if darkdetect is unavailable or returns None.
        return ctk.get_appearance_mode()
    return appearance


def _resolve(color, mode):
    """Resolve a (light, dark) tuple to one color for the given mode ('Light'
    or 'Dark'). Single strings pass through unchanged.

    `mode` is passed in explicitly (derived from the app's own setting) rather
    than read from global state, so the painted colors always match what the
    app intends to display — even mid-preview or after a cancelled change."""
    if isinstance(color, (tuple, list)):
        return color[1] if mode == "Dark" else color[0]
    return color


class SudokuGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Sudoku")
        self.root.resizable(False, False)

        self.settings = load_settings()
        ctk.set_appearance_mode(self.settings["appearance"])

        self.puzzle = None
        self.solution = None
        self.cells = {}
        self.selected = None

        self._build_grid()
        self._build_controls()
        self._apply_settings()
        self.new_game(DEFAULT_DIFFICULTY)

    # ---- UI construction -------------------------------------------------

    def _build_grid(self):
        # Canvas grid: lines drawn as exact-pixel rectangles, Entry cells placed
        # on top. Precise widths, DPI-independent.
        self.canvas = ctk.CTkCanvas(self.root, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, padx=16, pady=16)

        vcmd = (self.root.register(self._validate_entry), "%P")
        for r in range(SIZE):
            for c in range(SIZE):
                # Plain tk.Entry: it sits on the canvas and we fully control its
                # look, so it themes consistently regardless of platform.
                e = tk.Entry(self.canvas, width=2,
                             font=("Helvetica", 20, "bold"),
                             justify="center", bd=0, relief="flat",
                             highlightthickness=0)
                e.bind("<FocusIn>", lambda ev, rc=(r, c): self._on_focus(rc))
                e.bind("<KeyRelease>", lambda ev, rc=(r, c): self._on_type(rc))
                self.cells[(r, c)] = e

        self._layout_grid()

    def _layout_grid(self):
        """(Re)compute geometry from current line widths; draw lines; place cells."""
        cell_w = int(self.settings["cell_line"])
        box_w = int(self.settings["box_line"])
        mode = self._mode()
        line_color = _resolve(LINE_COLOR, mode)
        cell_bg = _resolve(CELL_BG, mode)

        def line_at(i):
            return box_w if (i % BOX == 0) else cell_w

        offsets = [0]
        for i in range(SIZE):
            offsets.append(offsets[-1] + line_at(i) + CELL_PX)
        total = offsets[-1] + box_w

        # Canvas background = line color (the lines are the gaps showing through).
        self.canvas.config(width=total, height=total, bg=line_color)
        self.canvas.delete("grid")

        pos = 0
        for i in range(SIZE + 1):
            w = line_at(i)
            self.canvas.create_rectangle(pos, 0, pos + w, total,
                                         fill=line_color, width=0, tags="grid")
            self.canvas.create_rectangle(0, pos, total, pos + w,
                                         fill=line_color, width=0, tags="grid")
            if i < SIZE:
                pos += w + CELL_PX

        for r in range(SIZE):
            for c in range(SIZE):
                x = offsets[c] + line_at(c)
                y = offsets[r] + line_at(r)
                e = self.cells[(r, c)]
                e.place(x=x, y=y, width=CELL_PX, height=CELL_PX)
                # Refresh per-mode colors on the entry.
                e.config(disabledbackground=cell_bg,
                         disabledforeground=_resolve(GIVEN_FG, mode),
                         bg=cell_bg, fg=_resolve(USER_FG, mode))

    def _build_controls(self):
        self.bar = ctk.CTkFrame(self.root, fg_color="transparent")
        self.bar.grid(row=1, column=0, pady=(0, 8))

        specs = [("New Game", lambda: self.new_game(DEFAULT_DIFFICULTY)),
                 ("Check", self.check),
                 ("Solve", self.solve),
                 ("Settings", self.open_settings)]
        for col, (text, cmd) in enumerate(specs):
            ctk.CTkButton(self.bar, text=text, width=90, command=cmd
                          ).grid(row=0, column=col, padx=5)

        self.status = ctk.CTkLabel(self.root, text="")
        self.status.grid(row=2, column=0, pady=(0, 12))

    # ---- settings --------------------------------------------------------

    def _mode(self):
        """The effective 'Light'/'Dark' mode this app should paint with, based
        on its own appearance setting (not raw global state)."""
        return _effective_mode(self.settings["appearance"])

    def _apply_settings(self):
        ctk.set_appearance_mode(self.settings["appearance"])
        self._layout_grid()
        if self.selected and self.cells[self.selected]["state"] != "disabled":
            self.cells[self.selected].config(bg=self.settings["highlight_bg"])

    def open_settings(self):
        SettingsDialog(self.root, self.settings,
                       on_save=self._on_settings_saved,
                       on_preview=self._on_settings_preview)

    def _on_settings_preview(self, draft):
        self.settings.update(draft)
        self._apply_settings()

    def _on_settings_saved(self, new_settings):
        self.settings.update(new_settings)
        ok = save_settings(self.settings)
        self._apply_settings()
        self.status.configure(
            text="Settings saved." if ok else "Applied (couldn't write file).")

    # ---- input validation ------------------------------------------------

    @staticmethod
    def _validate_entry(proposed):
        return proposed == "" or (len(proposed) == 1 and proposed in "123456789")

    # ---- game lifecycle --------------------------------------------------

    def new_game(self, difficulty):
        clues_removed = DIFFICULTIES.get(difficulty, 50)
        self.status.configure(text="Generating...")
        self.root.update_idletasks()
        self.puzzle, self.solution = sudoku.make_puzzle(clues_removed=clues_removed)
        self.selected = None
        self._render_puzzle()
        self.status.configure(text=f"New game ({difficulty}). Good luck!")

    def _render_puzzle(self):
        mode = self._mode()
        cell_bg = _resolve(CELL_BG, mode)
        for (r, c), e in self.cells.items():
            e.config(state="normal")
            e.delete(0, tk.END)
            e.config(bg=cell_bg, fg=_resolve(USER_FG, mode))
            val = self.puzzle[r][c]
            if val != 0:
                e.insert(0, str(val))
                e.config(state="disabled")

    # ---- interaction -----------------------------------------------------

    def _on_focus(self, rc):
        if self.selected and self.selected in self.cells:
            prev = self.cells[self.selected]
            if prev["state"] != "disabled":
                prev.config(bg=_resolve(CELL_BG, self._mode()))
        self.selected = rc
        cell = self.cells[rc]
        if cell["state"] != "disabled":
            cell.config(bg=self.settings["highlight_bg"])

    def _on_type(self, rc):
        cell = self.cells[rc]
        if cell["state"] != "disabled":
            cell.config(bg=self.settings["highlight_bg"],
                        fg=_resolve(USER_FG, self._mode()))
        if self._is_complete() and self._is_correct():
            self.status.configure(text="Solved! Well done.")
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
            self.status.configure(
                text="All correct — solved!" if self._is_complete()
                else "No mistakes so far. Keep going.")
        else:
            self.status.configure(text=f"{wrong} incorrect cell(s) highlighted.")

    def solve(self):
        mode = self._mode()
        cell_bg = _resolve(CELL_BG, mode)
        for (r, c), e in self.cells.items():
            if e["state"] == "disabled":
                continue
            e.delete(0, tk.END)
            e.insert(0, str(self.solution[r][c]))
            e.config(bg=cell_bg, fg=_resolve(SOLVED_FG, mode))
        self.status.configure(text="Solution revealed.")


class SettingsDialog(ctk.CTkToplevel):
    """Modal settings dialog. Calls on_preview(dict) live and on_save(dict)."""

    COLOR_LABELS = [("highlight_bg", "Selected cell"),
                    ("error_bg", "Error highlight")]
    WIDTH_LABELS = [("cell_line", "Cell line width"),
                    ("box_line", "Box border width")]

    def __init__(self, parent, current, on_save, on_preview=None):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.on_save = on_save
        self.on_preview = on_preview
        self.draft = dict(current)
        self._original = dict(current)
        self.swatches = {}
        self.width_menus = {}

        pad = {"padx": 12, "pady": 8}
        row = 0

        # Appearance mode
        ctk.CTkLabel(self, text="Appearance").grid(row=row, column=0, sticky="w", **pad)
        self.appearance_menu = ctk.CTkOptionMenu(
            self, values=APPEARANCES, width=120, command=self._set_appearance)
        self.appearance_menu.set(self.draft["appearance"])
        self.appearance_menu.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        row += 1

        # Color pickers
        for key, label in self.COLOR_LABELS:
            ctk.CTkLabel(self, text=label).grid(row=row, column=0, sticky="w", **pad)
            sw = ctk.CTkButton(self, text="", width=48, height=24,
                               fg_color=self.draft[key], hover=False,
                               border_width=1, command=lambda k=key: self._pick(k))
            sw.grid(row=row, column=1, **pad)
            self.swatches[key] = sw
            ctk.CTkButton(self, text="Choose...", width=90,
                          command=lambda k=key: self._pick(k)
                          ).grid(row=row, column=2, **pad)
            row += 1

        # Line widths (dropdowns 1..8)
        width_vals = [str(i) for i in range(LINE_MIN, LINE_MAX + 1)]
        for key, label in self.WIDTH_LABELS:
            ctk.CTkLabel(self, text=label).grid(row=row, column=0, sticky="w", **pad)
            m = ctk.CTkOptionMenu(self, values=width_vals, width=80,
                                  command=lambda v, k=key: self._set_width(k, v))
            m.set(str(self.draft[key]))
            m.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
            self.width_menus[key] = m
            row += 1

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=row, column=0, columnspan=3, pady=(8, 14))
        ctk.CTkButton(btns, text="Restore Defaults", width=120,
                      command=self._restore).grid(row=0, column=0, padx=5)
        ctk.CTkButton(btns, text="Cancel", width=90,
                      command=self._cancel).grid(row=0, column=1, padx=5)
        ctk.CTkButton(btns, text="Save", width=90,
                      command=self._save).grid(row=0, column=2, padx=5)

        self.transient(parent)
        self.after(10, self.grab_set)  # small delay: CTkToplevel needs to map first
        self.update_idletasks()
        self._center_on(parent)

    def _center_on(self, parent):
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 3}")

    def _preview(self):
        if self.on_preview:
            self.on_preview(dict(self.draft))

    def _set_appearance(self, value):
        self.draft["appearance"] = value
        self._preview()

    def _set_width(self, key, value):
        self.draft[key] = int(value)
        self._preview()

    def _pick(self, key):
        chosen = colorchooser.askcolor(color=self.draft[key],
                                       parent=self, title="Pick a color")
        if chosen and chosen[1]:
            self.draft[key] = chosen[1]
            self.swatches[key].configure(fg_color=chosen[1])
            self._preview()

    def _restore(self):
        for key, _ in self.COLOR_LABELS:
            self.draft[key] = DEFAULT_SETTINGS[key]
            self.swatches[key].configure(fg_color=self.draft[key])
        for key, _ in self.WIDTH_LABELS:
            self.draft[key] = DEFAULT_SETTINGS[key]
            self.width_menus[key].set(str(self.draft[key]))
        self.draft["appearance"] = DEFAULT_SETTINGS["appearance"]
        self.appearance_menu.set(self.draft["appearance"])
        self._preview()

    def _cancel(self):
        if self.on_preview:
            self.on_preview(dict(self._original))
        self.destroy()

    def _save(self):
        self.on_save(self.draft)
        self.destroy()


def main():
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    SudokuGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()