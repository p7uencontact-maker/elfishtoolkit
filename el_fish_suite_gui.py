#!/usr/bin/env python3
"""El-Fish Suite -- the FSH viewer/GIF maker and the ROE gene editor, in one window.

Two tabs, each the same app you already know:
  - "FSH Viewer" (open by default): browse a folder of .FSH portraits and generate swim/idle GIFs.
  - "ROE Editor": load a .ROE save, dial in genes with sliders, export a new .ROE.

Both tabs are built once at startup and never torn down when you switch between them, so whatever
you were doing in one -- the folder you browsed, the fish you had selected, the sliders you'd
already moved -- is still exactly as you left it when you switch back. Each keeps its own
"remembers the last folder" setting, saved next to this program.
"""
import tkinter as tk
from tkinter import ttk

from fsh_viewer_tab import App as FshViewerApp
from roe_editor_tab import FishGeneratorApp

APP_TITLE = "El-Fish Suite"
WINDOW_BG = "#1c1c1e"
CARD_BG = "#2c2c2e"
TEXT_PRIMARY = "#eaeaea"
TEXT_SECONDARY = "#9a9a9c"
BUTTON_BG = "#3a3a3d"


def _style_notebook():
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Suite.TNotebook", background=WINDOW_BG, borderwidth=0,
                     tabmargins=(4, 6, 4, 0))
    style.configure("Suite.TNotebook.Tab", background=BUTTON_BG, foreground=TEXT_SECONDARY,
                     padding=(20, 10), font=("Segoe UI", 10), borderwidth=0)
    style.map("Suite.TNotebook.Tab",
              background=[("selected", CARD_BG)], foreground=[("selected", TEXT_PRIMARY)],
              # Themes normally grow the selected tab a bit past the others (so it looks like
              # it's "popping out" over the pane border below it) -- some do that through
              # "-expand", others through a "-padding" state map, and which one a given Tk/
              # theme build uses isn't consistent across machines. Pin BOTH explicitly to the
              # same value for selected and not-selected so the grey, inactive tab can't end up
              # a different size from the active one no matter which mechanism is in play.
              expand=[("selected", [0, 0, 0, 0]), ("!selected", [0, 0, 0, 0])],
              padding=[("selected", (20, 10)), ("!selected", (20, 10))])


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.configure(bg=WINDOW_BG)
    root.geometry("1280x800")
    root.minsize(1000, 650)

    _style_notebook()

    notebook = ttk.Notebook(root, style="Suite.TNotebook")
    notebook.pack(fill="both", expand=True)

    # FSH Viewer first -- it's the tab that opens by default.
    fsh_tab = tk.Frame(notebook, bg=WINDOW_BG)
    notebook.add(fsh_tab, text="FSH Viewer")
    FshViewerApp(fsh_tab)

    roe_tab = tk.Frame(notebook, bg=WINDOW_BG)
    notebook.add(roe_tab, text="ROE Editor")
    FishGeneratorApp(roe_tab)

    notebook.select(fsh_tab)

    root.mainloop()


if __name__ == "__main__":
    main()
