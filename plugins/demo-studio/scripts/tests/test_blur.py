import contextlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import blur  # noqa: E402
import fake_ocr  # noqa: E402
import project  # noqa: E402
import run_bounded as rb  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
need_ffmpeg = unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "ffmpeg/ffprobe missing")
CLIPS = {"s01": {"file": "media/s01.raw.mp4", "w": 640, "h": 360, "fps": 25, "offset_ms": 0},
         "s02": {"file": "media/s02.raw.mp4", "w": 640, "h": 360, "fps": 25, "offset_ms": 0}}


def legacy(i, scene, bbox=(100, 90, 300, 50), t=(0, 3000), **kw):
    r = {"id": "b%d" % i, "scene": scene, "t_start": t[0], "t_end": t[1], "bbox": list(bbox),
         "pad": 12, "margin_ms": 0, "mode": "boxblur", "strength": 25,
         "source": "events:sensitive:email", "keyframes": None}
    r.update(kw)
    return r


band_ocr_ref = fake_ocr.band_ocr


def no_fullframe_text(rgb, w, h):
    """An OCR blind on full frames (640x360) that still reads ROI crops."""
    return [] if (w, h) == (640, 360) else band_ocr_ref(rgb, w, h)


def um(**kw):
    u = {"surface": "canvas", "selector": "canvas#c", "reason": "canvas", "t_start": 500,
         "t_end": 2500, "bbox": [200, 120, 120, 60]}
    u.update(kw)
    return u


class PlanTests(unittest.TestCase):
    def test_duplicate_static_regions_merge_into_one_with_many_spans(self):
        regs = [legacy(i, "s%02d" % i) for i in range(1, 11)]
        clips = {"s%02d" % i: {"fps": 25, "masked": False} for i in range(1, 11)}
        out, rep = blur.plan_regions(regs, clips)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["spans"]), 10)
        self.assertIsNone(out[0]["scene"])
        self.assertEqual(out[0]["merged_ids"][0], "b1")
        self.assertEqual(rep["merged"], 9)
        self.assertEqual(out[0]["mode"], "static")

    def test_adjacent_spans_in_one_scene_join_but_gaps_do_not(self):
        regs = [legacy(1, "s01", t=(0, 1000)), legacy(2, "s01", t=(1050, 2000)),
                legacy(3, "s01", t=(5000, 6000))]
        out, _ = blur.plan_regions(regs, merge_gap_ms=100)
        self.assertEqual(out[0]["spans"], [[0, 2000], [5000, 6000]])

    def test_different_bbox_not_merged(self):
        out, _ = blur.plan_regions([legacy(1, "s01"), legacy(2, "s01", bbox=(10, 10, 300, 50))])
        self.assertEqual(len(out), 2)

    def test_thin_strip_is_cover_and_opaque(self):
        out, _ = blur.plan_regions([legacy(1, "s01", bbox=(81, 0, 176, 7))])
        self.assertEqual((out[0]["mode"], out[0]["style"]), ("cover", "opaque"))

    def test_secret_label_is_opaque_never_pixelated(self):
        r = legacy(1, "s01", mode="pixelate", source="events:sensitive:API key")
        out, _ = blur.plan_regions([r])
        self.assertEqual(out[0]["style"], "opaque")

    def test_strength_rule_by_text_height(self):
        self.assertEqual(blur.strength("boxblur", 24), 6)    # ceil(h/4)
        self.assertEqual(blur.strength("boxblur", 25), 7)
        self.assertEqual(blur.strength("pixelize", 24), 8)   # ceil(h/3)

    def test_moving_region_adjacent_frames_stay_one_track_not_interpolated(self):
        kfs = [{"t": 1000 + 40 * i, "bbox": [81, 700 - 100 * i, 176, 42]} for i in range(5)]
        r = legacy(1, "s01", bbox=(81, 300, 176, 42), t=(1000, 1160), keyframes=kfs,
                   source="events:sensitive:name")
        out, _ = blur.plan_regions([r], CLIPS)
        self.assertEqual(out[0]["mode"], "track")
        self.assertEqual(len(out[0]["keyframes"]), 5)       # exactly the given keyframes
        self.assertEqual(out[0]["keyframes"][1][2], 600)    # nothing invented in between

    def test_keyframe_jump_without_split_is_exit_2(self):
        kfs = [{"t": 1000, "bbox": [81, 700, 176, 42]}, {"t": 1400, "bbox": [81, 100, 176, 42]}]
        r = legacy(1, "s01", t=(1000, 1400), keyframes=kfs)
        with self.assertRaises(blur.BlurError) as cm:
            blur.plan_regions([r], CLIPS)
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(cm.exception.failures[0]["class"], "jump")

    def test_explicit_split_segments_the_track(self):
        kfs = [{"t": 1000, "bbox": [81, 700, 176, 42]},
               {"t": 1400, "bbox": [81, 100, 176, 42], "split": True}]
        r = legacy(1, "s01", t=(1000, 1400), keyframes=kfs)
        out, _ = blur.plan_regions([r], CLIPS)
        self.assertEqual(len(out[0]["spans"]), 2)
        self.assertLess(out[0]["spans"][0][1], out[0]["spans"][1][0])  # the gap stays uncovered

    def test_small_drift_within_pad_is_fine_with_long_gap(self):
        kfs = [{"t": 1000, "bbox": [81, 100, 176, 42]}, {"t": 2000, "bbox": [85, 104, 176, 42]}]
        out, _ = blur.plan_regions([legacy(1, "s01", t=(1000, 2000), keyframes=kfs)], CLIPS)
        self.assertEqual(out[0]["mode"], "track")

    def test_masked_clip_drops_capture_mask_regions_only(self):
        regs = [legacy(1, "s01", source="capture-mask"), legacy(2, "s01", bbox=(1, 1, 99, 30))]
        out, rep = blur.plan_regions(regs, {"s01": {"masked": True}})
        self.assertEqual([r["id"] for r in out], ["b2"])
        self.assertEqual(rep["dropped"], ["b1"])

    def test_unmasked_clip_keeps_every_region(self):
        regs = [legacy(1, "s01", source="capture-mask"), legacy(2, "s01", bbox=(1, 1, 99, 30))]
        for clips in ({"s01": {"masked": False}}, {}):
            out, rep = blur.plan_regions(regs, clips)
            self.assertEqual(len(out), 2)
            self.assertEqual(rep["dropped"], [])

    def test_capture_mask_drop_needs_every_spanned_scene_masked(self):  # R-12
        r = legacy(1, "s01", source="capture-mask")
        r2 = dict(legacy(2, "s02", source="capture-mask"))
        merged = dict(r, spans=[[0, 3000, "s01"], [0, 3000, "s02"]], scene=None)
        out, rep = blur.plan_regions([merged], {"s01": {"masked": True}, "s02": {"masked": False}})
        self.assertEqual((len(out), rep["dropped"]), (1, []))
        out, rep = blur.plan_regions([merged], {"s01": {"masked": True}, "s02": {"masked": True}})
        self.assertEqual((len(out), rep["dropped"]), (0, ["b1"]))

    def test_unmaskable_becomes_opaque_padded_region_in_scene_time(self):  # R-04
        clips = {"s01": {"masked": True, "offset_ms": 300, "w": 640, "h": 360, "unmaskable": [um()]}}
        out, rep = blur.plan_regions([], clips)
        self.assertEqual(rep["unmaskable_regions"], 1)
        r = out[0]
        self.assertEqual((r["style"], r["source"], r["scene"], r["bbox"]), ("opaque", "unmaskable", "s01",
                                                                         [200, 120, 120, 60]))
        self.assertEqual(r["spans"], [[200, 2200]])           # clip ms minus offset_ms
        self.assertGreater(r["pad"], 0)
        self.assertEqual(blur.uncovered_unmaskable(out, clips), [])
        out2, rep2 = blur.plan_regions(out, clips)            # idempotent: already covered
        self.assertEqual((len(out2), rep2["unmaskable_regions"]), (1, 0))

    def test_unmaskable_without_bbox_or_time_is_exit_2(self):
        for bad in (um(bbox=None), um(t_start=None), {"surface": "iframe", "attr": "src", "tag": "iframe",
                                                       "selector": "iframe"}):
            with self.assertRaises(blur.BlurError) as cm:
                blur.plan_regions([], {"s01": {"unmaskable": [bad]}})
            self.assertEqual(cm.exception.code, 2)
            self.assertEqual(cm.exception.failures[0]["owner"], "capture-operator")

    def test_uncovered_unmaskable_detects_missing_and_too_small_regions(self):
        clips = {"s01": {"offset_ms": 0, "unmaskable": [um()]}}
        self.assertEqual(len(blur.uncovered_unmaskable([], clips)), 1)
        small = blur.plan_regions([legacy(1, "s01", bbox=(200, 120, 20, 20), t=(500, 2500))])[0]
        self.assertEqual(len(blur.uncovered_unmaskable(small, clips)), 1)
        short = blur.plan_regions([legacy(1, "s01", bbox=(200, 120, 120, 60), t=(500, 900))])[0]
        self.assertEqual(len(blur.uncovered_unmaskable(short, clips)), 1)

    def test_needs_input_exit_2(self):
        with self.assertRaises(blur.BlurError) as cm:
            blur.plan_regions([legacy(1, "s01"), {"id": "bx", "scene": "s01", "t_start": 0,
                                                  "t_end": 5, "bbox": None}])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(cm.exception.failures[0]["id"], "bx")

    def test_plan_is_idempotent_on_its_own_output(self):
        regs = [legacy(i, "s%02d" % i) for i in (1, 2)]
        out1, _ = blur.plan_regions(regs)
        out2, _ = blur.plan_regions(out1)
        strip = lambda rs: [{k: v for k, v in r.items() if k != "merged_ids"} for r in rs]  # noqa: E731
        self.assertEqual(strip(out1), strip(out2))


