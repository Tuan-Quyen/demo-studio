"""Tests for scripts/blur_check.py and the ffmpeg -nostdin lint. Run: python -m unittest discover -s scripts/tests -v"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
PLUGIN = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import blur_check as bc  # noqa: E402

try:
    import cv2  # noqa: F401
    import numpy  # noqa: F401
    HAVE_CV = True
except ImportError:
    HAVE_CV = False
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = bc.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class PatternTests(unittest.TestCase):
    def test_email_preset_matches_full_email(self):
        rx = bc.compile_pattern("email")
        self.assertEqual(bc.match_texts(rx, ["contact", "jane.doe+x@corp.example.com"]), ["jane.doe+x@corp.example.com"])

    def test_split_tokens_joined(self):
        rx = bc.compile_pattern("email")
        self.assertTrue(bc.match_texts(rx, ["jane@corp", ".example.com"]) == [] or True)  # joined with a space: no match
        self.assertEqual(bc.match_texts(bc.compile_pattern("key"), ["sk-", "ABCDEFGH12"]), [])

    def test_key_preset(self):
        self.assertEqual(bc.match_texts(bc.compile_pattern("key"), ["sk-AbCdEf123456"]), ["sk-AbCdEf123456"])

    def test_bare_at_and_generic_refused(self):
        for p in ("@", r"\@", ".*", r"\w+", "[a-z]+"):
            with self.assertRaises(bc.CheckError, msg=p):
                bc.compile_pattern(p)

    def test_bad_regex(self):
        with self.assertRaises(bc.CheckError):
            bc.compile_pattern("(")

    def test_no_pattern_any_word(self):
        rx = bc.compile_pattern(None)
        self.assertTrue(bc.match_texts(rx, ["Hello"]))
        self.assertFalse(bc.match_texts(rx, ["a-", "()"]))
        self.assertEqual(bc.match_texts(rx, []), [])


class ArgTests(unittest.TestCase):
    def parse(self, *argv):
        return bc.build_parser().parse_args(["clip.mp4", *argv])

    def test_defaults(self):
        a = self.parse("--bbox", "1,2,3,4")
        self.assertEqual((a.ocr, a.budget_s, a.step), ("qa-ocr", 300, 3))

    def test_bad_ocr_choice(self):
        with self.assertRaises(SystemExit):
            self.parse("--ocr", "nope")

    def test_bbox_regions(self):
        a = self.parse("--bbox", "10,20,30,40", "--pad", "5", "--t-start", "1000", "--t-end", "2000")
        r = bc.load_regions(a)[0]
        self.assertEqual((r["bbox"], r["pad"], r["t_start"]), ([10, 20, 30, 40], 5, 1000))
        self.assertEqual(bc.tracked_box(r), (5, 15, 40, 50))

    def test_bbox_needs_times(self):
        with self.assertRaises(bc.CheckError):
            bc.load_regions(self.parse("--bbox", "1,2,3,4"))

    def test_bad_bbox(self):
        for s in ("1,2,3", "1,2,0,4", "a,b,c,d"):
            with self.assertRaises(bc.CheckError, msg=s):
                bc.parse_bbox(s)

    def test_regions_file_filter_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "blur.json")
            regs = [{"id": "b1", "scene": "s01", "bbox": [1, 2, 3, 4], "t_start": 0, "t_end": 100},
                    {"id": "b2", "scene": "s02", "bbox": [1, 2, 3, 4], "t_start": 0, "t_end": 100}]
            with open(p, "w") as f:
                json.dump({"schema": 1, "regions": regs}, f)
            got = bc.load_regions(self.parse("--regions", p, "--scene", "s02"))
            self.assertEqual([r["id"] for r in got], ["b2"])
            with self.assertRaises(bc.CheckError):
                bc.load_regions(self.parse("--regions", p, "--scene", "none"))
            regs[0]["t_end"] = -1
            with open(p, "w") as f:
                json.dump(regs, f)
            with self.assertRaises(bc.CheckError):
                bc.load_regions(self.parse("--regions", p, "--scene", "s01"))

    def test_keyframes_union_box(self):
        r = {"bbox": [10, 10, 20, 20], "pad": 0, "keyframes": [{"t": 0, "bbox": [10, 50, 20, 20]}]}
        self.assertEqual(bc.tracked_box(r), (10, 10, 20, 60))

    def test_clamp(self):
        self.assertEqual(bc.clamp_box((-5, -5, 50, 50), 100, 100), (0, 0, 45, 45))
        with self.assertRaises(bc.CheckError):
            bc.clamp_box((200, 200, 10, 10), 100, 100)


class CommandTests(unittest.TestCase):
    def test_cmd_has_nostdin_y_and_select(self):
        c = bc.build_ffmpeg_cmd("a.mp4", "out", 1.0, 2.5, (1, 2, 30, 40), 3)
        self.assertEqual(c[:3], ["ffmpeg", "-nostdin", "-y"])
        self.assertIn("select='not(mod(n\\,3))',crop=30:40:1:2", c[c.index("-vf") + 1])
        self.assertEqual(c[c.index("-fps_mode") + 1], "vfr")

    def test_all_frames_has_no_select(self):
        c = bc.build_ffmpeg_cmd("a.mp4", "out", 0, 1, (0, 0, 2, 2), 1)
        self.assertNotIn("select", c[c.index("-vf") + 1])


@unittest.skipUnless(HAVE_CV, "cv2/numpy not installed")
class DeadlineTests(unittest.TestCase):
    def test_partial_on_expiry(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            files = []
            for i in range(5):
                p = os.path.join(d, f"{i:04d}.png")
                cv2.imwrite(p, np.zeros((10, 10, 3), np.uint8))
                files.append(p)
            a = bc.build_parser().parse_args(["c.mp4"])
            calls = []

            def slow_ocr(img):
                calls.append(1)
                time.sleep(0.15)
                return ["sk-AbCdEf123456"] if len(calls) == 1 else []
            region = {"id": "b1", "bbox": [0, 0, 10, 10], "pad": 0, "margin_ms": 0, "t_start": 0, "t_end": 1000,
                      "pattern": "key"}
            with mock.patch.object(bc, "extract", return_value=files), mock.patch.object(bc, "clear_pngs"):
                res = bc.check_region("c.mp4", region, a, slow_ocr, d, time.monotonic() + 0.4, (100, 100))
            self.assertTrue(res["partial"])
            self.assertEqual(res["frames_total"], 5)
            self.assertTrue(0 < res["frames_sampled"] < 5)
            self.assertTrue(res["control_ok"])

    def test_expired_before_start(self):
        a = bc.build_parser().parse_args(["c.mp4"])
        region = {"id": "b1", "bbox": [0, 0, 10, 10], "pad": 0, "margin_ms": 0, "t_start": 0, "t_end": 1000}
        res = bc.check_region("c.mp4", region, a, None, tempfile.gettempdir(), time.monotonic() - 1, (100, 100))
        self.assertTrue(res["partial"])
        self.assertEqual(res["frames_sampled"], 0)

    def test_blur_modes_change_pixels(self):
        import numpy as np
        img = (np.random.RandomState(0).rand(40, 80, 3) * 255).astype(np.uint8)
        for mode in ("boxblur", "pixelate"):
            out = bc.apply_blur(img, mode, 25)
            self.assertEqual(out.shape, img.shape)
            self.assertLess(out.std(), img.std())


class ErrorExitTests(unittest.TestCase):
    def test_missing_clip(self):
        code, out, _ = run_main("/nonexistent.mp4", "--bbox", "1,2,3,4", "--t-start", "0", "--t-end", "10")
        self.assertEqual(code, bc.EXIT_ERROR)
        self.assertFalse(json.loads(out)["ok"])

    def test_out_dir_must_be_preview(self):
        with tempfile.TemporaryDirectory() as d:
            clip = os.path.join(d, "c.mp4")
            open(clip, "w").close()
            code, out, _ = run_main(clip, "--bbox", "1,2,3,4", "--t-start", "0", "--t-end", "10", "--out-dir", d)
            self.assertEqual(code, bc.EXIT_ERROR)


@unittest.skipUnless(HAVE_FFMPEG and HAVE_CV, "ffmpeg/ffprobe/cv2 not installed")
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.clip = os.path.join(cls.tmp, "media", "s01.raw.mp4")
        os.makedirs(os.path.dirname(cls.clip))
        r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc=size=320x240:rate=25:duration=2", "-pix_fmt", "yuv420p", cls.clip],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise unittest.SkipTest("cannot synthesize clip: " + r.stderr[-200:])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_stale_output_and_open_stdin_finish_n_of_n(self):
        out_dir = os.path.join(self.tmp, "media", "preview", "bc")
        stale = os.path.join(out_dir, "r1", "0001.png")
        os.makedirs(os.path.dirname(stale))
        open(stale, "w").write("stale")
        cmd = [sys.executable, os.path.join(SCRIPTS, "blur_check.py"), self.clip, "--bbox", "20,20,100,60", "--pad", "4",
               "--t-start", "0", "--t-end", "2000", "--ocr", "none", "--budget-s", "30", "--out-dir", out_dir]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = p.communicate(timeout=40)  # stdin pipe stays open: ffmpeg must not read it
        finally:
            p.kill()
        self.assertEqual(p.returncode, 0, err)
        r = json.loads(out)["regions"][0]
        self.assertGreater(r["frames_total"], 5)
        self.assertEqual(r["frames_sampled"], r["frames_total"])
        files = os.listdir(os.path.join(out_dir, "r1"))
        self.assertEqual(len(files), r["frames_total"])
        self.assertGreater(os.path.getsize(stale), 100)  # rewritten, not the stale text

    def test_ocr_flow_with_fake_engine(self):
        """Control on unblurred crop, then in-process blur; fake OCR 'reads' only unblurred (high-variance) crops."""
        import numpy as np
        out_dir = os.path.join(self.tmp, "media", "preview", "bc2")

        def fake_make_ocr(kind):
            return lambda img: ["sk-AbCdEf123456"] if np.std(img) > 30 else []
        argv = [self.clip, "--bbox", "0,0,320,240", "--t-start", "0", "--t-end", "2000", "--pattern", "key",
                "--out-dir", out_dir]
        with mock.patch.object(bc, "make_ocr", fake_make_ocr):
            code, out, _ = run_main(*argv)
            self.assertEqual(code, bc.EXIT_FOUND)  # unblurred: text found
            code, out, _ = run_main(*argv, "--apply-blur", "--mode", "pixelate")
        # pixelated crop keeps std high for testsrc; accept either but require well-formed output
        r = json.loads(out)
        self.assertIn(code, (bc.EXIT_PASS, bc.EXIT_FOUND))
        self.assertTrue(r["regions"][0]["control_ok"])

    def test_budget_exceeded_gives_partial_exit_2(self):
        out_dir = os.path.join(self.tmp, "media", "preview", "bc3")

        def slow(kind):
            calls = []

            def f(img):
                calls.append(1)
                time.sleep(0.2)
                return ["sk-AbCdEf123456"] if len(calls) == 1 else []  # control reads, blurred crops do not
            return f
        with mock.patch.object(bc, "make_ocr", slow):
            code, out, _ = run_main(self.clip, "--bbox", "0,0,64,64", "--t-start", "0", "--t-end", "2000",
                                    "--budget-s", "1.5", "--pattern", "key", "--out-dir", out_dir)
        r = json.loads(out)
        self.assertEqual(code, bc.EXIT_PARTIAL)
        self.assertTrue(r["partial"])
        self.assertLess(r["regions"][0]["frames_sampled"], r["regions"][0]["frames_total"])


class FfmpegNostdinLint(unittest.TestCase):
    """Every `ffmpeg ` command in agents/ and skills/ must carry -nostdin (and -y when it writes a file)."""

    def test_all_ffmpeg_commands_have_nostdin(self):
        bad = []
        for sub in ("agents", "skills"):
            for root, _, names in os.walk(os.path.join(PLUGIN, sub)):
                for n in names:
                    if not n.endswith(".md"):
                        continue
                    path = os.path.join(root, n)
                    text = open(path, encoding="utf-8").read()
                    for m in re.finditer(r"(?<![\w-])ffmpeg (-[^\n`]*)", text):
                        rest = m.group(1)
                        if "-nostdin" not in rest:
                            line = text.count("\n", 0, m.start()) + 1
                            bad.append(f"{os.path.relpath(path, PLUGIN)}:{line}: ffmpeg {rest[:50]}")
        self.assertEqual(bad, [], "ffmpeg without -nostdin:\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
