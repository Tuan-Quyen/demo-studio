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

    def blur(self, aspect, verdict="pass", ctrl=None, hits=()):
        project.write_checks(self.pj, {"blur": {aspect: {
            "verdict": verdict, "sampled": 3, "total": 3, "seconds": 1.0, "fullframe": {},
            "positive_control": ctrl if ctrl is not None else {"r1": True}, "hits": list(hits)}}},
            writer="blur.py", merge=True)

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
        self.assertEqual(code, 0, res)

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
