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
sys.path.insert(0, os.path.dirname(HERE))
import checks  # noqa: E402
import project  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
need_ffmpeg = unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "ffmpeg/ffprobe missing")
LOUD = "volume=7.8dB"   # sine 300 Hz at default amplitude -> about -14 LUFS


def ff(*args):
    subprocess.run([FFMPEG, "-v", "error", "-nostdin", "-y"] + list(args), check=True)


def synth(path, dur=6, vf=None, af=LOUD, black=False, freeze=False):
    """320x180 25 fps clip + sine audio. black: 1 s black at 2-3 s; freeze: static colour only."""
    if freeze:
        src = ["-f", "lavfi", "-i", "color=c=blue:s=320x180:r=25:d=%d" % dur]
    else:
        src = ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=%d" % dur]
    vfx = vf or ("drawbox=x=0:y=0:w=320:h=180:color=black:t=fill:enable='between(t,2,3)'" if black else "null")
    ff(*src, "-f", "lavfi", "-i", "sine=f=300:d=%d" % dur, "-vf", vfx, "-af", af,
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", path)


class Env:
    def __init__(self, test, formats='["16:9"]', length=6):
        self.tmp = tempfile.mkdtemp(prefix="checks-test-")
        test.addCleanup(shutil.rmtree, self.tmp, True)
        self.sdir = os.path.join(self.tmp, ".demo", "demo")
        os.makedirs(os.path.join(self.sdir, "media"))
        self.pj = os.path.join(self.sdir, "project.json")
        project.main(["--project", self.pj, "init"])
        with open(os.path.join(self.sdir, "demo.yaml"), "w") as f:
            f.write("formats: %s\nlength_s: %d\n" % (formats, length))

    def put(self, key, value):
        project.store_key(self.pj, key, project.OWNERS[key], value, 5)

    def blur(self, aspect, verdict="pass", ctrl=None, hits=(), bind=True):
        """A verdict as blur.py verify stores it: bound to the current final file and input versions."""
        entry = {"verdict": verdict, "sampled": 3, "total": 3, "seconds": 1.0,
                 "fullframe": {"sampled": 1}, "positive_control": ctrl if ctrl is not None else {"r1": True},
                 "hits": list(hits)}
        if bind:
            f = os.path.join(self.sdir, "media", "final-%s.mp4" % aspect)
            entry.update(file=project.stat_fingerprint(f), video="media/final-%s.mp4" % aspect,
                         inputs=project.current_inputs(self.stored(), ("blur", "timeline", "events")))
        project.write_checks(self.pj, {"blur": {aspect: entry}}, writer="blur.py", merge=True)

    def run(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = checks.main(["--project", self.pj] + list(extra))
        return code, json.loads(out.getvalue().strip().splitlines()[-1])

    def stored(self):
        return project.read_project(self.pj)


@need_ffmpeg
class ChecksTests(unittest.TestCase):
    def good(self, **kw):
        e = Env(self)
        synth(os.path.join(e.sdir, "media", "final-16x9.mp4"), **kw)
        with open(os.path.join(e.sdir, "media", "final.vtt"), "w") as f:
            f.write("WEBVTT\n\n00:00:00.300 --> 00:00:02.900\nCreate an invoice\n")
        return e

    def test_all_pass_writes_checks_as_checks_py(self):
        e = self.good()
        e.blur("16x9")
        code, res = e.run()
        self.assertEqual(code, 0, res)
        self.assertTrue(res["pass"])
        d = e.stored()
        self.assertTrue(d["checks"]["pass"])
        self.assertEqual(d["checks"]["schema"], 2)
        self.assertEqual(d["checks"]["blur"]["16x9"]["verdict"], "pass")  # blur.py's entry is kept
        self.assertEqual(d["checks"]["results"]["blur"]["verdict"], "pass")
        self.assertAlmostEqual(d["checks"]["results"]["loudness"]["lufs"], -14.0, delta=1.0)
        self.assertEqual(d["_meta"]["keys"]["checks"]["owner"], "render-engineer")
        self.assertEqual(d["checks"]["outputs"]["16x9"]["w"], 320)

    def test_missing_blur_verdict_is_incomplete_not_pass(self):
        e = self.good()
        code, res = e.run()
        self.assertEqual(code, 3)
        self.assertFalse(res["pass"])
        self.assertEqual(res["results"]["blur"]["verdict"], "incomplete")

    def test_failed_positive_control_is_inconclusive(self):
        e = self.good()
        e.blur("16x9", verdict="pass", ctrl={"r1": False})
        code, res = e.run()
        self.assertEqual(code, 10)
        self.assertEqual(res["results"]["blur"]["verdict"], "inconclusive")
        self.assertEqual(res["failures"][0], {"id": "blur", "owner": "privacy-blurrer", "class": "finding"})

    def test_leak_is_exit_11(self):
        e = self.good()
        e.blur("16x9", verdict="leak", hits=[{"region": "r1", "t_ms": 100, "match_len": 9}])
        code, res = e.run()
        self.assertEqual(code, 11)
        self.assertEqual(res["status"], "leak")

    def test_every_rendered_aspect_needs_a_verdict(self):
        e = Env(self, formats='["16:9", "1:1"]')
        for a in ("16x9", "1x1"):
            synth(os.path.join(e.sdir, "media", "final-%s.mp4" % a))
        with open(os.path.join(e.sdir, "media", "final.vtt"), "w") as f:
            f.write("WEBVTT\n\n00:00:00.300 --> 00:00:02.900\nHello there\n")
        e.blur("16x9")
        code, res = e.run()
        self.assertEqual(code, 3)
        self.assertEqual(res["results"]["blur"]["verdicts"], {"16x9": "pass", "1x1": "incomplete"})
        e.blur("1x1")
        code, res = e.run()
        self.assertEqual(code, 0, res)

    def test_loudness_off_target(self):
        e = Env(self)
        synth(os.path.join(e.sdir, "media", "final-16x9.mp4"), af="volume=10dB")
        e.blur("16x9")
        code, res = e.run()
        self.assertEqual(code, 10)
        self.assertFalse(res["results"]["loudness"]["pass"])
        self.assertEqual(res["failures"][0]["owner"], "sound-mixer")

    def test_loudness_vs_mix_preview(self):
        e = self.good()
        e.blur("16x9")
        e.put("mix", {"preview": {"lufs": -16.0, "tp_db": -3.0}})
        code, res = e.run()
        self.assertEqual(code, 10)
        self.assertIn("#mix.preview", res["results"]["loudness"]["detail"])

    def test_black_found_and_allowed(self):
        e = self.good(black=True)
        e.blur("16x9")
        code, res = e.run("--only", "black")
        self.assertEqual(code, 10, res)
        h = res["results"]["black"]["hits"][0]
        self.assertAlmostEqual(h["t_start"], 2.0, delta=0.2)
        e.put("motion", {"allow": {"black": [[1900, 3100]], "freeze": []}})
        code, res = e.run("--only", "black")
        self.assertTrue(res["results"]["black"]["pass"])
        self.assertEqual(code, 3, res)  # a subset can never be a pass (R-03)
        self.assertFalse(res["pass"])

    def test_freeze_found(self):
        e = self.good(freeze=True)
        code, res = e.run("--only", "freeze")
        self.assertEqual(code, 10, res)
        self.assertEqual(res["failures"][0]["owner"], "capture-operator")

    def test_length_off(self):
        e = Env(self, length=20)
        synth(os.path.join(e.sdir, "media", "final-16x9.mp4"))
        code, res = e.run("--only", "length")
        self.assertEqual(code, 10)
        self.assertEqual(res["results"]["length"]["owner"], "storyboarder")

    def test_captions_lint(self):
        e = self.good()
        with open(os.path.join(e.sdir, "media", "final.vtt"), "w") as f:
            f.write("WEBVTT\n\n00:00:00.300 --> 00:00:02.900\nCreate an invoice\nin three clicks.\n\n"
                    "00:00:03.000 --> 00:00:05.000\n" + "x" * 60 + "\n")
        code, res = e.run("--only", "captions")
        self.assertEqual(code, 10)
        self.assertIn("60 chars", res["results"]["captions"]["detail"])

    def test_missing_output_is_input_error(self):
        e = Env(self)
        code, res = e.run()
        self.assertEqual(code, 2)
        self.assertEqual(res["failures"][0]["owner"], "render-engineer")

    def test_unmasked_capture_frames_are_a_leak(self):
        e = self.good()
        e.blur("16x9")
        e.put("events", {"clips": {"s01": {"masked": False, "mask": {"frames_unmasked": 2}}}})
        code, res = e.run()
        self.assertEqual(code, 11)
        self.assertEqual(res["privacy_capture"]["frames_unmasked"], 2)

    def test_set_checks_still_refused_and_runs_logged(self):
        e = self.good()
        with contextlib.redirect_stderr(io.StringIO()):
            rc = project.main(["--project", e.pj, "set", "checks", "--as", "render-engineer", "--json", "{}"])
        self.assertEqual(rc, 4)
        e.run("--dry-run")
        e.blur("16x9")
        e.run()
        with open(os.path.join(e.sdir, "runs.jsonl")) as f:
            self.assertTrue(any('"checks.py"' in l for l in f))

    def test_dry_run_runs_no_ffmpeg_and_writes_nothing(self):
        e = self.good()
        code, res = e.run("--dry-run")
        self.assertEqual((code, res["ffmpeg_passes"]), (0, 1))
        self.assertNotIn("checks", e.stored())


@need_ffmpeg
class StalenessTests(unittest.TestCase):
    """R-01/R-02/R-03/R-13/S-04/S-06/S-15: `pass` is recomputed from live evidence, never inherited."""

    def good(self):
        e = Env(self)
        synth(os.path.join(e.sdir, "media", "final-16x9.mp4"))
        with open(os.path.join(e.sdir, "media", "final.vtt"), "w") as f:
            f.write("WEBVTT\n\n00:00:00.300 --> 00:00:02.900\nCreate an invoice\n")
        e.blur("16x9")
        return e

    def test_only_subset_never_carries_an_old_pass(self):
        e = self.good()
        code, res = e.run()
        self.assertEqual(code, 0, res)
        self.assertTrue(e.stored()["checks"]["pass"])
        code, res = e.run("--only", "black")      # subset: exit 3, not pass, old results dropped
        self.assertEqual(code, 3, res)
        ck = e.stored()["checks"]
        self.assertFalse(ck["pass"])
        self.assertEqual(sorted(ck["results"]), ["black"])
        self.assertIn("blur", res["missing_checks"])
        self.assertEqual(ck["blur"]["16x9"]["verdict"], "pass")  # blur.py's verdict is kept

    def test_only_blur_is_exit_3_not_0(self):
        e = self.good()
        code, res = e.run("--only", "blur")
        self.assertEqual((code, res["status"], res["pass"]), (3, "incomplete", False))

    def test_leak_verdict_written_after_a_pass_makes_the_next_run_fail(self):
        e = self.good()
        self.assertEqual(e.run()[0], 0)
        e.blur("16x9", verdict="leak", hits=[{"region": "r1", "t_ms": 1, "match_len": 5}])
        code, res = e.run("--only", "black")
        self.assertFalse(e.stored()["checks"]["pass"])
        code, res = e.run()
        self.assertEqual(code, 11)
        self.assertFalse(e.stored()["checks"]["pass"])

    def test_rerender_after_verify_is_incomplete(self):
        e = self.good()
        self.assertEqual(e.run()[0], 0)
        synth(os.path.join(e.sdir, "media", "final-16x9.mp4"), dur=6)   # new file, same name
        code, res = e.run()
        self.assertEqual(code, 3, res)
        self.assertEqual(res["results"]["blur"]["verdict"], "incomplete")
        self.assertIn("not bound", res["results"]["blur"]["detail"])
        self.assertFalse(e.stored()["checks"]["pass"])

    def test_verdict_without_fingerprint_is_incomplete(self):
        e = Env(self)
        synth(os.path.join(e.sdir, "media", "final-16x9.mp4"))
        e.blur("16x9", bind=False)
        code, res = e.run("--only", "blur")
        self.assertEqual(res["results"]["blur"]["verdict"], "incomplete")

    def test_stale_upstream_key_makes_the_verdict_incomplete(self):
        e = self.good()
        self.assertEqual(e.run()[0], 0)
        e.put("blur", {"regions": []})          # #blur changed after verify
        code, res = e.run()
        self.assertEqual(code, 3, res)
        self.assertIn("#blur changed", res["results"]["blur"]["detail"])

    def test_timeline_scene_before_safe_from_ms_is_rejected(self):
        e = self.good()
        e.put("events", {"clips": {"s01": {"masked": True, "safe_from_ms": 900,
                                           "mask": {"rects_checked": 3, "frames_unmasked": 0}}}})
        e.blur("16x9")
        e.put("timeline", {"scenes": [{"id": "s01", "in": 400, "out": 6000, "speed": 1.0,
                                       "start": 0, "end": 6000}]})
        e.blur("16x9")
        code, res = e.run()
        self.assertEqual(code, 10, res)
        self.assertEqual(res["results"]["safe_start"]["owner"], "sync-editor")
        self.assertFalse(res["results"]["safe_start"]["pass"])

    def test_clip_not_captured_needs_blur_coverage(self):
        e = self.good()
        e.put("events", {"clips": {"s01": {"masked": False, "mask": {"rects_checked": 0}}}})
        e.blur("16x9")
        code, res = e.run()
        self.assertEqual(code, 3, res)
        self.assertEqual(res["privacy_capture"]["uncaptured"], ["s01"])
        self.assertEqual(res["failures"][-1]["owner"], "privacy-blurrer")
        # blur style and rect_checks==0 count as not captured even when masked is true
        e.put("events", {"clips": {"s01": {"masked": True, "mask": {"rects_checked": 0}}}})
        e.blur("16x9")
        self.assertEqual(e.run()[1]["privacy_capture"]["uncaptured"], ["s01"])
        e.put("events", {"clips": {"s01": {"masked": True, "mask": {"rects_checked": 4, "style": "blur"}}}})
        e.blur("16x9")
        self.assertEqual(e.run()[1]["privacy_capture"]["uncaptured"], ["s01"])
        # a blur region for the scene is the coverage
        e.put("blur", {"regions": [{"id": "b1", "scene": "s01", "bbox": [1, 1, 50, 20],
                                    "spans": [[0, 1000]], "mode": "static", "style": "opaque", "pad": 4}]})
        e.blur("16x9")
        code, res = e.run()
        self.assertEqual(code, 0, res)

    def weak_clip(self, **mask):
        m = {"rects_checked": 4, "frames_unmasked": 0}
        m.update(mask)
        return {"masked": True, "mask": m}

    def test_soft_frames_and_raised_thresholds_need_a_recorded_decision(self):   # S-24
        e = self.good()
        for mask in ({"frames_soft": 2}, {"thresholds": {"max_soft": 3, "max_resync": 0}},
                     {"thresholds": {"max_soft": 0, "max_resync": 0, "accepted_unmaskable": ["canvas"]}}):
            e.put("events", {"clips": {"s01": self.weak_clip(**mask)}})
            e.blur("16x9")
            code, res = e.run()
            self.assertEqual(code, 10, (mask, res))
            self.assertEqual(res["privacy_capture"]["undecided"], ["s01"])
            self.assertEqual(res["failures"][-1], {"id": "privacy_capture", "owner": "demo-director",
                                                   "class": "finding"})
        # the user's recorded decision (demo.yaml privacy.accepted) is the only way through
        with open(os.path.join(e.sdir, "demo.yaml"), "a") as f:
            f.write('privacy:\n  accepted: ["s01: user accepted 2 soft frames on 2026-11-21"]\n')
        code, res = e.run()
        self.assertEqual(code, 0, res)
        self.assertIn("s01", res["privacy_capture"]["weakened"])
        # a reason-less entry is no decision
        with open(os.path.join(e.sdir, "demo.yaml"), "w") as f:
            f.write('formats: ["16:9"]\nlength_s: 6\nprivacy:\n  accepted: ["s01: ok"]\n')
        self.assertEqual(e.run()[0], 10)

    def test_default_thresholds_without_soft_frames_pass(self):
        e = self.good()
        e.put("events", {"clips": {"s01": self.weak_clip(frames_soft=0, thresholds={
            "max_soft": 0, "max_resync": 0, "accepted_unmaskable": []})}})
        e.blur("16x9")
        self.assertEqual(e.run()[0], 0)

    def test_stale_tmp_capture_dir_is_a_finding(self):
        e = self.good()
        e.put("events", {"clips": {"s01": self.weak_clip()}})
        e.blur("16x9")
        os.makedirs(os.path.join(e.sdir, "media", ".tmp-s01-77"))
        code, res = e.run()
        self.assertEqual(code, 10, res)
        self.assertEqual(res["privacy_capture"]["stale_tmp"], ["media/.tmp-s01-77"])

    def test_unmaskable_without_region_is_incomplete(self):
        e = self.good()
        e.put("events", {"clips": {"s01": {"masked": True, "offset_ms": 0, "mask": {"rects_checked": 3},
                                           "unmaskable": [{"surface": "canvas", "reason": "canvas",
                                                           "bbox": [10, 10, 80, 30], "t_start": 0,
                                                           "t_end": 2000}]}}})
        e.blur("16x9")
        code, res = e.run()
        self.assertEqual(code, 3, res)
        self.assertIn("unmaskable", res["results"]["blur"]["detail"])
        self.assertEqual(res["results"]["blur"]["owner"], "privacy-blurrer")


class PureTests(unittest.TestCase):
    def test_parse_pass(self):
        txt = ("[blackdetect @ 0x1] black_start:2 black_end:3 black_duration:1\n"
               "[Parsed_freezedetect_1 @ 0x2] lavfi.freezedetect.freeze_start: 1.5\n"
               "[Parsed_freezedetect_1 @ 0x2] lavfi.freezedetect.freeze_end: 5.0\n"
               "[silencedetect @ 0x3] silence_start: 0\n[silencedetect @ 0x3] silence_end: 0.4 | silence_duration: 0.4\n"
               "    I:         -14.2 LUFS\n    Peak:      -1.3 dBFS\n")
        r = checks.parse_pass(txt, 6.0)
        self.assertEqual((r["lufs"], r["tp_db"]), (-14.2, -1.3))
        self.assertEqual((r["black"], r["freeze"], r["silence"]), ([[2.0, 3.0]], [[1.5, 5.0]], [[0.0, 0.4]]))


if __name__ == "__main__":
    unittest.main()
