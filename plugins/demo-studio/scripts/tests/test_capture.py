"""Unit tests for capture.py (gate, eval rules, CLI contract, redaction): synthetic clips, no browser needed.
Run: cd plugins/demo-studio/scripts && python3 -m pytest -q tests/test_capture.py
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

try:
    import numpy as np
except ImportError:
    np = None
HAVE = np is not None and capture.ffmpeg_exe() is not None
PILL = capture.hex_rgb(capture.DEFAULT_PILL)
E0 = 1_000_000_000_000.0     # fake page epoch (ms)
RECT = [50, 40, 100, 20]


def run_capture(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = capture.main(list(argv))
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


def make_clip(path, leak=False, n=40, w=320, h=180, plain=False):
    """frame 0 = calibration magenta, then white pages with a pill (or glyph-like noise when leak) at RECT."""
    rng = np.random.RandomState(3)
    cmd = [capture.ffmpeg_exe(), "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h),
           "-r", "25", "-i", "-", "-c:v", "libvpx", "-b:v", "4M", "-g", "5", path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        f = np.full((h, w, 3), 255, dtype=np.uint8)
        if i < 3:
            f[:] = (255, 0, 255)
        else:
            x, y, rw, rh = RECT
            if leak:
                f[y:y + rh, x:x + rw] = rng.choice([0, 255], size=(rh, rw, 1)).repeat(3, 2)
            elif not plain:
                f[y:y + rh, x:x + rw] = PILL
        p.stdin.write(f.tobytes())
    p.stdin.close()
    assert p.wait() == 0


def write_case(d, leak=False, log_kind="ok", w=320, h=180):
    clip = os.path.join(d, "s01.raw.webm")
    make_clip(clip, leak, w=w, h=h, plain=(log_kind == "plain"))
    times = capture.probe_clip(clip)["times"]
    entries = [{"t": E0 + times[5] * 1000.0, "kind": "tick", "items": 1, "frames": 1}]
    for tv in times[5:]:
        te = E0 + tv * 1000.0
        e = {"t": te, "kind": "masked", "selector": "[data-sensitive]", "count": 1, "rects": [RECT], "state": "masked"}
        if log_kind == "all_skipped":
            e["skip"] = [0]
        entries.append(e)
    if log_kind == "empty":
        entries = []
    logp = os.path.join(d, "s01.mask.jsonl")
    with open(logp, "w") as f:
        f.write("".join(json.dumps(x) + "\n" for x in entries))
    sync = {"viewport": {"width": w, "height": h}, "t_flashes": [E0], "t_page_epoch": E0 - 50, "scene_start_epoch": E0 + 400,
            "scene_end_epoch": E0 + 900, "sensitive_present": True}
    sp = os.path.join(d, "s01.sync.json")
    with open(sp, "w") as f:
        json.dump(sync, f)
    return clip, logp, sp


class EvalRules(unittest.TestCase):
    """eval_group on synthetic frames (S-02, S-06)."""

    def setUp(self):
        if np is None:
            self.skipTest("numpy missing")
        self.fr = np.full((100, 300, 3), 255, dtype=np.uint8)
        rng = np.random.RandomState(1)
        self.fr[20:40, 20:120] = rng.choice([0, 255], size=(20, 100, 1)).repeat(3, 2)       # glyph-like edges at A
        self.fr[60:80, 20:120] = PILL                                                       # pill at B
        self.A, self.B, self.PLAIN = [20, 20, 100, 20], [20, 60, 100, 20], [160, 20, 100, 20]
        self.res = capture._new_res("solid")

    def entry(self, dt, rect, **kw):
        return dict({"t": 1000 + dt, "kind": "masked", "selector": "s", "rects": [rect], "state": "masked"}, **kw)

    def ev(self, cands, narrow=90):
        return capture.eval_group(self.fr, cands, 1000, narrow, PILL, self.res)[0]

    def test_s02_bad_in_narrow_window_not_rescued_by_soft_nearby(self):
        v = self.ev([self.entry(0, self.A), self.entry(200, self.PLAIN)])    # the old code returned 'soft' here
        self.assertEqual(v, "bad")

    def test_s02_bad_decides_even_with_soft_in_narrow(self):
        self.assertEqual(self.ev([self.entry(0, self.A), self.entry(40, self.PLAIN)]), "bad")

    def test_s19_bad_nearest_entry_decides_even_with_a_strict_neighbour(self):
        self.assertEqual(self.ev([self.entry(0, self.A), self.entry(40, self.B)]), "bad")

    def test_s19_strict_nearest_wins_and_strict_neighbour_of_soft_nearest_is_resync(self):
        self.assertEqual(self.ev([self.entry(0, self.B), self.entry(40, self.A)]), "strict")
        self.assertEqual(self.ev([self.entry(0, self.PLAIN), self.entry(40, self.B)]), "resync")

    def test_s02_wide_strict_only_is_resync_not_ok(self):
        self.assertEqual(self.ev([self.entry(0, self.PLAIN), self.entry(200, self.B)]), "resync")

    def test_s02_soft_is_counted(self):
        self.assertEqual(self.ev([self.entry(d, self.PLAIN) for d in (-80, -40, 0, 40, 80)]), "soft")
        self.assertEqual(self.ev([self.entry(d, self.PLAIN) for d in (-80, -40, 0, 10)]), "empty")    # the run ends around here

    def test_s06_state_unmasked_never_graced(self):
        self.assertEqual(self.ev([self.entry(0, self.B, state="unmasked")]), "bad")

    def test_s06_appearing_element_glyphs_are_bad(self):
        """an element whose first log entry is 40 ms after this frame, glyphs showing now: no edge grace."""
        self.assertEqual(self.ev([self.entry(40, self.A, _start=True)]), "bad")

    def test_proven_occluded_rect_is_skipped_unproven_is_checked(self):
        self.assertEqual(self.ev([self.entry(0, self.A, skip=[0])]), "skipped")
        self.assertEqual(self.ev([self.entry(0, self.A, occluded=[0])]), "bad")   # S-01: occlusion alone proves nothing

    def test_oracle_rects_checked_like_mask_rects(self):
        g, _, _ = capture.split_log([{"t": 1000, "kind": "oracle", "rects": [self.A]}])
        v = capture.eval_group(self.fr, g["oracle"], 1000, 90, PILL, self.res)[0]
        self.assertEqual(v, "bad")
        self.assertGreater(self.res["oracle_rect_checks"], 0)

    def test_loading_entries_are_not_judged(self):
        g, ticks, _ = capture.split_log([{"t": 1, "kind": "masked", "selector": "s", "rects": [self.A], "state": "masked", "loading": True},
                                         {"t": 2, "kind": "tick", "items": 1, "loading": True}])
        self.assertEqual((g, ticks), ({}, []))


class PassProbes(unittest.TestCase):
    """Round 2 synthetic probes on _pass (S-18, S-20): they must fail closed."""
    W, H, R = 200, 100, [40, 30, 120, 30]

    def setUp(self):
        if np is None:
            self.skipTest("numpy missing")

    def text_frame(self, alpha):
        f = np.full((self.H, self.W, 3), 255, np.uint8)
        x, y, w, h = self.R
        reg = np.full((h, w, 3), 255, np.float32)
        reg[:, ::4] = 0
        f[y:y + h, x:x + w] = (np.array(PILL, np.float32) * (1 - alpha) + reg * alpha).round().astype(np.uint8)
        return f

    def run_pass(self, frames, log, ready=0.0):
        old = capture.iter_frames
        capture.iter_frames = lambda v, w, h, b: iter(enumerate(frames))
        try:
            return capture._pass("x", {"w": self.W, "h": self.H}, [i * 0.04 for i in range(len(frames))], {"s": log}, 0.0, ready, PILL, 10)
        finally:
            capture.iter_frames = old

    def entries(self, n, rect=None):
        return [{"t": i * 40.0, "kind": "masked", "selector": "s", "rects": [rect or self.R], "state": "masked"} for i in range(n)]

    def test_s18_slow_fade_is_not_carried_forever(self):
        fr = [self.text_frame(0)] * 5 + [self.text_frame(min(1, (i + 1) / 30)) for i in range(30)] + [self.text_frame(1)] * 5
        r = self.run_pass(fr, self.entries(len(fr)))
        self.assertGreater(r["frames_unmasked"], 20)            # was 0 (32 readable frames carried)
        self.assertLessEqual(r["frames_carried"], 3 * 5)

    def test_s18_carry_run_is_capped(self):
        """a stale run longer than CARRY_MAX: the first CARRY_MAX frames are carried from the anchor, the rest fail."""
        r2 = [40, 60, 120, 30]
        f = np.full((self.H, self.W, 3), 255, np.uint8)
        f[30:60, 40:160] = PILL                     # strict at R (the anchor state) ...
        f[60:90, 40:160:4] = 0                      # ... glyph-like content at R2, unchanged in every later frame
        extra = 10                                  # longer than the documented cap of 6
        log = self.entries(1 + extra)
        for e in log[1:]:
            e["rects"] = [r2]                       # the log says the key is at R2: bad nearest entry every frame
        r = self.run_pass([f] * (1 + extra), log)
        self.assertEqual(r["frames_carried"], 6)
        self.assertEqual(r["frames_unmasked"], extra - 6)

    def test_near_ms_is_the_nearest_window(self):
        fr = self.text_frame(0)
        res = capture._new_res("solid")
        bad_rect = [40, 70, 120, 20]
        fr = fr.copy()
        fr[70:90, 40:160:4] = 0
        near = [{"t": 0.0, "kind": "masked", "selector": "s", "rects": [bad_rect], "state": "masked"},
                {"t": capture.NEAR_MS - 2, "kind": "masked", "selector": "s", "rects": [self.R], "state": "masked"}]
        far = [near[0], dict(near[1], t=capture.NEAR_MS + 2)]
        self.assertEqual(capture.eval_group(fr, near, 0.0, 90, PILL, res)[0], "strict")
        self.assertEqual(capture.eval_group(fr, far, 0.0, 90, PILL, res)[0], "bad")

    def ent(self, t):
        return {"t": t, "kind": "masked", "selector": "s", "rects": [self.R], "state": "masked"}

    def test_edge_ms_soft_near_a_run_edge_is_not_counted(self):
        plain = np.full((self.H, self.W, 3), 255, np.uint8)
        cands = [self.ent(d) for d in range(-80, 81, 17)]          # dense both sides: no _boundary
        res = capture._new_res("solid")
        self.assertEqual(capture.eval_group(plain, cands, 0.0, 90, PILL, res, [95.0])[0], "empty")   # documented: 100 ms
        self.assertEqual(capture.eval_group(plain, cands, 0.0, 90, PILL, res, [105.0])[0], "soft")

    def test_boundary_slice_is_named(self):
        plain = np.full((self.H, self.W, 3), 255, np.uint8)
        res = capture._new_res("solid")
        dense = [self.ent(d) for d in range(-90, 91, 15)]
        ends_early = [e for e in dense if e["t"] <= 90 - capture.BOUNDARY_OUTER_MS - 2]       # nothing in the outer slice
        self.assertEqual(capture.eval_group(plain, dense, 0.0, 90, PILL, res)[0], "soft")
        self.assertEqual(capture.eval_group(plain, ends_early, 0.0, 90, PILL, res)[0], "empty")

    def test_s20_soft_through_the_end_never_strict(self):
        fr = [np.full((self.H, self.W, 3), 255, np.uint8)] * 40
        r = self.run_pass(fr, self.entries(40))
        self.assertEqual(r["strict_frames"], 0)
        self.assertGreater(r["rect_checks"], 0)

    def test_s19_stale_strict_does_not_trump_bad(self):
        r2 = [40, 60, 120, 30]
        f = np.full((self.H, self.W, 3), 255, np.uint8)
        f[30:60, 40:160] = PILL                  # overlay still at the old rect ...
        f[60:90, 40:160:4] = 0                   # ... text visible at the new rect
        fr = [self.text_frame(0)] * 3 + [f] + [self.text_frame(0)] * 3
        log = self.entries(7)
        log[3] = dict(log[3], rects=[r2])
        r = self.run_pass(fr, log)
        self.assertGreaterEqual(r["frames_unmasked"], 1)


class Unmaskable(unittest.TestCase):
    def test_contract_fields_in_clip_ms_and_px(self):
        ent = [{"t": E0 + 100 + 17 * i, "kind": "unmaskable", "surface": "iframe", "selector": "iframe",
                "reason": "r", "rect": [10, 20 + i, 300, 80]} for i in range(5)]
        out = capture.aggregate_unmaskable(ent, E0)
        self.assertEqual(len(out), 1)
        u = out[0]
        self.assertEqual({"surface", "selector", "reason", "t_start", "t_end", "bbox"}, set(u))
        self.assertEqual((u["t_start"], u["t_end"]), (100, 168))
        p = capture.aggregate_unmaskable(ent, E0, pad_ms=300)[0]       # S-23: padded by a detection interval
        self.assertEqual((p["t_start"], p["t_end"]), (0, 468))
        self.assertEqual(u["bbox"], [10, 20, 300, 84])

    def test_gap_splits_intervals_and_accept_marks(self):
        ent = [{"t": E0 + t, "kind": "unmaskable", "surface": "canvas", "selector": "canvas#c", "reason": "r", "rect": [0, 0, 5, 5]}
               for t in (0, 20, 1000, 1020)]
        out = capture.aggregate_unmaskable(ent, E0, accepted=("canvas#c",))
        self.assertEqual(len(out), 2)
        self.assertTrue(all(u.get("accepted") for u in out))


@unittest.skipUnless(HAVE, "numpy/ffmpeg missing")
class GateSynthetic(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="dsgate-")
        self.addCleanup(shutil.rmtree, self.d, True)

    def gate(self, clip, log, sync, *extra):
        return run_capture("gate", "--clip", clip, "--mask-log", log, "--sync", sync, "--scene", "s01", *extra)

    def test_pass(self):
        code, res = self.gate(*write_case(self.d))
        self.assertEqual((code, res["status"]), (0, "ok"), json.dumps(res)[:500])
        self.assertTrue(res["masked"])
        self.assertEqual(res["cross_check"]["frames_unmasked"], 0)
        self.assertGreater(res["cross_check"]["rect_checks"], 10)
        self.assertIsNotNone(res["safe_from_ms"])

    def test_leak_frames_fail_exit_11(self):
        code, res = self.gate(*write_case(self.d, leak=True))
        self.assertEqual((code, res["status"], res["masked"]), (11, "leak", False))
        self.assertGreater(res["cross_check"]["frames_unmasked"], 10)

    def test_missing_log_exit_11_never_masked_true(self):
        clip, log, sync = write_case(self.d)
        os.remove(log)
        code, res = self.gate(clip, log, sync)
        self.assertEqual((code, res["masked"]), (11, False))
        self.assertIn("mask_log_missing_or_empty", res["gate_fail"])

    def test_empty_log_exit_11(self):
        code, res = self.gate(*write_case(self.d, log_kind="empty"))
        self.assertEqual((code, res["masked"]), (11, False))
        self.assertIn("mask_log_missing_or_empty", res["gate_fail"])

    def test_s01_zero_rect_checks_with_rects_present_fails(self):
        """every logged rect 'skipped': nothing was pixel-checked although sensitive rects were on screen."""
        code, res = self.gate(*write_case(self.d, log_kind="all_skipped"))
        self.assertEqual((code, res["masked"]), (11, False))
        self.assertIn("no_rect_pixel_checked", res["gate_fail"])

    def test_viewport_must_equal_clip(self):
        clip, log, sync = write_case(self.d)
        s = json.load(open(sync))
        s["viewport"] = {"width": 640, "height": 360}
        json.dump(s, open(sync, "w"))
        code, res = self.gate(clip, log, sync)
        self.assertEqual(code, 11)
        self.assertIn("viewport_ne_clip_size", res["gate_fail"])

    def test_unm_pad_is_applied_by_gate(self):
        """UNM_PAD_MS reaches the gate output (not passed in by the test)."""
        clip, log, sync = write_case(self.d)
        times = capture.probe_clip(clip)["times"]
        raw0, raw1 = times[10] * 1000.0, times[14] * 1000.0
        with open(log, "a") as f:
            for t in (raw0, raw1):
                f.write(json.dumps({"t": E0 + t, "kind": "unmaskable", "surface": "canvas", "selector": "canvas#c", "reason": "r",
                                    "rect": [10, 10, 50, 40]}) + "\n")
        code, res = self.gate(clip, log, sync)
        self.assertEqual(code, 11)
        u = res["unmaskable"][0]
        self.assertGreaterEqual(capture.UNM_PAD_MS, 250)
        self.assertEqual(u["t_start"], max(round(raw0 - capture.UNM_PAD_MS), 0))
        self.assertEqual(u["t_end"], min(round(raw1 + capture.UNM_PAD_MS), res["clip"]["duration_ms"]))

    def test_s20_no_strict_evidence_fails_gate(self):
        clip, log, sync = write_case(self.d, log_kind="plain")
        code, res = self.gate(clip, log, sync)
        self.assertEqual((code, res["masked"]), (11, False))
        self.assertIn("no_strict_evidence", res["gate_fail"])

    def test_s24_thresholds_recorded_in_events(self):
        import project
        sdir = os.path.join(self.d, ".demo", "demo")
        os.makedirs(os.path.join(sdir, "media"))
        pj = os.path.join(sdir, "project.json")
        project.main(["--project", pj, "init"])
        clip, log, sync = write_case(os.path.join(sdir, "media"))
        old = os.getcwd()
        os.chdir(self.d)
        self.addCleanup(os.chdir, old)
        code, res = self.gate(clip, log, sync, "--slug", "demo", "--max-soft", "3", "--max-resync", "2", "--accept-unmaskable", "canvas")
        self.assertEqual(code, 0, json.dumps(res)[:300])
        m = project.read_project(pj)["events"]["clips"]["s01"]["mask"]
        self.assertEqual(m["thresholds"], {"max_soft": 3, "max_resync": 2, "accepted_unmaskable": ["canvas"]})
        self.assertIn("frames_soft", m)

    def test_blur_style_is_never_masked_true(self):
        cfg = os.path.join(self.d, "m.json")
        json.dump({"mask_style": "blur"}, open(cfg, "w"))
        code, res = self.gate(*write_case(self.d), "--config", cfg)
        self.assertEqual((code, res["masked"]), (0, False))

    def test_gate_writes_events_and_reverify_invalidates(self):
        import project
        sdir = os.path.join(self.d, ".demo", "demo")
        os.makedirs(os.path.join(sdir, "media"))
        pj = os.path.join(sdir, "project.json")
        project.main(["--project", pj, "init"])
        clip, log, sync = write_case(os.path.join(sdir, "media"))
        old = os.getcwd()
        os.chdir(self.d)
        self.addCleanup(os.chdir, old)
        code, res = self.gate(clip, log, sync, "--slug", "demo")
        self.assertEqual(code, 0, json.dumps(res)[:300])
        c = project.read_project(pj)["events"]["clips"]["s01"]
        self.assertTrue(c["masked"])
        self.assertEqual(c["file"], "media/s01.raw.webm")
        self.assertIn("rects_checked", c["mask"])
        self.assertEqual(c["mask"]["style"], "solid")
        self.assertIn("safe_from_ms", c)
        # S-03: the clip is re-verified against a log that no longer covers it: masked must flip to false
        make_clip(clip, leak=True)
        code, res = self.gate(clip, log, sync, "--slug", "demo")
        self.assertEqual(code, 11)
        self.assertFalse(project.read_project(pj)["events"]["clips"]["s01"]["masked"])

    def test_invalidate_events_clears_stale_masked_true(self):
        import project
        sdir = os.path.join(self.d, ".demo", "demo")
        os.makedirs(sdir)
        pj = os.path.join(sdir, "project.json")
        project.main(["--project", pj, "init"])
        project.store_key(pj, "events", project.OWNERS["events"],
                          {"schema": 1, "clips": {"s01": {"file": "media/s01.raw.webm", "masked": True, "safe_from_ms": 100}}}, 5)
        old = os.getcwd()
        os.chdir(self.d)
        self.addCleanup(os.chdir, old)
        self.assertIsNotNone(capture.invalidate_events("demo", "s01", "adapter_exit_11"))
        c = project.read_project(pj)["events"]["clips"]["s01"]
        self.assertFalse(c["masked"])
        self.assertIsNone(c["safe_from_ms"])


class CliContract(unittest.TestCase):
    def test_no_subcommand_exit_2(self):
        code, _ = run_capture() if False else (capture.main([]), None)
        self.assertEqual(code, 2)

    def test_bad_input_exit_2(self):
        code, res = run_capture("run", "--out-dir", tempfile.gettempdir())   # no --url
        self.assertEqual((code, res["status"]), (2, "input"))

    def test_abbreviated_flags_rejected(self):
        self.assertEqual(capture.main(["run", "--ur", "http://x", "--out-dir", tempfile.gettempdir()]), 2)

    def test_dry_run_prints_no_regex_literal_nor_url_query(self):
        code, res = run_capture("run", "--url", "http://h/p?token=SECRETTOKEN", "--out-dir", tempfile.gettempdir(),
                                "--selector", "#a", "--regex", r"sk_live_[A-Za-z0-9]+", "--dry-run")
        self.assertEqual(code, 0)
        txt = json.dumps(res)
        self.assertNotIn("sk_live", txt)
        self.assertNotIn("SECRETTOKEN", txt)
        self.assertIn("#a", res["spec"]["mask"]["selectors"])
        self.assertEqual(len(res["spec"]["mask"]["regexes"]), 1)

    def test_actions_flag_is_gone(self):
        self.assertEqual(capture.main(["run", "--url", "http://x", "--out-dir", tempfile.gettempdir(), "--actions", "a.json"]), 2)

    def test_redaction_of_argv(self):
        out = capture.redact_argv(["run", "--rege", "secret", "--regex=abc", "--url=http://h/p?t=1", "--url", "http://x/?q=2"])
        txt = json.dumps(out)
        for lit in ("secret", "abc", "t=1", "q=2"):
            self.assertNotIn(lit, txt)

    def test_missing_ffmpeg_exit_4(self):
        old = capture.ffmpeg_exe
        capture.ffmpeg_exe = lambda: None
        self.addCleanup(setattr, capture, "ffmpeg_exe", old)
        d = tempfile.mkdtemp(prefix="dsgate-")
        self.addCleanup(shutil.rmtree, d, True)
        code, res = run_capture("gate", "--clip", "x.webm", "--mask-log", "x", "--sync", "x", "--scene", "s01")
        self.assertEqual((code, res["status"]), (4, "missing-tool"))
        self.assertIn("ffmpeg", res["missing"])

    def test_scene_script_missing_exit_2(self):
        code, res = run_capture("run", "--url", "http://x", "--out-dir", tempfile.gettempdir(), "--scene-script", "/nope.py")
        self.assertEqual(code, 2)


class PixelUnit(unittest.TestCase):
    def setUp(self):
        if np is None:
            self.skipTest("numpy missing")
        self.frame = np.full((100, 200, 3), 255, dtype=np.uint8)

    def test_pill_passes_text_fails(self):
        self.frame[20:40, 20:120] = PILL
        self.assertIsNone(capture.check_rect(self.frame, [20, 20, 100, 20], PILL, False))
        rng = np.random.RandomState(1)
        self.frame[20:40, 20:120] = rng.choice([0, 255], size=(20, 100, 1)).repeat(3, 2)
        self.assertIn("not_uniform", capture.check_rect(self.frame, [20, 20, 100, 20], PILL, False))

    def test_white_is_uniform_not_pill(self):
        self.assertIn("not_mask_colour", capture.check_rect(self.frame, [20, 20, 100, 20], PILL, False))

    def test_box_needs_sentinel(self):
        self.frame[20:40, 20:120] = PILL
        self.assertEqual(capture.check_rect(self.frame, [20, 20, 100, 20], PILL, True), "sentinel_missing")
        self.frame[20, 20:120] = (11, 31, 77)
        self.frame[39, 20:120] = (11, 31, 77)
        self.assertIsNone(capture.check_rect(self.frame, [20, 20, 100, 20], PILL, True))


class NoActionsLeft(unittest.TestCase):
    def test_no_actions_replay_anywhere(self):
        root = os.path.dirname(os.path.dirname(SCRIPTS))
        bad = []
        for dp, _, fs in os.walk(root):
            if ".git" in dp or "__pycache__" in dp or "test_capture.py" in fs and False:
                continue
            for f in fs:
                if f == "test_capture.py" or f.endswith((".pyc", ".webm")):
                    continue
                try:
                    t = open(os.path.join(dp, f), encoding="utf-8").read()
                except (OSError, UnicodeDecodeError):
                    continue
                if "scenes.web.actions" in t or "--actions" in t:
                    bad.append(os.path.join(dp, f))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