class Workspace(unittest.TestCase):
    """A .demo/vid project with a synthetic raw clip (text on white) per scene."""
    dur = 4

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.sdir = os.path.join(self.root, ".demo", "vid")
        os.makedirs(os.path.join(self.sdir, "media"))
        self.pj = os.path.join(self.sdir, "project.json")

    def ff(self, *args):
        r = subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-y", *args], capture_output=True,
                           text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)

    def make_raw(self, name="s01", text=True):
        vf = "drawtext=text='demo@example.com':fontsize=32:fontcolor=black:x=110:y=100" if text else "null"
        self.ff("-f", "lavfi", "-i", "color=c=white:s=640x360:r=25:d=%d" % self.dur, "-vf", vf,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                os.path.join(self.sdir, "media", "%s.raw.mp4" % name))

    def write_project(self, regions, scenes=("s01",)):
        clips = {s: dict(CLIPS["s01"], file="media/%s.raw.mp4" % s) for s in scenes}
        tl = {"scenes": [{"id": s, "clip": clips[s]["file"], "in": 0, "out": self.dur * 1000,
                          "speed": 1.0, "start": i * self.dur * 1000,
                          "end": (i + 1) * self.dur * 1000} for i, s in enumerate(scenes)]}
        data = {"_meta": {"schema": 2, "keys": {}}, "events": {"clips": clips}, "timeline": tl,
                "blur": {"schema": 2, "space": "source", "time": "scene", "regions": regions}}
        with open(self.pj, "w") as f:
            json.dump(data, f)

    def region(self, **kw):
        r = {"id": "b1", "scene": "s01", "bbox": [100, 90, 340, 50], "spans": [[0, 4000]],
             "mode": "static", "style": "boxblur", "pad": 12, "text_h": 32, "secret": False,
             "source": "events"}
        r.update(kw)
        return r

    def cli(self, argv, ocr=None):
        out, err = io.StringIO(), io.StringIO()
        old = os.getcwd()
        os.chdir(self.root)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = blur.main(argv, ocr=ocr)
        finally:
            os.chdir(old)
        last = out.getvalue().strip().splitlines()[-1] if out.getvalue().strip() else "{}"
        return code, json.loads(last)

    def render_with_graph(self, dst, space="final", scene=None):
        argv = ["--slug", "vid", "graph", "--space", space]
        if scene:
            argv += ["--scene", scene]
        code, g = self.cli(argv)
        self.assertEqual(code, 0, g)
        src = os.path.join(self.sdir, "media", "s01.raw.mp4")
        self.ff("-i", src, "-filter_complex", g["filter_complex"], "-map", "[vb]", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", dst)
        return g

    def frames(self, path, times):
        s = blur.FrameStream(path, times, 640, 360, wall=60)
        it = iter(s)
        out = list(it)
        it.close()
        return out

    @staticmethod
    def px(buf, x, y, w=640):
        i = (y * w + x) * 3
        return tuple(buf[i:i + 3])


@need_ffmpeg
class GraphTests(Workspace):
    def test_graph_string_shape(self):
        self.write_project([self.region(spans=[[0, 1000], [2000, 3000]]),
                            self.region(id="b2", bbox=[10, 0, 100, 6], mode="cover", style="opaque")])
        code, g = self.cli(["--slug", "vid", "graph", "--space", "final", "--aspect", "16x9"])
        fc = g["filter_complex"]
        self.assertEqual(code, 0)
        self.assertIn("between(t,0,1)+between(t,2,3)", fc)
        # enable= on BOTH the blur and the overlay
        self.assertRegex(fc, r"boxblur=lr=8:lp=1:enable='between\(t,0,1\)\+between\(t,2,3\)'")
        self.assertRegex(fc, r"overlay@tr0=x=88:y=78:enable='between\(t,0,1\)\+between\(t,2,3\)'")
        self.assertRegex(fc, r"drawbox@tr1=.*color=black:t=fill:enable=")
        self.assertEqual(fc.count("split"), 1)       # cover strip needs no split/blur branch
        self.assertTrue(fc.startswith("[0:v]") and fc.endswith("[vb]"))
        self.assertEqual(g["branches"], 2)

    def test_same_box_across_scenes_is_one_branch(self):
        self.write_project([self.region(scene=None, spans=[[0, 1000, "s01"], [0, 1000, "s02"]])],
                           scenes=("s01", "s02"))
        _, g = self.cli(["--slug", "vid", "graph", "--space", "final"])
        self.assertEqual(g["branches"], 1)
        self.assertIn("between(t,0,1)+between(t,4,5)", g["filter_complex"])

    def test_source_space_filters_by_scene_and_uses_clip_time(self):
        self.write_project([self.region(scene=None, spans=[[0, 1000, "s01"], [500, 900, "s02"]])],
                           scenes=("s01", "s02"))
        _, g = self.cli(["--slug", "vid", "graph", "--space", "source", "--scene", "s02"])
        self.assertIn("between(t,0.5,0.9)", g["filter_complex"])
        self.assertNotIn("between(t,0,1)", g["filter_complex"])

    def test_tiny_box_for_radius_falls_back_to_opaque(self):
        self.write_project([self.region(bbox=[100, 100, 200, 10], text_h=40, pad=0)])
        _, g = self.cli(["--slug", "vid", "graph", "--space", "final"])
        self.assertIn("drawbox", g["filter_complex"])
        self.assertTrue(g["notes"])

    def test_graph_with_no_regions_is_passthrough(self):
        self.write_project([])
        _, g = self.cli(["--slug", "vid", "graph", "--space", "final"])
        self.assertEqual(g["filter_complex"], "[0:v]null[vb]")

    def test_static_graph_blurs_only_inside_its_window(self):
        self.make_raw()
        self.write_project([self.region(spans=[[1000, 2000]], style="opaque")])
        dst = os.path.join(self.root, "out.mp4")
        self.render_with_graph(dst)
        before, during, after = (f for _, f in self.frames(dst, [0.5, 1.5, 2.5]))
        self.assertLess(sum(self.px(during, 150, 115)), 30)          # opaque inside the window
        self.assertGreater(sum(self.px(before, 105, 80)), 700)       # white before
        self.assertGreater(sum(self.px(after, 105, 80)), 700)        # and after

    def test_blur_hides_text_that_raw_shows(self):
        self.make_raw()
        self.write_project([self.region()])
        dst = os.path.join(self.root, "out.mp4")
        self.render_with_graph(dst)
        raw = self.frames(os.path.join(self.sdir, "media", "s01.raw.mp4"), [1.0])[0][1]
        out = self.frames(dst, [1.0])[0][1]
        box = (88, 78, 364, 74)
        raw_bands = fake_ocr._bands(blur.crop_rgb(raw, 640, box[0], box[1], box[2], box[3]),
                                    box[2], box[3])
        out_bands = fake_ocr._bands(blur.crop_rgb(out, 640, box[0], box[1], box[2], box[3]),
                                    box[2], box[3])
        self.assertTrue(raw_bands)
        self.assertFalse(out_bands)

    def test_moving_region_follows_keyframes_frame_by_frame(self):
        self.write_project([])
        src = os.path.join(self.sdir, "media", "s01.raw.mp4")
        self.ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=4", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", src)
        kfs = [[2000 + 40 * i, 100 + 8 * i, 150, 60, 30] for i in range(25)]
        reg = self.region(mode="track", style="opaque", bbox=[100, 150, 60, 30], pad=4,
                          keyframes=kfs, spans=[[2000, 3000]])
        self.write_project([reg])
        dst = os.path.join(self.root, "out.mp4")
        g = self.render_with_graph(dst)
        self.assertEqual(g["sendcmd_times"], 25)
        for i in (2, 10, 20):
            t = (2000 + 40 * i) / 1000.0
            (pts, buf), = self.frames(dst, [t])
            cx, cy = 100 + 8 * i + 30, 150 + 15
            self.assertEqual(self.px(buf, cx, cy), (0, 0, 0), "frame %d at t=%s" % (i, pts))
            # where the region was at keyframe 0 (it moved on) is not covered any more
            if i == 20:
                self.assertNotEqual(self.px(buf, 100 + 30, cy), (0, 0, 0))

    def test_moving_blur_branch_renders(self):
        self.write_project([])
        src = os.path.join(self.sdir, "media", "s01.raw.mp4")
        self.ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=4", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", src)
        kfs = [[1000 + 40 * i, 50 + 10 * i, 150, 200, 40] for i in range(10)]
        self.write_project([self.region(mode="track", bbox=[50, 150, 200, 40], keyframes=kfs,
                                        spans=[[1000, 1400]], text_h=32)])
        self.render_with_graph(os.path.join(self.root, "o.mp4"))

    def test_plan_cli_writes_blur_and_graph_runs_on_schema1(self):
        regs = [legacy(1, "s01"), legacy(2, "s02")]
        self.write_project([])
        d = json.load(open(self.pj))
        d["blur"] = {"schema": 1, "space": "source", "time": "scene", "regions": regs}
        d["_meta"]["keys"]["blur"] = {"version": 1, "owner": "privacy-blurrer", "updated": "x"}
        d["events"]["clips"]["s02"] = dict(CLIPS["s02"], masked=False)
        d["timeline"]["scenes"].append({"id": "s02", "in": 0, "out": 4000, "speed": 1.0,
                                        "start": 4000, "end": 8000})
        json.dump(d, open(self.pj, "w"))
        code, res = self.cli(["--slug", "vid", "plan", "--dry-run"])
        self.assertEqual((code, res["regions_out"]), (0, 1))
        self.assertEqual(json.load(open(self.pj))["blur"]["schema"], 1)       # dry run: untouched
        code, g = self.cli(["--slug", "vid", "graph", "--space", "final"])    # schema 1 planned in memory
        self.assertEqual((code, g["branches"]), (0, 1))
        code, res = self.cli(["--slug", "vid", "plan"])
        self.assertEqual(code, 0)
        new = json.load(open(self.pj))
        self.assertEqual(new["blur"]["schema"], 2)
        self.assertEqual(len(new["blur"]["regions"]), 1)
        self.assertEqual(new["_meta"]["keys"]["blur"]["version"], 2)
        with open(os.path.join(self.sdir, "runs.jsonl")) as f:
            self.assertIn("blur.py", f.read())

    def test_plan_cli_exit_2_on_jump(self):
        kfs = [{"t": 1000, "bbox": [81, 700, 176, 42]}, {"t": 1400, "bbox": [81, 100, 176, 42]}]
        self.write_project([])
        d = json.load(open(self.pj))
        d["blur"]["regions"] = [legacy(1, "s01", t=(1000, 1400), keyframes=kfs)]
        json.dump(d, open(self.pj, "w"))
        code, res = self.cli(["--slug", "vid", "plan"])
        self.assertEqual(code, 2)
        self.assertEqual(res["failures"][0]["class"], "jump")


