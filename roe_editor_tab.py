#!/usr/bin/env python3
"""El-Fish ROE Fish Generator -- load a .ROE, dial in the size/shape genes with sliders, and save
the result as a new .ROE.

Each slider shows a real preview image of a reference fish at that exact value, one gene at a
time -- not a live combination of every slider together (that would mean pre-rendering every
possible combination of genes, an astronomical number of images), so treat the preview as "here's
what this one gene does on its own," and judge the combined look by loading the generated .ROE
into El-Fish.
"""
import os
import sys
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from gene_data import GENES, SECTIONS
from roe_io import RoeFile, ROE_SIZE

APP_TITLE = "El-Fish ROE Fish Generator"
CONFIG_FILENAME = "fish_generator_config.json"

PREVIEW_BOX = (420, 230)   # max area the preview image is fit into
LIST_PANEL_WIDTH = 640
PREVIEW_PANEL_WIDTH = 460

# -- dark theme palette (matches the rest of the El-Fish toolkit) --------------------------
WINDOW_BG = "#1c1c1e"
PANEL_BG = "#242426"
CARD_BG = "#2c2c2e"
CARD_BORDER = "#3d3d40"
ROW_BORDER_FOCUS = "#5a8fd6"
TEXT_PRIMARY = "#eaeaea"
TEXT_SECONDARY = "#9a9a9c"
TEXT_MUTED = "#707072"
ACCENT = "#5a8fd6"
GOOD = "#5fd37a"
AMBER = "#e0a542"
BAD = "#e0664a"
BUTTON_BG = "#3a3a3d"
BUTTON_ACTIVE_BG = "#48484c"
BUTTON_DISABLED_FG = "#6a6a6c"
PORTRAIT_BG = (33, 36, 40)


def _config_path():
    # Next to the .exe when frozen by PyInstaller -- __file__ would otherwise point into the
    # temporary extraction folder PyInstaller unpacks to on each run, which is wiped afterwards,
    # so anything written there (like the last-used folder) would silently fail to be remembered
    # from one run to the next.
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, CONFIG_FILENAME)


def load_config():
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def fit_image(img, box):
    w, h = img.size
    bw, bh = box
    scale = min(bw / w, bh / h)
    if scale < 1:
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        img = img.resize(new_size, Image.NEAREST)
    return img


