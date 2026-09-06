# El-Fish Suite

Both El-Fish (Maxis, 1993) tools in one window, as two tabs: the **FSH Viewer** (browse `.FSH`
portraits, generate swim/idle GIFs) and the **ROE Editor** (dial in a fish's genes with sliders and
export a new `.ROE`). Switching tabs never resets what you were doing -- the folder you'd browsed,
the fish you had selected, the sliders you'd already moved are all still there when you come back.

The **FSH Viewer** tab is what's open when you start the program.

## FSH Viewer tab

Point it at a folder and every fish's full-size portrait shows up in a dark, scrollable grid. Each
card carries a **GIFs** badge that says, at a glance, where that fish stands: a grey **✕ GIFs**
means it's never been animated in El-Fish so there's nothing to render; an amber **● GIFs** means
it's animated and ready to generate; a green **✓ GIFs** means its swim/idle GIFs already exist. The
Generate button in the details panel stays greyed out for anything marked ✕, instead of failing
partway through.

Click a fish to select it. The details panel on the right shows it bigger, repeats that same
status, and -- if it's ready or already done -- a **Generate GIFs** button writes a swim loop and
an idle loop to a `<fishname>_gifs` folder next to the source file (or wherever you set with
**Change...**), with a live progress bar. A fish that already has GIFs starts playing its swim
loop automatically the moment you select it, so you can flip through your collection without
clicking Generate again just to see what you've already made. A small **📂 Open Folder** button
sits right on the preview pane itself -- enabled whenever GIFs exist for the selected fish -- so
you can jump straight to the generated files in Explorer without hunting for a button elsewhere.

This tab remembers the last folder you opened and loads it again automatically next time you start
the suite, so you don't have to re-browse to it every session.

> **Use fish saved by El-Fish v1.2 (SVGA).** Portraits and animations saved by other
> versions/resolutions can come out clipped -- a resolution mismatch this tool can't detect or fix,
> it just shows and renders whatever's actually stored in the file.

## ROE Editor tab

Customise an El-Fish `.ROE` genetics file using sliders for each of a fish's genes -- body, fins,
eyes and gills, covering their shape, colour and pattern -- with a live preview image showing
exactly what each slider does. The preview images are bundled right in with the program, so
there's nothing else to download or point it at.

1. **Load ROE...** -- pick any `.ROE` file. Every slider moves to that fish's own current value for
   each gene, so you're editing from where it already is, not from zero. If a byte's real value
   falls outside that gene's normal safe range (or, for a discrete gene, isn't one of its known
   settings), it's kept exactly as-is rather than being pulled into range -- the slider's thumb
   just shows at whichever end it can reach, but the number next to it, the preview, and
   **Generate ROE...** all use the true value.
2. Genes are organised into three tabs -- **Fins**, **Body**, **Other** (eyes and gills) -- mirroring
   the companion web guide's own sections and order exactly, right down to the sub-groupings within
   each tab (Fins, for instance, goes Enable/Disable, then Shape, Colour, and Pattern, each broken
   down further by which fin). Each gene gets its own row: a description of what it changes, a
   slider (plus a type-in box for an exact value) limited to the values that gene actually uses --
   most genes stop well short of 255, and some only ever take a small handful of distinct values,
   either because higher/other values do nothing further or because they destabilize the game, so
   the slider simply doesn't offer them -- and its own **Reset** button, greyed out until you
   actually change that gene, at which point it lights up amber. Click it to put just that one gene
   back to the value it had in the file you loaded, leaving every other change you've made alone.
   **Reset All**, up in the toolbar, does the same for every gene at once.
3. Click or drag any slider and the **Preview** panel on the right shows a real screenshot of a
   reference fish at that exact value.
4. **Mutant: ON/OFF**, up in the toolbar next to Reset All, toggles the fish's mutant flag -- a
   2-byte header field (0x000-0x001, ahead of the gene bytes) that El-Fish itself reads to decide
   whether a fish counts as a mutant, rather than one of the appearance genes the sliders below it
   control. It's grey when off, blue when on, and turns amber the moment it no longer matches what
   the loaded file had -- the same "you've changed this" colour the per-gene Reset buttons use.
   Leave it alone and Generate writes the file's own mutant bytes back untouched, whatever they
   were.
5. **Generate ROE...** writes every slider's value (and the mutant flag, per above) into a **copy**
   of the file you loaded and asks where to save it -- your original `.ROE` is never touched. The
   confirmation tells you how many bytes actually changed from what you loaded.

This tab remembers the last folder you loaded a `.ROE` from, the same way the FSH Viewer tab
remembers its last folder, so **Load ROE...** opens back where you left off.

### 201 rows covering 196 bytes, across Fins, Body, and Other (eyes and gills)

This covers every size/shape gene plus body, fin, eye and gill colour and pattern genes, and stays
in sync with the web guide's own gene list -- same bytes, same names and descriptions, same order,
same sections. A few of the gill genes -- there are several closely related "gill line colour"
sliders in particular -- look similar to each other; each one's preview and description show
exactly what makes it distinct, so when in doubt, drag it and watch the preview.