@need_ffmpeg
class VerifyTests(Workspace):
    def setUp(self):
        super().setUp()
        self.make_raw()
        self.write_project([self.region()])
        self.blurred = os.path.join(self.root, "blurred.mp4")
        self.render_with_graph(self.blurred)

    def verify(self, video, ocr=fake_ocr.band_ocr, extra=()):
        return self.cli(["--slug", "vid", "verify", "--video", video, "--aspect", "16x9",
                         *extra], ocr=ocr)

    def checks(self):
        return json.load(open(self.pj)).get("checks", {})

    def test_blurred_output_passes_and_records_checks(self):
        code, res = self.verify(self.blurred)
        self.assertEqual((code, res["verdict"]), (0, "pass"), res)
        self.assertEqual(res["positive_control"], {"b1": True, "fullframe": True})
        self.assertGreater(res["fullframe"]["sampled"], 0)
        self.assertEqual(res["sampled"], res["total"])
        self.assertEqual(self.checks()["blur"]["16x9"]["verdict"], "pass")
        self.assertEqual(self.checks()["blur"]["16x9"]["hits"], [])

    def test_unblurred_output_is_a_leak_exit_11_without_plaintext(self):
        code, res = self.verify(os.path.join(self.sdir, "media", "s01.raw.mp4"))
        self.assertEqual((code, res["verdict"]), (11, "leak"))
        hit = res["hits"][0]
        self.assertEqual(set(hit) - {"hmac"}, {"region", "t_ms", "match_len"})
        self.assertEqual(hit["match_len"], len("demo@example.com"))
        self.assertNotIn("demo@example.com", json.dumps(self.checks()))
        self.assertEqual(res["failures"][0]["owner"], "privacy-blurrer")

    def test_failed_positive_control_is_inconclusive_not_pass(self):
        self.make_raw(text=False)   # raw has no readable text: the OCR "cannot read it" there
        code, res = self.verify(self.blurred)
        self.assertEqual((code, res["verdict"]), (10, "inconclusive"))
        self.assertEqual(res["positive_control"], {"b1": False, "fullframe": True})
        self.assertEqual(self.checks()["blur"]["16x9"]["verdict"], "inconclusive")

    def test_missing_raw_clip_means_no_control_inconclusive(self):
        os.unlink(os.path.join(self.sdir, "media", "s01.raw.mp4"))
        code, res = self.verify(self.blurred)
        self.assertEqual((code, res["verdict"]), (10, "inconclusive"))

    def test_budget_is_enforced_in_code(self):
        t = time.monotonic()
        code, res = self.verify(self.blurred, ocr=fake_ocr.slow_band_ocr(0.4),
                                extra=["--budget-s", "1.5"])
        self.assertEqual((code, res["verdict"]), (3, "incomplete"))
        self.assertLess(time.monotonic() - t, 1.5 + 10)
        self.assertLess(res["sampled"], res["total"])
        self.assertEqual(self.checks()["blur"]["16x9"]["verdict"], "incomplete")

    def test_budget_is_checked_before_every_positive_control_ocr_call(self):
        code, res = self.verify(self.blurred, ocr=fake_ocr.slow_band_ocr(0.2), extra=["--budget-s", "0.01"])
        self.assertEqual(code, 3, res)
        self.assertIs(self.checks()["pass"] if "pass" in self.checks() else False, False)

    def test_one_decode_per_output_and_one_per_raw_clip(self):
        real = rb.Bounded
        launched = []

        class Spy(real):
            def __init__(self, cmd, *a, **k):
                launched.append(os.path.basename(cmd[0]))
                super().__init__(cmd, *a, **k)

        with mock.patch.object(rb, "Bounded", Spy):
            code, res = self.verify(self.blurred)
        self.assertEqual(code, 0, res)
        # 1 raw (positive control) + 1 output + 1 render of the full-frame control frame
        self.assertEqual(launched.count("ffmpeg"), 3)

    def test_two_outputs_two_aspect_entries(self):
        self.verify(self.blurred)
        self.cli(["--slug", "vid", "verify", "--video", self.blurred, "--aspect", "1x1"],
                 ocr=fake_ocr.band_ocr)
        self.assertEqual(sorted(self.checks()["blur"]), ["16x9", "1x1"])

    def test_hmac_key_outside_project_json(self):
        code, res = self.verify(os.path.join(self.sdir, "media", "s01.raw.mp4"), extra=["--hmac"])
        self.assertEqual(code, 11)
        self.assertTrue(os.path.exists(os.path.join(self.sdir, ".secret", "key")))
        self.assertEqual(len(res["hits"][0]["hmac"]), 16)
        key = open(os.path.join(self.sdir, ".secret", "key"), "rb").read()
        self.assertNotIn(key.hex(), open(self.pj).read())  # the key itself never enters project.json
        import hashlib
        self.assertNotEqual(res["hits"][0]["hmac"],        # keyed, so not a bare brute-forceable hash
                            hashlib.sha256(b"demo@example.com").hexdigest()[:16])

    def test_dry_run_decodes_nothing(self):
        code, res = self.verify(self.blurred, extra=["--dry-run"])
        self.assertEqual(code, 0)
        self.assertGreater(res["frames"], 0)
        self.assertNotIn("checks", json.load(open(self.pj)))

    def test_seeded_without_regions_runs_the_fullframe_pass(self):
        self.write_project([])
        with open(os.path.join(self.sdir, "demo.yaml"), "w") as f:
            f.write('privacy:\n  data_mode: seeded\n  seed_confirmation: "yes"\n')
        code, res = self.verify(self.blurred)
        self.assertEqual((code, res["verdict"]), (0, "pass"), res)
        self.assertGreater(res["total"], 0)               # never "pass" on zero samples (S-05, R-11)
        self.assertGreater(res["fullframe"]["sampled"], 0)

    def test_runs_jsonl_redacts_regex_literals(self):
        with open(os.path.join(self.sdir, "demo.yaml"), "w") as f:
            f.write('privacy:\n  regexes: ["demo@example[.]com"]\n')
        self.verify(self.blurred, extra=["--pattern", "zzz"])
        argv = json.loads(open(os.path.join(self.sdir, "runs.jsonl")).read().splitlines()[-1])["argv"]
        self.assertNotIn("demo@example[.]com", " ".join(argv))


