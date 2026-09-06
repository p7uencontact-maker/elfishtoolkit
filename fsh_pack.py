#!/usr/bin/env python3
"""
fsh_pack.py -- extract an El-Fish .FSH portrait/icon frame to a PNG for editing, and repack an
edited PNG back into a valid .FSH.

Format background (so future-you doesn't have to re-derive this):

An .FSH file is: a fixed-layout header (see parse_fsh.parse_header), then an optional ICON frame,
then the DETAILED (portrait) frame, then an optional chain of ANIMATION frames -- laid out
back-to-back in the file in that order, sometimes with a gap of other per-fish data (genetics/
breeding metadata, never decoded, always just an opaque blob) in between two of them. detailed_off
is fixed once written, but icon/detailed/anim frames still reference each other and the header
still reaches into the file with plain 4-byte ABSOLUTE offsets -- icon_off/anim_off in the header,
and every frame's own prev/nxt fields -- so replacing one frame with a differently-sized one shifts
every absolute offset that points at or past the old frame's end. This module's whole job is doing
that shift correctly.

A frame's pixel data (see parse_fsh.render_frame for the read side) is a sequence of
[dlen:u16][posval:s16][dlen raw palette-index bytes] records, one per contiguous run of opaque
pixels, processed top-to-bottom/left-to-right:
  - `posval >= 0` means "move to the next row, then draw at column posval" -- this is the ONLY way
    to advance the current row, so it happens exactly once per non-blank row (on that row's first
    run) and drives the whole row-by-row cursor.
  - `posval < 0` means "stay on the current row, draw at column -posval" -- used for a row's 2nd+
    run when the shape has a transparent gap partway across it (rare but real, e.g. a fin sticking
    out past a gap).
  - `dlen == 0 and posval == 0` is a dedicated "this row has nothing on it, just advance" marker.
  - The very first record of a frame is special: the cursor starts already "on" row 0 (not before
    it), so row 0's own first run must use `posval < 0` (continue-current-row) to stay on row 0 --
    using `posval >= 0` here would immediately advance to row 1 and draw there instead. This makes
    a genuinely blank row 0 followed by real content on row 0 unrepresentable via posval alone, and
    more importantly means a run whose local x is exactly 0 can never be encoded as a "continue"
    event (-0 == 0, which reads back as "advance"). Real frames are tightly cropped to their own
    opaque pixels, so a shape's very top-left corner is essentially never itself opaque -- but this
    encoder guards it explicitly anyway (see _pad_left_if_needed) rather than relying on luck.
  - frame_len (the frame header's own field) is not simply len(pixel data): empirically, across
    every frame in every real .FSH file sampled (icon, detailed, and every animation frame),
    frame_len == len(pixel data) + 14 exactly. This encoder reproduces that relationship, and the
    reader (parse_fsh.render_frame) already relies on the equivalent off+frame_len+16 identity.
"""
import argparse
import struct
import sys

from parse_fsh import PALETTE, parse_header, parse_frame, render_frame

try:
    from PIL import Image
except ImportError:
    Image = None


# -- palette matching -----------------------------------------------------------------------

_PALETTE_ITEMS = sorted(PALETTE.items())  # [(index, (r,g,b)), ...] -- stable order for tie-breaks


def build_nearest_index_fn():
    """Returns a function rgb -> nearest palette index, memoized per-call (a portrait typically
    uses only a few dozen distinct colours, so a plain dict cache beats any fancier structure)."""
    cache = {}

    def nearest(rgb):
        hit = cache.get(rgb)
        if hit is not None:
            return hit
        best_idx, best_dist = 0, None
        r, g, b = rgb
        for idx, (pr, pg, pb) in _PALETTE_ITEMS:
            dr, dg, db = r - pr, g - pg, b - pb
            dist = dr * dr + dg * dg + db * db
            if best_dist is None or dist < best_dist:
                best_dist, best_idx = dist, idx
        cache[rgb] = best_idx
        return best_idx

    return nearest


# -- encoding ---------------------------------------------------------------------------------

ALPHA_THRESHOLD = 128  # matches the format's binary (all-or-nothing) transparency


