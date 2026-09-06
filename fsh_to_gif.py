#!/usr/bin/env python3
"""
fsh_to_gif.py -- turn an El-Fish .FSH file's swim animation into a looping GIF.

Background (so future-you doesn't have to rediscover this):

An .FSH file can contain up to three frame streams: a "detailed" portrait
(single static image, used for the breeding/library screens), an "icon"
thumbnail, and an "anim" stream -- the swim animation this tool renders. Not
every .FSH file has one: a fish only gets animation frames once it's been
animated in El-Fish itself. A file with no animation data has anim_off == 0.

The anim stream is a singly-linked list of frames (via each frame's `nxt`
field, ending at nxt == 0). The frame_num field is NOT an arbitrary counter
-- www.vidarholen.net/contents/elfish/ (the same site parse_fsh.py's format
spec and palette came from) documents it as three decimal fields "DANN":

    D  = Direction   (0-3 for a 4-directional fish, 0-5 for 6-directional)
    A  = Action      (0 Swim, 1 Turn-first [dir -> dir+1], 2 Turn-mid
                       [dir-1 -> dir+1], 3 Turn-last [dir+1 -> dir],
                       4 Paddle, 5 Idle, 6 Stop [swim -> idle])
    NN = frame position within that direction+action's own short sequence

i.e. frame_num = D*1000 + A*100 + NN. Confirmed empirically against several
animated fish: each (direction, action) bucket is a clean, independently-
looping few-frame sequence, and Action 0 (Swim) is specifically the
continuous side-on tail-flap cycle -- 4 frames for 6-directional fish, 6
frames for 4-directional ones. Walking a whole direction's frames in list
order (the tool's default) concatenates ALL SEVEN actions back-to-back into
one long loop, which is exactly what reads as "jerky": the Turn actions are
where the sprite visibly shrinks as it rotates through the tank's faux-3D
depth. Use `--action swim` (or `--list-layers` to see what's available) to
get just the intended continuous side-on cycle instead.

Each frame is tightly cropped to its non-transparent pixels; `xoff`/`yoff`
locate that crop within a shared coordinate space (the same space the
detailed/icon frame's own xoff/yoff use), so frames must be placed at their
own (xoff, yoff) on one shared canvas to stay visually anchored instead of
jittering around.

Confirmed empirically (see check below, safe across every animated fish
tested): palette index 0 (00FFFF cyan) is never used by an actual opaque
pixel, only ever left as the untouched/background value. That makes it
safe to use as the GIF's transparent colour-key -- no need to requantize
away from the game's exact 256-colour palette.

--mirror-loop -- Vidar Holen's actual "complete animation" trick, found by
reading his original Java source (Jelfish.java, the interactive renderer,
plus Fish.java's `invertDirection`). El-Fish fish are bilaterally
symmetric, and the game exploits that to double a direction's continuous
action (swim/paddle/idle) frame count for free instead of storing twice as
much data: `update()` plays a direction's own action frames all the way
through, then flips a `mirror` flag and plays invertDirection(dir) =
(dirmode/2 + dir)'s frames for that *same* action, horizontally flipped, as
a continuation of the *same* direction's motion -- then flips back. So a
direction's "swim" isn't really just its own few stored frames, it's twice
that: its own frames, then its mirror-partner direction's frames, flipped.
The paint() geometry (`xo=x+now.x+(mirror?now.w*2:0)`,
`w=mirror?-now.w:now.w`) places the flipped frame's canvas left-edge at
(that frame's own xoff + width), which in one shared coordinate space lands
it almost exactly where the source direction's own frames sit -- confirming
the two halves are meant to be visually interchangeable, not two separate
fish positions.

This was tested and measured, not just implemented on faith: on a
4-directional test fish, the plain 6-frame single-direction loop's worst
transition is its wrap (frame 5 -> 0, pixel-diff 0.451, clearly the largest
of the six -- this is the visible "jump"). The 12-frame mirror-loop's two
splice points measure 0.408 and 0.430 -- both *smaller* than the plain
loop's wrap, and in line with the ordinary frame-to-frame transitions
elsewhere in the cycle (0.30-0.43) rather than standing out as a spike. In
other words this isn't a cosmetic smoothing hack like --crossfade -- it's
the game's own real second half of the animation, and it measurably removes
the seam rather than just blurring it.
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)  # parse_fsh.py ships next to this file
from parse_fsh import parse_header, parse_frame, render_frame, PALETTE

from PIL import Image

TRANSPARENT_INDEX = 0  # verified safe -- see module docstring
FLAT_PALETTE = []
for i in range(256):
    FLAT_PALETTE.extend(PALETTE.get(i, (0, 0, 0)))

ACTION_NAMES = {0: "swim", 1: "turn-first", 2: "turn-mid", 3: "turn-last", 4: "paddle", 5: "idle", 6: "stop"}
ACTION_BY_NAME = {v: k for k, v in ACTION_NAMES.items()}
ACTION_CHOICES = ["all", "turn"] + list(ACTION_NAMES.values())  # 'all' = whole native chain, 'turn' = stages 1+2+3


def decode_frame_num(frame_num):
    """DANN encoding, per the vidarholen.net FSH spec -- see module docstring."""
    direction = frame_num // 1000
    action = (frame_num % 1000) // 100
    nn = frame_num % 100
    return direction, action, nn


def walk_anim_chain(data, anim_off):
    """Follow the frame linked list from anim_off, returns list of frame dicts in list order."""
    frames = []
    seen = set()
    off = anim_off
    while off != 0 and off not in seen:
        seen.add(off)
        f = parse_frame(data, off)
        frames.append(f)
        off = f["nxt"]
    return frames


def group_by_direction(frames):
    directions = {}
    for f in frames:
        d, _, _ = decode_frame_num(f["frame_num"])
        directions.setdefault(d, []).append(f)
    return directions


def select_action(frames, action_arg):
    """Filter one direction's frames down to a single named action (or 'turn' for all three
    turn stages concatenated in order), sorted by frame_num so NN order is guaranteed regardless
    of chain traversal order. action_arg == 'all' returns frames unchanged (the native chain)."""
    if action_arg == "all":
        return frames
    if action_arg == "turn":
        wanted = {1, 2, 3}
    else:
        wanted = {ACTION_BY_NAME[action_arg]}
    kept = [f for f in frames if decode_frame_num(f["frame_num"])[1] in wanted]
    kept.sort(key=lambda f: f["frame_num"])
    return kept


def find_side_on_run(frames, threshold=0.85):
    """Legacy fallback from before the DANN encoding above was confirmed -- prefer
    `--action swim` now, this is kept only in case a file ever doesn't follow the spec cleanly.

    Finds the longest run of frames whose width stays within `threshold` of the direction's max
    width, treating the sequence as circular (a plateau can wrap past the end of the list back to
    the start). Returns just that run's frames, in original order."""
    widths = [f["width"] for f in frames]
    n = len(widths)
    cutoff = max(widths) * threshold
    is_wide = [w >= cutoff for w in widths]

    if all(is_wide):
        return frames

    start = next(i for i, wide in enumerate(is_wide) if not wide)
    start = (start + 1) % n

    best_run, cur_run = [], []
    for k in range(n):
        idx = (start + k) % n
        if is_wide[idx]:
            cur_run.append(idx)
            if len(cur_run) > len(best_run):
                best_run = list(cur_run)
        else:
            cur_run = []

    return [frames[i] for i in best_run]