@need_ffmpeg
class VerdictLifecycleTests(Workspace):
    """R-01/R-02/R-05/S-04/S-05/S-11/S-12/S-14 on a real clip with the fake OCR."""

    def setUp(self):
        super().setUp()
        self.make_raw()
        self.write_project([self.region()])
        self.blurred = os.path.join(self.root, "blurred.mp4")
        self.render_with_graph(self.blurred)

    def project_with(self, **extra):
        d = json.load(open(self.pj))
        d.update(extra)
        json.dump(d, open(self.pj, "w"))

    def verify(self, video=None, ocr=fake_ocr.band_ocr, extra=(), aspect="16x9"):
        return self.cli(["--slug", "vid", "verify", "--video", video or self.blurred, "--aspect", aspect,
                         *extra], ocr=ocr)

    def checks(self):
        return json.load(open(self.pj)).get("checks", {})

    def test_verify_resets_pass_and_drops_stale_blur_results(self):
        old = {"schema": 2, "pass": True, "results": {"blur": {"pass": True}, "black": {"pass": True}},
               "blur": {"16x9": {"verdict": "pass"}, "1x1": {"verdict": "pass"}}}
        self.project_with(checks=old)
        code, res = self.verify(os.path.join(self.sdir, "media", "s01.raw.mp4"))   # leak
        self.assertEqual(code, 11)
        ck = self.checks()
        self.assertIs(ck["pass"], False)
        self.assertNotIn("blur", ck["results"])
        self.assertEqual(ck["results"]["black"], {"pass": True})    # other checks' results stay for reference
        self.assertEqual(ck["blur"]["16x9"]["verdict"], "leak")
        self.assertEqual(ck["blur"]["1x1"]["verdict"], "pass")      # another aspect is untouched

    def test_verify_never_sets_pass_true(self):
        self.project_with(checks={"schema": 2, "pass": True})
        code, res = self.verify()
        self.assertEqual(code, 0, res)
        self.assertIs(self.checks()["pass"], False)

    def test_crashed_verify_leaves_pass_false(self):
        self.project_with(checks={"schema": 2, "pass": True, "blur": {"16x9": {"verdict": "pass"}}})
        with self.assertRaises(RuntimeError):     # guard_main turns this into exit 70 on the CLI
            self.verify(ocr=fake_ocr.hang_now)
        self.assertIs(self.checks()["pass"], False)
        self.assertNotIn("16x9", self.checks()["blur"])

    def test_verdict_binds_the_verified_file_and_input_versions(self):
        project.store_key(self.pj, "blur", "privacy-blurrer", json.load(open(self.pj))["blur"], 5)
        final = os.path.join(self.sdir, "media", "final-16x9.mp4")
        shutil.copyfile(self.blurred, final)
        code, res = self.verify(final)
        self.assertEqual(code, 0, res)
        e = self.checks()["blur"]["16x9"]
        self.assertEqual(e["video"], "media/final-16x9.mp4")
        st = os.stat(final)
        self.assertEqual((e["file"]["size"], e["file"]["mtime_ns"], e["file"]["ino"]),
                         (st.st_size, st.st_mtime_ns, st.st_ino))
        self.assertEqual(len(e["file"]["sha256"]), 64)      # inside the slug folder: hashed via the cache
        self.assertIn("media/final-16x9.mp4", json.load(open(os.path.join(self.sdir, "cache", "hashes.json"))))
        self.assertEqual(e["inputs"], {"blur": 1})

    def test_unmaskable_not_in_plan_is_exit_2_for_graph_and_verify(self):
        d = json.load(open(self.pj))
        d["events"]["clips"]["s01"]["unmaskable"] = [um()]
        json.dump(d, open(self.pj, "w"))
        code, res = self.cli(["--slug", "vid", "graph", "--space", "final"])
        self.assertEqual(code, 2)
        self.assertIn("unmaskable", res["error"])
        code, res = self.verify()
        self.assertEqual(code, 2)
        self.assertIs(self.checks()["pass"], False)
        code, res = self.cli(["--slug", "vid", "plan"])            # plan adds the region ...
        self.assertEqual((code, res["unmaskable_regions"]), (0, 1))
        code, res = self.cli(["--slug", "vid", "graph", "--space", "final"])   # ... and graph accepts it
        self.assertEqual(code, 0, res)
        self.assertIn("drawbox", res["filter_complex"])

    def test_timeline_scene_before_safe_from_ms_is_exit_2(self):
        d = json.load(open(self.pj))
        d["events"]["clips"]["s01"]["safe_from_ms"] = 800
        d["timeline"]["scenes"][0]["in"] = 200
        json.dump(d, open(self.pj, "w"))
        code, res = self.cli(["--slug", "vid", "graph", "--space", "final"])
        self.assertEqual(code, 2)
        self.assertEqual(res["failures"][0]["owner"], "sync-editor")
        self.assertEqual(self.verify()[0], 2)

    def test_non_identity_aspect_needs_transforms(self):
        sq = os.path.join(self.root, "sq.mp4")
        self.ff("-i", self.blurred, "-vf", "scale=360:360", "-c:v", "libx264", "-pix_fmt", "yuv420p", sq)
        code, res = self.verify(sq, aspect="1x1")
        self.assertEqual(code, 2)
        self.assertEqual(res["failures"][0], {"id": "transforms.1x1", "owner": "render-engineer",
                                             "class": "needs-input"})
        self.assertNotIn("1x1", self.checks().get("blur", {}))
        code, res = self.cli(["--slug", "vid", "set-transform", "--aspect", "1x1", "--scale", "1",
                              "--ox", "-140", "--oy", "0"])
        self.assertEqual(code, 0, res)
        self.assertEqual(json.load(open(self.pj))["blur"]["transforms"]["1x1"]["ox"], -140)
        code, res = self.verify(sq, aspect="1x1", ocr=fake_ocr.band_ocr)
        self.assertNotEqual(code, 2, res)          # mapped now (the fake OCR decides leak/pass)

    def test_motion_zoom_needs_transform_with_segments(self):
        self.project_with(motion={"effects": [{"scene": "s01", "type": "zoom", "t_start": 500,
                                               "t_end": 1500, "params": {"scale": 1.6}}]})
        code, res = self.verify()
        self.assertEqual(code, 2)
        self.assertIn("transforms", res["error"])
        self.assertEqual(self.cli(["--slug", "vid", "set-transform", "--aspect", "16x9", "--identity"])[0], 0)
        code, res = self.verify()
        self.assertEqual(code, 2)
        self.assertIn("segments", res["error"])
        self.assertEqual(self.cli(["--slug", "vid", "set-transform", "--aspect", "16x9", "--identity",
                                   "--segment", "0.5", "1.5", "1.6", "-100", "-60"])[0], 0)
        code, res = self.verify()
        self.assertNotEqual(code, 2, res)
        # an effect limited to another aspect does not require it
        self.project_with(motion={"effects": [{"type": "zoom", "params": {"aspects": ["9x16"]}}]})
        d = json.load(open(self.pj))
        d["blur"].pop("transforms")
        json.dump(d, open(self.pj, "w"))
        self.assertEqual(self.verify()[0], 0)

    def test_segments_split_rois_by_mapping_window(self):
        tr = {"scale": 1.0, "ox": 0.0, "oy": 0.0,
              "segments": [{"t0": 1.0, "t1": 2.0, "scale": 2.0, "ox": -100.0, "oy": -50.0}]}
        pieces = blur.tr_pieces(tr, [(0.0, 4.0)])
        self.assertEqual([(p[0]["scale"], p[1]) for p in pieces], [(2.0, [(1.0, 2.0)]),
                                                                    (1.0, [(0.0, 1.0), (2.0, 4.0)])])
        clips = {"s01": dict(CLIPS["s01"])}
        tl = {"scenes": [{"id": "s01", "in": 0, "out": 4000, "speed": 1.0, "start": 0, "end": 4000}]}
        reg = blur._as_v2([self.region()], clips)
        rois = blur.build_rois(reg, blur.TimeMap("final", clips, tl), clips, tr, (640, 360), 25, [])
        self.assertEqual(len(rois), 2)
        boxes = {roi["bbox"][0] for roi in rois}
        self.assertEqual(len(boxes), 2)                       # same region, two different output boxes

    def test_blur_fuzz_is_not_a_hit_but_readable_text_is(self):   # R-16
        clips = {"s01": dict(CLIPS["s01"])}
        tl = {"scenes": [{"id": "s01", "in": 0, "out": 4000, "speed": 1.0, "start": 0, "end": 4000}]}
        tr = blur.default_transform("16x9", (640, 360), (640, 360))

        def run(read):
            rois = blur.build_rois(blur._as_v2([self.region()], clips), blur.TimeMap("final", clips, tl),
                                   clips, tr, (640, 360), 25, [])
            for r in rois:
                r["ctrl_text"] = "demo@example.com"
            ocr = lambda rgb, w, h: [{"text": read, "box": None}]   # noqa: E731
            return blur.run_verify(self.blurred, rois, ocr, 4.0, 25.0, (640, 360), budget_s=30,
                                   stride_s=2.0, fullframe=False, full_matcher=blur.make_matcher([r"x"]),
                                   controls={"b1": True})["verdict"]
        self.assertEqual(run("Bengngie con"), "pass")
        self.assertEqual(run("demo@example.com"), "leak")
        self.assertEqual(run("demo@exampl"), "leak")        # a real partial read (>= 4 char run)
        self.assertTrue(blur.similar_text("Demo @ Example.com", "demo@example.com"))
        self.assertFalse(blur.similar_text("Bengngie con", "demo@example.com"))

    def test_seeded_values_are_searched_full_frame(self):
        self.write_project([])
        with open(os.path.join(self.sdir, "demo.yaml"), "w") as f:
            f.write('privacy:\n  data_mode: seeded\n  seed_confirmation: "yes"\n'
                    '  seed_values: ["demo@example.com"]\n')
        code, res = self.verify(os.path.join(self.sdir, "media", "s01.raw.mp4"))
        self.assertEqual((code, res["verdict"]), (11, "leak"))
        self.assertEqual(res["hits"][0]["region"], "fullframe")

    def test_zero_samples_is_incomplete_never_pass(self):
        r = blur.run_verify(self.blurred, [], fake_ocr.band_ocr, 4.0, 25.0, (640, 360), budget_s=30,
                            stride_s=2.0, fullframe=False, full_matcher=blur.make_matcher([r"x"]),
                            controls={})
        self.assertEqual((r["verdict"], r["incomplete_reason"]), ("incomplete", "no-samples"))

    def test_blind_fullframe_ocr_is_inconclusive(self):
        code, res = self.verify(ocr=no_fullframe_text)
        self.assertEqual((code, res["verdict"]), (10, "inconclusive"))
        self.assertEqual(res["positive_control"], {"b1": True, "fullframe": False})

    def test_tools_ocr_none_is_inconclusive_not_exit_4(self):
        with open(os.path.join(self.sdir, "demo.yaml"), "w") as f:
            f.write("tools:\n  ocr: none\n")
        code, res = self.cli(["--slug", "vid", "verify", "--video", self.blurred, "--aspect", "16x9"])
        self.assertEqual((code, res["verdict"]), (10, "inconclusive"))
        self.assertEqual(self.checks()["blur"]["16x9"]["verdict"], "inconclusive")
        self.assertEqual(res["failures"][0]["id"], "ocr")

    def test_tools_ocr_maps_to_engine(self):
        a = type("A", (), {"ocr": None})()
        for val, want in (("qa-ocr", "rapidocr"), ("qa-ocr-tesseract", "tesseract"), ("none", "none"),
                          ("null", "rapidocr")):
            with open(os.path.join(self.sdir, "demo.yaml"), "w") as f:
                f.write("tools:\n  ocr: %s\n" % val)
            self.assertEqual(blur.resolve_ocr(a, self.sdir), want)
        a.ocr = "python:m:f"
        self.assertEqual(blur.resolve_ocr(a, self.sdir), "python:m:f")

    def test_hmac_key_is_created_0600_in_a_0700_dir(self):
        blur.hmac_key_for(self.sdir, create=True)
        key = os.path.join(self.sdir, ".secret", "key")
        if os.name == "posix":
            self.assertEqual(os.stat(key).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(os.path.dirname(key)).st_mode & 0o777, 0o700)
        self.assertEqual(blur.hmac_key_for(self.sdir), open(key, "rb").read())

    def test_runs_jsonl_redacts_pattern_literals_and_abbreviations(self):
        with open(os.path.join(self.sdir, "demo.yaml"), "w") as f:
            f.write('privacy:\n  seed_values: ["Acme Seed Corp"]\n')
        self.verify(extra=["--pattern", "zz-literal-99"])
        line = open(os.path.join(self.sdir, "runs.jsonl")).read().splitlines()[-1]
        self.assertNotIn("zz-literal-99", line)
        with self.assertRaises(SystemExit):               # no abbreviations: `--pat` is refused
            blur.build_parser().parse_args(["--slug", "vid", "verify", "--video", "x", "--aspect", "a",
                                            "--pat", "secret-lit"])