def _find_runs(row_opaque):
    """row_opaque: list[bool], one per column. Returns [(x_start, x_end_exclusive), ...] for each
    maximal contiguous True run, left to right."""
    runs = []
    x = 0
    n = len(row_opaque)
    while x < n:
        if not row_opaque[x]:
            x += 1
            continue
        start = x
        while x < n and row_opaque[x]:
            x += 1
        runs.append((start, x))
    return runs


def _pad_left_if_needed(rows_idx, rows_opaque, width):
    """If row 0's leftmost opaque pixel would land at local x=0, every other row is untouched but
    row 0's first run becomes unencodable (see module docstring). Shift the whole frame 1px right
    to guarantee it never happens -- cheap (one extra all-transparent column) and fully general."""
    if rows_opaque and rows_opaque[0] and rows_opaque[0][0]:
        for r in rows_opaque:
            r.insert(0, False)
        for r in rows_idx:
            r.insert(0, 0)
        return width + 1, 1
    return width, 0


def encode_pixels(width, height, rows_idx, rows_opaque):
    """rows_idx[y][x] = palette index (only meaningful where rows_opaque[y][x] is True).
    Returns (pixel_bytes, n_records) -- n_records is the count of [dlen][posval] records written,
    which the frame header's own "unk2" field stores verbatim (confirmed against real files, see
    build_frame_bytes)."""
    out = bytearray()
    n_records = 0
    for y in range(height):
        runs = _find_runs(rows_opaque[y])
        if not runs:
            out += struct.pack("<Hh", 0, 0)
            n_records += 1
            continue
        for i, (x0, x1) in enumerate(runs):
            # A run advances the row iff it's the first run of a row OTHER than row 0 -- row 0 is
            # already "current" when the stream starts, so even its first run must be a
            # continue-current-row event (see module docstring).
            first_of_row = (i == 0)
            advance = first_of_row and y > 0
            posval = x0 if advance else -x0
            pixels = bytes(rows_idx[y][x0:x1])
            if posval == 0 and not advance:
                # x0 == 0 on a continue-run: structurally impossible (see docstring) -- can only
                # happen on row 0's own first run, which _pad_left_if_needed already prevents.
                raise ValueError(f"row {y} run {i} starts at column 0 and isn't a row-advance -- "
                                  f"this frame needs the left-padding guard, which should already "
                                  f"have prevented this; this is a bug in the encoder, not the input.")
            out += struct.pack("<Hh", len(pixels), posval)
            out += pixels
            n_records += 1
    return bytes(out), n_records


def image_to_frame_data(img, nearest_fn):
    """img: a PIL RGBA image, straight from extraction (or an edited copy of the same size/
    convention -- alpha 0 = transparent, else opaque; see ALPHA_THRESHOLD). Auto-crops to the
    tight bounding box of its opaque pixels (matching how every real frame is stored) and applies
    the row-0 left-padding guard. Returns (pixel_bytes, n_records, width, height, dx, dy) where
    (dx, dy) is how far the returned frame's local (0,0) has moved relative to the input image's
    (0,0) -- add this to the ORIGINAL frame's (xoff, yoff) to get the new frame's (xoff, yoff)."""
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    opaque = [[px[x, y][3] >= ALPHA_THRESHOLD for x in range(w)] for y in range(h)]
    xs = [x for y in range(h) for x in range(w) if opaque[y][x]]
    ys = [y for y in range(h) for x in range(w) if opaque[y][x]]
    if not xs:
        raise ValueError("this image is fully transparent -- nothing to pack")
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    crop_w = x_max - x_min + 1
    crop_h = y_max - y_min + 1

    rows_opaque = [[opaque[y][x] for x in range(x_min, x_max + 1)] for y in range(y_min, y_max + 1)]
    rows_idx = [[nearest_fn(px[x, y][:3]) if opaque[y][x] else 0 for x in range(x_min, x_max + 1)]
                for y in range(y_min, y_max + 1)]

    crop_w, left_pad = _pad_left_if_needed(rows_idx, rows_opaque, crop_w)

    pixel_bytes, n_records = encode_pixels(crop_w, crop_h, rows_idx, rows_opaque)
    dx = x_min - left_pad
    dy = y_min
    return pixel_bytes, n_records, crop_w, crop_h, dx, dy


# -- frame (re)building -------------------------------------------------------------------------

