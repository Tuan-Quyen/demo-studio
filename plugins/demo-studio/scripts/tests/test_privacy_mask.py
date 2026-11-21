"""Tests for privacy_mask.js + privacy_oracle.js + web_adapter.py + capture.py (real Chromium via Python Playwright).

Needs python playwright with a launchable Chromium (never `playwright install`), ffmpeg and numpy; skipped otherwise.
Run: cd plugins/demo-studio/scripts && python3 -m pytest -q tests/test_privacy_mask.py
"""
import contextlib
import glob
import io
import json
import os
import shutil
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
SCENE = os.path.join(FIX, "scenes.web.py")
EXTRA = os.path.join(HERE, "fixtures", "scenes_extra.py")


def fx(name):
    return "file://" + os.path.join(HERE, "fixtures", name)


REGEXES = [r"[\w.+-]+@[\w-]+\.[\w.]+", r"sk_live_[A-Za-z0-9]+", r"\b\d{3}-\d{2}-\d{4}\b"]


def _have():
    try:
        import numpy  # noqa: F401
        from playwright.sync_api import sync_playwright
        if not capture.ffmpeg_exe():
            return False
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAVE = _have()


def run_capture(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = capture.main(list(argv))
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


def rx_args():
    a = []
    for r in REGEXES:
        a += ["--regex", r]
    return a


def leftovers(out):
    return sorted(f for f in (os.listdir(out) if os.path.isdir(out) else []) if f.startswith(".tmp"))


@unittest.skipUnless(HAVE, "python playwright + chromium / ffmpeg / numpy not available")
class Recording(unittest.TestCase):
    """One masked recording (~5 s of scenario) shared by the assertions below."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dsmask-")
        cls.out = os.path.join(cls.tmp, "main")
        cls.priv = tempfile.mkdtemp(prefix="dspriv-")       # private temp root: only this class's spec dirs can appear in it
        cls.old_tempdir = tempfile.tempdir
        tempfile.tempdir = cls.priv
        cls.code, cls.res = run_capture("run", "--url", INDEX, "--scene", "s01", "--scene-script", SCENE, "--out-dir", cls.out,
                                        *rx_args(), "--probe", "#hdr-email", "--probe", "#toast")
        cls.log = capture.load_log(cls.res["mask_log"]) if cls.code == 0 else []

    @classmethod
    def tearDownClass(cls):
        tempfile.tempdir = cls.old_tempdir
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(cls.priv, ignore_errors=True)

    def setUp(self):
        # one failed recording must be ONE failure (test_zero_frames...), not seven: the others skip with the reason
        if self.code != 0 and not self._testMethodName.startswith("test_zero_frames"):
            self.skipTest("shared recording failed (exit %s): see test_zero_frames_leak_and_zero_tolerance_used" % self.code)

    def test_zero_frames_leak_and_zero_tolerance_used(self):
        xc = self.res["cross_check"]
        self.assertEqual((self.code, self.res["status"]), (0, "ok"), json.dumps(self.res.get("gate_fail")) + json.dumps(xc.get("failures")))
        self.assertEqual((xc["frames_unmasked"], xc["frames_soft"], xc["frames_resynced"]), (0, 0, 0))   # default thresholds: 0
        self.assertGreater(xc["frames_with_masks"], 80)
        self.assertGreater(xc["rect_checks"], 200)
        self.assertGreater(xc["oracle_rect_checks"], 100)       # the independent DOM oracle was checked too
        print("\nleak counts: frames=%d verified_masked=%d unmasked=%d soft=%d resynced=%d carried=%d strict=%d unverified_leadin=%d "
              "rect_checks=%d oracle=%d check_s=%s recal=%s" % (
                  xc["frames_total"], xc["frames_with_masks"], xc["frames_unmasked"], xc["frames_soft"], xc["frames_resynced"],
                  xc["frames_carried"], xc["strict_frames"], xc["frames_unverified"], xc["rect_checks"], xc["oracle_rect_checks"], xc["check_s"], xc["recalibrated"]))

    def test_events_contract_and_temp_cleanup(self):
        ev = json.load(open(self.res["events"]))
        c = ev["clips"]["s01"]
        self.assertTrue(c["masked"])
        self.assertEqual((c["w"], c["h"]), (1280, 720))
        self.assertEqual(c["unmaskable"], [])
        self.assertGreater(c["offset_ms"], 500)
        self.assertLessEqual(c["safe_from_ms"], c["offset_ms"])      # the scene starts on verified frames
        self.assertGreater(c["mask"]["rects_checked"], 200)
        self.assertEqual(c["mask"]["style"], "solid")
        self.assertEqual(ev["bbox_space"]["frame"], [1280, 720])
        self.assertTrue(any(m["type"] == "scene_start" for m in ev["markers"]))
        self.assertEqual(leftovers(self.out), [])
        self.assertEqual(glob.glob(os.path.join(self.priv, "dscap-*")), [])      # the spec dir (regexes, typed text) is gone

    def test_gate_standalone_reverifies_existing_clip(self):
        c = self.res["clip"]
        code, res = run_capture("gate", "--clip", self.res["video"], "--mask-log", self.res["mask_log"], "--sync", self.res["sync"],
                                "--scene", "s01", *rx_args())
        self.assertEqual((code, res["masked"], res["cross_check"]["frames_unmasked"]), (0, True, 0), json.dumps(res)[:400])
        self.assertEqual(res["clip"], c)

    def test_log_schema(self):
        masked = [e for e in self.log if e["kind"] == "masked"]
        e = masked[len(masked) // 2]
        for k in ("t", "kind", "selector", "count", "rects", "state"):
            self.assertIn(k, e)
        self.assertTrue(all(x["state"] == "masked" for x in masked))
        self.assertTrue([x for x in self.log if x["kind"] == "tick"])
        self.assertTrue([x for x in self.log if x["kind"] == "oracle"])
        ts = [x["t"] for x in masked if x["selector"] == "[data-sensitive]"]
        gaps = sorted(b - a for a, b in zip(ts, ts[1:]))
        self.assertLess(gaps[len(gaps) // 2], 20)       # one entry per frame (median ~16.7 ms)

    def test_mask_follows_scroll(self):
        ys = {round(r[1]) for e in self.log if e["kind"] == "masked" and e["selector"] == "[data-sensitive]" for r in e["rects"] if abs(r[0] - 332) < 3}
        self.assertGreater(len(ys), 15, "API key rect did not move with scroll")

    def test_header_email_pixels_independent_of_log(self):
        """DOM probe of the sticky header email (no mask code) vs the pixels."""
        xc, cal = self.res["cross_check"], self.res["calibration"]
        probe = [json.loads(x) for x in open(self.res["probe_log"]) if x.strip()]
        hdr = [p for p in probe if p["selector"] == "#hdr-email"]
        self.assertGreater(len(hdr), 100)
        epoch0 = xc["sync"]["epoch0_ms"]
        times = capture.frame_times(self.res["video"])
        pill = capture.hex_rgb(capture.DEFAULT_PILL)
        x, y, w, h = hdr[-1]["rect"]
        bad = checked = 0
        for i, fr in capture.iter_frames(self.res["video"], 1280, 720, 60):
            if epoch0 + times[i] * 1000 < cal["scene_start_epoch"] + 100:
                continue
            checked += 1
            if capture.check_rect(fr, [x + 16, y + 11, w - 32, h - 22], pill, False):
                bad += 1
        self.assertGreater(checked, 100)
        self.assertEqual(bad, 0, "%d/%d frames show the header email unmasked" % (bad, checked))

    def test_late_toast_masked_in_first_frame(self):
        toast = [json.loads(x) for x in open(self.res["probe_log"]) if x.strip()]
        toast = [p for p in toast if p["selector"] == "#toast"]
        self.assertTrue(toast, "toast never appeared")
        t_first = toast[0]["t"]
        masked = [e for e in self.log if e["kind"] == "masked" and e["t"] >= t_first - 1 and any(r[0] > 900 and r[1] > 600 for r in e["rects"])]
        self.assertTrue(masked, "toast text never masked")
        self.assertLessEqual(masked[0]["t"] - t_first, 17.5, "toast masked later than its first frame")

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
            hits += any(p.search(" ".join(r[1] for r in (res or []))) for p in pats)
        self.assertEqual(hits, 0)


@unittest.skipUnless(HAVE, "python playwright + chromium / ffmpeg / numpy not available")
class Variants(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dsmask-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = os.path.join(self.tmp, "o")

    def _record(self, *extra, url=INDEX, script=SCENE, scene="s02", out=None):
        return run_capture("run", "--url", url, "--scene", scene, "--scene-script", script, "--out-dir", out or self.out, *extra)

    def test_slug_writes_events_and_failed_reshoot_clears_masked(self):
        import project
        sdir = os.path.join(self.tmp, ".demo", "demo")
        os.makedirs(sdir)
        pj = os.path.join(sdir, "project.json")
        project.main(["--project", pj, "init"])
        with open(os.path.join(sdir, "demo.yaml"), "w") as f:
            f.write("privacy:\n  regexes: [%s]\n" % ", ".join(json.dumps(r) for r in REGEXES))
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        code, res = run_capture("run", "--url", INDEX, "--slug", "demo", "--scene", "s02", "--scene-script", SCENE)
        self.assertEqual((code, res["status"]), (0, "ok"), json.dumps({k: res.get(k) for k in ("gate_fail", "cross_check")})[:1500])
        d = project.read_project(pj)
        clip = d["events"]["clips"]["s02"]
        self.assertEqual(d["_meta"]["keys"]["events"]["owner"], "capture-operator")
        self.assertEqual(clip["file"], "media/s02.raw.webm")
        self.assertTrue(clip["masked"])
        self.assertTrue(all(m["scene"] == "s02" for m in d["events"]["markers"]))
        with open(os.path.join(sdir, "runs.jsonl")) as f:
            line = f.read()
        self.assertIn("capture.py", line)
        self.assertNotIn("sk_live", line)
        # S-03: a failing re-shoot (invalid selector -> exit 11) must not leave masked:true or a new file behind
        code, res = run_capture("run", "--url", INDEX, "--slug", "demo", "--scene", "s02", "--scene-script", SCENE, "--selector", ":::bad")
        self.assertEqual(code, 11)
        d = project.read_project(pj)
        self.assertFalse(d["events"]["clips"]["s02"]["masked"])
        self.assertEqual(leftovers(os.path.join(sdir, "media")), [])

    def test_overlay_fallback_zero_leak(self):
        code, res = self._record("--force-overlay", *rx_args())
        self.assertEqual(res["assertion"]["final"]["mode"], "overlay")
        self.assertEqual((code, res["cross_check"]["frames_unmasked"]), (0, 0), json.dumps(res["cross_check"]["failures"]))

    def test_style_element_fallback_zero_leak(self):
        code, res = self._record("--force-style-element", *rx_args())
        self.assertEqual((code, res["cross_check"]["frames_unmasked"]), (0, 0), json.dumps(res["cross_check"]["failures"]))

    def test_positive_control_unmasked_video_is_flagged(self):
        """Record WITHOUT the mask (the oracle still logs where the sensitive text is), then run the pixel check as if
        the mask were on: it must report leaks (the checker is not vacuous)."""
        code, res = self._record("--no-mask", *rx_args())
        self.assertEqual((code, res["masked"]), (0, False))
        entries = [e for e in capture.load_log(res["mask_log"]) if e["kind"] == "oracle"]
        self.assertTrue(entries)
        cal = res["calibration"]
        xc = capture.cross_check(res["video"], res["clip"], entries, cal["t_flashes"], cal["t_page_epoch"], cal["scene_start_epoch"],
                                 capture.hex_rgb(capture.DEFAULT_PILL), "solid")
        self.assertGreater(xc["frames_unmasked"], 20, "unmasked clip passed the gate")

    def test_fail_closed_invalid_selector_records_nothing(self):
        code, res = self._record("--selector", ":::bad")
        self.assertEqual((code, res["status"]), (11, "leak"))
        self.assertEqual([f for f in os.listdir(self.out) if f.endswith(".webm")] if os.path.isdir(self.out) else [], [])
        self.assertEqual(leftovers(self.out), [])
        reasons = [f["reason"] for f in res["adapter"]["preflight"]["failures"]]
        self.assertIn("invalid_selector", reasons)

    def test_r08_invalid_regex_is_bad_input_exit_2(self):
        code, res = self._record("--regex", "(unclosed")
        self.assertEqual((code, res["status"]), (2, "input"))
        self.assertNotIn("(unclosed", json.dumps(res).replace("invalid regex (JS semantics): regex#0", ""))
        self.assertEqual(leftovers(self.out), [])

    def test_r08_js_only_syntax_is_accepted(self):
        code, res = self._record("--regex", r"(?<u>[a-z]+)@\k<u>\.zz", "--regex", r"\p{Lu}{9}", scene="s02")
        self.assertEqual(code, 0, json.dumps(res)[:300])

    def test_step_failure_exit_10_and_cleanup(self):
        code, res = self._record(script=EXTRA, scene="s04")
        self.assertEqual((code, res["status"]), (10, "step"))
        self.assertEqual(leftovers(self.out), [])

    def test_every_wait_is_bounded(self):
        code, res = self._record(script=EXTRA, scene="s05", url=fx("typed.html"), *["--step-s", "1"])
        self.assertEqual((code, res["status"]), (3, "incomplete"), json.dumps(res)[:300])
        self.assertEqual(leftovers(self.out), [])

    # ---- S-01: a hit-testable, fading, translucent backdrop must not make the mask skip anything
    def test_s01_fading_modal_backdrop_overlays_always_drawn(self):
        code, res = self._record("--force-overlay", "--regex", REGEXES[0], script=EXTRA, scene="s01", url=fx("modal.html"))
        xc = res["cross_check"]
        self.assertGreater(xc["rect_checks"], 0, "gate saw no rect at all (the silent S-01 pass)")
        self.assertEqual(xc["frames_unmasked"], 0, json.dumps(xc["failures"]))
        self.assertEqual(code, 0, json.dumps(res.get("gate_fail")))
        log = capture.load_log(res["mask_log"])
        self.assertTrue([e for e in log if e["kind"] == "masked" and e.get("occluded")], "occluded rects must be logged, not dropped")
        self.assertFalse([e for e in log if e["kind"] == "masked" and e.get("skip")], "a translucent backdrop is no opacity proof")

    # ---- S-07 / R-04: surfaces CSS cannot mask are detected with the exact contract
    def test_s07_unmaskable_surfaces_detected_needs_input(self):
        code, res = self._record("--regex", REGEXES[0], script=EXTRA, scene="s01", url=fx("unmaskable.html"))
        self.assertEqual((code, res["status"], res["masked"]), (11, "needs-input", False), json.dumps(res)[:300])
        surfaces = {u["surface"] for u in res["unmaskable"]}
        self.assertTrue({"iframe", "canvas", "shadow-dom", "pseudo-element"} <= surfaces, surfaces)
        for u in res["unmaskable"]:
            self.assertEqual({"surface", "selector", "reason", "t_start", "t_end", "bbox"}, set(u))
            x, y, w, h = u["bbox"]
            self.assertTrue(0 <= x < 1280 and 0 <= y < 720 and w > 0 and h > 0, u)
            self.assertTrue(0 <= u["t_start"] <= u["t_end"] <= res["clip"]["duration_ms"], u)
        c = json.load(open(res["events"]))["clips"]["s01"]
        self.assertFalse(c["masked"])
        self.assertEqual(c["mask"]["status"], "needs-input")
        self.assertEqual(len(c["unmaskable"]), len(res["unmaskable"]))

    def test_s07_accepted_unmaskable_does_not_block(self):
        a = []
        for s in ("iframe", "canvas", "shadow-dom", "pseudo-element"):
            a += ["--accept-unmaskable", s]
        code, res = self._record("--regex", REGEXES[0], *a, script=EXTRA, scene="s01", url=fx("unmaskable.html"))
        self.assertEqual((code, res["status"]), (0, "ok"), json.dumps(res)[:300])
        self.assertTrue(all(u.get("accepted") for u in res["unmaskable"]))

    # ---- S-08: typed text that matches a regex is masked before the first key, or refused
    def test_s08_typed_secret_masked_from_first_keystroke(self):
        code, res = self._record("--regex", REGEXES[2], script=EXTRA, scene="s02", url=fx("typed.html"))
        self.assertEqual((code, res["cross_check"]["frames_unmasked"]), (0, 0), json.dumps(res)[:400])
        log = capture.load_log(res["mask_log"])
        forced = [e for e in log if e["kind"] == "masked" and e["selector"] == "regex#typed"]
        self.assertTrue(forced, "target was not pre-masked")
        self.assertTrue(res["masked"])

    def test_s08_typing_into_unmaskable_target_is_refused_exit_2(self):
        code, res = self._record("--regex", REGEXES[2], script=EXTRA, scene="s03", url=fx("typed.html"))
        self.assertEqual((code, res["status"]), (2, "input"))
        self.assertEqual(leftovers(self.out), [])


@unittest.skipUnless(HAVE, "python playwright + chromium / ffmpeg / numpy not available")
class Round2(unittest.TestCase):
    """Repros of the round 2 security findings (fake data), each must fail closed or be masked."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dsmask-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = os.path.join(self.tmp, "o")

    def rec(self, scene, url, *extra):
        return run_capture("run", "--url", fx(url), "--scene", scene, "--scene-script", EXTRA, "--out-dir", self.out,
                           "--regex", REGEXES[0], *extra)

    def assert_masked(self, code, res):
        xc = res["cross_check"]
        self.assertEqual((code, xc["frames_unmasked"]), (0, 0), json.dumps({k: res.get(k) for k in ("gate_fail", "cross_check")})[:1200])
        self.assertTrue(res["masked"])
        return capture.load_log(res["mask_log"])

    def test_s17_programmatic_value_is_masked_and_logged(self):
        code, res = self.rec("s06", "typed.html")
        log = self.assert_masked(code, res)
        self.assertTrue([e for e in log if e["kind"] == "masked" and e["selector"].startswith("regex#") and e["rects"]], "value never logged")
        self.assertGreater(res["cross_check"]["oracle_rect_checks"], 10)
        self.assertGreater(res["cross_check"]["strict_frames"], 10)

    def test_s17_value_set_then_cleared_is_still_masked_while_visible(self):
        code, res = self.rec("s11", "typed.html")
        log = self.assert_masked(code, res)
        self.assertTrue([e for e in log if e["kind"] == "oracle" and e["rects"]], "oracle blind to the value")

    def test_s17_unlogged_final_regex_hit_fails_the_gate(self):
        """gate-level: the final assertion saw a regex hit but the log never had that group (mask blind) -> exit 11."""
        code, res = self.rec("s06", "typed.html")
        self.assertEqual(code, 0)
        sync = json.load(open(res["sync"]))
        sync["final"]["regex_labels"] = ["regex#0", "regex#7"]
        json.dump(sync, open(res["sync"], "w"))
        code, g = run_capture("gate", "--clip", res["video"], "--mask-log", res["mask_log"], "--sync", res["sync"], "--scene", "s06",
                              "--regex", REGEXES[0])
        self.assertEqual(code, 11)
        self.assertIn("regex_hits_not_logged", g["gate_fail"])

    def test_s22_modal_dialog_top_layer_is_masked(self):
        code, res = self.rec("s07", "dialog.html")
        self.assert_masked(code, res)

    def test_s08_split_typing_is_premasked(self):
        code, res = self.rec("s08", "typed.html")
        log = self.assert_masked(code, res)
        self.assertTrue([e for e in log if e["kind"] == "masked" and e["selector"] == "regex#typed"])

    def test_s08_locator_press_and_handle_type_and_keyboard_down(self):
        for sc in ("s09", "s10", "s12"):
            shutil.rmtree(self.out, ignore_errors=True)
            code, res = self.rec(sc, "typed.html")
            log = self.assert_masked(code, res)
            self.assertTrue([e for e in log if e["kind"] == "masked" and e["selector"] == "regex#typed"], sc)

    def test_s08_fields_are_premasked_even_without_a_regex_match(self):
        """fail closed: every field that receives typing is masked while regexes are configured."""
        code, res = run_capture("run", "--url", fx("typed.html"), "--scene", "s08", "--scene-script", EXTRA, "--out-dir", self.out,
                                "--regex", r"zzz@never\.match")
        log = capture.load_log(res["mask_log"])
        self.assertTrue([e for e in log if e["kind"] == "masked" and e["selector"] == "regex#typed" and e["rects"]], json.dumps(res)[:300])

    def test_s21_pointer_events_none_owner_is_not_proven_occluded(self):
        code, res = self.rec("s01", "pe.html")
        log = self.assert_masked(code, res)
        self.assertFalse([e for e in log if e["kind"] in ("masked", "oracle") and e.get("skip")], "ancestor hit taken for an occluder")
        self.assertGreater(res["cross_check"]["rect_checks"], 50)

    def test_s23_unmaskable_is_detected_within_the_mutation_throttle(self):
        """canvases inserted at different poll phases are all logged within ~60 ms + 2 frames, not up to 250 ms."""
        code, res = run_capture("run", "--url", fx("typed.html"), "--scene", "s13", "--scene-script", EXTRA, "--out-dir", self.out,
                                "--regex", REGEXES[0])
        self.assertEqual(code, 11, json.dumps(res)[:300])       # canvases are unmaskable: needs-input
        sync = json.load(open(res["sync"]))
        log = capture.load_log(res["mask_log"])
        marks = [m for m in sync["markers"] if m["type"] == "key"]
        self.assertEqual(len(marks), 4)
        lags = []
        for i, m in enumerate(marks):
            t_ins = sync["scene_start_epoch"] + m["t"]
            first = min(e["t"] for e in log if e["kind"] == "unmaskable" and e["selector"] == "canvas#c%d" % i)
            lags.append(first - t_ins)
        self.assertLess(max(lags), 120, lags)

    def test_s25_events_write_failure_rolls_back(self):
        import project
        sdir = os.path.join(self.tmp, ".demo", "demo")
        os.makedirs(os.path.join(sdir, "media"))
        pj = os.path.join(sdir, "project.json")
        project.main(["--project", pj, "init"])
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        args = ["run", "--url", fx("typed.html"), "--slug", "demo", "--scene", "s01", "--scene-script", EXTRA, "--regex", REGEXES[0]]
        code, res = run_capture(*args)
        self.assertEqual(code, 0)
        media = os.path.join(sdir, "media")
        before = {f: open(os.path.join(media, f), "rb").read() for f in os.listdir(media)}
        real = capture.write_events

        def boom(*a, **k):
            raise capture.Fail(70, "events write failed")
        capture.write_events = boom
        self.addCleanup(setattr, capture, "write_events", real)
        code, res = run_capture(*args)
        self.assertEqual(code, 70)
        self.assertEqual({f: open(os.path.join(media, f), "rb").read() for f in os.listdir(media)}, before)   # old files restored
        self.assertFalse(project.read_project(pj)["events"]["clips"]["s01"]["masked"])
        self.assertEqual(leftovers(media), [])


@unittest.skipUnless(HAVE, "python playwright + chromium / ffmpeg / numpy not available")
class DomUnchanged(unittest.TestCase):
    def _snap(self, url, cfg):
        from playwright.sync_api import sync_playwright
        mask_js = open(os.path.join(SCRIPTS, "privacy_mask.js"), encoding="utf-8").read()
        out = []
        with sync_playwright() as p:
            b = p.chromium.launch()
            for c in (None, cfg):
                ctx = b.new_context(viewport={"width": 1000, "height": 700})
                if c:
                    ctx.add_init_script(script="window.__DS_MASK_CONFIG = " + json.dumps(c) + ";\n" + mask_js)
                page = ctx.new_page()
                page.goto(url, wait_until="load")
                if c:
                    page.wait_for_function("window.__dsMaskReady === true", timeout=5000)
                    if page.query_selector("#note"):
                        page.fill("#note", "ssn 123-45-6789")
                    page.wait_for_timeout(300)
                out.append(page.evaluate("""() => {
                  const attrs = (el) => Array.from(el.attributes).map((a) => a.name + '=' + a.value).sort().join('|');
                  return {kids: Array.from(document.documentElement.children).map((e) => e.tagName.toLowerCase()),
                    root_attrs: attrs(document.documentElement), body: document.body.innerHTML.replace(/value="[^"]*"/g, ''), head: document.head.innerHTML,
                    all: Array.from(document.querySelectorAll('body, body *, head, head *')).map((e) => e.tagName + ':' + attrs(e)),
                    ranges: window.CSS && CSS.highlights && CSS.highlights.get('ds-mask') ? CSS.highlights.get('ds-mask').size : -1,
                    adopted: document.adoptedStyleSheets.length}; }"""))
                ctx.close()
            b.close()
        return out

    def test_app_dom_untouched_overlay_host_only(self):
        base, masked = self._snap(STATIC, {"regexes": REGEXES})
        self.assertEqual((base["body"], base["head"], base["root_attrs"]), (masked["body"].replace('', ''), masked["head"], masked["root_attrs"]))
        self.assertEqual(base["all"], masked["all"])
        self.assertEqual(masked["kids"][:len(base["kids"])], base["kids"])
        self.assertEqual(masked["kids"][len(base["kids"]):], ["div"])    # the closed-shadow overlay host
        self.assertEqual(masked["adopted"], 1)

    def test_text_only_page_adds_no_node_at_all(self):
        base, masked = self._snap(TEXT_ONLY, {"regexes": REGEXES})
        self.assertEqual(masked["kids"], base["kids"])
        self.assertEqual((base["body"], base["head"], base["all"]), (masked["body"], masked["head"], masked["all"]))
        self.assertGreaterEqual(masked["ranges"], 2)


if __name__ == "__main__":
    unittest.main()