def _ocr_python():
    """An interpreter with rapidocr: this one, or $DEMO_STUDIO_OCR_PYTHON (a toolkit venv)."""
    import importlib.util
    if importlib.util.find_spec("rapidocr") and importlib.util.find_spec("onnxruntime"):
        return sys.executable
    cand = os.environ.get("DEMO_STUDIO_OCR_PYTHON")
    if cand and os.path.exists(cand):
        r = subprocess.run([cand, "-c", "import rapidocr, onnxruntime"], capture_output=True)
        return cand if r.returncode == 0 else None
    return None


@need_ffmpeg
@unittest.skipUnless(_ocr_python(), "real OCR integration needs rapidocr+onnxruntime in this interpreter "
                                    "or in $DEMO_STUDIO_OCR_PYTHON (not installed)")
class RealOcrVerifyTests(Workspace):
    """verify with the real RapidOCR engine: the unblurred crop is read (positive control), the blurred
    output is not, and a raw output is a leak."""

    def test_real_engine_reads_unblurred_not_blurred(self):
        self.make_raw()
        # 32 px text with the strength-rule floor (lr 8): the real engine still reads fuzz out of it
        # ("Bengngie con"), which is NOT the protected text: pass (R-16). A raw output stays a leak.
        self.write_project([self.region()])
        blurred = os.path.join(self.root, "blurred.mp4")
        self.render_with_graph(blurred)

        def cli(video):
            r = subprocess.run([_ocr_python(), os.path.join(os.path.dirname(HERE), "blur.py"), "--slug",
                                "vid", "verify", "--video", video, "--aspect", "16x9", "--ocr", "rapidocr",
                                "--budget-s", "240"], cwd=self.root, capture_output=True, text=True,
                               timeout=300)
            return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])

        code, res = cli(blurred)
        self.assertEqual(code, 0, res)
        self.assertEqual(res["verdict"], "pass")
        self.assertEqual(res["positive_control"], {"b1": True, "fullframe": True})   # the raw crop IS read
        self.assertEqual(res["hits"], [])                                              # the blurred one is not
        code, res = cli(os.path.join(self.sdir, "media", "s01.raw.mp4"))
        self.assertEqual(code, 11, res)
        self.assertEqual(res["verdict"], "leak")


