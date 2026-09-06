# El-Fish

More information on El Fish, the El Fish Toolkit, and the El Fish Genome Project which lead to this, is available on my website.
p7uen.neocities.com/faqs/ElFish.html

El Fish is a virtual aquarium from Maxis (The Sims, SimCity, etc) developed by the guys who made Tetris and some Russian rocket scientists. This might seem like overkill for a fish tank game, but there is a twist: the fish can be bred and evolved to spawn new fish based on their genetic makeup, and the fish attributes, animations, the aquarium plants and even the background music, are all procedurally generated.

I loved El Fish when I reviewed it, to the point of obsession. It feels like one of those core memory games I've played since childhood, even though I played it for the first time in 2026. I then spent 5 months trying to decode the .ROE files, working on it pretty much every day.

It's worth saying upfront that a big part of the fun of <i>El Fish</i> is twiddling with the sliders and breeding and evolving the fish to see what comes out; making your own fish manually defeats the object of the game. However it's your fish tank to populate however you want and, just as the Petz community found many years ago, it can also be fun to customise your friends via the magic of hex editing. Most of the genes are still unknown, and I also have no idea how the many, many genes interact, especially those so similar to each other, so the element of discovery is not lost even to gene-explorers.

# The El Fish Toolkit

At the beginning of the project I turned to AI to help me create tens of thousands of .ROE files with single hex values changed. Later in the project I asked it to make a tool to speed up the viewing of fish without having to load up the game, which I had to often do when comparing to old fish. Later I got it to add a couple of simple features, which is what you see here today.

The FSH viewer and gif generator is all based on Vidar Holen's work from https://www.vidarholen.net/contents/elfish, in 2002 (24 years before today), although not his actual code.

If you don't like AI coded apps, don't use this. My website has a list of all the hex value with illustrative pictures of what they do, so you can manually edit the hex files, which is how I did it. I just wanted to lower the barrier of entry for people. 

# Downloads
Go the downloads folder for the Windows .exe or zip. 
The source is also all available. Hopefully someone can build on my work and tie down more fish genes in future.


# Using The Toolkit
For more information visit p7uen.neocities.com/faqs/ElFish.html

## FSH Viewer
Point it to a folder and you will see a preview of all the fish in there.
The gif indicator shows you the status of the gifs.
  Grey: fish not animated in El Fish. Animate it in the game to enable gif creation.
  Amber: fish animated, but gif not yet created. Click the generate button in the preview pane to make the gif.
  Green: Gif already created, see it in the preview pane.


## ROE Editor tab

The ROE editing was something I added at the end to make it easier for the layman if they can't get to grips with the manual hex editing of the El Fish Fish Customisation Guide (p7uen.neocities.com/faqs/El-Fish-Fish-Customisation-Guide.html). Load in a ROE, change the sliders, with a visual representation of what the slider does (taken from my test portraits). It's janky but at least you can see the effect better than the single examples on the guide.

- Load your ROE and start editing.
- Reset all with the reset button, or individually from the reset button on each gene.
- Click Generate ROE when you're ready to save it (it will not overwrite your original ROE.
- You can edit the mutant flag as well. I included this as an option because edited fish will often not be able to be evolved properly (it will evolve from it's original fish, not from the new edited features).
- Mutant fish cannot breed or be evolved, so if you want to avoid confusion you can make your edited fish mutants.
- Alternatively, use this to make mutant fish from the game non-mutant, so that they can be used to breed or evolve.
- Note the previews are from the original control fish, and only display what the potential change is for that byte, not combined for all your changes.

Genes
- There are around 200 genes, organised by body part and then by type: shape, colour or pattern.
- A preview is displayed on what it does for the control fish used in testing. This may vary from your fish.
- In particular, colours will not be the same on your fish from the test fish.
- Shapes are more reliable, but genes will interact differently so beware.

Roe Editing Tips
- This is an iterative process; make repeated small adjustments and check each time until you get what you want.
- It works best with shape and size genes; colours and patterns are very hit and miss. It's best to use this with a combination of small edits and evolutions.
- Start with obvious things like body size and shape.
- Don't change too many things at once, especially if they are related to each other, e.g. 2 shape genes of the same fin. They may interact in unforseen ways and you can't tell which effects they have.
- Save and backup your favourite fish so that you dont overwrite and lose any.
- If you do lose any, you can regenerate a roe from a fish as long as it is still in the game.

Notes:
- This is Windows only, the source code is available in case you want to make your own version for other platforms.
- Warning: it was coded by AI. I think AI is bad & using it for art is horrible, but it's good at coding. If you prefer not to use AI please avoid.
- I provide these as-is for people who want it, but make no claims about how well they work.
- If your gifs get cropped off, try animating them in-game using NORMAL, not ZOOMED mode.
- Beware: often you can't evolve the fish that are edited; it will evolve the original fish.


# Technical Info
The below was included by the AI. Have fun!

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