def resource_path(*parts):
    """Resolve a path bundled alongside this script -- whether running from source or from a
    PyInstaller --onefile exe, where bundled data is unpacked to a temp folder at sys._MEIPASS."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


PREVIEWS_DIR = resource_path("previews")


class GeneRow:
    """One gene's slider + its bookkeeping. Owns no image state -- the shared preview panel handles
    that for whichever row last had focus."""

    def __init__(self, parent, gene, on_change, on_focus, on_reset):
        self.gene = gene
        self.offset = gene["offset"]
        self.min_value = gene["safe_min"]
        self.max_value = gene["safe_max"]
        self.on_change = on_change
        self.on_focus = on_focus
        self.on_reset = on_reset
        # The value this offset had in the file that's currently loaded, as set by
        # set_loaded_value() -- None until a fish is actually loaded. The per-row reset button
        # compares the live value against this to decide whether it's enabled/highlighted.
        self.loaded_value = None
        # A handful of genes are effectively flags/switches -- only 2-5 values across the whole
        # safe range ever produce a visually different result (confirmed by pixel-diffing every
        # bundled preview image). For those, the slider is restricted to exactly those "stop"
        # values instead of the full continuous range, and it moves over the index into this list
        # rather than over raw byte values.
        discrete_values = gene.get("discrete_values")
        self.is_discrete = bool(discrete_values) and len(discrete_values) >= 2
        self.discrete_values = list(discrete_values) if self.is_discrete else None

        default_value = self.discrete_values[0] if self.is_discrete else self.min_value
        self.var = tk.IntVar(value=default_value)
        self.entry_var = tk.StringVar(value=str(default_value))
        self._suppress = False

        self.frame = tk.Frame(parent, bg=CARD_BG, highlightthickness=1,
                               highlightbackground=CARD_BORDER, highlightcolor=CARD_BORDER)
        self.frame.pack(fill="x", padx=10, pady=5)

        top = tk.Frame(self.frame, bg=CARD_BG)
        top.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(top, text=f"0x{self.offset:03X}", bg=CARD_BG, fg=ACCENT,
                 font=("Consolas", 10, "bold")).pack(side="left")
        tk.Label(top, text="  " + gene["label"], bg=CARD_BG, fg=TEXT_PRIMARY,
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        desc = tk.Label(self.frame, text=gene["changes"], bg=CARD_BG, fg=TEXT_SECONDARY,
                         font=("Segoe UI", 9), wraplength=LIST_PANEL_WIDTH - 90, justify="left",
                         anchor="w")
        desc.pack(fill="x", padx=10, pady=(2, 6))

        slider_row = tk.Frame(self.frame, bg=CARD_BG)
        slider_row.pack(fill="x", padx=10, pady=(0, 10))
        if self.is_discrete:
            self.scale = ttk.Scale(slider_row, from_=0, to=len(self.discrete_values) - 1,
                                    orient="horizontal", command=self._on_scale)
        else:
            self.scale = ttk.Scale(slider_row, from_=self.min_value, to=self.max_value,
                                    orient="horizontal", command=self._on_scale)
        self.scale.pack(side="left", fill="x", expand=True)
        self.scale.bind("<Button-1>", lambda e: self.on_focus(self))

        self.entry = tk.Entry(slider_row, textvariable=self.entry_var, width=4, bg=BUTTON_BG,
                               fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY, relief="flat",
                               justify="center")
        self.entry.pack(side="left", padx=(8, 0))
        self.entry.bind("<Return>", self._on_entry_commit)
        self.entry.bind("<FocusOut>", self._on_entry_commit)
        self.entry.bind("<FocusIn>", lambda e: self.on_focus(self))

        # Per-gene reset -- greyed out and inert until this byte's live value actually differs
        # from what was loaded from the file, at which point it lights up amber. Restores this
        # gene (and any sibling row sharing the same offset, see gene_data.py) to exactly the
        # value the file had, even if that value is itself outside the normal safe range/stops.
        self.reset_btn = tk.Button(slider_row, text="Reset", command=self._on_reset_click,
                                    bg=BUTTON_BG, fg=BUTTON_DISABLED_FG,
                                    activebackground=BUTTON_ACTIVE_BG, activeforeground=TEXT_PRIMARY,
                                    disabledforeground=BUTTON_DISABLED_FG, relief="flat",
                                    cursor="hand2", font=("Segoe UI", 8), padx=6, pady=1,
                                    state="disabled")
        self.reset_btn.pack(side="left", padx=(6, 0))

        note_text = f"Range: {gene['safe_note']}"
        if self.is_discrete:
            stops = ", ".join(str(v) for v in self.discrete_values)
            note_text += f"  |  This gene only has distinct settings at: {stops}"
        note = tk.Label(self.frame, text=note_text, bg=CARD_BG,
                         fg=TEXT_MUTED, font=("Segoe UI", 8), wraplength=LIST_PANEL_WIDTH - 90,
                         justify="left", anchor="w")
        note.pack(fill="x", padx=10, pady=(0, 8), anchor="w")

    def _nearest_discrete(self, value):
        """Snap an arbitrary byte value to the closest allowed stop -- used when a loaded .ROE
        file's real byte doesn't land exactly on one of this gene's stops, so we can still show
        an honest closest-match rather than refusing to display it."""
        return min(self.discrete_values, key=lambda v: abs(v - value))

    def _on_scale(self, value_str):
        # ttk.Scale fires its `command` for a PROGRAMMATIC .set() too, not just a user drag -- so
        # set_value()'s own `self.scale.set(...)` call below would otherwise re-enter this method
        # and fire on_change all over again (and, now that on_change can update sibling rows that
        # share this same offset, recurse forever between them). set_value flips `_suppress` on
        # for the exact duration of that call, so bail out here rather than treat it as new input.
        if self._suppress:
            return
        if self.is_discrete:
            idx = int(round(float(value_str)))
            idx = max(0, min(len(self.discrete_values) - 1, idx))
            value = self.discrete_values[idx]
        else:
            value = int(round(float(value_str)))
        self.set_value(value, from_slider=True)
        self.on_focus(self)
        self.on_change(self.offset, value)

    def _on_entry_commit(self, _event=None):
        try:
            value = int(self.entry_var.get())
        except ValueError:
            value = self.var.get()
        self.set_value(value, from_slider=False)
        self.on_focus(self)
        self.on_change(self.offset, self.var.get())

    def set_value(self, value, from_slider):
        if self.is_discrete:
            value = self._nearest_discrete(value)
        else:
            value = max(self.min_value, min(self.max_value, value))
        self._suppress = True
        self.var.set(value)
        self.entry_var.set(str(value))
        if not from_slider:
            if self.is_discrete:
                self.scale.set(self.discrete_values.index(value))
            else:
                self.scale.set(value)
        self._suppress = False
        self._update_reset_btn()
        return value

    def is_out_of_range(self, value):
        if self.is_discrete:
            return value not in self.discrete_values
        return value < self.min_value or value > self.max_value

    def set_loaded_value(self, value):
        """Used only for loading a .ROE file and for Reset: keeps the fish's real byte exactly as
        it is, even when it falls outside this gene's normal safe range (or, for a discrete gene,
        isn't one of its known stops) -- we never silently rewrite a fish's actual data just to fit
        the slider's usual bounds. The slider widget itself can only show a thumb position within
        its own track, so that thumb clamps visually to whichever end is closest, but the entry box,
        the value Generate writes, and the preview lookup all use the true unmodified byte."""
        self.loaded_value = value
        self._suppress = True
        self.var.set(value)
        self.entry_var.set(str(value))
        if self.is_discrete:
            nearest = self._nearest_discrete(value)
            self.scale.set(self.discrete_values.index(nearest))
        else:
            display_value = max(self.min_value, min(self.max_value, value))
            self.scale.set(display_value)
        self._suppress = False
        self._update_reset_btn()
        return value

    def _update_reset_btn(self):
        """Grey/inert when there's nothing to reset to yet, or the live value already matches what
        was loaded; amber and clickable the moment this byte diverges from the loaded file."""
        if self.loaded_value is None or self.var.get() == self.loaded_value:
            self.reset_btn.configure(state="disabled", bg=BUTTON_BG, fg=BUTTON_DISABLED_FG)
        else:
            self.reset_btn.configure(state="normal", bg=AMBER, fg="#1c1c1e")

    def _on_reset_click(self):
        if self.loaded_value is None:
            return
        self.on_focus(self)
        self.on_reset(self.offset)

    def set_focused(self, focused):
        color = ROW_BORDER_FOCUS if focused else CARD_BORDER
        self.frame.configure(highlightbackground=color, highlightcolor=color)


class FishGeneratorApp:
    def __init__(self, root):
        # `root` is the actual Tk() window when this app runs standalone, or a plain Frame when
        # it's embedded as one tab of a bigger app -- only the former supports title/geometry, so
        # those are skipped rather than raising when embedded.
        self.root = root
        if isinstance(root, tk.Tk):
            self.root.title(APP_TITLE)
            self.root.geometry("1180x760")
            self.root.minsize(900, 600)
        self.root.configure(bg=WINDOW_BG)

        self._style_ttk()

        self.cfg = load_config()
        self.roe = None
        self.loaded_values = {}
        # The mutant flag lives at 0x000-0x001, ahead of the gene-data region -- it's a 2-byte
        # header field (any non-zero byte there flags the fish as a mutant in-game), not a "gene"
        # the web guide lists, so it gets its own toggle button rather than a GeneRow/slider.
        self.mutant_on = False
        self.loaded_mutant = None          # None until a file is loaded
        self.loaded_mutant_bytes = (0, 0)  # the file's own two bytes, preserved exactly if untouched
        # offset -> list of GeneRow. Usually one row per offset, but a handful of bytes do
        # double duty and show up under two different headings in the guide (e.g. a Shape
        # slider that's also the fin's on/off switch) -- each gets its own row/widget here, and
        # they're kept in sync at runtime since they're really the same byte (see on_gene_changed).
        self.rows = {}
        self.focused_row = None
        self._preview_after_id = None
        self._img_ref = None

        self._build_toolbar()
        self._build_body()
        self._set_generate_enabled(False)
        self._update_mutant_btn()
        if not os.path.isdir(PREVIEWS_DIR):
            self._set_status("Note: the bundled previews/ folder is missing -- sliders and Generate "
                              "still work, you just won't see preview images.")

        # Show something in the preview panel from the moment the window opens, instead of a
        # blank box until the user touches a slider -- the first gene row, at its own default
        # value, is as good a starting point as any (moving any slider immediately replaces it).
        if self.rows:
            self.focus_row(next(iter(self.rows.values()))[0])

    # -- chrome ---------------------------------------------------------------------------
    def _style_ttk(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TScale", background=CARD_BG, troughcolor=BUTTON_BG)
        style.configure("Horizontal.TScale", background=CARD_BG)

    def _make_button(self, parent, text, command, primary=False, small=False):
        fg = "#ffffff" if primary else TEXT_PRIMARY
        bg = ACCENT if primary else BUTTON_BG
        active_bg = "#6fa0e0" if primary else BUTTON_ACTIVE_BG
        b = tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=active_bg,
                      activeforeground=fg, relief="flat", cursor="hand2",
                      font=("Segoe UI", 9 if small else 10),
                      padx=8 if small else 14, pady=3 if small else 6,
                      disabledforeground=BUTTON_DISABLED_FG)
        return b

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=PANEL_BG)
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=PANEL_BG)
        inner.pack(fill="x", padx=14, pady=10)

        self.load_btn = self._make_button(inner, "Load ROE...", self.on_load_roe)
        self.load_btn.pack(side="left")
        self.roe_label = tk.Label(inner, text="No file loaded", bg=PANEL_BG, fg=TEXT_SECONDARY,
                                   font=("Segoe UI", 9))
        self.roe_label.pack(side="left", padx=(10, 0))

        self.generate_btn = self._make_button(inner, "Generate ROE...", self.on_generate, primary=True)
        self.generate_btn.pack(side="right")
        self.reset_btn = self._make_button(inner, "Reset All", self.on_reset_all)
        self.reset_btn.pack(side="right", padx=(0, 8))
        # Toggles the 0x000-0x001 mutant-flag header field -- grey when off, blue when on, and (once
        # a file is loaded) amber whenever it no longer matches what the loaded file actually had,
        # the same "changed" language the per-gene Reset buttons use.
        self.mutant_btn = self._make_button(inner, "Mutant: OFF", self.on_toggle_mutant)
        self.mutant_btn.pack(side="right", padx=(0, 8))

        self.status_label = tk.Label(bar, text="", bg=PANEL_BG, fg=TEXT_SECONDARY,
                                      font=("Segoe UI", 8), anchor="w", justify="left")
        self.status_label.pack(fill="x", padx=14, pady=(0, 10))
        self.root.bind("<Configure>", self._on_root_resize)

    def _on_root_resize(self, _event=None):
        width = self.root.winfo_width()
        if width > 100:
            self.status_label.configure(wraplength=width - 28)

    def _make_scrollable(self, parent):
        """A canvas+frame scroll region that only grabs the mouse wheel while the pointer is
        actually over it -- so each tab scrolls independently and switching tabs never leaves a
        stale wheel binding pointed at a hidden tab's canvas."""
        outer = tk.Frame(parent, bg=WINDOW_BG)
        canvas = tk.Canvas(outer, bg=WINDOW_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=WINDOW_BG)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return outer, inner

    def _build_gene_tab(self, parent, section):
        outer, inner = self._make_scrollable(parent)
        genes_here = [g for g in GENES if g["section"] == section]
        if not genes_here:
            tk.Label(inner, text="No genes in this section yet.", bg=WINDOW_BG, fg=TEXT_MUTED,
                     font=("Segoe UI", 9)).pack(padx=14, pady=14, anchor="w")
            return outer

        # Genes are already in the guide's own document order (see gene_data.py) -- group
        # consecutive genes that share a (subsection, group) pair under one header instead of
        # sorting into a fixed category list, so the tool's grouping/order matches the guide's
        # <h3> headings and collapsible sub-sections exactly, whatever they happen to be.
        prev_key = None
        for gene in genes_here:
            key = (gene.get("subsection"), gene.get("group"))
            if key != prev_key:
                self._build_section_header(inner, gene.get("subsection"), gene.get("group"))
                prev_key = key
            row = GeneRow(inner, gene, on_change=self.on_gene_changed, on_focus=self.focus_row,
                          on_reset=self.on_row_reset)
            self.rows.setdefault(gene["offset"], []).append(row)
        return outer

    def _build_section_header(self, parent, subsection, group):
        """Mirrors the guide's own two-tier heading: a bold <h3>-style header for the subsection
        (Shape/Colour/Pattern/Enable-Disable) when there is one, then the finer collapsible-group
        title (Dorsal fin, Body Shape, Eyes, ...) beneath it -- or just the group title alone when
        the guide has no subsection heading for this part (Body, Other)."""
        header = tk.Frame(parent, bg=WINDOW_BG)
        header.pack(fill="x", padx=10, pady=(14, 2))
        if subsection and subsection != group:
            tk.Label(header, text=subsection, bg=WINDOW_BG, fg=TEXT_SECONDARY,
                     font=("Segoe UI", 11, "bold")).pack(side="left")
            tk.Frame(header, bg=CARD_BORDER, height=1).pack(side="left", fill="x", expand=True,
                                                             padx=(10, 0), pady=(9, 0))
            if group:
                sub = tk.Frame(parent, bg=WINDOW_BG)
                sub.pack(fill="x", padx=10, pady=(2, 4))
                tk.Label(sub, text=group, bg=WINDOW_BG, fg=TEXT_MUTED,
                         font=("Segoe UI", 9, "bold")).pack(side="left")
        else:
            text = group or subsection or ""
            tk.Label(header, text=text, bg=WINDOW_BG, fg=TEXT_SECONDARY,
                     font=("Segoe UI", 11, "bold")).pack(side="left")
            tk.Frame(header, bg=CARD_BORDER, height=1).pack(side="left", fill="x", expand=True,
                                                             padx=(10, 0), pady=(9, 0))

    def _build_body(self):
        body = tk.Frame(self.root, bg=WINDOW_BG)
        body.pack(fill="both", expand=True)

        # -- left: tabbed, scrollable gene lists --
        list_outer = tk.Frame(body, bg=WINDOW_BG, width=LIST_PANEL_WIDTH)
        list_outer.pack(side="left", fill="both", expand=False)
        list_outer.pack_propagate(False)

        style = ttk.Style()
        style.configure("Fish.TNotebook", background=WINDOW_BG, borderwidth=0, tabmargins=(4, 6, 4, 0))
        style.configure("Fish.TNotebook.Tab", background=BUTTON_BG, foreground=TEXT_SECONDARY,
                         padding=(16, 8), font=("Segoe UI", 10), borderwidth=0)
        style.map("Fish.TNotebook.Tab",
                  background=[("selected", CARD_BG)], foreground=[("selected", TEXT_PRIMARY)],
                  # Same fix as the outer Suite notebook -- pin both "-expand" and "-padding" to
                  # identical values regardless of selected state, since different Tk/theme
                  # builds grow the selected tab through one or the other and leaving either one
                  # unpinned lets the grey, inactive tab end up a different size again.
                  expand=[("selected", [0, 0, 0, 0]), ("!selected", [0, 0, 0, 0])],
                  padding=[("selected", (16, 8)), ("!selected", (16, 8))])

        notebook = ttk.Notebook(list_outer, style="Fish.TNotebook")
        notebook.pack(fill="both", expand=True)
        for section in SECTIONS:
            tab = self._build_gene_tab(notebook, section)
            notebook.add(tab, text=section)

        # -- right: preview panel --
        preview_outer = tk.Frame(body, bg=PANEL_BG, width=PREVIEW_PANEL_WIDTH)
        preview_outer.pack(side="right", fill="both", expand=True)
        preview_outer.pack_propagate(False)

        pad = dict(padx=16)
        tk.Label(preview_outer, text="Preview", bg=PANEL_BG, fg=TEXT_SECONDARY,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad, pady=(16, 4))
        self.preview_title = tk.Label(preview_outer, text="Select a slider to preview its effect",
                                       bg=PANEL_BG, fg=TEXT_PRIMARY, font=("Segoe UI", 11, "bold"),
                                       wraplength=PREVIEW_PANEL_WIDTH - 60, justify="left")
        self.preview_title.pack(anchor="w", **pad)

        image_holder = tk.Frame(preview_outer, bg=CARD_BG, width=PREVIEW_BOX[0] + 20,
                                 height=PREVIEW_BOX[1] + 20)
        image_holder.pack_propagate(False)
        image_holder.pack(**pad, pady=10)
        self.preview_image_label = tk.Label(image_holder, bg=CARD_BG)
        self.preview_image_label.pack(fill="both", expand=True)

        self.preview_value_label = tk.Label(preview_outer, text="", bg=PANEL_BG, fg=ACCENT,
                                             font=("Consolas", 10, "bold"))
        self.preview_value_label.pack(anchor="w", **pad)

        self.preview_detail = tk.Label(preview_outer, text="", bg=PANEL_BG, fg=TEXT_SECONDARY,
                                        font=("Segoe UI", 9), wraplength=PREVIEW_PANEL_WIDTH - 60,
                                        justify="left")
        self.preview_detail.pack(anchor="w", **pad, pady=(6, 0))

        caveat = ("Note: this shows the isolated effect of this one gene on a reference fish, with "
                  "every other gene left at its default -- not a live combination of everything "
                  "you've set. Judge the combined look by loading the generated .ROE into El-Fish.")
        tk.Label(preview_outer, text=caveat, bg=PANEL_BG, fg=TEXT_MUTED, font=("Segoe UI", 8),
                 wraplength=PREVIEW_PANEL_WIDTH - 60, justify="left").pack(
            anchor="w", **pad, pady=(16, 16), side="bottom")

    # -- ROE loading ------------------------------------------------------------------------
    def on_load_roe(self):
        initial_dir = self.cfg.get("last_roe_dir") or None
        path = filedialog.askopenfilename(title="Choose a .ROE file",
                                           initialdir=initial_dir,
                                           filetypes=[("ROE files", "*.ROE *.roe"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.roe = RoeFile.load(path)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Couldn't read that file:\n{e}")
            return

        warning = self.roe.size_warning
        if warning:
            messagebox.showwarning(APP_TITLE, warning)

        self.loaded_values = {}
        out_of_range_count = 0
        # Iterate unique offsets (self.rows), not GENES -- a handful of offsets have two GENES
        # entries (see gene_data.py) and would otherwise be counted twice here.
        for off, rows in self.rows.items():
            value = self.roe.get(off) if off < len(self.roe.data) else 0
            for row in rows:
                row.set_loaded_value(value)
            self.loaded_values[off] = value
            if rows[0].is_out_of_range(value):
                out_of_range_count += 1

        b0 = self.roe.data[0] if len(self.roe.data) > 0 else 0
        b1 = self.roe.data[1] if len(self.roe.data) > 1 else 0
        self.loaded_mutant_bytes = (b0, b1)
        self.mutant_on = bool(b0 or b1)
        self.loaded_mutant = self.mutant_on
        self._update_mutant_btn()

        self.roe_label.configure(text=os.path.basename(path), fg=TEXT_PRIMARY)
        self.cfg["last_roe_dir"] = os.path.dirname(path)
        save_config(self.cfg)
        self._set_generate_enabled(True)
        status = (f"Loaded {os.path.basename(path)} ({len(self.roe.data)} bytes) -- "
                  f"sliders set to this fish's current gene values.")
        if out_of_range_count:
            status += (f" {out_of_range_count} value(s) fall outside a slider's normal safe range "
                       f"or known stops -- they're kept exactly as loaded (the slider itself just "
                       f"shows its thumb at the nearest end it can reach). Generate will still save "
                       f"them at that exact value, and Reset restores them too, unless you move the "
                       f"slider yourself.")
        self._set_status(status)

    def on_reset_all(self):
        if not self.roe:
            return
        for off, value in self.loaded_values.items():
            for row in self.rows[off]:
                row.set_loaded_value(value)
        self.mutant_on = self.loaded_mutant
        self._update_mutant_btn()
        self._set_status("All sliders reset to the loaded file's values.")
        if self.focused_row:
            self._schedule_preview_update(self.focused_row)

    def on_toggle_mutant(self):
        if self.loaded_mutant is None:
            return
        self.mutant_on = not self.mutant_on
        self._update_mutant_btn()
        self._set_status(f"Mutant flag set to {'ON' if self.mutant_on else 'OFF'} -- takes effect "
                          f"the next time you click Generate ROE...")

    def _update_mutant_btn(self):
        text = "Mutant: ON" if self.mutant_on else "Mutant: OFF"
        if self.loaded_mutant is None:
            self.mutant_btn.configure(text=text, state="disabled", bg=BUTTON_BG,
                                       fg=BUTTON_DISABLED_FG)
            return
        if self.mutant_on != self.loaded_mutant:
            bg, fg = AMBER, "#1c1c1e"
        elif self.mutant_on:
            bg, fg = ACCENT, "#ffffff"
        else:
            bg, fg = BUTTON_BG, TEXT_PRIMARY
        self.mutant_btn.configure(text=text, state="normal", bg=bg, fg=fg)

    def on_row_reset(self, offset):
        """A single gene's own reset button -- restores just this byte (and any sibling row that
        shares it, see gene_data.py) to exactly what the loaded file had, leaving every other
        gene's own edits untouched."""
        if offset not in self.loaded_values:
            return
        value = self.loaded_values[offset]
        for row in self.rows[offset]:
            row.set_loaded_value(value)
        self._set_status(f"0x{offset:03X} reset to its loaded value ({value}).")
        if self.focused_row and self.focused_row.offset == offset:
            self._schedule_preview_update(self.focused_row)

    # -- preview images -----------------------------------------------------------------------
    def focus_row(self, row):
        if self.focused_row is row:
            return
        if self.focused_row:
            self.focused_row.set_focused(False)
        self.focused_row = row
        row.set_focused(True)
        self._schedule_preview_update(row)

    def on_gene_changed(self, offset, value):
        # A handful of offsets have more than one slider (see gene_data.py) -- they're the same
        # underlying byte, so whichever one the user just moved, every row sharing that offset
        # needs to show the same value, including ones sitting on a tab the user isn't currently
        # looking at.
        for row in self.rows.get(offset, []):
            row.set_value(value, from_slider=False)
        if self.focused_row and self.focused_row.offset == offset:
            self._schedule_preview_update(self.focused_row)

    def _schedule_preview_update(self, row):
        if self._preview_after_id:
            self.root.after_cancel(self._preview_after_id)
        self._preview_after_id = self.root.after(30, lambda: self._update_preview(row))

    def _image_path_for(self, offset, value):
        folder = os.path.join(PREVIEWS_DIR, f"0x{offset:03X}_full_range")
        fname = f"{offset:03X}{value:02X}.png"
        return os.path.join(folder, fname)

    def _previous_available(self, offset, value):
        """To cut down the bundled download, most genes only ship a preview PNG for every second
        value (plus any value where the picture actually changes) -- when the exact value has no
        image, show the previous (next-lower) value's image rather than hunting in both
        directions, so the preview never jumps ahead of where the slider actually is. Every
        gene's lowest safe value always has an image, so this always finds something as long as
        `value` is within the gene's safe range."""
        folder = os.path.join(PREVIEWS_DIR, f"0x{offset:03X}_full_range")
        if not os.path.isdir(folder):
            return None, None
        for candidate in range(value, -1, -1):
            path = os.path.join(folder, f"{offset:03X}{candidate:02X}.png")
            if os.path.isfile(path):
                return path, candidate
        return None, None

    def _update_preview(self, row):
        # Read the gene/offset/value straight off the row that's actually focused, rather than
        # looking them up by offset -- an offset with two rows (see gene_data.py) has two
        # different gene dicts (different label/description), and only the specific row the user
        # clicked knows which one it is.
        gene = row.gene
        offset = row.offset
        value = row.var.get()

        self.preview_title.configure(text=f"0x{offset:03X} -- {gene['label']}")
        self.preview_value_label.configure(text=f"Current value: {value}")
        detail_parts = [gene["changes"]]
        if gene.get("low") is not None and gene.get("high") is not None:
            detail_parts.append(f"Low: {gene['low']}\nHigh: {gene['high']}")
        if gene.get("real_range"):
            detail_parts.append(f"Real fish natural range: {gene['real_range']}")
        detail = "\n\n".join(detail_parts)
        self.preview_detail.configure(text=detail)

        exact_path = self._image_path_for(offset, value)
        path = exact_path if os.path.isfile(exact_path) else None
        shown_value = value
        if path is None:
            path, shown_value = self._previous_available(offset, value)

        if path is None:
            self.preview_image_label.configure(
                image="", text="No bundled preview image found for this gene", fg=TEXT_MUTED)
            self._img_ref = None
            return

        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            self.preview_image_label.configure(image="", text=f"Couldn't open preview image:\n{e}",
                                                fg=TEXT_MUTED)
            self._img_ref = None
            return

        bg = Image.new("RGB", img.size, PORTRAIT_BG)
        bg.paste(img, mask=img.split()[3])
        bg = fit_image(bg, PREVIEW_BOX)
        photo = ImageTk.PhotoImage(bg)
        self._img_ref = photo  # keep a reference so it isn't garbage-collected
        self.preview_image_label.configure(image=photo, text="")

        if shown_value != value:
            self.preview_value_label.configure(
                text=f"Current value: {value}  (showing the previous available preview, {shown_value})")

    # -- generate -----------------------------------------------------------------------------
    def _set_generate_enabled(self, enabled):
        self.generate_btn.configure(state="normal" if enabled else "disabled")
        self.reset_btn.configure(state="normal" if enabled else "disabled")

    def on_generate(self):
        if not self.roe:
            return
        out = self.roe.clone()
        changed = []
        # Iterate unique offsets (self.rows), not GENES -- a handful of offsets have two GENES
        # entries (see gene_data.py) and would otherwise be written/counted twice here. Their
        # rows are always kept in sync (on_gene_changed), so any one of them holds the value.
        for off, rows in self.rows.items():
            value = rows[0].var.get()
            if off < len(out.data) and out.data[off] != value:
                changed.append((off, out.data[off], value))
            if off < len(out.data):
                out.data[off] = value

        # Mutant flag (0x000-0x001): if the toggle wasn't touched, write the file's own two bytes
        # back exactly as loaded -- untouched genes never get silently rewritten in this tool, and
        # that includes header fields. Only write the canonical ON/OFF pattern once the user has
        # actually flipped the toggle away from what the file had.
        if self.mutant_on == self.loaded_mutant:
            mutant_bytes = self.loaded_mutant_bytes
        else:
            mutant_bytes = (1, 0) if self.mutant_on else (0, 0)
        for off, value in zip((0, 1), mutant_bytes):
            if off < len(out.data) and out.data[off] != value:
                changed.append((off, out.data[off], value))
            if off < len(out.data):
                out.data[off] = value

        base = os.path.splitext(os.path.basename(self.roe.path or "fish.ROE"))[0]
        initial_dir = os.path.dirname(self.roe.path) if self.roe.path else (self.cfg.get("last_roe_dir") or None)
        path = filedialog.asksaveasfilename(title="Save generated ROE as", initialdir=initial_dir,
                                             initialfile=f"{base}_custom.ROE",
                                             defaultextension=".ROE",
                                             filetypes=[("ROE files", "*.ROE"), ("All files", "*.*")])
        if not path:
            return
        try:
            out.save_as(path)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Couldn't save that file:\n{e}")
            return

        self._set_status(f"Saved {os.path.basename(path)} -- {len(changed)} byte(s) changed from the "
                          f"loaded file. Your original file was not touched.")
        messagebox.showinfo(APP_TITLE, f"Saved:\n{path}\n\n{len(changed)} gene byte(s) changed from "
                                        f"the file you loaded.")

    def _set_status(self, text):
        self.status_label.configure(text=text)


def main():
    root = tk.Tk()
    app = FishGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
