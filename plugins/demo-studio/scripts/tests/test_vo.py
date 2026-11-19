"""Tests for scripts/vo.py with synthetic WAVs. Run: python -m unittest discover -s scripts/tests -v"""
import array
import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import vo  # noqa: E402

RATE = 24000


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = vo.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def tone(ms, rate=RATE, ch=1):
    n = int(rate * ms / 1000)
    s = array.array("h")
    for i in range(n):
        v = int(0.3 * 32767 * math.sin(2 * math.pi * 440 * i / rate))
        s.extend([v] * ch)
    return s


def silence(ms, rate=RATE, ch=1):
    return array.array("h", [0]) * (int(rate * ms / 1000) * ch)


def seq(*parts):
    out = array.array("h")
    for p in parts:
        out.extend(p)
    return out


class VoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def wav(self, name, samples, rate=RATE, ch=1):
        path = os.path.join(self.dir, name)
        with wave.open(path, "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(samples.tobytes())
        return path

    def path(self, name):
        return os.path.join(self.dir, name)

    def frames(self, path):
        with wave.open(path, "rb") as w:
            return w.getnframes()

    def raw_like(self, name="raw.wav"):
        # 0.2 s lead, 1 s speech, 0.9 s internal gap, 1 s speech, 0.85 s tail
        return self.wav(name, seq(silence(200), tone(1000), silence(900), tone(1000), silence(850)))


class Trim(VoTest):
    def test_trim_accuracy(self):
        src = self.wav("a.wav", seq(silence(600), tone(1000), silence(850)))
        code, out, _ = run("trim", src, self.path("o.wav"))
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertAlmostEqual(res["lead_ms"], 200, delta=10)
        self.assertAlmostEqual(res["trail_ms"], 150, delta=10)
        self.assertAlmostEqual(res["duration_ms"], 200 + 1000 + 150, delta=20)
        self.assertEqual(self.frames(self.path("o.wav")), int(res["duration_ms"] * RATE / 1000))

    def test_trim_options_and_short_margins_kept(self):
        src = self.wav("a.wav", seq(silence(80), tone(500), silence(60)))
        res = json.loads(run("trim", src, self.path("o.wav"), "--lead-ms", "200",
                             "--trail-ms", "30")[1])
        self.assertAlmostEqual(res["lead_ms"], 80, delta=10)  # cannot add silence
        self.assertAlmostEqual(res["trail_ms"], 30, delta=10)

    def test_stereo(self):
        src = self.wav("s.wav", seq(silence(500, ch=2), tone(300, ch=2), silence(500, ch=2)), ch=2)
        res = json.loads(run("trim", src, self.path("o.wav"))[1])
        self.assertAlmostEqual(res["lead_ms"], 200, delta=10)
        with wave.open(self.path("o.wav"), "rb") as w:
            self.assertEqual(w.getnchannels(), 2)

    def test_all_silent_is_error(self):
        src = self.wav("z.wav", silence(500))
        self.assertEqual(run("trim", src, self.path("o.wav"))[0], 2)

    def test_missing_and_bad_files(self):
        self.assertEqual(run("trim", self.path("none.wav"), self.path("o.wav"))[0], 2)
        bad = self.path("bad.wav")
        with open(bad, "wb") as f:
            f.write(b"not a wav")
        self.assertEqual(run("check", bad)[0], 2)


class Join(VoTest):
    def test_join_gap_exact(self):
        a = self.wav("a.wav", seq(silence(300), tone(500), silence(850)))
        b = self.wav("b.wav", seq(silence(100), tone(700), silence(900)))
        code, out, _ = run("join", self.path("o.wav"), a, b, "--gap-ms", "300", "--edge-ms", "50")
        self.assertEqual(code, 0)
        res = json.loads(out)
        seg = res["segments"]
        self.assertEqual(len(seg), 2)
        self.assertAlmostEqual(seg[1]["start_ms"] - seg[0]["end_ms"], 300, delta=1)
        # total length is exact: trimmed pieces + exactly 300 ms of silence
        ta = vo.trim_audio(vo.read_wav(a), 50, 50, -50).frames
        tb = vo.trim_audio(vo.read_wav(b), 50, 50, -50).frames
        self.assertEqual(self.frames(self.path("o.wav")), ta + tb + 300 * RATE // 1000)
        self.assertAlmostEqual(res["lead_ms"], 50, delta=10)
        self.assertAlmostEqual(res["trail_ms"], 50, delta=10)
        # the silence between the two tones measures about gap + 2 * edge
        chk = json.loads(run("check", self.path("o.wav"), "--gap-max", "100", "--lead-max", "100",
                             "--trail-max", "100", "--pause-ms", "400")[1])
        self.assertEqual(len(chk["internal_gaps"]), 1)
        self.assertAlmostEqual(chk["internal_gaps"][0]["len_ms"], 400, delta=20)

    def test_mismatched_formats_exit_2(self):
        a = self.wav("a.wav", tone(300))
        b = self.wav("b.wav", tone(300, rate=16000), rate=16000)
        code, _, err = run("join", self.path("o.wav"), a, b)
        self.assertEqual(code, 2)
        self.assertIn("differ", err)
        c = self.wav("c.wav", tone(300, ch=2), ch=2)
        self.assertEqual(run("join", self.path("o.wav"), a, c)[0], 2)
        self.assertFalse(os.path.exists(self.path("o.wav")))

    def test_single_input(self):
        a = self.wav("a.wav", seq(silence(500), tone(300), silence(500)))
        res = json.loads(run("join", self.path("o.wav"), a)[1])
        self.assertEqual(len(res["segments"]), 1)


class Check(VoTest):
    def test_raw_like_file_fails(self):
        code, out, _ = run("check", self.raw_like())
        self.assertEqual(code, 1)
        res = json.loads(out)
        self.assertFalse(res["pass"])
        self.assertAlmostEqual(res["trail_ms"], 850, delta=20)
        self.assertEqual(len(res["internal_gaps"]), 1)
        self.assertAlmostEqual(res["internal_gaps"][0]["len_ms"], 900, delta=20)
        self.assertAlmostEqual(res["internal_gaps"][0]["start_ms"], 1200, delta=20)
        self.assertEqual(len(res["failures"]), 2)  # tail + gap (lead 200 ms is within limit)

    def test_passes_after_trim_and_join(self):
        raw1 = self.wav("r1.wav", seq(silence(200), tone(1000), silence(850)))
        raw2 = self.wav("r2.wav", seq(silence(200), tone(1000), silence(850)))
        self.assertEqual(run("check", raw1)[0], 1)  # 850 ms tail
        run("trim", raw1, self.path("t1.wav"))
        code, out, _ = run("check", self.path("t1.wav"))
        self.assertEqual(code, 0, out)
        run("join", self.path("j.wav"), raw1, raw2, "--gap-ms", "300")
        code, out, _ = run("check", self.path("j.wav"), "--lead-max", "100", "--trail-max", "100")
        self.assertEqual(code, 0, out)
        res = json.loads(out)
        self.assertTrue(res["pass"])
        self.assertEqual(res["failures"], [])

    def test_pause_allowance(self):
        path = self.wav("p.wav", seq(tone(500), silence(800), tone(500)))
        self.assertEqual(run("check", path)[0], 1)
        code, out, _ = run("check", path, "--pause-ms", "800")
        self.assertEqual(code, 0, out)
        res = json.loads(out)
        self.assertTrue(res["internal_gaps"][0]["allowed"])
        self.assertEqual(run("check", path, "--pause-ms", "700")[0], 0)  # within +-150
        self.assertEqual(run("check", path, "--pause-ms", "600")[0], 1)  # 200 ms off
        self.assertEqual(run("check", path, "--pause-ms", "600", "--pause-ms", "800")[0], 0)

    def test_short_gaps_are_not_reported(self):
        path = self.wav("g.wav", seq(tone(500), silence(300), tone(500)))
        res = json.loads(run("check", path)[1])
        self.assertEqual(res["internal_gaps"], [])
        self.assertTrue(res["pass"])


class Threshold(unittest.TestCase):
    def test_single_default_threshold(self):
        p = vo.build_parser()
        defaults = {c: p.parse_args(a).threshold_db for c, a in
                    (("trim", ["trim", "i", "o"]), ("join", ["join", "o", "i"]),
                     ("check", ["check", "i"]))}
        self.assertEqual(set(defaults.values()), {vo.SILENCE_DB}, defaults)


if __name__ == "__main__":
    unittest.main()