@need_ffmpeg
class OcrWorkerTests(Workspace):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"PYTHONPATH": HERE})
        env.start()
        self.addCleanup(env.stop)

    def test_worker_roundtrip_and_engine_built_once(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        w = blur.OcrWorker("python:fake_ocr:echo", "en", 30, d)
        self.addCleanup(w.close)
        buf = bytes([255]) * (64 * 40 * 3)
        self.assertEqual(w(buf, 64, 40), [])
        self.assertEqual(w(buf, 64, 40), [])
        self.assertEqual(os.listdir(d), [])                 # crops are deleted as soon as read

    def test_unavailable_engine_is_exit_4(self):
        with self.assertRaises(blur.BlurError) as cm:
            blur.OcrWorker("python:fake_ocr:broken", "en", 30, self.root)
        self.assertEqual(cm.exception.code, 4)

    def test_hung_ocr_worker_is_killed_by_stall(self):
        w = blur.OcrWorker("python:fake_ocr:hang", "en", 60, self.root, stall=3.0)
        t = time.monotonic()
        with self.assertRaises(blur.BlurError) as cm:
            w(bytes([0]) * (8 * 8 * 3), 8, 8)
        self.assertEqual(cm.exception.code, 70)
        self.assertLess(time.monotonic() - t, 20)
        w.close()
        self.assertEqual(w.b.reason, "stall")


class HelperTests(unittest.TestCase):
    def test_montage_bands_and_min_height(self):
        a = (4, 2, bytes([10]) * (4 * 2 * 3))
        b = (6, 3, bytes([20]) * (6 * 3 * 3))
        w, h, buf, bands = blur.montage([a, b], min_h=10, gap=2)
        self.assertEqual((w, h, len(buf)), (6, 24, 6 * 24 * 3))
        self.assertEqual(bands, [(0, 2), (12, 15)])

    def test_select_script_picks_first_frame_at_or_after_each_time(self):
        s = blur.select_script([0.5, 2])
        self.assertIn("gte(t,0.5)", s)
        self.assertIn("prev_selected_t", s)
        self.assertTrue(s.endswith("showinfo"))

    def test_matcher_generic_vs_pattern(self):
        self.assertEqual(blur.make_matcher([])("ab"), 0)
        self.assertGreater(blur.make_matcher([])("hello"), 0)
        self.assertEqual(blur.make_matcher([r"sk-\w+"])("hello"), 0)
        self.assertEqual(blur.make_matcher([r"sk-\w+"])("key sk-abc123"), 9)

    def test_default_transform_same_aspect_and_cover(self):
        t = blur.default_transform("16x9", (1280, 720), (1920, 1080))
        self.assertAlmostEqual(t["scale"], 1.5)
        t = blur.default_transform("9x16", (1280, 720), (1080, 1920))
        self.assertAlmostEqual(t["scale"], 1920 / 720.0)
        self.assertLess(t["ox"], 0)
        self.assertIsNone(blur.map_bbox([0, 0, 10, 10], t, 1080, 1920))  # cropped away

    def test_sample_schedule_every_half_second_plus_first_last_and_track_frames(self):
        roi = {"id": "r", "spans": [(1.0, 3.0)], "bbox": (0, 0, 10, 10), "matcher": None}
        s = blur.sample_schedule([roi], 10.0, 25, 2.0, False)
        self.assertEqual(sorted(s), [1.0, 1.5, 2.0, 2.5, 2.96])
        trk = {"id": "t", "spans": [(1.0, 1.2)], "boxes": [(1.0, (0, 0, 1, 1)), (1.04, (0, 0, 1, 1)),
                                                           (1.08, (0, 0, 1, 1))], "matcher": None}
        s = blur.sample_schedule([trk], 10.0, 25, 2.0, False)
        self.assertIn(1.04, s)
        self.assertIn(1.08, s)
        s = blur.sample_schedule([], 6.0, 25, 2.0, True)
        self.assertEqual(sorted(s), [0.0, 2.0, 4.0, 5.96])


if __name__ == "__main__":
    unittest.main()
