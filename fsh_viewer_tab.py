#!/usr/bin/env python3
"""El-Fish Toolkit -- browse your fish portraits and generate swim/idle GIFs, in one app.

Combines the portrait browser and the swim-GIF maker: point it at a folder, look through every
fish's full-size portrait in a grid, click one to select it, and -- if that fish has actually been
animated in El-Fish -- generate its swim and idle GIFs right there in the details panel. A fish
with no animation data gets a plain indicator on its card and a greyed-out Generate button, instead
of failing partway through.
"""
import os
import sys
import glob
import json
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk, ImageSequence

from parse_fsh import parse_header, parse_frame, render_frame, PALETTE
from fsh_to_gif import generate_all_direction_gifs

APP_TITLE = "El-Fish Toolkit"
CONFIG_FILENAME = "toolkit_config.json"

THUMB_BOX = (180, 116)        # image area every card reserves, regardless of a fish's own shape
THUMB_SCALE = 2               # nearest-neighbour upscale applied before fitting to THUMB_BOX
DETAIL_BOX = (260, 170)       # image area in the details panel
DETAIL_SCALE = 4
GIF_PREVIEW_MAX_SIDE = 200
CARD_SIZE = (208, 190)        # every tile is exactly this size, so rows and columns line up
CARD_GAP = 10
CAPTION_MAX_CHARS = 26        # long names/filenames are ellipsised so card height stays fixed
DETAILS_PANEL_WIDTH = 300

# -- dark theme palette -------------------------------------------------------------------
WINDOW_BG = "#1c1c1e"
PANEL_BG = "#242426"
CARD_BG = "#2c2c2e"
CARD_BORDER = "#3d3d40"
CARD_BORDER_HOVER = "#5a8fd6"
CARD_BORDER_SELECTED = "#7fb0ff"
TEXT_PRIMARY = "#eaeaea"
TEXT_SECONDARY = "#9a9a9c"
TEXT_MUTED = "#707072"
ACCENT = "#5a8fd6"
GOOD = "#5fd37a"
AMBER = "#e0a542"
BAD = "#8a8a8d"
BUTTON_BG = "#3a3a3d"
BUTTON_ACTIVE_BG = "#48484c"
BUTTON_DISABLED_FG = "#6a6a6c"
PORTRAIT_BG = (33, 36, 40)    # solid backdrop a transparent portrait is composited onto


# -- .FSH reading ---------------------------------------------------------------------------

def load_portrait(path):
    """Returns a dict describing one .FSH file's portrait for the gallery/details panel, or raises
    ValueError with a human-readable reason. `source` says which part of the file the image came
    from ("detailed portrait", "icon", or "first swim frame") so the UI can flag a fallback.
    `animated` is whether this file has any animation chain at all -- that's the same thing
    fsh_to_gif.py requires, so it's also what gates the Generate GIFs button."""
    data = open(path, "rb").read()
    hdr = parse_header(data)
    animated = bool(hdr.get("anim_off", 0))

    for off_key, source in (("detailed_off", "detailed portrait"), ("icon_off", "icon")):
        off = hdr.get(off_key, 0)
        if off:
            frame = parse_frame(data, off)
            if frame["width"] and frame["height"]:
                img = _render_to_image(data, frame)
                return {"image": img, "name": hdr["name"], "source": source,
                        "native_size": (frame["width"], frame["height"]), "animated": animated}

    if animated:
        frame = parse_frame(data, hdr["anim_off"])
        if frame["width"] and frame["height"]:
            img = _render_to_image(data, frame)
            return {"image": img, "name": hdr["name"], "source": "first swim frame",
                     "native_size": (frame["width"], frame["height"]), "animated": animated}

    raise ValueError("no portrait, icon, or animation frame in this file")


def _render_to_image(data, frame):
    buf, alpha = render_frame(data, frame)
    w, h = frame["width"], frame["height"]
    img = Image.new("RGBA", (w, h))
    pix = img.load()
    for y in range(h):
        row = y * w
        for x in range(w):
            idx = row + x
            if alpha[idx]:
                r, g, b = PALETTE[buf[idx]]
                pix[x, y] = (r, g, b, 255)
            else:
                pix[x, y] = (0, 0, 0, 0)
    return img