FRAME_HEADER_SIZE = 30
FRAME_LEN_FUDGE = 14  # empirical: frame_len field == len(pixel data) + 14, see module docstring


def build_frame_bytes(*, frame_num, prev, nxt, xoff, yoff, width, height, pixel_bytes, n_records):
    frame_len = len(pixel_bytes) + FRAME_LEN_FUDGE
    header = struct.pack("<IIIIIHhhHH", frame_len, frame_num, prev, nxt,
                          frame_len,  # "unk1" -- confirmed against every real frame sampled (icon,
                                      # detailed, and multiple animation frames across files): this
                                      # field always exactly equals frame_len, not a separate value.
                          n_records,  # "unk2" -- confirmed to equal the exact count of [dlen][posval]
                                      # records in the pixel stream, including blank-row markers.
                          xoff, yoff, width, height)
    assert len(header) == FRAME_HEADER_SIZE
    return header + pixel_bytes


# -- high-level extract / repack -----------------------------------------------------------------

FRAME_KINDS = ("detailed", "icon")  # anim frames are a chain, not a single named slot; see --anim-index


def _get_target_frame(data, hdr, which, anim_index):
    if which in ("detailed", "icon"):
        off = hdr[f"{which}_off"]
        if not off:
            raise ValueError(f"this file has no {which} frame (offset is 0)")
        return parse_frame(data, off)
    if which == "anim":
        off = hdr["anim_off"]
        if not off:
            raise ValueError("this file has no animation frames")
        for _ in range(anim_index):
            f = parse_frame(data, off)
            if not f["nxt"]:
                raise ValueError(f"animation chain only has {_ + 1} frame(s), index {anim_index} "
                                  f"is out of range")
            off = f["nxt"]
        return parse_frame(data, off)
    raise ValueError(f"unknown frame kind {which!r}")


def extract_frame(fsh_path, out_png_path, which="detailed", anim_index=0):
    if Image is None:
        raise RuntimeError("Pillow (PIL) is required -- pip install Pillow")
    data = open(fsh_path, "rb").read()
    hdr = parse_header(data)
    frame = _get_target_frame(data, hdr, which, anim_index)
    buf, alpha = render_frame(data, frame)
    w, h = frame["width"], frame["height"]
    img = Image.new("RGBA", (w, h))
    pix = img.load()
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if alpha[i]:
                r, g, b = PALETTE[buf[i]]
                pix[x, y] = (r, g, b, 255)
            else:
                pix[x, y] = (0, 0, 0, 0)
    img.save(out_png_path)
    return dict(name=hdr["name"], which=which, width=w, height=h,
                xoff=frame["xoff"], yoff=frame["yoff"])


