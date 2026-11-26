#!/usr/bin/env python3
"""Split one user-approved character sheet into one RGBA PNG per character. Stdlib only, Python 3.9+.

key-art takes the user's characters from ONE generated image (all roles on one sheet, row by row,
left to right). This cuts it so agents never improvise image code. Input: 8-bit RGB or RGBA PNG,
not interlaced. Background: transparent, or one saturated key colour (e.g. #FF00FF), never white,
grey or black (a neutral key would also cut the character's own whites, eyes and outlines).

  art_assets.py split SHEET --out-dir DIR --roles r1,r2,... [--bg auto|transparent|#RRGGBB]
                [--tolerance 48] [--min-gap 12] [--min-area 0.02] [--pad 4] [--dry-run]
      Finds the characters (rows separated by empty rows of at least min-gap px, then columns
      separated the same way inside each row), orders them row by row, left to right, and maps
      them to --roles in that order. Writes DIR/c01.png, c02.png, ... (tight crop + pad, RGBA;
      a key colour is removed with soft edges and its spill taken out). Clusters smaller than
      min-area x the largest one (sparkles, specks) are ignored and listed. Prints one JSON
      object: sheet {w,h,sha256,bg,flags (the non-default flags, to re-run the split)}, files [{id,role,file,w,h,sha256,src{x,y,w,h},touches_edge}],
      ignored [{x,y,w,h,pixels}]. --dry-run writes nothing (--roles optional) and lists the
      clusters it found. The output is deterministic: same sheet + flags = same bytes.

Exit codes: 0 ok, 1 split failed (found count != roles, no usable background), 2 usage,
unreadable or unsupported PNG.
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PIXELS = 4096 * 4096
ALPHA_MIN = 16      # alpha at or above this counts as character
OCCUPIED_MIN = 2    # a row/column with fewer character pixels counts as empty
NEUTRAL_SPREAD = 96  # key colour must have max-min channel spread >= this (saturated)


class ArtError(Exception):
    def __init__(self, msg, code=2, extra=None):
        Exception.__init__(self, msg)
        self.code = code
        self.extra = extra or {}


# ---------- PNG read / write ----------

def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path):
    """Return (w, h, rgba bytearray, has_alpha)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise ArtError("%s: %s" % (path, e))
    if data[:8] != SIGNATURE:
        raise ArtError("%s: not a PNG file" % path)
    pos, idat, ihdr = 8, [], None
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if len(body) != length:
            raise ArtError("%s: truncated chunk %r" % (path, ctype))
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if not ihdr or not idat:
        raise ArtError("%s: missing IHDR or IDAT" % path)
    w, h, depth, ctype, _comp, _filt, interlace = ihdr
    if depth != 8 or ctype not in (2, 6) or interlace != 0:
        raise ArtError("%s: only 8-bit RGB/RGBA non-interlaced PNG is supported (bit depth %d, "
                       "colour type %d, interlace %d); re-save it as 8-bit RGBA PNG"
                       % (path, depth, ctype, interlace))
    if w * h > MAX_PIXELS or w == 0 or h == 0:
        raise ArtError("%s: %dx%d is outside 1..%d pixels" % (path, w, h, MAX_PIXELS))
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise ArtError("%s: corrupt image data (%s)" % (path, e))
    bpp = 4 if ctype == 6 else 3
    stride = w * bpp
    if len(raw) < h * (stride + 1):
        raise ArtError("%s: image data too short" % path)
    pix = bytearray(h * stride)
    prev = bytearray(stride)
    for y in range(h):
        off = y * (stride + 1)
        ftype = raw[off]
        row = bytearray(raw[off + 1:off + 1 + stride])
        if ftype == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 255
        elif ftype == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 255
        elif ftype == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 255
        elif ftype == 4:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + _paeth(left, prev[i], upleft)) & 255
        elif ftype != 0:
            raise ArtError("%s: bad filter type %d on row %d" % (path, ftype, y))
        pix[y * stride:(y + 1) * stride] = row
        prev = row
    if ctype == 6:
        return w, h, pix, True
    rgba = bytearray(w * h * 4)
    for c in range(3):
        rgba[c::4] = pix[c::3]
    rgba[3::4] = b"\xff" * (w * h)
    return w, h, rgba, False