def composite_on_bg(img, bg=PORTRAIT_BG):
    canvas = Image.new("RGB", img.size, bg)
    canvas.paste(img, (0, 0), img)
    return canvas


def scale_and_fit(img, box, scale):
    """Nearest-neighbour upscale (keeps the pixel-art look), then shrink to fit inside `box` if
    the upscaled image is still bigger than that."""
    w, h = img.size
    img = img.resize((max(1, w * scale), max(1, h * scale)), Image.NEAREST)
    w, h = img.size
    bw, bh = box
    if w > bw or h > bh:
        ratio = min(bw / w, bh / h)
        img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.NEAREST)
    return img


def ellipsise(text, max_chars=CAPTION_MAX_CHARS):
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


# -- GIF status (the amber/grey/green "GIFs" badge) ------------------------------------------
# Three states: a fish with no animation data can never generate GIFs (grey X); an animated fish
# that hasn't been rendered yet is ready to (amber circle); one that has -- found by checking for
# its default-location swim GIF on disk -- is already done (green tick). This only checks the
# default "<name>_gifs next to the source file" location, not a custom output folder someone
# picked via Change..., so a fish generated somewhere else will still show as "ready" here.

STATUS_BADGE = {           # status -> (short badge text, colour) used on cards and the panel
    "not_capable": ("✕ GIFs", BAD),
    "ready": ("● GIFs", AMBER),
    "done": ("✓ GIFs", GOOD),
}
STATUS_DETAIL_SUFFIX = {
    "not_capable": "no animation data -- animate this fish in El Fish first",
    "ready": "ready to generate",
    "done": "already generated",
}


def default_out_dir_for(path, name):
    return os.path.join(os.path.dirname(path), f"{name}_gifs")


def existing_swim_gif(path, name):
    p = os.path.join(default_out_dir_for(path, name), f"{name}_swim.gif")
    return p if os.path.exists(p) else None


def compute_status(record):
    if not record["animated"]:
        return "not_capable"
    return "done" if existing_swim_gif(record["path"], record["name"]) else "ready"


# -- remembering the last folder used ---------------------------------------------------------
# Stored as a small JSON file next to the script (or next to the .exe, when frozen by PyInstaller)
# so a portable copy of this tool keeps its own memory rather than writing somewhere system-wide.

def _config_path():
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
            json.dump(cfg, f)
    except Exception:
        pass  # best-effort -- a read-only install folder just won't remember, not fatal