def compute_canvas(placements, pad=4):
    """placements: list of (frame, effective_xoff, flip) -- effective_xoff is frame['xoff'] for a
    normal placement, or frame['xoff']+frame['width'] for a mirrored one (see --mirror-loop)."""
    min_x = min(xo for f, xo, flip in placements)
    min_y = min(f["yoff"] for f, xo, flip in placements)
    max_x = max(xo + f["width"] for f, xo, flip in placements)
    max_y = max(f["yoff"] + f["height"] for f, xo, flip in placements)
    ox = pad - min_x
    oy = pad - min_y
    cw = (max_x - min_x) + pad * 2
    ch = (max_y - min_y) + pad * 2
    return cw, ch, ox, oy


def build_mirror_placements(directions, direction, action_arg):
    """Vidar Holen's actual technique (found in Jelfish.java/Fish.java) for doubling a continuous
    action's frame count for free using bilateral symmetry -- see module docstring for the full
    explanation and the measurements that confirm it closes the loop seam rather than just hiding
    it. Returns the invertDirection direction's frames for the same action, each tagged for a
    horizontal flip and placed at (xoff + width) so they land in the same shared coordinate space
    as the source direction's own frames."""
    dirmode = max(directions.keys()) + 1
    inv = ((dirmode // 2) + direction) % dirmode
    if inv == direction or inv not in directions:
        return [], inv, dirmode
    inv_frames = select_action(directions[inv], action_arg)
    return [(f, f["xoff"] + f["width"], True) for f in inv_frames], inv, dirmode


def stabilize_placements(placements):
    """--anchor-nose: re-anchor every frame on the fish's nose instead of the shared in-tank
    coordinate space, so a looping GIF holds still instead of drifting the way it would swimming
    across a real tank.

    xoff/yoff (or the mirrored xoff+width) already place frames correctly relative to each other
    -- that's real swim translation, confirmed useful for --all-layers/turn sequences -- but for a
    single looping action it reads as the whole fish sliding around the frame. The head stays
    rigid while the tail sweeps, so whichever edge (of each axis) moves *least* across the frame
    set is the nose/head edge; the opposite edge is the tail, and its natural movement is exactly
    the flap motion worth keeping. Shift each frame so its nose edge lands on a fixed reference
    point (the first frame's own position) -- the tail's relative sweep is untouched, only the
    shared drift is cancelled."""
    lefts = [xo for f, xo, flip in placements]
    rights = [xo + f["width"] for f, xo, flip in placements]
    tops = [f["yoff"] for f, xo, flip in placements]
    bottoms = [f["yoff"] + f["height"] for f, xo, flip in placements]

    x_is_left = (max(lefts) - min(lefts)) <= (max(rights) - min(rights))
    y_is_top = (max(tops) - min(tops)) <= (max(bottoms) - min(bottoms))
    target_x = lefts[0] if x_is_left else rights[0]
    target_y = tops[0] if y_is_top else bottoms[0]

    stabilized = []
    for (f, xo, flip), l, r, t, b in zip(placements, lefts, rights, tops, bottoms):
        dx = target_x - (l if x_is_left else r)
        dy = target_y - (t if y_is_top else b)
        f2 = dict(f, yoff=f["yoff"] + dy)
        stabilized.append((f2, xo + dx, flip))

    axis_desc = f"{'left' if x_is_left else 'right'}-edge nose, {'top' if y_is_top else 'bottom'}-edge"
    return stabilized, axis_desc


def render_placements(data, placements, pad=4):
    """Render a list of (frame, effective_xoff, flip) placements onto one shared canvas.
    Returns (list of 'P' mode PIL Images, canvas size)."""
    cw, ch, ox, oy = compute_canvas(placements, pad)
    images = []
    for f, xo, flip in placements:
        buf, alpha = render_frame(data, f)
        canvas = bytearray([TRANSPARENT_INDEX]) * (cw * ch)
        w, h = f["width"], f["height"]
        for y in range(h):
            row_base = (y + f["yoff"] + oy) * cw
            src_row = y * w
            for x in range(w):
                sx = (w - 1 - x) if flip else x
                idx = src_row + sx
                if alpha[idx]:
                    cx = x + xo + ox
                    if 0 <= cx < cw:
                        canvas[row_base + cx] = buf[idx]
        img = Image.new("P", (cw, ch))
        img.putpalette(FLAT_PALETTE)
        img.putdata(bytes(canvas))
        img.info["transparency"] = TRANSPARENT_INDEX
        images.append(img)
    return images, (cw, ch)


def render_direction_frames(data, frames, pad=4):
    """Render one direction's frames (no mirroring) onto a shared canvas. Thin wrapper over
    render_placements for callers that just have a plain frame list."""
    placements = [(f, f["xoff"], False) for f in frames]
    return render_placements(data, placements, pad)


def composite_to_rgb(images, bg_rgb):
    """Flatten transparent-P frames onto a solid RGB background (no quantizing yet -- crossfading
    needs real RGB blending, which a palette index can't do)."""
    rgb_frames = []
    for img in images:
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, bg_rgb + (255,))
        bg.alpha_composite(rgba)
        rgb_frames.append(bg.convert("RGB"))
    return rgb_frames


def quantize_shared_palette(rgb_frames, bg_rgb):
    """Quantize a list of same-size RGB frames to one shared 256-colour palette (built from a
    strip of all of them together) so colours don't flicker frame-to-frame."""
    strip_w = sum(im.width for im in rgb_frames)
    strip_h = max(im.height for im in rgb_frames)
    strip = Image.new("RGB", (strip_w, strip_h), bg_rgb)
    x = 0
    for im in rgb_frames:
        strip.paste(im, (x, 0))
        x += im.width
    pal_img = strip.quantize(colors=256, method=Image.MEDIANCUT)
    return [im.quantize(palette=pal_img, dither=Image.NONE) for im in rgb_frames]


def build_background_frames(images, bg_rgb):
    """Composite transparent-P frames onto a solid RGB background, quantized to one shared palette."""
    return quantize_shared_palette(composite_to_rgb(images, bg_rgb), bg_rgb)


def crossfade_loop(rgb_frames, n):
    """Insert `n` dissolve frames between the end of the sequence and its own start, to soften
    the loop-back seam (see the module docstring's note on the swim action's one-way arc: the
    last frame doesn't fully return to the first, and no reordering fixes that -- confirmed by
    brute-force search -- because the missing motion was simply never captured/stored. This
    doesn't recover it; it just blurs the cut over a few frames instead of showing it as one hard
    jump). Needs flat RGB (no per-pixel alpha), since GIF transparency is binary and can't
    represent a partial blend."""
    if n <= 0 or len(rgb_frames) < 2:
        return rgb_frames
    last, first = rgb_frames[-1], rgb_frames[0]
    blended = [Image.blend(last, first, k / (n + 1)) for k in range(1, n + 1)]
    return rgb_frames + blended


def describe_directions(hdr, all_frames, directions):
    """Structured version of what --list-layers prints -- used by the CLI and by the GUI's
    'file loaded' summary. Returns {"name", "total_frames", "directions": [{"direction",
    "frame_count", "actions": {name: count}}, ...]}."""
    dirs_info = []
    for d, frames in sorted(directions.items()):
        by_action = {}
        for f in frames:
            _, a, nn = decode_frame_num(f["frame_num"])
            by_action.setdefault(ACTION_NAMES.get(a, f"action{a}"), []).append(nn)
        dirs_info.append({
            "direction": d,
            "frame_count": len(frames),
            "actions": {name: len(nns) for name, nns in sorted(by_action.items())},
        })
    return {"name": hdr["name"], "total_frames": len(all_frames), "directions": dirs_info}


def render_direction_gif(data, directions, direction, *, action="swim", side_on=False,
                          side_on_threshold=0.85, mirror_loop=False, anchor_nose=False,
                          nose_pad=5, scale=3, fps=12.0, background=None, boomerang=False,
                          crossfade=0, out_path=None):
    """Render one direction of one FSH file's animation to a GIF at out_path. This is the one
    function both the CLI (main(), below) and the GUI call, so the two never drift apart. Returns
    a dict: {"out_path", "frame_count", "size", "scaled_size", "duration_ms", "messages"} on
    success, or raises ValueError with a human-readable reason (direction/action not found) that's
    safe to show directly in the GUI.
    """
    messages = []
    if direction not in directions:
        raise ValueError(f"direction {direction} not found; available: {sorted(directions.keys())}")

    frames = select_action(directions[direction], action)
    if not frames:
        raise ValueError(f"direction {direction}: no frames for action '{action}'")

    if side_on:
        kept = find_side_on_run(frames, side_on_threshold)
        messages.append(f"side-on filter kept {len(kept)}/{len(frames)} frames "
                         f"(widths {min(f['width'] for f in kept)}-{max(f['width'] for f in kept)} "
                         f"of {max(f['width'] for f in frames)} max)")
        frames = kept

    placements = [(f, f["xoff"], False) for f in frames]

    if mirror_loop:
        mirror_placements, inv, dirmode = build_mirror_placements(directions, direction, action)
        if not mirror_placements:
            messages.append(f"--mirror-loop has nothing to add (dirmode={dirmode}, "
                             f"invertDirection({direction})={inv} not present or is itself) -- "
                             f"continuing without it")
        else:
            messages.append(f"--mirror-loop appending {len(mirror_placements)} flipped frame(s) "
                             f"from direction {inv} (dirmode={dirmode})")
            placements = placements + mirror_placements

    if anchor_nose:
        placements, axis_desc = stabilize_placements(placements)
        messages.append(f"--anchor-nose stabilized on {axis_desc}")

    pad = nose_pad if anchor_nose else 4
    images, (cw, ch) = render_placements(data, placements, pad=pad)

    if boomerang and len(images) > 2:
        images = images + images[-2:0:-1]

    if crossfade > 0:
        bg = background
        if bg is None:
            bg = (255, 255, 255)
            messages.append("no background given; --crossfade needs a solid backdrop to blend "
                             "against -- defaulting to white")
        rgb_frames = composite_to_rgb(images, bg)
        rgb_frames = crossfade_loop(rgb_frames, crossfade)
        images = quantize_shared_palette(rgb_frames, bg)
        save_kwargs = {}
    elif background is not None:
        images = build_background_frames(images, background)
        save_kwargs = {}
    else:
        save_kwargs = {"transparency": TRANSPARENT_INDEX, "disposal": 2}

    if scale != 1:
        images = [im.resize((cw * scale, ch * scale), Image.NEAREST) for im in images]

    duration_ms = int(round(1000.0 / fps))
    images[0].save(
        out_path,
        save_all=True,
        append_images=images[1:],
        loop=0,
        duration=duration_ms,
        optimize=False,
        **save_kwargs,
    )
    return {
        "out_path": out_path,
        "frame_count": len(images),
        "size": (cw, ch),
        "scaled_size": (cw * scale, ch * scale),
        "duration_ms": duration_ms,
        "messages": messages,
    }


def dedupe_output_names(file_infos):
    """file_infos: list of (path, hdr). Returns {path: name-to-use-for-that-file's-output}, normally
    just hdr['name'] -- but a file's internal fish name and its filename on disk aren't required to
    match (the stock copy of YELLY.FSH, for instance, is internally named "F1"), so two files in the
    same batch can genuinely share an internal name. Whenever that happens, every file sharing that
    name gets its own filename stem appended, so a batch never has two fish silently writing into
    (and overwriting each other in) the same '<name>_gifs' folder."""
    from collections import Counter
    counts = Counter(hdr["name"] for _, hdr in file_infos)
    result = {}
    for path, hdr in file_infos:
        name = hdr["name"]
        if counts[name] > 1:
            stem = os.path.splitext(os.path.basename(path))[0]
            result[path] = f"{name}_{stem}"
        else:
            result[path] = name
    return result


def generate_all_direction_gifs(fsh_path, out_dir, *, actions=("swim", "idle"), directions=None,
                                 mirror_loop=True, anchor_nose=True, nose_pad=5, scale=3, fps=12.0,
                                 background=None, boomerang=False, crossfade=0,
                                 progress_cb=None):
    """Batch entry point: render each action in `actions` (by default the two continuous loops
    worth having as a GIF: the swim cycle and the idle/resting cycle) to its own GIF in out_dir,
    with the mirror-loop + nose-anchor fixes on by default. Used by the GUI's single "Generate"
    button and available to script callers too.

    `directions` controls which direction(s) to render: the default (None) is just the
    lowest-numbered direction present -- normally 0, the plain side-on view, which is the only one
    worth a GIF for most purposes. Pass an explicit list/tuple (e.g. every direction the file has)
    to render more than one.

    Not every fish has every action -- a direction missing one of `actions` is recorded as an
    error result rather than aborting the whole batch, since e.g. idle frames are common but not
    guaranteed on every fish.

    progress_cb, if given, is called as progress_cb(done, total, result_or_None, error_or_None)
    after each (action, direction), so a GUI can update a progress bar/log without polling.

    Returns (hdr, list of per-result dicts -- each either the render_direction_gif() result plus
    "direction"/"action", or {"direction", "action", "error"} on failure).
    """
    data = open(fsh_path, "rb").read()
    hdr = parse_header(data)
    if hdr["anim_off"] == 0:
        raise ValueError("No animation data found in the FSH file. Animate this fish in El Fish "
                          "and try again.")

    all_frames = walk_anim_chain(data, hdr["anim_off"])
    dirs_by_index = group_by_direction(all_frames)
    os.makedirs(out_dir, exist_ok=True)

    targets = [sorted(dirs_by_index.keys())[0]] if directions is None else list(directions)
    include_dir_suffix = len(targets) > 1
    jobs = [(action, direction) for action in actions for direction in targets]
    results = []
    for i, (action, direction) in enumerate(jobs):
        suffix = f"_dir{direction}" if include_dir_suffix else ""
        out_path = os.path.join(out_dir, f"{hdr['name']}_{action}{suffix}.gif")
        try:
            result = render_direction_gif(
                data, dirs_by_index, direction, action=action, mirror_loop=mirror_loop,
                anchor_nose=anchor_nose, nose_pad=nose_pad, scale=scale, fps=fps,
                background=background, boomerang=boomerang, crossfade=crossfade,
                out_path=out_path,
            )
            result["direction"] = direction
            result["action"] = action
            results.append(result)
            if progress_cb:
                progress_cb(i + 1, len(jobs), result, None)
        except ValueError as e:
            err = {"direction": direction, "action": action, "error": str(e)}
            results.append(err)
            if progress_cb:
                progress_cb(i + 1, len(jobs), None, err)
    return hdr, results


def parse_color(s):
    s = s.strip()
    named = {
        "white": (255, 255, 255),
        "black": (0, 0, 0),
        "water": (40, 90, 130),
        "aquarium": (40, 90, 130),
    }
    if s.lower() in named:
        return named[s.lower()]
    s = s.lstrip("#")
    if len(s) == 6:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    raise argparse.ArgumentTypeError(f"unrecognised colour: {s}")


def main():
    ap = argparse.ArgumentParser(description="Render an El-Fish .FSH swim animation to a looping GIF.")
    ap.add_argument("fsh_paths", nargs="+", metavar="fsh_path",
                     help="path(s) to one or more .FSH files (each needs a real swim animation -- "
                          "see --list-layers). Pass more than one (or a shell glob like *.FSH) to "
                          "process a batch in one go -- with --batch-all each gets its own "
                          "'<fish name>_gifs' folder; without it, --output is ignored for batches "
                          "of more than one file and each still gets its own default name.")
    ap.add_argument("-o", "--output", help="output .gif path (default: <fish name>[_action][_dir{N}].gif "
                                            "in the current directory) -- only meaningful for a single "
                                            "fsh_path; ignored (with a warning) when more than one is given "
                                            "outside --batch-all, where it's instead treated as a shared "
                                            "parent directory")
    ap.add_argument("--layer", "--direction", dest="layer", type=int, default=None,
                     help="which direction (0-3 or 0-5) to render (default: lowest available)")
    ap.add_argument("--all-layers", "--all-directions", dest="all_layers", action="store_true",
                     help="render every direction to its own GIF instead of just one")
    ap.add_argument("--list-layers", "--list", dest="list_layers", action="store_true",
                     help="print available directions and their action/frame breakdown, then exit")
    ap.add_argument("--action", choices=ACTION_CHOICES, default="all",
                     help="which action to render: 'all' (default -- the full native chain, every "
                          "action back to back, including the turns); 'swim' for just the continuous "
                          "side-on tail-flap loop (this is what you want for a non-jerky swim GIF); "
                          "'turn' for the three turn stages played in sequence; or paddle/idle/stop")
    ap.add_argument("--scale", type=int, default=3, help="integer upscale factor, nearest-neighbour (default: 3)")
    ap.add_argument("--fps", type=float, default=12.0, help="playback speed in frames/sec (default: 12)")
    ap.add_argument("--background", type=parse_color, default=None,
                     help="bake a solid background instead of GIF transparency, e.g. white / water / #1a2b3c")
    ap.add_argument("--boomerang", action="store_true",
                     help="append the sequence in reverse for a guaranteed-smooth loop")
    ap.add_argument("--crossfade", type=int, default=0,
                     help="insert N dissolve frames to soften the loop-back seam instead of a hard cut "
                          "(the seam is real -- the swim action's last frame doesn't fully return to its "
                          "first, on every fish checked -- this can't recover missing motion, only blur "
                          "the cut). Forces a solid background if --background wasn't given, since GIF "
                          "transparency can't represent a partial blend.")
    ap.add_argument("--mirror-loop", action="store_true",
                     help="Vidar Holen's actual technique (from his Java source) for a direction's "
                          "continuous actions (swim/paddle/idle): append the mirror-image "
                          "direction's own frames for the same action, flipped, as a second half "
                          "of the same loop -- measured to close the loop-seam jump rather than "
                          "just blur it, unlike --crossfade. See module docstring for the numbers.")
    ap.add_argument("--anchor-nose", action="store_true",
                     help="re-anchor every frame on the fish's nose instead of the file's shared "
                          "in-tank coordinates, so the loop holds still instead of drifting across "
                          "the canvas the way it would swimming across a real tank. Keeps the tail-"
                          "flap motion, cancels the shared translation. Good for a static/looping GIF; "
                          "skip it for --all-layers or --action turn, where that translation is real "
                          "swim/turn movement you want to see.")
    ap.add_argument("--nose-pad", type=int, default=5,
                     help="canvas padding in px, applied after --anchor-nose stabilizes the frames "
                          "-- controls how close the canvas starts to the nose tip (default: 5)")
    ap.add_argument("--side-on", action="store_true",
                     help="legacy width-heuristic filter, superseded by '--action swim' -- kept as a fallback only")
    ap.add_argument("--side-on-threshold", type=float, default=0.85,
                     help="width fraction for --side-on (default: 0.85)")
    ap.add_argument("--batch-all", action="store_true",
                     help="convenience shorthand for the settings already confirmed to look best: "
                          "the plain side-on direction, both the swim and idle loops, mirror-loop + "
                          "anchor-nose applied, transparent background. Writes into a "
                          "'<fish name>_gifs' folder next to the input file (or the directory given "
                          "via --output, if any). For every direction instead, use --all-layers "
                          "with --action/--mirror-loop/--anchor-nose set manually.")
    args = ap.parse_args()
    multi = len(args.fsh_paths) > 1

    if args.list_layers:
        for fsh_path in args.fsh_paths:
            if multi:
                print(f"=== {fsh_path} ===")
            try:
                data = open(fsh_path, "rb").read()
                hdr = parse_header(data)
            except Exception as e:
                print(f"  couldn't read: {e}")
                continue
            if hdr["anim_off"] == 0:
                print("  No animation data found. Animate this fish in El Fish and try again.")
                continue
            all_frames = walk_anim_chain(data, hdr["anim_off"])
            directions = group_by_direction(all_frames)
            info = describe_directions(hdr, all_frames, directions)
            print(f"{info['name']}: {info['total_frames']} total animation frames across "
                  f"{len(info['directions'])} direction(s)")
            for d in info["directions"]:
                parts = ", ".join(f"{name}={count}" for name, count in d["actions"].items())
                print(f"  direction {d['direction']}: {d['frame_count']} frames  ({parts})")
        return

    if args.batch_all:
        if multi and args.output:
            print(f"(--output '{args.output}' treated as a shared parent directory -- each fish "
                  f"still gets its own '<fish name>_gifs' subfolder inside it)")

        # Read every header up front (cheap -- just the fixed header, not the animation chain) so
        # a fish-name collision across files (a file's internal name and its filename on disk
        # aren't required to match -- see dedupe_output_names) can be caught before anything is
        # written, rather than having one file's output silently overwritten by another's.
        file_infos = []
        for fsh_path in args.fsh_paths:
            try:
                data = open(fsh_path, "rb").read()
                hdr = parse_header(data)
            except Exception as e:
                if multi:
                    print(f"=== {fsh_path} ===")
                print(f"  couldn't read: {e}")
                continue
            if hdr["anim_off"] == 0:
                if multi:
                    print(f"=== {fsh_path} ===")
                print("  No animation data found. Animate this fish in El Fish and try again.")
                continue
            file_infos.append((fsh_path, hdr))

        out_names = dedupe_output_names(file_infos)
        for fsh_path, hdr in file_infos:
            if multi:
                print(f"=== {fsh_path} ===")

            if args.output:
                out_dir = os.path.join(args.output, f"{out_names[fsh_path]}_gifs") if multi else args.output
            else:
                out_dir = f"{out_names[fsh_path]}_gifs"

            def cli_progress(done, total, result, error):
                if error:
                    print(f"  direction {error['direction']} ({error['action']}): {error['error']}")
                    return
                for msg in result["messages"]:
                    print(f"  direction {result['direction']} ({result['action']}): {msg}")
                cw, ch = result["size"]
                sw, sh = result["scaled_size"]
                print(f"  wrote {result['out_path']}  ({result['frame_count']} frames, {cw}x{ch} native, "
                      f"{sw}x{sh} scaled, {result['duration_ms']}ms/frame)")

            generate_all_direction_gifs(fsh_path, out_dir, progress_cb=cli_progress)
        return

    if multi and args.output:
        print(f"(--output '{args.output}' ignored for {len(args.fsh_paths)} input files outside "
              f"--batch-all -- each fish is written under its own default name instead)")

    for fsh_path in args.fsh_paths:
        if multi:
            print(f"=== {fsh_path} ===")
        try:
            data = open(fsh_path, "rb").read()
            hdr = parse_header(data)
        except Exception as e:
            print(f"  couldn't read: {e}")
            continue
        if hdr["anim_off"] == 0:
            print("  No animation data found. Animate this fish in El Fish and try again.")
            continue

        all_frames = walk_anim_chain(data, hdr["anim_off"])
        directions = group_by_direction(all_frames)

        default_base = hdr["name"]  # write to the current directory by default, not next to the source FSH
        targets = sorted(directions.keys()) if args.all_layers else [args.layer if args.layer is not None else sorted(directions.keys())[0]]
        name_suffix = "" if args.action == "all" else f"_{args.action}"

        for direction in targets:
            if direction not in directions:
                print(f"  direction {direction} not found; available: {sorted(directions.keys())}")
                continue

            if args.all_layers:
                if args.output and not multi:
                    out_base, out_ext = os.path.splitext(args.output)
                    out_path = f"{out_base}{name_suffix}_dir{direction}{out_ext or '.gif'}"
                else:
                    out_path = f"{default_base}{name_suffix}_dir{direction}.gif"
            else:
                out_path = args.output if (args.output and not multi) else f"{default_base}{name_suffix}.gif"

            try:
                result = render_direction_gif(
                    data, directions, direction, action=args.action, side_on=args.side_on,
                    side_on_threshold=args.side_on_threshold, mirror_loop=args.mirror_loop,
                    anchor_nose=args.anchor_nose, nose_pad=args.nose_pad, scale=args.scale,
                    fps=args.fps, background=args.background, boomerang=args.boomerang,
                    crossfade=args.crossfade, out_path=out_path,
                )
            except ValueError as e:
                print(f"  direction {direction}: {e}")
                continue

            for msg in result["messages"]:
                print(f"  direction {direction}: {msg}")
            cw, ch = result["size"]
            sw, sh = result["scaled_size"]
            print(f"  wrote {result['out_path']}  ({result['frame_count']} frames, {cw}x{ch} native, "
                  f"{sw}x{sh} scaled, {result['duration_ms']}ms/frame, direction {direction}, "
                  f"action {args.action})")


if __name__ == "__main__":
    main()