def _chunk(ctype, body):
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def encode_png(w, h, rgba):
    """RGBA 8-bit PNG; per row the smallest of filters None/Sub/Up (deterministic)."""
    stride = w * 4
    out = bytearray()
    prev = bytes(stride)
    for y in range(h):
        row = rgba[y * stride:(y + 1) * stride]
        sub = bytearray(stride)
        up = bytearray(stride)
        for i in range(stride):
            sub[i] = (row[i] - (row[i - 4] if i >= 4 else 0)) & 255
            up[i] = (row[i] - prev[i]) & 255
        best, best_ft = row, 0
        best_cost = sum(v if v < 128 else 256 - v for v in row)
        for ft, cand in ((1, sub), (2, up)):
            cost = sum(v if v < 128 else 256 - v for v in cand)
            if cost < best_cost:
                best, best_ft, best_cost = cand, ft, cost
        out.append(best_ft)
        out += best
        prev = row
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(out), 9)) + _chunk(b"IEND", b"")


# ---------- background ----------

def parse_hex(s):
    s = s.strip().lstrip("#")
    if len(s) != 6:
        raise ArtError("--bg must be auto, transparent or #RRGGBB (got %r)" % s)
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise ArtError("--bg must be auto, transparent or #RRGGBB (got %r)" % s)


def hexcol(c):
    return "#%02X%02X%02X" % tuple(c)


def _corners(w, h, rgba):
    pts = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    return [tuple(rgba[(y * w + x) * 4:(y * w + x) * 4 + 4]) for x, y in pts]


def detect_bg(w, h, rgba, has_alpha, want, tolerance):
    """Return 'transparent' or an (r, g, b) key colour."""
    corners = _corners(w, h, rgba)
    if want == "transparent" or (want == "auto" and has_alpha and all(c[3] < ALPHA_MIN for c in corners)):
        if not has_alpha or not all(c[3] < ALPHA_MIN for c in corners):
            raise ArtError("background is not transparent at the corners; regenerate the sheet with a "
                           "transparent background or a solid #FF00FF one", code=1)
        return "transparent"
    if want == "auto":
        if any(c[3] < 255 for c in corners):
            raise ArtError("corners are partly transparent; use --bg transparent or regenerate", code=1)
        key = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
        if any(max(abs(c[i] - key[i]) for i in range(3)) > tolerance for c in corners):
            raise ArtError("the four corners differ (%s); the background is not one solid colour"
                           % ", ".join(hexcol(c[:3]) for c in corners), code=1)
    else:
        key = parse_hex(want)
    if max(key) - min(key) < NEUTRAL_SPREAD:
        raise ArtError("background %s is white, grey or black; keying it would cut the characters' "
                       "own whites and outlines. Regenerate with a transparent or #FF00FF background"
                       % hexcol(key), code=1)
    return key


def key_out(rgba, key, tolerance):
    """Remove a key colour in place: soft alpha ramp over [tolerance, 2*tolerance], spill removed."""
    kr, kg, kb = key
    t0, t1 = tolerance, tolerance * 2
    span = float(t1 - t0)
    for p in range(0, len(rgba), 4):
        r, g, b = rgba[p], rgba[p + 1], rgba[p + 2]
        d = max(abs(r - kr), abs(g - kg), abs(b - kb))
        if d >= t1:
            continue
        if d <= t0:
            rgba[p:p + 4] = b"\x00\x00\x00\x00"
            continue
        a = (d - t0) / span
        inv = 1.0 - a
        rgba[p] = min(255, max(0, int(round((r - inv * kr) / a))))
        rgba[p + 1] = min(255, max(0, int(round((g - inv * kg) / a))))
        rgba[p + 2] = min(255, max(0, int(round((b - inv * kb) / a))))
        rgba[p + 3] = min(255, int(round(a * rgba[p + 3])))


# ---------- clustering ----------

def _runs(counts, min_gap):
    """Occupied runs [(start, end_exclusive)], merging gaps shorter than min_gap."""
    runs, start, last = [], None, None
    for i, n in enumerate(counts):
        if n >= OCCUPIED_MIN:
            if start is None:
                start = i
            elif i - last - 1 >= min_gap:
                runs.append((start, last + 1))
                start = i
            last = i
    if start is not None:
        runs.append((start, last + 1))
    return runs


def find_clusters(w, h, rgba, min_gap, min_area):
    alpha = rgba[3::4]
    mask = bytes(1 if a >= ALPHA_MIN else 0 for a in alpha)
    row_counts = [sum(mask[y * w:(y + 1) * w]) for y in range(h)]
    found = []
    for y0, y1 in _runs(row_counts, min_gap):
        col_counts = [0] * w
        for y in range(y0, y1):
            row = mask[y * w:(y + 1) * w]
            for x in range(w):
                if row[x]:
                    col_counts[x] += 1
        for x0, x1 in _runs(col_counts, min_gap):
            ys = [y for y in range(y0, y1) if any(mask[y * w + x0:y * w + x1])]
            cy0, cy1 = ys[0], ys[-1] + 1
            pixels = sum(sum(mask[y * w + x0:y * w + x1]) for y in range(cy0, cy1))
            found.append({"x": x0, "y": cy0, "w": x1 - x0, "h": cy1 - cy0, "pixels": pixels})
    if not found:
        return [], []
    biggest = max(c["pixels"] for c in found)
    keep = [c for c in found if c["pixels"] >= min_area * biggest]
    ignored = [c for c in found if c["pixels"] < min_area * biggest]
    return keep, ignored