def open_in_file_manager(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        pass


class GifPreview(tk.Frame):
    """Cycles an animated GIF's frames on a Label using Pillow."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.label = tk.Label(self, bg=CARD_BG, fg=TEXT_MUTED)
        self.label.pack(fill="both", expand=True)
        self._frames = []
        self._durations = []
        self._job = None
        self._idx = 0

    def clear(self, placeholder=""):
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self._frames = []
        self.label.configure(image="", text=placeholder)

    def load(self, gif_path, max_side=GIF_PREVIEW_MAX_SIDE):
        self.clear()
        try:
            im = Image.open(gif_path)
            frames, durations = [], []
            for frame in ImageSequence.Iterator(im):
                rgba = frame.convert("RGBA")
                bg = Image.new("RGB", rgba.size, PORTRAIT_BG)
                bg.paste(rgba, (0, 0), rgba)
                scale = min(1.0, max_side / max(bg.width, bg.height))
                if scale < 1.0:
                    bg = bg.resize((max(1, int(bg.width * scale)), max(1, int(bg.height * scale))))
                frames.append(ImageTk.PhotoImage(bg))
                durations.append(max(30, frame.info.get("duration", 83)))
            self._frames = frames
            self._durations = durations
            self._idx = 0
            self.label.configure(text="")
            self._tick()
        except Exception:
            self.label.configure(image="", text="(couldn't preview this file)")

    def _tick(self):
        if not self._frames:
            return
        self.label.configure(image=self._frames[self._idx])
        delay = self._durations[self._idx]
        self._idx = (self._idx + 1) % len(self._frames)
        self._job = self.after(delay, self._tick)


class App:
    def __init__(self, root):
        # `root` is the actual Tk() window when this app runs standalone, or a plain Frame when
        # it's embedded as one tab of a bigger app -- only the former supports title/geometry, so
        # those are skipped rather than raising when embedded.
        self.root = root
        if isinstance(root, tk.Tk):
            root.title(APP_TITLE)
            root.geometry("1240x760")
        root.configure(bg=WINDOW_BG)

        self.folder = None
        self.include_subfolders = tk.BooleanVar(value=False)
        self.cards = []                # per-card dict: frame, photo, record, path
        self.columns = 1
        self.card_slot_width = CARD_SIZE[0] + CARD_GAP

        self.selected = None           # currently selected record dict (see load_portrait)
        self.selected_card = None
        self.output_override = None
        self._gen_token = 0            # bumped on every new selection so stale generate results
                                        # from a previous fish never overwrite the panel

        self._style = ttk.Style()
        try:
            self._style.theme_use("clam")
        except tk.TclError:
            pass
        self._style.configure("Dark.Vertical.TScrollbar", background=BUTTON_BG,
                               troughcolor=WINDOW_BG, bordercolor=WINDOW_BG,
                               arrowcolor=TEXT_PRIMARY, lightcolor=BUTTON_BG, darkcolor=BUTTON_BG)
        self._style.map("Dark.Vertical.TScrollbar", background=[("active", BUTTON_ACTIVE_BG)])
        self._style.configure("Dark.Horizontal.TProgressbar", background=ACCENT,
                               troughcolor=CARD_BG, bordercolor=CARD_BG, lightcolor=ACCENT,
                               darkcolor=ACCENT)

        self._build_top_bar()
        self._build_body()
        self._build_status_bar()
        self._restore_last_folder()

    # -- layout ---------------------------------------------------------------------------

    def _build_top_bar(self):
        top = tk.Frame(self.root, bg=PANEL_BG, pady=10, padx=10)
        top.pack(side="top", fill="x")

        self._make_button(top, "Choose folder...", self.choose_folder).pack(side="left")
        self._make_button(top, "Refresh", self.refresh).pack(side="left", padx=(6, 0))

        tk.Checkbutton(top, text="Include subfolders", variable=self.include_subfolders,
                        command=self.refresh, bg=PANEL_BG, fg=TEXT_PRIMARY,
                        selectcolor=CARD_BG, activebackground=PANEL_BG,
                        activeforeground=TEXT_PRIMARY, highlightthickness=0,
                        borderwidth=0).pack(side="left", padx=(14, 0))

        self.folder_label = tk.Label(top, text="No folder chosen yet.", bg=PANEL_BG,
                                      fg=TEXT_SECONDARY, anchor="w")
        self.folder_label.pack(side="left", padx=(14, 0), fill="x", expand=True)

    def _build_body(self):
        body = tk.Frame(self.root, bg=WINDOW_BG)
        body.pack(side="top", fill="both", expand=True)

        # -- gallery (left) --
        gallery = tk.Frame(body, bg=WINDOW_BG)
        gallery.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(gallery, bg=WINDOW_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(gallery, orient="vertical", command=self.canvas.yview,
                                   style="Dark.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.grid_frame = tk.Frame(self.canvas, bg=WINDOW_BG)
        self.grid_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")

        self.grid_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        # Scoped to "pointer is actually over this canvas" rather than bound once for the whole
        # app's lifetime -- this app can now be embedded as one tab alongside others, and a
        # permanent bind_all would make the mouse wheel scroll this gallery even while looking at
        # a different tab entirely.
        self.canvas.bind("<Enter>", lambda e: self._bind_wheel())
        self.canvas.bind("<Leave>", lambda e: self._unbind_wheel())

        # -- details panel (right) --
        panel = tk.Frame(body, bg=PANEL_BG, width=DETAILS_PANEL_WIDTH)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)
        self._build_details_panel(panel)

    def _bind_wheel(self):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    def _unbind_wheel(self):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _build_details_panel(self, panel):
        pad = dict(padx=14)
        tk.Label(panel, text="Details", bg=PANEL_BG, fg=TEXT_PRIMARY,
                 font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(14, 8), **pad)

        self.detail_empty_label = tk.Label(
            panel, text="Select a fish to see details and generate GIFs.", bg=PANEL_BG,
            fg=TEXT_SECONDARY, wraplength=DETAILS_PANEL_WIDTH - 28, justify="left")
        self.detail_empty_label.pack(anchor="w", **pad)

        self.detail_content = tk.Frame(panel, bg=PANEL_BG)
        # not packed until a fish is selected

        img_holder = tk.Frame(self.detail_content, bg=CARD_BG, width=DETAIL_BOX[0],
                               height=DETAIL_BOX[1])
        img_holder.pack_propagate(False)
        img_holder.pack(**pad, pady=(0, 8))
        self.detail_img_label = tk.Label(img_holder, bg=CARD_BG)
        self.detail_img_label.place(relx=0.5, rely=0.5, anchor="center")

        self.detail_name = tk.Label(self.detail_content, text="", bg=PANEL_BG, fg=TEXT_PRIMARY,
                                     font=("TkDefaultFont", 10, "bold"), anchor="w",
                                     wraplength=DETAILS_PANEL_WIDTH - 28, justify="left")
        self.detail_name.pack(anchor="w", **pad)

        self.detail_meta = tk.Label(self.detail_content, text="", bg=PANEL_BG, fg=TEXT_MUTED,
                                     anchor="w", wraplength=DETAILS_PANEL_WIDTH - 28,
                                     justify="left")
        self.detail_meta.pack(anchor="w", **pad, pady=(2, 8))

        self.detail_indicator = tk.Label(self.detail_content, text="", bg=PANEL_BG,
                                          font=("TkDefaultFont", 9, "bold"), anchor="w")
        self.detail_indicator.pack(anchor="w", **pad, pady=(0, 10))

        tk.Frame(self.detail_content, bg=CARD_BORDER, height=1).pack(fill="x", **pad)

        outrow = tk.Frame(self.detail_content, bg=PANEL_BG)
        outrow.pack(fill="x", **pad, pady=(10, 4))
        tk.Label(outrow, text="Output:", bg=PANEL_BG, fg=TEXT_SECONDARY).pack(anchor="w")
        self.detail_out_label = tk.Label(outrow, text="", bg=PANEL_BG, fg=TEXT_MUTED,
                                          wraplength=DETAILS_PANEL_WIDTH - 28, justify="left")
        self.detail_out_label.pack(anchor="w")
        self._make_button(outrow, "Change...", self.choose_out_dir, small=True).pack(
            anchor="w", pady=(4, 0))

        self.generate_btn = self._make_button(self.detail_content, "Generate GIFs",
                                               self.on_generate)
        self.generate_btn.pack(fill="x", **pad, pady=(10, 6))

        self.gen_progress = ttk.Progressbar(self.detail_content, mode="determinate",
                                             style="Dark.Horizontal.TProgressbar")
        self.gen_progress.pack(fill="x", **pad, pady=(0, 4))

        self.gen_status = tk.Label(self.detail_content, text="", bg=PANEL_BG, fg=TEXT_MUTED,
                                    anchor="w", wraplength=DETAILS_PANEL_WIDTH - 28,
                                    justify="left")
        self.gen_status.pack(anchor="w", **pad, pady=(0, 8))

        preview_header = tk.Frame(self.detail_content, bg=PANEL_BG)
        preview_header.pack(fill="x", **pad, pady=(0, 4))
        tk.Label(preview_header, text="Preview", bg=PANEL_BG, fg=TEXT_SECONDARY).pack(side="left")
        # the button this feature is about: sits right on the preview pane itself, so jumping to
        # the generated files never means hunting further down the panel for a separate control
        self.open_folder_btn = self._make_button(preview_header, "📂 Open Folder",
                                                   self.on_open_folder, small=True)
        self.open_folder_btn.pack(side="right")

        preview_holder = tk.Frame(self.detail_content, bg=CARD_BG, width=DETAILS_PANEL_WIDTH - 28,
                                   height=GIF_PREVIEW_MAX_SIDE)
        preview_holder.pack_propagate(False)
        preview_holder.pack(**pad, pady=(0, 14))
        self.gif_preview = GifPreview(preview_holder, bg=CARD_BG)
        self.gif_preview.pack(fill="both", expand=True)
        self.gif_preview.clear()

    def _build_status_bar(self):
        self.status = tk.Label(self.root, text="Pick a folder to get started.", bg=PANEL_BG,
                                fg=TEXT_SECONDARY, anchor="w", padx=10, pady=6)
        self.status.pack(side="bottom", fill="x")

    def _make_button(self, parent, text, command, small=False):
        btn = tk.Button(parent, text=text, command=command, bg=BUTTON_BG, fg=TEXT_PRIMARY,
                         activebackground=BUTTON_ACTIVE_BG, activeforeground=TEXT_PRIMARY,
                         disabledforeground=BUTTON_DISABLED_FG, relief="flat", borderwidth=0,
                         padx=(8 if small else 12), pady=(3 if small else 5),
                         highlightthickness=0, cursor="hand2")
        return btn

    # -- folder handling --------------------------------------------------------------------

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Choose your fish folder")
        if not folder:
            return
        self.folder = folder
        self.folder_label.config(text=folder)
        cfg = load_config()
        cfg["last_folder"] = folder
        save_config(cfg)
        self.refresh()

    def _restore_last_folder(self):
        folder = load_config().get("last_folder")
        if folder and os.path.isdir(folder):
            self.folder = folder
            self.folder_label.config(text=folder)
            self.refresh()

    def refresh(self):
        if not self.folder:
            return
        pattern = "**/*.FSH" if self.include_subfolders.get() else "*.FSH"
        paths = sorted(
            glob.glob(os.path.join(self.folder, pattern), recursive=self.include_subfolders.get()),
            key=lambda p: os.path.basename(p).lower(),
        )
        if not self.include_subfolders.get():
            extra = glob.glob(os.path.join(self.folder, "*.fsh"))
        else:
            extra = glob.glob(os.path.join(self.folder, "**/*.fsh"), recursive=True)
        for p in extra:
            if p not in paths:
                paths.append(p)

        self._populate(paths)

    # -- gallery building ---------------------------------------------------------------------

    def _populate(self, paths):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.cards = []
        self._clear_selection()

        if not paths:
            self.status.config(text="No .FSH files found in this folder.")
            return

        self.status.config(text=f"Loading {len(paths)} file(s)...")
        self.root.update_idletasks()

        loaded, skipped = [], []
        for path in paths:
            try:
                record = load_portrait(path)
                record["path"] = path
            except Exception as e:
                skipped.append((path, str(e)))
                continue
            loaded.append(record)

        self._layout(loaded)

        n_done = sum(1 for r in loaded if r["status"] == "done")
        n_ready = sum(1 for r in loaded if r["status"] == "ready")
        msg = f"{len(loaded)} fish loaded ({n_ready} ready to generate, {n_done} already have GIFs)"
        if skipped:
            msg += f", {len(skipped)} skipped (hover here for details)"
        self.status.config(text=msg)
        if skipped:
            details = "\n".join(f"{os.path.basename(p)}: {err}" for p, err in skipped[:25])
            if len(skipped) > 25:
                details += f"\n... and {len(skipped) - 25} more"
            self.status.bind("<Enter>", lambda e, d=details: print("Skipped files:\n" + d))
        else:
            self.status.unbind("<Enter>")

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.grid_window, width=event.width)
        new_columns = max(1, event.width // self.card_slot_width)
        if new_columns != self.columns:
            self.columns = new_columns
            self._relayout_existing()

    def _relayout_existing(self):
        if not self.cards:
            return
        for i, card in enumerate(self.cards):
            card["frame"].grid_forget()
            card["frame"].grid(row=i // self.columns, column=i % self.columns,
                                padx=CARD_GAP // 2, pady=CARD_GAP // 2)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _layout(self, loaded):
        self.columns = max(1, self.canvas.winfo_width() // self.card_slot_width)
        for i, record in enumerate(loaded):
            display = composite_on_bg(record["image"])
            thumb = scale_and_fit(display, THUMB_BOX, THUMB_SCALE)
            photo = ImageTk.PhotoImage(thumb)

            card = tk.Frame(self.grid_frame, bg=CARD_BG, highlightbackground=CARD_BORDER,
                             highlightthickness=1, width=CARD_SIZE[0], height=CARD_SIZE[1])
            card.pack_propagate(False)
            card.grid_propagate(False)

            img_holder = tk.Frame(card, bg=CARD_BG, width=THUMB_BOX[0], height=THUMB_BOX[1])
            img_holder.pack_propagate(False)
            img_holder.pack(pady=(10, 4))
            img_label = tk.Label(img_holder, image=photo, bg=CARD_BG, cursor="hand2")
            img_label.place(relx=0.5, rely=0.5, anchor="center")

            filename = os.path.basename(record["path"])
            caption = record["name"] if record["name"] == os.path.splitext(filename)[0] \
                else f"{record['name']} ({filename})"
            tk.Label(card, text=ellipsise(caption), bg=CARD_BG, fg=TEXT_PRIMARY,
                     font=("TkDefaultFont", 9, "bold")).pack()

            # the indicator this feature is about: every card says up front whether this fish
            # can have GIFs generated from it (and whether that's already been done), so you
            # don't find out only after selecting it
            record["status"] = compute_status(record)
            badge_text, badge_fg = STATUS_BADGE[record["status"]]
            badge_label = tk.Label(card, text=badge_text, bg=CARD_BG, fg=badge_fg,
                                    font=("TkDefaultFont", 8, "bold"))
            badge_label.pack()

            card.grid(row=i // self.columns, column=i % self.columns,
                      padx=CARD_GAP // 2, pady=CARD_GAP // 2)

            card_entry = {"frame": card, "photo": photo, "record": record,
                          "badge_label": badge_label}
            for widget in (img_label, img_holder, card):
                widget.bind("<Button-1>", lambda e, c=card_entry: self.select_card(c))
                widget.bind("<Enter>", lambda e, c=card: self._hover(c, True))
                widget.bind("<Leave>", lambda e, c=card: self._hover(c, False))
            self.cards.append(card_entry)

    def _hover(self, card, entering):
        if card is self.selected_card:
            return
        card.config(highlightbackground=CARD_BORDER_HOVER if entering else CARD_BORDER)

    # -- selection & details panel --------------------------------------------------------

    def _clear_selection(self):
        self.selected = None
        self.selected_card = None
        self._gen_token += 1
        self.detail_content.pack_forget()
        self.detail_empty_label.pack(anchor="w", padx=14)

    def select_card(self, card_entry):
        if self.selected_card is not None:
            self.selected_card.config(highlightbackground=CARD_BORDER)
        self.selected_card = card_entry["frame"]
        self.selected_card.config(highlightbackground=CARD_BORDER_SELECTED)
        self.selected = card_entry["record"]
        self.output_override = None
        self._gen_token += 1

        self.detail_empty_label.pack_forget()
        self.detail_content.pack(fill="both", expand=True)

        display = composite_on_bg(self.selected["image"])
        big = scale_and_fit(display, DETAIL_BOX, DETAIL_SCALE)
        self._detail_photo = ImageTk.PhotoImage(big)  # keep alive
        self.detail_img_label.configure(image=self._detail_photo)

        filename = os.path.basename(self.selected["path"])
        self.detail_name.configure(text=self.selected["name"])
        w, h = self.selected["native_size"]
        meta = f"{filename}\n{w}x{h} native"
        if self.selected["source"] != "detailed portrait":
            meta += f"\nshown from: {self.selected['source']}"
        self.detail_meta.configure(text=meta)

        # recompute fresh rather than trusting the record's status from when the gallery was
        # scanned -- a fish generated (or re-generated) since then should reflect that right away
        status = self.selected["status"] = compute_status(self.selected)
        badge_text, badge_fg = STATUS_BADGE[status]
        self.detail_indicator.configure(text=f"{badge_text} -- {STATUS_DETAIL_SUFFIX[status]}",
                                         fg=badge_fg)
        self.generate_btn.configure(state="disabled" if status == "not_capable" else "normal")

        self._refresh_out_label()
        self.gen_progress.configure(value=0)
        self.gen_status.configure(text="")

        # feature: a fish that's already been generated starts playing its swim GIF right away,
        # instead of making you click Generate again just to see what you already have
        swim_path = existing_swim_gif(self.selected["path"], self.selected["name"]) \
            if status == "done" else None
        if swim_path:
            self.gif_preview.load(swim_path)
        else:
            self.gif_preview.clear()
        self.open_folder_btn.configure(state="normal" if status == "done" else "disabled")

    def _default_out_dir(self):
        return default_out_dir_for(self.selected["path"], self.selected["name"])

    def choose_out_dir(self):
        if not self.selected:
            return
        start = self.output_override or os.path.dirname(self.selected["path"])
        chosen = filedialog.askdirectory(title="Choose output folder", initialdir=start)
        if chosen:
            self.output_override = chosen
            self._refresh_out_label()

    def _refresh_out_label(self):
        if not self.selected:
            return
        self.detail_out_label.configure(text=self.output_override or self._default_out_dir())

    # -- generate ---------------------------------------------------------------------------

    def on_generate(self):
        if not self.selected or not self.selected["animated"]:
            return
        record = self.selected
        path = record["path"]
        out_dir = self.output_override or self._default_out_dir()
        token = self._gen_token

        self.generate_btn.configure(state="disabled")
        self.open_folder_btn.configure(state="disabled")
        self.gen_status.configure(text="Generating...")
        self.gen_progress.configure(value=0, maximum=2)
        self.gif_preview.clear()

        q = queue.Queue()

        def progress_cb(done, total, result, error):
            q.put({"kind": "step", "done": done, "total": total, "result": result, "error": error})

        def worker():
            try:
                generate_all_direction_gifs(path, out_dir, progress_cb=progress_cb)
            except Exception as e:
                q.put({"kind": "fatal", "error": str(e)})
            q.put({"kind": "done"})

        threading.Thread(target=worker, daemon=True).start()
        self._poll_generate(q, token, out_dir)

    def _poll_generate(self, q, token, out_dir):
        # if the user has since selected a different fish, this generation is still running (the
        # files still get written) but there's nothing of its progress left to show, so stop here
        if token != self._gen_token:
            return
        try:
            results = []
            while True:
                msg = q.get_nowait()
                if msg["kind"] == "done":
                    self.generate_btn.configure(state="normal")
                    record = self.selected  # still the same fish: token check above guarantees it
                    if os.path.isdir(out_dir):
                        self.open_folder_btn.configure(state="normal")
                        first_gif = next((f for f in ("swim", "idle")
                                           if os.path.exists(os.path.join(out_dir, f"{record['name']}_{f}.gif"))),
                                          None)
                        if first_gif:
                            self.gif_preview.load(os.path.join(out_dir, f"{record['name']}_{first_gif}.gif"))
                        self.gen_status.configure(text=f"Done -- wrote to {out_dir}")

                        # refresh the amber/grey/green badge -- both here in the details panel and
                        # back on this fish's card in the gallery -- now that a GIF may exist
                        new_status = record["status"] = compute_status(record)
                        badge_text, badge_fg = STATUS_BADGE[new_status]
                        self.detail_indicator.configure(
                            text=f"{badge_text} -- {STATUS_DETAIL_SUFFIX[new_status]}", fg=badge_fg)
                        for entry in self.cards:
                            if entry["record"] is record:
                                entry["badge_label"].configure(text=badge_text, fg=badge_fg)
                                break
                    else:
                        self.gen_status.configure(text="Nothing was generated -- see above")
                    return
                if msg["kind"] == "fatal":
                    self.generate_btn.configure(state="normal")
                    self.gen_status.configure(text=f"Failed: {msg['error']}")
                    return
                if msg["kind"] == "step":
                    done, total, result, error = msg["done"], msg["total"], msg["result"], msg["error"]
                    if result:
                        results.append(result)
                    if total:
                        self.gen_progress.configure(value=done, maximum=total)
                    if error:
                        self.gen_status.configure(text=f"{error['direction']} ({error['action']}): {error['error']}")
                    else:
                        self.gen_status.configure(text=f"Generating... ({done}/{total})")
        except queue.Empty:
            pass
        self.root.after(50, lambda: self._poll_generate(q, token, out_dir))

    def on_open_folder(self):
        out_dir = self.output_override or (self._default_out_dir() if self.selected else None)
        if out_dir and os.path.isdir(out_dir):
            open_in_file_manager(out_dir)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
