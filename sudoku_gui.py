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
import threading
import tkinter as tk

import customtkinter as ctk
from tkinter import colorchooser, messagebox
from tkinter import font as tkfont

try:
    import darkdetect  # ships with CustomTkinter; reads the OS theme directly
except ImportError:
    darkdetect = None

import sudoku
import solver

SIZE = 9
BOX = 3

# Difficulty: label -> number of cells to attempt to remove (more removed =
# fewer starting clues = harder). The generator's uniqueness check may keep a
# few more clues than requested, so these are targets, not exact clue counts.
DIFFICULTIES = {
    "Beginner": 36,
    "Easy": 44,
    "Intermediate": 50,
    "Expert": 58,
}
DIFFICULTY_ORDER = ["Beginner", "Easy", "Intermediate", "Expert"]
DEFAULT_DIFFICULTY = "Easy"

# Digit colors. These are tuples (light_mode, dark_mode) so they stay legible
# in either appearance; CustomTkinter picks the right one automatically.
GIVEN_FG = ("#1a1a1a", "#f0f0f0")   # original clues (locked)
USER_FG = ("#1565c0", "#5fa8ff")    # player-entered values
SOLVED_FG = ("#2e7d32", "#5fd36a")  # auto-solve fills
NOTE_FG = ("#888888", "#aaaaaa")    # pencil-mark notes (dimmer than values)

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
    "auto_check": True,         # flag wrong entries when leaving a cell
    "notes_clear": True,        # entering a big number clears that cell's notes
    "difficulty": DEFAULT_DIFFICULTY,  # current difficulty tier
}

APPEARANCES = ["System", "Light", "Dark"]
LINE_MIN, LINE_MAX = 1, 8
CELL_PX = 46