def crop(w, h, rgba, box, pad):
    x0, y0 = max(0, box["x"] - pad), max(0, box["y"] - pad)
    x1, y1 = min(w, box["x"] + box["w"] + pad), min(h, box["y"] + box["h"] + pad)
    cw, ch = x1 - x0, y1 - y0
    out = bytearray(cw * ch * 4)
    for y in range(ch):
        src = ((y0 + y) * w + x0) * 4
        out[y * cw * 4:(y + 1) * cw * 4] = rgba[src:src + cw * 4]
    return x0, y0, cw, ch, out


# ---------- command ----------

def split(args):
    roles = [r.strip() for r in (args.roles or "").split(",") if r.strip()]
    if not roles and not args.dry_run:
        raise ArtError("--roles is required (one role per character, row by row, left to right)")
    if len(set(roles)) != len(roles):
        raise ArtError("--roles has a duplicate role")
    if args.tolerance < 1 or args.tolerance > 127 or args.min_gap < 1 or args.pad < 0 or not 0 <= args.min_area < 1:
        raise ArtError("bad --tolerance (1-127), --min-gap (>=1), --pad (>=0) or --min-area (0-1)")
    with open(args.sheet, "rb") as f:
        sheet_sha = hashlib.sha256(f.read()).hexdigest()
    w, h, rgba, has_alpha = read_png(args.sheet)
    bg = detect_bg(w, h, rgba, has_alpha, args.bg, args.tolerance)
    if bg != "transparent":
        key_out(rgba, bg, args.tolerance)
    keep, ignored = find_clusters(w, h, rgba, args.min_gap, args.min_area)
    flags = []
    for name, default in (("bg", "auto"), ("tolerance", 48), ("min_gap", 12), ("min_area", 0.02), ("pad", 4)):
        if getattr(args, name) != default:
            flags += ["--" + name.replace("_", "-"), str(getattr(args, name))]
    result = {"sheet": {"w": w, "h": h, "sha256": sheet_sha,
                        "bg": "transparent" if bg == "transparent" else hexcol(bg), "flags": flags},
              "files": [], "ignored": ignored}
    if args.dry_run:
        result["found"] = [{k: c[k] for k in ("x", "y", "w", "h", "pixels")} for c in keep]
    if roles and len(keep) != len(roles):
        raise ArtError("found %d characters, expected %d (%s); regenerate the sheet with the characters "
                       "apart (no overlap, no shared shadow) or tune --min-gap / --min-area"
                       % (len(keep), len(roles), ",".join(roles)), code=1,
                       extra={"sheet": result["sheet"], "found": [{k: c[k] for k in ("x", "y", "w", "h", "pixels")}
                                                                   for c in keep], "ignored": ignored})
    if args.dry_run:
        print(json.dumps(result, indent=2))
        return 0
    os.makedirs(args.out_dir, exist_ok=True)
    for i, (box, role) in enumerate(zip(keep, roles), 1):
        x0, y0, cw, ch, pix = crop(w, h, rgba, box, args.pad)
        png = encode_png(cw, ch, pix)
        cid = "c%02d" % i
        path = os.path.join(args.out_dir, cid + ".png")
        with open(path, "wb") as f:
            f.write(png)
        touches = box["x"] == 0 or box["y"] == 0 or box["x"] + box["w"] == w or box["y"] + box["h"] == h
        result["files"].append({"id": cid, "role": role, "file": path, "w": cw, "h": ch,
                                "sha256": hashlib.sha256(png).hexdigest(),
                                "src": {"x": x0, "y": y0, "w": cw, "h": ch}, "touches_edge": touches})
    print(json.dumps(result, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="art_assets.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split", help="cut a character sheet into one PNG per character")
    s.add_argument("sheet")
    s.add_argument("--out-dir", default="art/assets")
    s.add_argument("--roles", default="")
    s.add_argument("--bg", default="auto")
    s.add_argument("--tolerance", type=int, default=48)
    s.add_argument("--min-gap", type=int, default=12)
    s.add_argument("--min-area", type=float, default=0.02)
    s.add_argument("--pad", type=int, default=4)
    s.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        return split(args)
    except ArtError as e:
        sys.stderr.write("art_assets: %s\n" % e)
        if e.extra:
            print(json.dumps(dict(e.extra, error=str(e)), indent=2))
        return e.code
    except OSError as e:
        sys.stderr.write("art_assets: %s\n" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
