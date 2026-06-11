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
import time
import tkinter as tk

import customtkinter as ctk
from tkinter import colorchooser
from tkinter import font as tkfont

try:
    import darkdetect  # ships with CustomTkinter; reads the OS theme directly
except ImportError:
    darkdetect = None

import sudoku
import solver
import puzzle_cache

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
NOTE_MATCH_FG = ("#1565c0", "#5fa8ff")  # a note matching the selected number

# Cell backgrounds (tuples for light/dark). Cells are plain tk widgets on the
# canvas, so these are resolved to a single color at render time.
CELL_BG = ("#ffffff", "#2b2b2b")

LINE_COLOR = ("#3a3a3a", "#888888")  # grid lines, per appearance mode

# Related-cell highlighting (when a cell is selected). PEER tints the selection's
# row and column; MATCH tints every cell holding the same big value. (light, dark)
# tuples so they read in either appearance; resolved at paint time.
PEER_BG = ("#ececec", "#3c3c3c")   # row/column of the selection (neutral grey)
MATCH_BG = ("#cfe0f5", "#24455f")  # same number as the selection (blue wash)

# User-configurable settings + defaults (what gets saved/loaded).
DEFAULT_SETTINGS = {
    "appearance": "System",     # "System" | "Light" | "Dark"
    "highlight_bg": "#3b6ea5",  # selected cell (single color, both modes)
    "error_bg": "#c0392b",      # cells flagged wrong by Check
    "cell_line": 1,             # px, lines between cells
    "box_line": 3,              # px, the 3x3 box borders
    "auto_check": True,         # flag wrong entries when leaving a cell
    "entry_clears_notes": True,  # placing a digit clears notes in that cell and its peers
    "highlight_related": True,  # tint matching numbers + selection's row/col
    "show_timer": False,        # show an elapsed-time clock above the board
    "difficulty": DEFAULT_DIFFICULTY,  # current difficulty tier
}

APPEARANCES = ["System", "Light", "Dark"]
LINE_MIN, LINE_MAX = 1, 8
CELL_PX = 46
UNDO_LIMIT = 100    # cap on stored undo snapshots (bounds memory)


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


# ---- button styling --------------------------------------------------------
# Two reusable looks layered over CustomTkinter's theme: an "accent" (the
# theme's filled primary, used for the main action and active toggles) and a
# "ghost" (subtle outline for secondary actions). Centralized so the main
# window and dialogs stay visually consistent.

def _theme_button_colors():
    """The active theme's default (fg, hover, text) button colors. Falls back
    to blue-theme values if the ThemeManager API differs across versions."""
    try:
        t = ctk.ThemeManager.theme["CTkButton"]
        return t["fg_color"], t["hover_color"], t["text_color"]
    except Exception:
        return ("#3a7ebf", "#1f538d"), ("#325882", "#14375e"), "#dce4ee"


def _accent_button_kwargs():
    fg, hover, text = _theme_button_colors()
    return {"fg_color": fg, "hover_color": hover, "text_color": text,
            "border_width": 0}