def _contrast_text(bg_hex):
    """Return '#000000' or '#ffffff', whichever is more readable on bg_hex.

    Uses the perceived-luminance formula (WCAG-style channel weights): green
    contributes most to brightness, blue least. A light background gets black
    text; a dark one gets white. Works for any color, including white/black."""
    h = bg_hex.lstrip("#")
    if len(h) == 3:                     # expand shorthand like #abc
        h = "".join(ch * 2 for ch in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "#000000"                # unparseable -> safe default
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.55 else "#ffffff"

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
            # Exact type match: `type(...) is type(...)` (not isinstance) so that
            # a JSON bool can't masquerade as an int and vice versa, since in
            # Python bool is a subclass of int.
            if type(val) is type(default):
                if k in ("cell_line", "box_line"):
                    val = max(LINE_MIN, min(LINE_MAX, int(val)))
                if k == "appearance" and val not in APPEARANCES:
                    continue
                if k == "difficulty" and val not in DIFFICULTIES:
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
        self.all_cells = [(r, c) for r in range(SIZE) for c in range(SIZE)]
        self.values = {}         # (r, c) -> int 0..9 (0 = no big value)
        self.notes = {}          # (r, c) -> list[int] of candidate notes (entry order)
        self.given = set()       # (r, c) of locked clue cells
        self.solved_cells = set()  # (r, c) filled by the Solve button
        self.selected = None
        self.notes_mode = False  # when True, typed digits toggle notes
        self._generating = False
        self._gen_result = None

        self._build_grid()
        self._build_controls()
        self._apply_settings()
        self.new_game(self.settings["difficulty"])

    # ---- UI construction -------------------------------------------------

    def _build_grid(self):
        # The board is a Canvas. Cell backgrounds are rectangles, cell contents
        # (big values and 3x3 notes) are canvas text. A single off-screen Entry
        # holds keyboard focus; clicks select cells. This avoids the layering
        # limits of placing 81 widgets on a canvas (notes can sit "in" a cell).
        self.canvas = ctk.CTkCanvas(self.root, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, padx=16, pady=16)

        self.cell_rect = {}     # (r, c) -> canvas rectangle id (background)
        self.cell_origin = {}   # (r, c) -> (x, y) top-left pixel

        # Hidden entry purely to own keyboard focus and receive key events.
        self.focus_sink = tk.Entry(self.canvas, width=1)
        self.focus_sink.place(x=-100, y=-100)   # off-screen
        self.focus_sink.bind("<Key>",
                             lambda ev: self._on_key(ev, self.selected, False))
        self.focus_sink.bind("<Shift-Key>",
                             lambda ev: self._on_key(ev, self.selected, True))

        self.canvas.bind("<Button-1>", self._on_click)

        self._layout_grid()

    def _layout_grid(self):
        """(Re)compute geometry from current line widths; draw lines, cell
        backgrounds, and all cell contents."""
        cell_w = int(self.settings["cell_line"])
        box_w = int(self.settings["box_line"])
        mode = self._mode()
        line_color = _resolve(LINE_COLOR, mode)

        def line_at(i):
            return box_w if (i % BOX == 0) else cell_w

        offsets = [0]
        for i in range(SIZE):
            offsets.append(offsets[-1] + line_at(i) + CELL_PX)
        total = offsets[-1] + box_w

        self.canvas.config(width=total, height=total, bg=line_color)
        self.canvas.delete("all")
        self.cell_rect = {}
        self.cell_origin = {}

        # Grid lines (rectangles so width is exact).
        pos = 0
        for i in range(SIZE + 1):
            w = line_at(i)
            self.canvas.create_rectangle(pos, 0, pos + w, total,
                                         fill=line_color, width=0)
            self.canvas.create_rectangle(0, pos, total, pos + w,
                                         fill=line_color, width=0)
            if i < SIZE:
                pos += w + CELL_PX

        # Cell backgrounds + contents.
        for r in range(SIZE):
            for c in range(SIZE):
                x = offsets[c] + line_at(c)
                y = offsets[r] + line_at(r)
                self.cell_origin[(r, c)] = (x, y)
                rect = self.canvas.create_rectangle(
                    x, y, x + CELL_PX, y + CELL_PX, width=0,
                    fill=_resolve(CELL_BG, mode))
                self.cell_rect[(r, c)] = rect
                self._paint_cell((r, c))
                self._render_cell_text((r, c))

    BIG_FONT = ("Helvetica", 20, "bold")
    NOTE_FONT = ("Helvetica", 11)

    def _content_tag(self, rc):
        return "content_%d_%d" % rc

    def _render_cell_text(self, rc):
        """Draw the cell's contents on the canvas: a big centered value, or a
        3x3 grid of notes filled by ENTRY ORDER (1st -> top-left, 2nd ->
        top-middle, ... reading across), or nothing."""
        self.canvas.delete(self._content_tag(rc))
        if rc not in self.cell_origin:
            return
        ox, oy = self.cell_origin[rc]
        mode = self._mode()
        val = self.values.get(rc, 0)
        notes = self.notes.get(rc, [])

        if val != 0:
            fg = self._value_color(rc, mode)
            self.canvas.create_text(ox + CELL_PX / 2, oy + CELL_PX / 2,
                                    text=str(val), fill=fg, font=self.BIG_FONT,
                                    tags=self._content_tag(rc))
        elif notes:
            color = _resolve(NOTE_FG, mode)
            third = CELL_PX / 3
            for i, n in enumerate(notes[:9]):
                sr, sc = divmod(i, 3)            # fill across then down
                cx = ox + third * (sc + 0.5)
                cy = oy + third * (sr + 0.5)
                self.canvas.create_text(cx, cy, text=str(n), fill=color,
                                        font=self.NOTE_FONT,
                                        tags=self._content_tag(rc))

    def _value_color(self, rc, mode):
        """Foreground for a big value, accounting for given/selected/wrong."""
        if rc in self.given:
            return _resolve(GIVEN_FG, mode)
        if rc == self.selected:
            return _contrast_text(self.settings["highlight_bg"])
        val = self.values.get(rc, 0)
        if (self.settings["auto_check"] and val != 0
                and self.solution is not None
                and val != self.solution[rc[0]][rc[1]]):
            return _contrast_text(self.settings["error_bg"])
        if rc in self.solved_cells:
            return _resolve(SOLVED_FG, mode)
        return _resolve(USER_FG, mode)

    def _paint_cell(self, rc):
        """Set a cell's background rectangle color from its state: selected ->
        highlight, wrong big value (auto-check) -> error, else normal. Then
        refresh its contents so value colors track the background."""
        if rc not in self.cell_rect:
            return
        mode = self._mode()
        if rc == self.selected and rc not in self.given:
            bg = self.settings["highlight_bg"]
        else:
            val = self.values.get(rc, 0)
            wrong = (self.settings["auto_check"] and val != 0
                     and rc not in self.given and self.solution is not None
                     and val != self.solution[rc[0]][rc[1]])
            bg = self.settings["error_bg"] if wrong else _resolve(CELL_BG, mode)
        self.canvas.itemconfig(self.cell_rect[rc], fill=bg)
        # Redraw contents so the value's foreground matches the new background.
        self._render_cell_text(rc)

    def _build_controls(self):
        # Difficulty selector on its own row above the action buttons.
        diff_row = ctk.CTkFrame(self.root, fg_color="transparent")
        diff_row.grid(row=1, column=0, pady=(0, 6))
        ctk.CTkLabel(diff_row, text="Difficulty:").grid(row=0, column=0, padx=(0, 6))
        self.difficulty_menu = ctk.CTkOptionMenu(
            diff_row, values=DIFFICULTY_ORDER, width=140,
            command=self._on_difficulty_change)
        self.difficulty_menu.set(self.settings["difficulty"])
        self.difficulty_menu.grid(row=0, column=1)

        self.bar = ctk.CTkFrame(self.root, fg_color="transparent")
        self.bar.grid(row=2, column=0, pady=(0, 8))

        ctk.CTkButton(self.bar, text="New Game", width=84,
                      command=self._new_game_clicked
                      ).grid(row=0, column=0, padx=4)
        self.notes_btn = ctk.CTkButton(self.bar, text="Notes: OFF", width=84,
                                       command=self.toggle_notes_mode)
        self.notes_btn.grid(row=0, column=1, padx=4)
        ctk.CTkButton(self.bar, text="Check", width=84, command=self.check
                      ).grid(row=0, column=2, padx=4)
        ctk.CTkButton(self.bar, text="Solve", width=84, command=self.solve
                      ).grid(row=0, column=3, padx=4)
        ctk.CTkButton(self.bar, text="Settings", width=84,
                      command=self.open_settings).grid(row=0, column=4, padx=4)

        self.status = ctk.CTkLabel(self.root, text="")
        self.status.grid(row=3, column=0, pady=(0, 12))

    def _new_game_clicked(self):
        self.new_game(self.settings["difficulty"])

    def _on_difficulty_change(self, value):
        # Remember the choice (persisted) but don't disrupt the current puzzle;
        # it takes effect on the next New Game.
        self.settings["difficulty"] = value
        save_settings(self.settings)
        self.status.configure(
            text=f"Difficulty set to {value}. Starts on next New Game.")

    # ---- settings --------------------------------------------------------

    def _mode(self):
        """The effective 'Light'/'Dark' mode this app should paint with, based
        on its own appearance setting (not raw global state)."""
        return _effective_mode(self.settings["appearance"])

    def _apply_settings(self):
        ctk.set_appearance_mode(self.settings["appearance"])
        self._layout_grid()

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

    # ---- game lifecycle --------------------------------------------------

    def new_game(self, difficulty):
        # Rated generation can take several seconds (it generates and grades many
        # candidates), so run it off the main thread to keep the UI responsive.
        # The worker only writes to a plain attribute; the main thread polls it
        # via _poll_generation (Tk calls must stay on the main thread).
        if getattr(self, "_generating", False):
            return                      # ignore clicks while a game is brewing
        self._generating = True
        self._gen_result = None
        self.status.configure(text=f"Generating a {difficulty} puzzle...")
        self.difficulty_menu.configure(state="disabled")

        def work():
            puzzle, solution, actual = sudoku.make_rated_puzzle(
                difficulty, rater=solver.rate)
            self._gen_result = (puzzle, solution, difficulty, actual)

        threading.Thread(target=work, daemon=True).start()
        self._poll_generation()

    def _poll_generation(self):
        """Main-thread poll for the worker's result; reschedules itself."""
        if self._gen_result is None:
            self.root.after(50, self._poll_generation)
            return
        puzzle, solution, requested, actual = self._gen_result
        self._gen_result = None
        self.puzzle, self.solution = puzzle, solution
        self.selected = None
        self._render_puzzle()
        self._generating = False
        self.difficulty_menu.configure(state="normal")
        if actual == requested:
            self.status.configure(text=f"New game ({requested}). Good luck!")
        else:
            # Couldn't hit the exact tier within the attempt budget; we used the
            # closest. Be honest rather than mislabel the puzzle.
            self.status.configure(
                text=f"New game (closest to {requested}: {actual}). Good luck!")

    def _render_puzzle(self):
        """Reset the model from the freshly generated puzzle and redraw."""
        self.values = {}
        self.notes = {}
        self.given = set()
        self.solved_cells = set()
        for (r, c) in self.all_cells:
            v = self.puzzle[r][c]
            self.values[(r, c)] = v
            self.notes[(r, c)] = []
            if v != 0:
                self.given.add((r, c))
        for rc in self.all_cells:
            self._paint_cell(rc)
            self._render_cell_text(rc)

    # ---- interaction -----------------------------------------------------

    def _cell_at(self, px, py):
        """Return the (r, c) whose pixel box contains (px, py), or None."""
        for rc, (ox, oy) in self.cell_origin.items():
            if ox <= px < ox + CELL_PX and oy <= py < oy + CELL_PX:
                return rc
        return None

    def _on_click(self, event):
        rc = self._cell_at(self.canvas.canvasx(event.x),
                            self.canvas.canvasy(event.y))
        if rc is not None:
            self._select(rc)
        self.focus_sink.focus_set()   # keep keyboard input flowing

    def _select(self, rc):
        prev = self.selected
        self.selected = rc
        if prev and prev != rc:
            self._paint_cell(prev)    # repaint (and possibly flag) the cell we left
        self._paint_cell(rc)          # highlight the newly selected cell

    # Some keyboard layouts report Shift+digit as the symbol keysym rather than
    # the digit. Map those back so Shift-noting works regardless of layout.
    _SHIFT_DIGIT = {
        "exclam": 1, "at": 2, "numbersign": 3, "dollar": 4, "percent": 5,
        "asciicircum": 6, "ampersand": 7, "asterisk": 8, "parenleft": 9,
    }

    def _on_key(self, event, rc, shift):
        """Handle a keystroke for the selected cell. `shift` is True when from
        the <Shift-Key> binding. Returns 'break' to suppress default handling."""
        if rc is None or rc in self.given:
            return "break"          # nothing selected, or a clue cell
        key = event.keysym
        # Resolve the digit: prefer a plain digit keysym; otherwise translate a
        # shifted-symbol keysym (layout-dependent) back to its digit.
        d = None
        if key in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            d = int(key)
        elif key in self._SHIFT_DIGIT:
            d = self._SHIFT_DIGIT[key]
        if d is not None:
            note_intent = self.notes_mode ^ shift   # toggle XOR Shift
            if note_intent:
                self._toggle_note(rc, d)
            else:
                self._set_value(rc, d)
            return "break"
        if key in ("BackSpace", "Delete", "0", "KP_0"):
            self._clear_cell(rc)
            return "break"
        if key == "space":
            self._clear_cell(rc)
            return "break"
        return "break"              # ignore everything else (letters, etc.)

    def _set_value(self, rc, d):
        self.values[rc] = d
        self.solved_cells.discard(rc)   # a player value is no longer "solved"
        if self.settings["notes_clear"]:
            self.notes[rc] = []     # entering a real number clears notes (setting)
        self._paint_cell(rc)
        self._render_cell_text(rc)
        self._check_win()

    def _toggle_note(self, rc, d):
        if self.values.get(rc, 0) != 0:
            return                  # a cell with a big value holds no notes
        notes = self.notes.setdefault(rc, [])
        if d in notes:
            notes.remove(d)         # typing an existing note removes it
        else:
            notes.append(d)         # kept in entry order (left-to-right)
        self._paint_cell(rc)
        self._render_cell_text(rc)

    def _clear_cell(self, rc):
        # Staged clear: if a big value is present, remove just the value (which
        # reveals any preserved notes); otherwise clear the notes.
        if self.values.get(rc, 0) != 0:
            self.values[rc] = 0
            self.solved_cells.discard(rc)
        else:
            self.notes[rc] = []
        self._paint_cell(rc)
        self._render_cell_text(rc)

    def _check_win(self):
        if self._is_complete() and self._is_correct():
            self.status.configure(text="Solved! Well done.")
            messagebox.showinfo("Sudoku", "You solved it!")

    def toggle_notes_mode(self):
        self.notes_mode = not self.notes_mode
        self.notes_btn.configure(
            text="Notes: ON" if self.notes_mode else "Notes: OFF")
        self.status.configure(
            text="Notes mode on — digits add pencil marks."
            if self.notes_mode else "Notes mode off.")

    # ---- actions ---------------------------------------------------------

    def _current_grid(self):
        grid = [[0] * SIZE for _ in range(SIZE)]
        for (r, c) in self.all_cells:
            grid[r][c] = self.values.get((r, c), 0)
        return grid

    def _is_complete(self):
        return all(self.values.get(rc, 0) != 0 for rc in self.all_cells)

    def _is_correct(self):
        return self._current_grid() == self.solution

    def check(self):
        wrong = 0
        for rc in self.all_cells:
            if rc in self.given:
                continue
            val = self.values.get(rc, 0)
            if val != 0 and val != self.solution[rc[0]][rc[1]]:
                if rc in self.cell_rect:
                    self.canvas.itemconfig(self.cell_rect[rc],
                                           fill=self.settings["error_bg"])
                    self._render_cell_text(rc)
                wrong += 1
        if wrong == 0:
            self.status.configure(
                text="All correct — solved!" if self._is_complete()
                else "No mistakes so far. Keep going.")
        else:
            self.status.configure(text=f"{wrong} incorrect cell(s) highlighted.")

    def solve(self):
        for (r, c) in self.all_cells:
            rc = (r, c)
            if rc in self.given:
                continue
            self.values[rc] = self.solution[r][c]
            self.notes[rc] = []
            self.solved_cells.add(rc)
            self._paint_cell(rc)
            self._render_cell_text(rc)
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

        # Auto-check toggle
        ctk.CTkLabel(self, text="Auto-check entries").grid(
            row=row, column=0, sticky="w", **pad)
        self.autocheck_switch = ctk.CTkSwitch(
            self, text="", command=self._toggle_autocheck)
        if self.draft["auto_check"]:
            self.autocheck_switch.select()
        else:
            self.autocheck_switch.deselect()
        self.autocheck_switch.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Notes-clear toggle
        ctk.CTkLabel(self, text="Number clears notes").grid(
            row=row, column=0, sticky="w", **pad)
        self.notesclear_switch = ctk.CTkSwitch(
            self, text="", command=self._toggle_notesclear)
        if self.draft["notes_clear"]:
            self.notesclear_switch.select()
        else:
            self.notesclear_switch.deselect()
        self.notesclear_switch.grid(row=row, column=1, sticky="w", **pad)
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

    def _toggle_autocheck(self):
        self.draft["auto_check"] = bool(self.autocheck_switch.get())
        self._preview()

    def _toggle_notesclear(self):
        self.draft["notes_clear"] = bool(self.notesclear_switch.get())
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
        self.draft["auto_check"] = DEFAULT_SETTINGS["auto_check"]
        (self.autocheck_switch.select if self.draft["auto_check"]
         else self.autocheck_switch.deselect)()
        self.draft["notes_clear"] = DEFAULT_SETTINGS["notes_clear"]
        (self.notesclear_switch.select if self.draft["notes_clear"]
         else self.notesclear_switch.deselect)()
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