A handful of bytes do double duty and are listed twice on the web guide, under two different
headings -- a fin's Shape slider that also fully disables that fin at value 0. The tool mirrors
that exactly: each shows up as two separate rows/sliders here too (5 pairs currently, all in the
Fins tab's Enable/Disable and Shape sections), rather than being merged into one. Moving either
slider updates its sibling automatically, since they're really the same underlying byte -- and
each row's description names exactly where its sibling lives.

### Important: the preview is per-gene, not a live combination

The preview images each show one gene's effect in isolation, with every other gene left at its
default -- not what your fish will look like with everything you've changed applied together
(showing every possible combination of sliders at once isn't practical). To see the real combined
result, generate the `.ROE` and load it into El-Fish.

## Running it

1. Install [Python 3.9+](https://www.python.org/downloads/) if you don't have it (tick "Add
   Python to PATH" on the Windows installer).
2. Open a terminal in this folder and run:
   ```
   pip install -r requirements.txt
   python el_fish_suite_gui.py
   ```
   (Windows: double-click `run_gui.bat` to do both of those for you.)
3. Click **Choose folder...** on the FSH Viewer tab, pick the folder your `.FSH` files live in,
   then click any fish to select it. **Refresh** re-scans the same folder (useful after animating
   more fish in El-Fish), and **Include subfolders** widens the scan to everything underneath it
   too. Switch to the ROE Editor tab at the top whenever you want to edit a `.ROE`'s genes instead.

## Building a standalone .exe

```
pip install -r requirements.txt pyinstaller
build_exe.bat
```

or by hand: `pyinstaller --onefile --windowed --name "ElFishSuite" --add-data "parse_fsh.py;." --add-data "fsh_to_gif.py;." --add-data "gene_data.py;." --add-data "roe_io.py;." --add-data "previews;previews" el_fish_suite_gui.py`.
Has to be run on an actual Windows Python install -- this can't be cross-compiled from
Linux/macOS. The finished `.exe` lands in `dist\` and needs no Python install to run -- the ROE
preview images are packed straight into it, so the exe is noticeably larger than a single-tool
build, but fully self-contained.

## Using the command line instead (batch / scripting)

`fsh_to_gif.py` still works standalone for scripted or batch use -- useful for processing a whole
folder at once rather than one fish at a time through the GUI:

```
python fsh_to_gif.py *.FSH --batch-all
```

Run `python fsh_to_gif.py --help` for the full set of options (choosing a direction, mirror-loop,
nose-anchoring, background color, scale, fps, etc).

## Editing a portrait: `fsh_pack.py` (experimental)

This extracts a fish's detailed portrait (or its small icon) to a PNG you can edit in any image
editor that keeps transparency (GIMP, Aseprite, Photoshop, Paint.NET...), then packs the edited
PNG back into a real, working copy of the `.FSH` -- no GUI yet, command line only:

```
python fsh_pack.py extract F1.FSH portrait.png
# ...edit portrait.png in your image editor, keeping its transparent background...
python fsh_pack.py repack F1.FSH portrait.png F1_edited.FSH
```

`--which icon` extracts/repacks the small icon frame instead of the portrait. Only those two are
supported for repacking -- the swim-animation frames can be extracted (`--which anim
--anim-index N`) for reference but not repacked yet.

**Important:** the edited PNG must keep real per-pixel transparency -- anywhere it's opaque
becomes part of the fish; anywhere it's transparent (alpha 0) stays background. Don't flatten it
onto a solid colour before saving. You can resize the canvas or move the opaque area around (say,
to make a fin stick out further) -- the tool re-crops to whatever's actually opaque and repositions
it automatically; you don't need to match the original pixel dimensions.

Every colour gets snapped to the nearest of the game's fixed 256 colours, same as everywhere else
in this suite. Two of those 256 are duplicated (three identical blacks, two identical reds) --
repacking an unedited extraction can occasionally write back a different one of a duplicate pair
than the original had, which is invisible in-game (same colour either way), not a bug.

This was reverse-engineered from real `.FSH` files (not from any spec on disk) and tested against
real game files -- null round-trips (extract, repack with no changes) render pixel-for-pixel
identical to the original, including every frame of a 216-frame swim animation after a resize
forced every offset after the edited frame to shift -- but it hasn't been confirmed working
in-game yet. If a repacked file doesn't load in El-Fish, or looks wrong, that's worth reporting
back with the specific file.

## Files in this folder

- `el_fish_suite_gui.py` -- the combined app's entry point (run this for the normal path).
- `fsh_viewer_tab.py` -- the FSH Viewer tab (portrait browser + GIF generator).
- `roe_editor_tab.py` -- the ROE Editor tab (gene sliders + preview).
- `fsh_to_gif.py` -- the rendering engine the FSH Viewer tab uses, also usable as its own
  command-line batch tool (see above).
- `parse_fsh.py` -- the low-level `.FSH` binary parser and the game's fixed 256-colour palette.
- `fsh_pack.py` -- extracts a portrait/icon frame to PNG and repacks an edited PNG back into a
  real `.FSH` (command line only, see above).
- `gene_data.py` -- the gene table (offsets, descriptions, slider ranges/values) used by the ROE
  Editor tab.
- `roe_io.py` -- the tiny `.ROE` read/write module (a `.ROE` is just a flat byte array, so this is
  much simpler than the `.FSH` parser).
- `previews/` -- the bundled per-value preview images used by the ROE Editor tab.
- `requirements.txt`, `run_gui.bat` -- for the plain-Python route.
- `build_exe.bat` -- builds the standalone `.exe` (run on Windows; see above).

## Also available separately

The FSH Viewer and ROE Editor are still available as their own standalone tools
(`ElFishToolkit.zip` and `ElFishFishGenerator.zip`) if you'd rather run just one of them without
the other tab.