def repack_frame(fsh_path, png_path, out_fsh_path, which="detailed", anim_index=0,
                  xoff=None, yoff=None):
    """Replace one frame's pixel data (and, if the edited image's opaque bounding box moved or
    changed size, its width/height/xoff/yoff too) with a re-encoded version of png_path, and
    write the result -- with every downstream absolute offset correctly shifted -- to
    out_fsh_path. The source file is never modified. Returns a stats dict."""
    if Image is None:
        raise RuntimeError("Pillow (PIL) is required -- pip install Pillow")
    data = bytearray(open(fsh_path, "rb").read())
    hdr = parse_header(bytes(data))
    if which == "anim":
        raise ValueError("repacking a single animation frame isn't supported yet -- only "
                          "'detailed' (the portrait) and 'icon' are")
    old_frame = _get_target_frame(bytes(data), hdr, which, anim_index)
    old_off = old_frame["off"]
    old_pixdata_end = old_frame["nxt"] if old_frame["nxt"] else old_off + old_frame["frame_len"] + 16
    old_span = old_pixdata_end - old_off

    img = Image.open(png_path)
    nearest_fn = build_nearest_index_fn()
    pixel_bytes, n_records, new_w, new_h, dx, dy = image_to_frame_data(img, nearest_fn)

    new_xoff = old_frame["xoff"] + dx if xoff is None else xoff
    new_yoff = old_frame["yoff"] + dy if yoff is None else yoff

    new_frame_bytes = build_frame_bytes(
        frame_num=old_frame["frame_num"], prev=old_frame["prev"], nxt=old_frame["nxt"],
        xoff=new_xoff, yoff=new_yoff, width=new_w, height=new_h, pixel_bytes=pixel_bytes,
        n_records=n_records)
    new_span = len(new_frame_bytes)
    delta = new_span - old_span

    out = bytearray()
    out += data[:old_off]
    out += new_frame_bytes
    tail_start = old_off + old_span
    tail = bytearray(data[tail_start:])

    # Patch every absolute-offset field that lives at or after the resized frame: the header's own
    # icon_off/detailed_off/anim_off pointers (repacking the icon, for instance, shifts detailed
    # and anim both -- only the frame that comes right before the one being replaced never moves),
    # and every animation frame's own prev/nxt (each frame chain-links via absolute file offsets).
    # A field of exactly 0 always means "no link" and must stay 0, never be shifted.
    def patch_u32(buf, off, old_val):
        new_val = old_val + delta if old_val >= tail_start else old_val
        struct.pack_into("<I", buf, off, new_val)

    # The header itself always lives before old_off, which is already copied into `out` above, so
    # these writes land safely inside that untouched prefix.
    for field, hdr_off in (("icon_off", 0x8F), ("detailed_off", 0x8B), ("anim_off", 0x93)):
        val = hdr[field]
        if val and val >= tail_start:
            struct.pack_into("<I", out, hdr_off, val + delta)

    if hdr["anim_off"]:
        walk_off = hdr["anim_off"]
        seen = set()
        while walk_off and walk_off not in seen:
            seen.add(walk_off)
            f = parse_frame(bytes(data), walk_off)
            rel = walk_off - tail_start
            if f["prev"]:
                patch_u32(tail, rel + 8, f["prev"])
            if f["nxt"]:
                patch_u32(tail, rel + 12, f["nxt"])
            walk_off = f["nxt"]

    out += tail

    new_total_len = len(out)
    struct.pack_into("<I", out, 0x20, new_total_len)

    with open(out_fsh_path, "wb") as fh:
        fh.write(out)

    return dict(name=hdr["name"], which=which, old_size=(old_frame["width"], old_frame["height"]),
                new_size=(new_w, new_h), old_xoff_yoff=(old_frame["xoff"], old_frame["yoff"]),
                new_xoff_yoff=(new_xoff, new_yoff), delta_bytes=delta,
                old_file_len=len(data), new_file_len=new_total_len)


def main():
    ap = argparse.ArgumentParser(description="Extract or repack an El-Fish .FSH portrait/icon frame.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("extract", help="save a frame to a PNG for editing")
    ex.add_argument("fsh_path")
    ex.add_argument("png_path")
    ex.add_argument("--which", choices=["detailed", "icon", "anim"], default="detailed")
    ex.add_argument("--anim-index", type=int, default=0, help="which frame in the animation chain (0-based)")

    rp = sub.add_parser("repack", help="pack an edited PNG back into a copy of the .FSH")
    rp.add_argument("fsh_path")
    rp.add_argument("png_path")
    rp.add_argument("out_fsh_path")
    rp.add_argument("--which", choices=["detailed", "icon"], default="detailed")
    rp.add_argument("--xoff", type=int, default=None, help="override the frame's stored X offset")
    rp.add_argument("--yoff", type=int, default=None, help="override the frame's stored Y offset")

    args = ap.parse_args()
    if args.cmd == "extract":
        info = extract_frame(args.fsh_path, args.png_path, which=args.which, anim_index=args.anim_index)
        print(f"Extracted {info['which']} frame from '{info['name']}': "
              f"{info['width']}x{info['height']} at (xoff={info['xoff']}, yoff={info['yoff']}) "
              f"-> {args.png_path}")
    elif args.cmd == "repack":
        info = repack_frame(args.fsh_path, args.png_path, args.out_fsh_path, which=args.which,
                             xoff=args.xoff, yoff=args.yoff)
        print(f"Repacked '{info['name']}' {info['which']} frame: "
              f"{info['old_size']} -> {info['new_size']}, "
              f"(xoff,yoff) {info['old_xoff_yoff']} -> {info['new_xoff_yoff']}, "
              f"file {info['old_file_len']} -> {info['new_file_len']} bytes "
              f"({info['delta_bytes']:+d}) -> {args.out_fsh_path}")


if __name__ == "__main__":
    main()
