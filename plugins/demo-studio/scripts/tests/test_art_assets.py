"""Tests for scripts/art_assets.py with synthetic sheets. Run: python -m unittest discover -s scripts/tests -v"""
import contextlib
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import art_assets  # noqa: E402

MAGENTA = (255, 0, 255)
BLUE = (40, 60, 200)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = art_assets.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def canvas(w, h, bg):
    """bg = (r,g,b,a); returns a list of rows of [r,g,b,a]."""
    return [[list(bg) for _ in range(w)] for _ in range(h)]


def rect(img, x, y, w, h, col):
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            img[yy][xx] = list(col)


def save_rgba(path, img):
    h, w = len(img), len(img[0])
    flat = bytearray(v for row in img for px in row for v in px)
    with open(path, "wb") as f:
        f.write(art_assets.encode_png(w, h, flat))


def save_rgb(path, img, ftype=0):
    """RGB PNG with every row in one filter type (0, 3 average or 4 paeth) to test the decoder."""
    h, w = len(img), len(img[0])
    raw, prev = bytearray(), bytearray(w * 3)
    for row in img:
        cur = bytearray(v for px in row for v in px[:3])
        out = bytearray(len(cur))
        for i in range(len(cur)):
            left = cur[i - 3] if i >= 3 else 0
            upleft = prev[i - 3] if i >= 3 else 0
            if ftype == 3:
                pred = (left + prev[i]) >> 1
            elif ftype == 4:
                pred = art_assets._paeth(left, prev[i], upleft)
            else:
                pred = 0
            out[i] = (cur[i] - pred) & 255
        raw.append(ftype)
        raw += out
        prev = cur
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(art_assets.SIGNATURE + art_assets._chunk(b"IHDR", ihdr)
                + art_assets._chunk(b"IDAT", zlib.compress(bytes(raw))) + art_assets._chunk(b"IEND", b""))


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.out = os.path.join(self.d, "assets")

    def tearDown(self):
        self.tmp.cleanup()

    def sheet(self, name="sheet.png"):
        return os.path.join(self.d, name)

    def test_transparent_row_split_in_order(self):
        img = canvas(120, 50, (0, 0, 0, 0))
        rect(img, 10, 10, 20, 30, (200, 0, 0, 255))
        rect(img, 50, 5, 15, 40, (0, 200, 0, 255))
        rect(img, 90, 20, 25, 20, (0, 0, 200, 255))
        save_rgba(self.sheet(), img)
        code, out, err = run("split", self.sheet(), "--out-dir", self.out, "--roles", "dev,qa,ops", "--pad", "2")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["sheet"]["bg"], "transparent")
        self.assertEqual(res["sheet"]["flags"], ["--pad", "2"])
        self.assertEqual([f["role"] for f in res["files"]], ["dev", "qa", "ops"])
        self.assertEqual([(f["w"], f["h"]) for f in res["files"]], [(24, 34), (19, 44), (29, 24)])
        with open(self.sheet(), "rb") as f:
            self.assertEqual(res["sheet"]["sha256"], hashlib.sha256(f.read()).hexdigest())
        for f in res["files"]:
            with open(f["file"], "rb") as fh:
                data = fh.read()
            self.assertEqual(f["sha256"], hashlib.sha256(data).hexdigest())
            w, h, rgba, alpha = art_assets.read_png(f["file"])
            self.assertTrue(alpha)
            self.assertEqual((w, h), (f["w"], f["h"]))
            self.assertEqual(rgba[3], 0)  # pad corner stays transparent
        w, h, rgba, _ = art_assets.read_png(res["files"][0]["file"])
        p = (2 * w + 2) * 4
        self.assertEqual(tuple(rgba[p:p + 4]), (200, 0, 0, 255))

    def test_deterministic_bytes(self):
        img = canvas(60, 30, (0, 0, 0, 0))
        rect(img, 5, 5, 10, 10, (9, 9, 9, 255))
        rect(img, 40, 5, 10, 10, (9, 9, 9, 255))
        save_rgba(self.sheet(), img)
        a = json.loads(run("split", self.sheet(), "--out-dir", self.out, "--roles", "a,b")[1])
        b = json.loads(run("split", self.sheet(), "--out-dir", self.out, "--roles", "a,b")[1])
        self.assertEqual([f["sha256"] for f in a["files"]], [f["sha256"] for f in b["files"]])

    def test_magenta_grid_row_major_and_keyed(self):
        img = canvas(100, 100, MAGENTA + (255,))
        rect(img, 10, 10, 20, 20, BLUE + (255,))
        rect(img, 60, 10, 20, 20, (250, 250, 250, 255))  # white character survives a magenta key
        rect(img, 10, 60, 20, 20, (255, 140, 200, 255))  # pink is not magenta
        rect(img, 60, 60, 20, 20, BLUE + (255,))
        img[10][9] = [230, 20, 240, 255]  # anti-aliased fringe next to magenta
        save_rgb(self.sheet(), img)
        code, out, err = run("split", self.sheet(), "--out-dir", self.out, "--roles", "a,b,c,d", "--pad", "1")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["sheet"]["bg"], "#FF00FF")
        self.assertEqual([(f["src"]["x"], f["src"]["y"]) for f in res["files"]],
                         [(9, 9), (59, 9), (9, 59), (59, 59)])
        w, h, rgba, _ = art_assets.read_png(res["files"][1]["file"])
        self.assertEqual(rgba[3], 0)
        p = (1 * w + 1) * 4
        self.assertEqual(tuple(rgba[p:p + 4]), (250, 250, 250, 255))
        w, h, rgba, _ = art_assets.read_png(res["files"][2]["file"])
        p = (1 * w + 1) * 4
        self.assertEqual(tuple(rgba[p:p + 4]), (255, 140, 200, 255))

    def test_spill_removed_from_partial_edge(self):
        img = canvas(40, 20, MAGENTA + (255,))
        rect(img, 10, 5, 10, 10, BLUE + (255,))
        # 25% blue / 75% magenta at the left edge (anti-aliased fringe)
        blend = [(BLUE[i] + 3 * MAGENTA[i]) // 4 for i in range(3)]
        img[8][9] = blend + [255]
        save_rgb(self.sheet(), img)
        code, out, err = run("split", self.sheet(), "--out-dir", self.out, "--roles", "a", "--tolerance", "40")
        self.assertEqual(code, 0, err)
        f = json.loads(out)["files"][0]
        w, h, rgba, _ = art_assets.read_png(f["file"])
        x, y = 9 - f["src"]["x"], 8 - f["src"]["y"]
        r, g, b, a = rgba[(y * w + x) * 4:(y * w + x) * 4 + 4]
        self.assertTrue(0 < a < 255)
        self.assertLess(r, blend[0] - 50)  # magenta spill taken out of red
        self.assertLess(b, blend[2])  # and out of blue

    def test_white_background_refused(self):
        img = canvas(40, 20, (255, 255, 255, 255))
        rect(img, 10, 5, 10, 10, BLUE + (255,))
        save_rgb(self.sheet(), img)
        code, out, err = run("split", self.sheet(), "--out-dir", self.out, "--roles", "a")
        self.assertEqual(code, 1)
        self.assertIn("white, grey or black", err)
        self.assertFalse(os.path.exists(self.out))

    def test_uneven_corners_refused(self):
        img = canvas(40, 20, MAGENTA + (255,))
        img[0][0] = [0, 255, 0, 255]
        rect(img, 10, 5, 10, 10, BLUE + (255,))
        save_rgb(self.sheet(), img)
        self.assertEqual(run("split", self.sheet(), "--out-dir", self.out, "--roles", "a")[0], 1)

    def test_count_mismatch_exit1_lists_found(self):
        img = canvas(60, 30, (0, 0, 0, 0))
        rect(img, 5, 5, 10, 10, (9, 9, 9, 255))
        rect(img, 40, 5, 10, 10, (9, 9, 9, 255))
        save_rgba(self.sheet(), img)
        code, out, err = run("split", self.sheet(), "--out-dir", self.out, "--roles", "a,b,c")
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(out)["found"]), 2)
        self.assertFalse(os.path.exists(self.out))

    def test_speck_ignored_and_small_gap_merged(self):
        img = canvas(100, 60, (0, 0, 0, 0))
        rect(img, 10, 20, 20, 30, (9, 9, 9, 255))
        rect(img, 12, 10, 16, 5, (9, 9, 9, 255))  # hat 5 px above: same character
        rect(img, 60, 20, 20, 30, (9, 9, 9, 255))
        rect(img, 92, 2, 2, 2, (9, 9, 9, 255))  # sparkle
        save_rgba(self.sheet(), img)
        code, out, err = run("split", self.sheet(), "--out-dir", self.out, "--roles", "a,b", "--pad", "0")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual((res["files"][0]["src"]["y"], res["files"][0]["h"]), (10, 40))
        self.assertEqual(len(res["ignored"]), 1)

    def test_dry_run_writes_nothing(self):
        img = canvas(60, 30, (0, 0, 0, 0))
        rect(img, 5, 5, 10, 10, (9, 9, 9, 255))
        save_rgba(self.sheet(), img)
        code, out, _ = run("split", self.sheet(), "--out-dir", self.out, "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["found"]), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_touches_edge_flag(self):
        img = canvas(40, 20, (0, 0, 0, 0))
        rect(img, 0, 5, 10, 10, (9, 9, 9, 255))
        save_rgba(self.sheet(), img)
        res = json.loads(run("split", self.sheet(), "--out-dir", self.out, "--roles", "a")[1])
        self.assertTrue(res["files"][0]["touches_edge"])

    def test_decoder_average_and_paeth(self):
        img = canvas(30, 12, MAGENTA + (255,))
        for y in range(12):
            for x in range(30):
                img[y][x] = [(x * 7 + y * 3) % 256, (x * y) % 256, (255 - x * 5) % 256, 255]
        for ft in (3, 4):
            save_rgb(self.sheet(), img, ftype=ft)
            w, h, rgba, alpha = art_assets.read_png(self.sheet())
            self.assertFalse(alpha)
            self.assertEqual(list(rgba), [v for row in img for px in row for v in px], "filter %d" % ft)

    def test_usage_errors_exit2(self):
        bad = self.sheet("bad.png")
        with open(bad, "wb") as f:
            f.write(b"not a png")
        self.assertEqual(run("split", bad, "--roles", "a")[0], 2)
        self.assertEqual(run("split", self.sheet("missing.png"), "--roles", "a")[0], 2)
        img = canvas(10, 10, (0, 0, 0, 0))
        save_rgba(self.sheet(), img)
        self.assertEqual(run("split", self.sheet(), "--out-dir", self.out)[0], 2)  # no roles
        self.assertEqual(run("split", self.sheet(), "--roles", "a,a")[0], 2)
        self.assertEqual(run("split", self.sheet(), "--roles", "a", "--bg", "#12")[0], 2)
        ihdr16 = struct.pack(">IIBBBBB", 1, 1, 16, 6, 0, 0, 0)
        with open(bad, "wb") as f:
            f.write(art_assets.SIGNATURE + art_assets._chunk(b"IHDR", ihdr16)
                    + art_assets._chunk(b"IDAT", zlib.compress(b"\x00" + b"\x00" * 8)) + art_assets._chunk(b"IEND", b""))
        code, _, err = run("split", bad, "--roles", "a")
        self.assertEqual(code, 2)
        self.assertIn("8-bit", err)


if __name__ == "__main__":
    unittest.main()