def _ghost_button_kwargs():
    return {"fg_color": "transparent", "border_width": 1,
            "border_color": ("#c2c2c2", "#4a4a4a"),
            "text_color": ("#1a1a1a", "#e6e6e6"),
            "hover_color": ("#ececec", "#333333")}


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
        self._undo_stack = []    # snapshots of prior states (most recent last)
        self._redo_stack = []    # snapshots undone, redo-able until a new action
        self._timer_start = None  # monotonic ts when the clock last started
        self._timer_accum = 0.0   # seconds banked before the current run
        self._timer_running = False
        self._timer_job = None    # pending after() id for the tick loop
        self._generating = False
        self._gen_result = None
        self.cache = puzzle_cache.PuzzleCache()  # rolling per-tier puzzle store

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
        self.canvas.grid(row=1, column=0, padx=16, pady=(6, 12))

        self.cell_rect = {}     # (r, c) -> canvas rectangle id (background)
        self.cell_origin = {}   # (r, c) -> (x, y) top-left pixel

        # Hidden entry purely to own keyboard focus and receive key events.
        self.focus_sink = tk.Entry(self.canvas, width=1)
        self.focus_sink.place(x=-100, y=-100)   # off-screen
        self.focus_sink.bind("<Key>",
                             lambda ev: self._on_key(ev, self.selected, False))
        self.focus_sink.bind("<Shift-Key>",
                             lambda ev: self._on_key(ev, self.selected, True))
        # Undo/redo accelerators. These are MORE specific than <Key>, so Tk fires
        # them instead of the digit handler; ⌘ on macOS, Ctrl elsewhere. Bound on
        # the focus sink (which holds focus during play) so they aren't swallowed
        # by its <Key> "break".
        for seq in ("<Command-z>", "<Control-z>"):
            self.focus_sink.bind(seq, self._on_undo_key)
        for seq in ("<Command-Shift-Z>", "<Command-Shift-z>",
                    "<Control-Shift-Z>", "<Control-Shift-z>", "<Control-y>"):
            self.focus_sink.bind(seq, self._on_redo_key)

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
    NOTE_MATCH_FONT = ("Helvetica", 11, "bold")

    def _content_tag(self, rc):
        return "content_%d_%d" % rc

    def _active_number(self):
        """The big value of the current selection (0 if nothing is selected or
        the selected cell is empty). Used to highlight matching values and
        notes across the board."""
        if self.selected is None:
            return 0
        return self.values.get(self.selected, 0)

    def _render_cell_text(self, rc):
        """Draw the cell's contents on the canvas: a big centered value, or a
        3x3 grid of notes in FIXED positions by digit value (1 -> top-left,
        2 -> top-middle, ... 9 -> bottom-right), or nothing."""
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
            normal = _resolve(NOTE_FG, mode)
            match = _resolve(NOTE_MATCH_FG, mode)
            # A note is "hot" when it matches the selected cell's value and
            # related highlighting is on; hot notes render bold and tinted.
            active = (self._active_number()
                      if self.settings["highlight_related"] else 0)
            third = CELL_PX / 3
            for n in notes:
                if not 1 <= n <= 9:
                    continue
                sr, sc = divmod(n - 1, 3)       # fixed slot from digit value
                cx = ox + third * (sc + 0.5)
                cy = oy + third * (sr + 0.5)
                hot = (active != 0 and n == active)
                self.canvas.create_text(cx, cy, text=str(n),
                                        fill=match if hot else normal,
                                        font=self.NOTE_MATCH_FONT if hot
                                        else self.NOTE_FONT,
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
        """Set a cell's background by state, in priority order: selected ->
        highlight; wrong big value (auto-check) -> error; same number as the
        selection -> match tint; selection's row/column -> peer tint; else
        normal. Then refresh contents so value colors track the background."""
        if rc not in self.cell_rect:
            return
        mode = self._mode()
        val = self.values.get(rc, 0)

        if rc == self.selected and rc not in self.given:
            bg = self.settings["highlight_bg"]
        elif (self.settings["auto_check"] and val != 0
                and rc not in self.given and self.solution is not None
                and val != self.solution[rc[0]][rc[1]]):
            bg = self.settings["error_bg"]
        else:
            bg = self._related_bg(rc, val, mode)

        self.canvas.itemconfig(self.cell_rect[rc], fill=bg)
        # Redraw contents so the value's foreground matches the new background.
        self._render_cell_text(rc)

    def _related_bg(self, rc, val, mode):
        """Background for a cell that isn't selected or flagged-wrong: a match or
        peer tint relative to the current selection, else the normal cell color.
        Normal when highlighting is off or nothing is selected."""
        normal = _resolve(CELL_BG, mode)
        if not self.settings["highlight_related"] or self.selected is None:
            return normal
        if rc == self.selected:          # focal (e.g. given) cell stays plain
            return normal
        sel_val = self.values.get(self.selected, 0)
        if sel_val != 0 and val == sel_val:
            return _resolve(MATCH_BG, mode)
        if rc[0] == self.selected[0] or rc[1] == self.selected[1]:
            return _resolve(PEER_BG, mode)
        return normal

    def _build_controls(self):
        icon_font = ("Helvetica", 18)

        # ---- top header: New Game (left) · timer (center) · settings gear (right)
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        header.columnconfigure(1, weight=1)     # center column absorbs slack

        self.newgame_btn = ctk.CTkButton(
            header, text="+", width=40, height=34, corner_radius=8,
            font=("Helvetica", 22), command=self._new_game_clicked,
            **_ghost_button_kwargs())
        self.newgame_btn.grid(row=0, column=0, sticky="w")

        self.timer_label = ctk.CTkLabel(header, text="00:00",
                                        font=("Helvetica", 18, "bold"))
        self.timer_label.grid(row=0, column=1)  # centered by the weighted column

        self.settings_btn = ctk.CTkButton(
            header, text="\u2699", width=40, height=34, corner_radius=8,
            font=("Helvetica", 20), command=self.open_settings,
            **_ghost_button_kwargs())
        self.settings_btn.grid(row=0, column=2, sticky="e")

        # ---- bottom bar: [undo redo]  ·  Notes  ·  [Check Solve]
        bar = ctk.CTkFrame(self.root, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(2, 4))
        bar.columnconfigure(0, weight=1)         # left/right expand, centering Notes
        bar.columnconfigure(2, weight=1)

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        self.undo_btn = ctk.CTkButton(left, text="\u21ba", width=40, height=34,
                                      corner_radius=8, font=icon_font,
                                      command=self.undo, **_ghost_button_kwargs())
        self.undo_btn.grid(row=0, column=0, padx=(0, 6))
        self.redo_btn = ctk.CTkButton(left, text="\u21bb", width=40, height=34,
                                      corner_radius=8, font=icon_font,
                                      command=self.redo, **_ghost_button_kwargs())
        self.redo_btn.grid(row=0, column=1)

        # Notes is a toggle: ghost when off, accent when on (set in toggle_notes_mode).
        self.notes_btn = ctk.CTkButton(
            bar, text="\u270e Notes", width=110, height=34, corner_radius=8,
            command=self.toggle_notes_mode, **_ghost_button_kwargs())
        self.notes_btn.grid(row=0, column=1, padx=8)

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e")
        ctk.CTkButton(right, text="Check", width=68, height=34, corner_radius=8,
                      command=self.check, **_ghost_button_kwargs()
                      ).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkButton(right, text="Hint", width=68, height=34, corner_radius=8,
                      command=self.hint, **_ghost_button_kwargs()
                      ).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(right, text="Solve", width=68, height=34, corner_radius=8,
                      command=self.solve, **_ghost_button_kwargs()
                      ).grid(row=0, column=2)

        self.status = ctk.CTkLabel(self.root, text="",
                                   text_color=("#6a6a6a", "#9a9a9a"))
        self.status.grid(row=3, column=0, pady=(2, 12))

    def _new_game_clicked(self):
        # Opens the difficulty picker (defaulting to the current tier); the
        # actual generation kicks off when a tier is chosen.
        if self._generating:
            return
        NewGameDialog(self.root, self.settings["difficulty"],
                      on_choose=self._start_new_game)

    def _start_new_game(self, difficulty):
        # Persist the choice so the picker defaults to it next time, then play.
        self.settings["difficulty"] = difficulty
        save_settings(self.settings)
        self.new_game(difficulty)

    # ---- settings --------------------------------------------------------

    def _mode(self):
        """The effective 'Light'/'Dark' mode this app should paint with, based
        on its own appearance setting (not raw global state)."""
        return _effective_mode(self.settings["appearance"])

    def _apply_settings(self):
        ctk.set_appearance_mode(self.settings["appearance"])
        self._layout_grid()
        self._apply_timer_visibility()

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
        self.newgame_btn.configure(state="disabled")

        def work():
            puzzle, solution, actual, source = sudoku.make_rated_puzzle(
                difficulty, rater=solver.rate, cache=self.cache)
            self.cache.save()           # persist any newly banked puzzles
            self._gen_result = (puzzle, solution, difficulty, actual, source)

        threading.Thread(target=work, daemon=True).start()
        self._poll_generation()

    def _poll_generation(self):
        """Main-thread poll for the worker's result; reschedules itself."""
        if self._gen_result is None:
            self.root.after(50, self._poll_generation)
            return
        puzzle, solution, requested, actual, source = self._gen_result
        self._gen_result = None
        self.puzzle, self.solution = puzzle, solution
        self.selected = None
        self._render_puzzle()
        self._generating = False
        self.newgame_btn.configure(state="normal")
        self.root.title(f"Sudoku \u2014 {requested}")
        if source == "fresh":
            self.status.configure(text=f"New game ({requested}). Good luck!")
        elif source == "cache":
            # Served a saved puzzle of the right tier; let the player regenerate.
            self.status.configure(
                text=f"New game ({requested}, saved puzzle). "
                     f"Tap New Game to try for a fresh one.")
        else:  # fallback
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
        self._reset_history()       # a fresh puzzle starts with empty history
        self._start_timer()         # and a fresh clock

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
        self.selected = rc
        # Related-cell highlighting depends on the whole board relative to the
        # selection, so repaint every cell (cheap at 81).
        self._refresh_board()

    def _refresh_board(self):
        for cell in self.all_cells:
            self._paint_cell(cell)

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
        self._push_undo()
        self.values[rc] = d
        self.solved_cells.discard(rc)   # a player value is no longer "solved"
        # Auto-tidy pencil marks (one setting): clear this cell's own notes and
        # remove the placed digit from every peer's notes (row/column/box). Done
        # regardless of correctness — a mistaken entry is recoverable via undo.
        if self.settings["entry_clears_notes"]:
            self.notes[rc] = []
            self._clear_peer_notes(rc, d)
        # The selection's value just changed, so which cells "match" changes too.
        self._refresh_board()
        self._check_win()

    def _clear_peer_notes(self, rc, d):
        """Remove digit `d` from the pencil notes of every cell sharing rc's
        row, column, or 3x3 box. Cells are repainted by the caller's full
        refresh, so no per-cell redraw is needed here."""
        r, c = rc
        br, bc = (r // BOX) * BOX, (c // BOX) * BOX
        peers = set()
        for i in range(SIZE):
            peers.add((r, i))           # row
            peers.add((i, c))           # column
        for i in range(BOX):
            for j in range(BOX):
                peers.add((br + i, bc + j))  # box
        peers.discard(rc)
        for p in peers:
            notes = self.notes.get(p)
            if notes and d in notes:
                notes.remove(d)

    def _toggle_note(self, rc, d):
        if self.values.get(rc, 0) != 0:
            return                  # a cell with a big value holds no notes
        self._push_undo()
        notes = self.notes.setdefault(rc, [])
        if d in notes:
            notes.remove(d)         # typing an existing note removes it
        else:
            notes.append(d)         # kept in entry order (left-to-right)
        self._paint_cell(rc)
        self._render_cell_text(rc)

    def _clear_cell(self, rc):
        # Staged clear: if a big value is present, remove just the value (which
        # reveals any preserved notes); otherwise clear the notes. Skip entirely
        # when there's nothing to clear, so undo doesn't record a no-op.
        has_value = self.values.get(rc, 0) != 0
        has_notes = bool(self.notes.get(rc))
        if not has_value and not has_notes:
            return
        self._push_undo()
        if has_value:
            self.values[rc] = 0
            self.solved_cells.discard(rc)
        else:
            self.notes[rc] = []
        # Clearing a value can change which cells match the selection.
        self._refresh_board()

    def _check_win(self):
        if self._is_complete() and self._is_correct():
            self._stop_timer()      # freeze the clock on a win
            if self.settings["show_timer"]:
                t = self._format_time(self._timer_elapsed())
                self.status.configure(text=f"Solved in {t}! Well done.")
                msg = f"You solved it in {t}!"
            else:
                self.status.configure(text="Solved! Well done.")
                msg = "You solved it!"
            ConfirmDialog(self.root, "Sudoku", msg,
                          confirm_text="Nice!", cancel_text=None)

    def toggle_notes_mode(self):
        self.notes_mode = not self.notes_mode
        # The button's fill conveys state: accent (filled) on, ghost (outline) off.
        style = _accent_button_kwargs() if self.notes_mode else _ghost_button_kwargs()
        self.notes_btn.configure(text="\u270e Notes", **style)
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

    def hint(self):
        """Reveal the correct value for the selected cell (marked as revealed,
        like a Solve fill). No-op with a status note if there's nothing valid
        to reveal. Undoable; mirrors `entry_clears_notes` for note tidy-up."""
        rc = self.selected
        if rc is None:
            self.status.configure(text="Select a cell first, then tap Hint.")
            return
        if rc in self.given:
            self.status.configure(text="That cell is a given clue.")
            return
        if self.solution is None:
            return
        r, c = rc
        correct = self.solution[r][c]
        if self.values.get(rc, 0) == correct:
            self.status.configure(text="That cell is already correct.")
            return
        self._push_undo()
        self.values[rc] = correct
        self.solved_cells.add(rc)       # revealed, not earned — colored like Solve
        if self.settings["entry_clears_notes"]:
            self.notes[rc] = []
            self._clear_peer_notes(rc, correct)
        self._refresh_board()
        self.status.configure(text="Hint revealed.")
        self._check_win()

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
        # Confirm first so an accidental click can't wipe the puzzle. Uses a
        # custom CTk dialog rather than tkinter.messagebox, which can SIGTRAP on
        # macOS when the canvas is redrawn as a native dialog unwinds.
        ConfirmDialog(
            self.root, "Reveal solution?",
            "This fills in the entire solution and ends the puzzle.\n"
            "You can still undo afterwards.",
            on_confirm=self._do_solve, confirm_text="Reveal", cancel_text="Cancel")

    def _do_solve(self):
        # Revealing ends the attempt, so freeze the clock; one undo snapshot
        # covers the whole reveal.
        self._stop_timer()
        self._push_undo()
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
        self.focus_sink.focus_set()

    # ---- undo / redo -----------------------------------------------------

    def _snapshot(self):
        """Capture the mutable game state as a restorable copy. `given` is
        immutable during play, so it isn't stored."""
        return {
            "values": dict(self.values),
            "notes": {rc: list(ns) for rc, ns in self.notes.items()},
            "solved": set(self.solved_cells),
            "selected": self.selected,
        }

    def _restore_snapshot(self, snap):
        """Install a snapshot as the current state and repaint the board."""
        self.values = dict(snap["values"])
        self.notes = {rc: list(ns) for rc, ns in snap["notes"].items()}
        self.solved_cells = set(snap["solved"])
        self.selected = snap["selected"]
        self._refresh_board()
        # Undo/redo can cross the solved boundary (e.g. undoing a Solve): keep
        # the clock running while the puzzle is unfinished, frozen once it's done.
        self._sync_timer_to_board()

    def _push_undo(self):
        """Record the current state before a mutating action; clears the redo
        stack (a new action invalidates any redo path)."""
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)         # drop oldest to bound memory
        self._redo_stack.clear()
        self._update_history_buttons()

    def _reset_history(self):
        """Drop all undo/redo history (used when a new puzzle loads)."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_history_buttons()

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore_snapshot(self._undo_stack.pop())
        self._update_history_buttons()
        self.status.configure(text="Undid last move.")

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore_snapshot(self._redo_stack.pop())
        self._update_history_buttons()
        self.status.configure(text="Redid move.")

    def _update_history_buttons(self):
        self.undo_btn.configure(
            state="normal" if self._undo_stack else "disabled")
        self.redo_btn.configure(
            state="normal" if self._redo_stack else "disabled")

    def _on_undo_key(self, event):
        self.undo()
        return "break"

    def _on_redo_key(self, event):
        self.redo()
        return "break"

    # ---- timer -----------------------------------------------------------
    # The clock always tracks elapsed time for the current puzzle (via
    # time.monotonic, so it can't drift or be skewed by clock changes); the
    # `show_timer` setting only controls whether the label is visible. Ticking
    # is driven by root.after on the main thread (never a background thread).

    def _timer_elapsed(self):
        """Seconds elapsed on the current puzzle (running or frozen)."""
        e = self._timer_accum
        if self._timer_running and self._timer_start is not None:
            e += time.monotonic() - self._timer_start
        return e

    @staticmethod
    def _format_time(secs):
        secs = int(secs)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _update_timer_label(self):
        self.timer_label.configure(text=self._format_time(self._timer_elapsed()))

    def _cancel_timer_job(self):
        if self._timer_job is not None:
            self.root.after_cancel(self._timer_job)
            self._timer_job = None

    def _tick_timer(self):
        """Refresh the label once a second while the clock runs and is shown.
        The loop only schedules itself when visible; elapsed time is still
        tracked via monotonic when hidden, so toggling on shows the right value."""
        self._timer_job = None
        self._update_timer_label()
        if self._timer_running and self.settings["show_timer"]:
            self._timer_job = self.root.after(1000, self._tick_timer)

    def _start_timer(self):
        """Begin timing a fresh puzzle from zero."""
        self._cancel_timer_job()
        self._timer_accum = 0.0
        self._timer_start = time.monotonic()
        self._timer_running = True
        if self.settings["show_timer"]:
            self._tick_timer()

    def _stop_timer(self):
        """Freeze the clock, banking elapsed time (idempotent)."""
        if self._timer_running:
            self._timer_accum += time.monotonic() - self._timer_start
            self._timer_running = False
            self._timer_start = None
        self._cancel_timer_job()
        self._update_timer_label()

    def _resume_timer(self):
        """Continue a frozen clock from its banked time (idempotent). Unlike
        _start_timer this does NOT reset to zero."""
        if self._timer_running:
            return
        self._timer_start = time.monotonic()
        self._timer_running = True
        if self.settings["show_timer"]:
            self._tick_timer()

    def _sync_timer_to_board(self):
        """Run the clock iff the puzzle is unfinished. Used after undo/redo so
        undoing a Solve/win resumes timing and redoing it freezes again."""
        if self._is_complete() and self._is_correct():
            self._stop_timer()
        else:
            self._resume_timer()

    def _apply_timer_visibility(self):
        """Show or hide the clock per the setting; (re)start the tick loop when
        showing a running clock. Called via _apply_settings (incl. live preview)."""
        if self.settings["show_timer"]:
            self.timer_label.grid()         # restore to its row
            self._update_timer_label()
            if self._timer_running and self._timer_job is None:
                self._tick_timer()
        else:
            self.timer_label.grid_remove()
            self._cancel_timer_job()


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

        # Entry-clears-notes toggle (own cell + peers, combined)
        ctk.CTkLabel(self, text="Entry clears notes").grid(
            row=row, column=0, sticky="w", **pad)
        self.entrynotes_switch = ctk.CTkSwitch(
            self, text="", command=self._toggle_entrynotes)
        if self.draft["entry_clears_notes"]:
            self.entrynotes_switch.select()
        else:
            self.entrynotes_switch.deselect()
        self.entrynotes_switch.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Highlight-related toggle
        ctk.CTkLabel(self, text="Highlight related cells").grid(
            row=row, column=0, sticky="w", **pad)
        self.highlight_switch = ctk.CTkSwitch(
            self, text="", command=self._toggle_highlight)
        if self.draft["highlight_related"]:
            self.highlight_switch.select()
        else:
            self.highlight_switch.deselect()
        self.highlight_switch.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Show-timer toggle
        ctk.CTkLabel(self, text="Show timer").grid(
            row=row, column=0, sticky="w", **pad)
        self.timer_switch = ctk.CTkSwitch(
            self, text="", command=self._toggle_timer)
        if self.draft["show_timer"]:
            self.timer_switch.select()
        else:
            self.timer_switch.deselect()
        self.timer_switch.grid(row=row, column=1, sticky="w", **pad)
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

    def _toggle_entrynotes(self):
        self.draft["entry_clears_notes"] = bool(self.entrynotes_switch.get())
        self._preview()

    def _toggle_highlight(self):
        self.draft["highlight_related"] = bool(self.highlight_switch.get())
        self._preview()

    def _toggle_timer(self):
        self.draft["show_timer"] = bool(self.timer_switch.get())
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
        self.draft["entry_clears_notes"] = DEFAULT_SETTINGS["entry_clears_notes"]
        (self.entrynotes_switch.select if self.draft["entry_clears_notes"]
         else self.entrynotes_switch.deselect)()
        self.draft["highlight_related"] = DEFAULT_SETTINGS["highlight_related"]
        (self.highlight_switch.select if self.draft["highlight_related"]
         else self.highlight_switch.deselect)()
        self.draft["show_timer"] = DEFAULT_SETTINGS["show_timer"]
        (self.timer_switch.select if self.draft["show_timer"]
         else self.timer_switch.deselect)()
        self._preview()

    def _cancel(self):
        if self.on_preview:
            self.on_preview(dict(self._original))
        self.destroy()

    def _save(self):
        self.on_save(self.draft)
        self.destroy()


class NewGameDialog(ctk.CTkToplevel):
    """Modal difficulty picker shown when starting a new game. The current
    difficulty is highlighted (accent); clicking any tier starts that game
    immediately. Cancel (or closing) leaves the current game untouched."""

    def __init__(self, parent, current, on_choose):
        super().__init__(parent)
        self.title("New Game")
        self.resizable(False, False)
        self.on_choose = on_choose

        ctk.CTkLabel(self, text="New Game",
                     font=("Helvetica", 22, "bold")).grid(
                         row=0, column=0, padx=28, pady=(22, 2))
        ctk.CTkLabel(self, text="Choose a difficulty",
                     text_color=("#6a6a6a", "#9a9a9a")).grid(
                         row=1, column=0, padx=28, pady=(0, 14))

        # Current tier renders accent (default CTkButton); the rest are ghost.
        for i, diff in enumerate(DIFFICULTY_ORDER):
            style = {} if diff == current else _ghost_button_kwargs()
            ctk.CTkButton(self, text=diff, width=240, height=42, corner_radius=8,
                          command=lambda d=diff: self._choose(d),
                          **style).grid(row=2 + i, column=0, padx=28, pady=4)

        ctk.CTkButton(self, text="Cancel", width=240, height=34, corner_radius=8,
                      command=self.destroy, **_ghost_button_kwargs()).grid(
                          row=2 + len(DIFFICULTY_ORDER), column=0,
                          padx=28, pady=(14, 22))

        self.transient(parent)
        self.after(10, self.grab_set)   # CTkToplevel must map before grabbing
        self.update_idletasks()
        self._center_on(parent)

    def _center_on(self, parent):
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 3}")

    def _choose(self, diff):
        self.destroy()
        self.on_choose(diff)


class ConfirmDialog(ctk.CTkToplevel):
    """Small modal dialog. With a cancel button it's a yes/no confirm (calls
    on_confirm() only if confirmed); with cancel_text=None it's a one-button
    acknowledgement. Replaces tkinter.messagebox, which can crash on macOS when
    the board is redrawn as the native dialog unwinds."""

    def __init__(self, parent, title, message, on_confirm=None,
                 confirm_text="OK", cancel_text="Cancel"):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.on_confirm = on_confirm

        ctk.CTkLabel(self, text=message, wraplength=340,
                     justify="center").grid(row=0, column=0, padx=28,
                                            pady=(24, 18))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=1, column=0, pady=(0, 22))
        col = 0
        if cancel_text is not None:
            ctk.CTkButton(btns, text=cancel_text, width=110, height=34,
                          corner_radius=8, command=self.destroy,
                          **_ghost_button_kwargs()).grid(row=0, column=col, padx=6)
            col += 1
        confirm = ctk.CTkButton(btns, text=confirm_text, width=110, height=34,
                                corner_radius=8, command=self._confirm)
        confirm.grid(row=0, column=col, padx=6)

        self.bind("<Escape>", lambda e: self.destroy())
        self.transient(parent)
        self.after(10, self.grab_set)   # CTkToplevel must map before grabbing
        self.update_idletasks()
        self._center_on(parent)

    def _center_on(self, parent):
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 3}")

    def _confirm(self):
        self.destroy()
        if self.on_confirm is not None:
            self.on_confirm()


def main():
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    SudokuGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()