"""Tests for privacy_mask.js + capture.py (P0-B). Real Chromium recordings of tests/fixtures/react-list.

Needs node + playwright (Chromium preinstalled; never `playwright install`), ffmpeg/ffprobe and numpy; skipped otherwise.
Run: cd plugins/demo-studio/scripts && python3 -m pytest -q tests/test_privacy_mask.py
Optional OCR cross-check runs only when rapidocr is importable.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
import capture  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "react-list")
INDEX = "file://" + os.path.join(FIX, "index.html")
STATIC = "file://" + os.path.join(FIX, "static.html")
TEXT_ONLY = "file://" + os.path.join(FIX, "text_only.html")
REGEXES = [r"[\w.+-]+@[\w-]+\.[\w.]+", r"sk_live_[A-Za-z0-9]+", r"\b\d{3}-\d{2}-\d{4}\b"]
SET_NOTE = ("(()=>{const i=document.getElementById('note');i.value='ssn 123-45-6789';"
            "i.dispatchEvent(new Event('input',{bubbles:true}));})()")
# ~5 s of scenario: window scroll down and back, inner list scroll, late toast (2 s after load), typed SSN
ACTIONS = [{"op": "wait", "ms": 500}, {"op": "scroll", "to": 500, "ms": 1000},
           {"op": "scroll_el", "selector": "#inner", "to": 300, "ms": 800}, {"op": "wait", "ms": 1500},
           {"op": "eval", "js": SET_NOTE}, {"op": "scroll", "to": 0, "ms": 600}, {"op": "wait", "ms": 300}]

HAVE = all(shutil.which(x) for x in ("node", "ffmpeg", "ffprobe"))
try:
    import numpy  # noqa: F401
except ImportError:
    HAVE = False
if HAVE:
    HAVE = subprocess.run(["node", "-e", "require('playwright')"], cwd=SCRIPTS, capture_output=True).returncode == 0


def run_capture(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = capture.main(list(argv))
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


def write_json(d, name, obj):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        json.dump(obj, f)
    return p


class PixelUnit(unittest.TestCase):
    """check_rect on synthetic frames: no browser needed."""

    def setUp(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy missing")
        self.np = np
        self.pill = capture.hex_rgb(capture.DEFAULT_PILL)
        self.frame = np.full((100, 200, 3), 255, dtype=np.uint8)

    def test_pill_passes_text_fails(self):
        np = self.np
        self.frame[20:40, 20:120] = self.pill
        self.assertIsNone(capture.check_rect(self.frame, [20, 20, 100, 20], self.pill, False))
        rng = np.random.RandomState(1)
        self.frame[20:40, 20:120] = rng.choice([0, 255], size=(20, 100, 1)).repeat(3, 2)  # glyph-like edges
        self.assertIn("not_uniform", capture.check_rect(self.frame, [20, 20, 100, 20], self.pill, False))

    def test_white_is_uniform_not_pill(self):
        self.assertIn("not_mask_colour", capture.check_rect(self.frame, [20, 20, 100, 20], self.pill, False))

    def test_box_needs_sentinel(self):
        self.frame[20:40, 20:120] = self.pill
        self.assertEqual(capture.check_rect(self.frame, [20, 20, 100, 20], self.pill, True), "sentinel_missing")
        self.frame[20, 20:120] = (11, 31, 77)
        self.frame[39, 20:120] = (11, 31, 77)
        self.assertIsNone(capture.check_rect(self.frame, [20, 20, 100, 20], self.pill, True))


class CliContract(unittest.TestCase):
    def test_bad_input_exit_2(self):
        code, res = run_capture("--out-dir", tempfile.gettempdir())  # no --url
        self.assertEqual(code, 2)
        self.assertEqual(res["status"], "input")

    def test_dry_run(self):
        code, res = run_capture("--url", "http://x", "--out-dir", tempfile.gettempdir(), "--selector", "#a", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("#a", res["spec"]["mask"]["selectors"])
        self.assertTrue(res["spec"]["preflight"])

    def test_regex_redacted_in_runs_line(self):
        self.assertEqual(capture.redact_argv(["--regex", "secret", "--regex=abc"]),
                         ["--regex", "<redacted:6>", "--regex=<redacted:3>"])


@unittest.skipUnless(HAVE, "node/playwright/ffmpeg/numpy not available")
class Recording(unittest.TestCase):
    """One masked recording (~5 s of scenario) shared by the assertions below."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dsmask-")
        cls.cfg = write_json(cls.tmp, "mask.json", {"regexes": REGEXES})
        cls.acts = write_json(cls.tmp, "acts.json", ACTIONS)
        cls.code, cls.res = run_capture("--url", INDEX, "--out-dir", os.path.join(cls.tmp, "main"), "--config", cls.cfg,
                                        "--actions", cls.acts, "--probe", "#hdr-email", "--probe", "#toast")
        cls.log = capture.load_log(cls.res["mask_log"]) if cls.code in (0, 11) and "mask_log" in cls.res else []

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_zero_frames_leak(self):
        xc = self.res["cross_check"]
        self.assertEqual((self.code, self.res["status"]), (0, "ok"), json.dumps(xc.get("failures")))
        self.assertEqual(xc["frames_unmasked"], 0)
        self.assertGreater(xc["frames_with_masks"], 80)
        self.assertGreater(xc["rect_checks"], 200)
        # most masked frames carry positive pill evidence (not just "uniform")
        self.assertLess(xc["frames_no_pill_evidence"], 0.2 * xc["frames_with_masks"])
        print("\nleak counts: frames=%d masked_frames=%d unmasked=%d resynced=%d no_pill_evidence=%d rect_checks=%d check_s=%s"
              % (xc["frames_total"], xc["frames_with_masks"], xc["frames_unmasked"], xc["frames_resynced"],
                 xc["frames_no_pill_evidence"], xc["rect_checks"], xc["check_s"]))

    def test_events_contract(self):
        ev = json.load(open(self.res["events"]))
        clip = ev["clips"]["s01"]
        self.assertTrue(clip["masked"])
        self.assertEqual((clip["w"], clip["h"]), (1280, 720))
        self.assertEqual(ev["bbox_space"]["frame"], [1280, 720])
        self.assertIn("unmaskable", clip)
        self.assertGreater(clip["offset_ms"], 500)  # calibration pulses + page load before scene_start

    def test_log_schema(self):
        e = self.log[len(self.log) // 2]
        for k in ("t", "kind", "selector", "count", "rects", "state"):
            self.assertIn(k, e)
        self.assertEqual(e["kind"], "masked")
        self.assertTrue(all(x["state"] == "masked" for x in self.log))
        # one entry per rAF: median spacing close to 16.7 ms
        ts = [x["t"] for x in self.log if x["selector"] == "[data-sensitive]"]
        gaps = sorted(b - a for a, b in zip(ts, ts[1:]))
        self.assertLess(gaps[len(gaps) // 2], 20)

    def test_mask_follows_scroll(self):
        # the API key (x~332, a text node inside the scrolling page) must be logged at many distinct y while scrolling
        ys = {round(r[1]) for e in self.log if e["selector"] == "[data-sensitive]" for r in e["rects"] if abs(r[0] - 332) < 3}
        self.assertGreater(len(ys), 15, "API key rect did not move with scroll")
        self.assertEqual(self.res["cross_check"]["frames_unmasked"], 0)

    def test_header_email_pixels_independent_of_log(self):
        """Independent oracle: DOM probe of the sticky header email (no mask code involved) vs the video pixels."""
        xc, cal = self.res["cross_check"], self.res["calibration"]
        probe = [json.loads(x) for x in open(self.res["probe_log"]) if x.strip()]
        hdr = [p for p in probe if p["selector"] == "#hdr-email"]
        self.assertGreater(len(hdr), 100)
        epoch0 = xc["sync"]["epoch0_ms"]
        times = capture.frame_times(self.res["video"])
        pill = capture.hex_rgb(capture.DEFAULT_PILL)
        rect = hdr[-1]["rect"]
        bad = checked = 0
        for i, fr in capture.iter_frames(self.res["video"], 1280, 720, 60):
            te = epoch0 + times[i] * 1000
            if te < cal["scene_start_epoch"] + 100:
                continue
            checked += 1
            # the pill is the text range inside the email span (padding is the app's own white pill): inset by the span padding
            x, y, w, h = rect
            if capture.check_rect(fr, [x + 16, y + 11, w - 32, h - 22], pill, False):
                bad += 1
        self.assertGreater(checked, 100)
        self.assertEqual(bad, 0, "%d/%d frames show the header email unmasked" % (bad, checked))

    def test_late_toast_masked_in_first_frame(self):
        toast = [p for p in [json.loads(x) for x in open(self.res["probe_log"]) if x.strip()] if p["selector"] == "#toast"]
        self.assertTrue(toast, "toast never appeared")
        t_first = toast[0]["t"]  # first rAF in which the toast box exists (independent probe)
        masked = [e for e in self.log if e["t"] >= t_first - 1 and any(r[0] > 900 and r[1] > 600 for r in e["rects"])]
        self.assertTrue(masked, "toast text never masked")
        self.assertLessEqual(masked[0]["t"] - t_first, 17, "toast masked later than its first frame")

    def test_overhead(self):
        o = self.res["overhead"]
        print("overhead: avg_frame_ms=%.3f max_frame_ms=%.2f scan_ms=%.1f frames=%d" % (o["avg_frame_ms"], o["max_frame_ms"], o["scan_ms"], o["frames"]))
        self.assertLess(o["avg_frame_ms"], 3.0)
        self.assertLess(o["max_frame_ms"], 50.0)

    def test_assertions_recorded(self):
        a = self.res["assertion"]
        for k in ("preflight", "inline", "final"):
            self.assertTrue(a[k]["ok"], k)
        self.assertEqual(a["final"]["mode"], "highlight")

    def test_optional_ocr_no_pii(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            self.skipTest("rapidocr not installed")
        import re
        ocr, hits = RapidOCR(), 0
        pats = [re.compile(r) for r in REGEXES]
        for i, fr in capture.iter_frames(self.res["video"], 1280, 720, 120):
            if i % 5:
                continue
            res, _ = ocr(fr[:, :, ::-1])
            text = " ".join(r[1] for r in (res or []))
            hits += any(p.search(text) for p in pats)
        self.assertEqual(hits, 0)


@unittest.skipUnless(HAVE, "node/playwright/ffmpeg/numpy not available")
class Variants(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dsmask-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg = write_json(self.tmp, "mask.json", {"regexes": REGEXES})
        self.acts = write_json(self.tmp, "acts.json", ACTIONS)

    def _record(self, *extra):
        return run_capture("--url", INDEX, "--out-dir", os.path.join(self.tmp, "o"), "--config", self.cfg,
                           "--actions", self.acts, *extra)

    def test_overlay_fallback_zero_leak(self):
        code, res = self._record("--force-overlay")
        self.assertEqual(res["assertion"]["final"]["mode"], "overlay")
        self.assertEqual((code, res["cross_check"]["frames_unmasked"]), (0, 0), json.dumps(res["cross_check"]["failures"]))

    def test_style_element_fallback_zero_leak(self):
        code, res = self._record("--force-style-element")
        self.assertEqual((code, res["cross_check"]["frames_unmasked"]), (0, 0), json.dumps(res["cross_check"]["failures"]))

    def test_positive_control_unmasked_video_is_flagged(self):
        """Record WITHOUT the mask, then run the pixel gate against the DOM-probe rects as if they were masked:
        it must report leaks (proves the checker is not vacuous)."""
        code, res = self._record("--no-mask", "--probe", "#hdr-email")
        self.assertEqual(code, 0)
        probe = [json.loads(x) for x in open(res["probe_log"]) if x.strip()]
        log = [{"t": p["t"], "kind": "masked", "selector": "[data-sensitive]", "count": 1, "rects": [p["rect"]], "state": "masked"}
               for p in probe]
        cal = res["calibration"]
        clip = res["clip"]
        xc = capture.cross_check(res["video"], clip, log, cal["t_flashes"], cal["t_page_epoch"], cal["scene_start_epoch"],
                                 capture.hex_rgb(capture.DEFAULT_PILL), "solid")
        self.assertGreater(xc["frames_unmasked"], 100, "unmasked clip passed the gate")

    def test_fail_closed_invalid_selector_records_nothing(self):
        out = os.path.join(self.tmp, "fc")
        code, res = run_capture("--url", INDEX, "--out-dir", out, "--selector", ":::bad", "--actions", self.acts)
        self.assertEqual(code, 11)
        self.assertEqual(res["status"], "leak")
        self.assertFalse([f for f in os.listdir(out) if f.endswith(".webm")] if os.path.isdir(out) else [])
        self.assertFalse(os.path.isdir(os.path.join(out, "tmp-video")))
        reasons = [f["reason"] for f in res["recorder"]["preflight"]["failures"]]
        self.assertIn("invalid_selector", reasons)

    def test_every_wait_is_bounded(self):
        t = [{"op": "wait_for", "selector": "#does-not-exist"}]
        a = write_json(self.tmp, "t.json", t)
        code, res = run_capture("--url", INDEX, "--out-dir", os.path.join(self.tmp, "to"), "--actions", a, "--step-s", "1")
        self.assertEqual(code, 3, json.dumps(res)[:300])
        self.assertEqual(res["status"], "incomplete")


@unittest.skipUnless(HAVE, "node/playwright/ffmpeg/numpy not available")
class DomUnchanged(unittest.TestCase):
    def _check(self, url, cfg):
        d = tempfile.mkdtemp(prefix="dsmask-")
        self.addCleanup(shutil.rmtree, d, True)
        p = write_json(d, "c.json", cfg)
        r = subprocess.run(["node", os.path.join(HERE, "dom_check.js"), url, p], cwd=SCRIPTS, capture_output=True, text=True, timeout=90)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_app_dom_untouched_overlay_host_only(self):
        j = self._check(STATIC, {"regexes": REGEXES})
        self.assertTrue(j["body_html_same"] and j["head_html_same"] and j["root_attrs_same"] and j["attrs_same"], j)
        extra = j["masked_children"][len(j["base_children"]):]
        self.assertEqual(j["masked_children"][:len(j["base_children"])], j["base_children"])
        self.assertEqual(extra, ["div"])  # the closed-shadow overlay host (inputs/svg/img need cover boxes)
        self.assertEqual(j["adopted"], 1)   # stylesheet is adopted, not a <style> node

    def test_text_only_page_adds_no_node_at_all(self):
        j = self._check(TEXT_ONLY, {"regexes": REGEXES})
        self.assertEqual(j["masked_children"], j["base_children"])
        self.assertTrue(j["body_html_same"] and j["head_html_same"] and j["attrs_same"])
        self.assertGreaterEqual(j["highlight_ranges"], 2)  # data-sensitive paragraph + regex match


if __name__ == "__main__":
    unittest.main()
