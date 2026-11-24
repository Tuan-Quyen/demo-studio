import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import project  # noqa: E402


def run(argv, cwd):
    old = os.getcwd()
    out, err = io.StringIO(), io.StringIO()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = project.main(argv)
    finally:
        os.chdir(old)
    return code, out.getvalue(), err.getvalue()


class ProjectPathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.slug_dir = os.path.join(self.root, ".demo", "vid")
        os.makedirs(self.slug_dir)
        self.pj = os.path.join(self.slug_dir, "project.json")

    def test_set_from_root_prints_version_and_path(self):
        code, out, _ = run(["--slug", "vid", "init"], self.root)
        self.assertEqual(code, 0)
        code, out, _ = run(["--slug", "vid", "set", "blur", "--as", "privacy",
                            "--json", '{"regions": []}'], self.root)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("blur version 1 ("), out)
        self.assertIn(self.pj, out)

    def test_run_from_inside_demo_dir_uses_same_file(self):
        run(["--slug", "vid", "init"], self.root)
        code, out, _ = run(["--slug", "vid", "set", "blur", "--as", "privacy",
                            "--json", "{}"], os.path.join(self.root, ".demo"))
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".demo", ".demo")))
        code, out, _ = run(["--slug", "vid", "get", "blur", "--version"], self.slug_dir)
        self.assertEqual(out.strip(), "1")

    def test_inside_demo_without_project_refuses(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        d = os.path.join(other.name, ".demo")
        os.makedirs(d)
        code, _, err = run(["--slug", "vid", "init"], d)
        self.assertEqual(code, 2)
        self.assertIn("inside .demo", err)
        self.assertFalse(os.path.exists(os.path.join(d, ".demo")))

    def test_explicit_nested_project_refused(self):
        bad = os.path.join(self.root, ".demo", ".demo", "vid", "project.json")
        code, _, err = run(["--project", bad, "init"], self.root)
        self.assertEqual(code, 2)
        self.assertIn("nested", err)

    def test_art_privacy_keys(self):
        run(["--slug", "vid", "init"], self.root)
        code, out, _ = run(["deps", "art"], self.root)
        self.assertEqual((code, out.split()), (0, ["privacy", "motion", "checks", "delivery"]))
        code, out, _ = run(["deps", "privacy"], self.root)
        self.assertEqual((code, out.split()), (0, []))
        code, out, _ = run(["deps", "art", "--json"], self.root)
        self.assertEqual([r["owner"] for r in json.loads(out)["rerun"]],
                         ["privacy", "motion-designer", "render-engineer", "packager"])
        for key, owner in (("art", "art-designer"), ("privacy", "privacy")):
            code, out, _ = run(["owner", key], self.root)
            self.assertEqual(out.strip(), owner)
            code, _, _ = run(["--slug", "vid", "set", key, "--as", "packager", "--json", "{}"], self.root)
            self.assertEqual(code, 4)
            code, out, _ = run(["--slug", "vid", "set", key, "--as", owner, "--json", "{}"], self.root)
            self.assertEqual(code, 0)
            self.assertTrue(out.startswith("%s version 1 (" % key), out)
        self.assertEqual(project.RUN_ORDER[:2], ["art", "privacy"])
        self.assertEqual(sorted(project.RUN_ORDER), sorted(project.OWNERS))
        pos = {k: i for i, k in enumerate(project.RUN_ORDER)}
        for k, deps in project.DOWNSTREAM.items():
            for d in deps:
                self.assertLess(pos[k], pos[d])

    def test_owner_mismatch_and_get_version_unset(self):
        run(["--slug", "vid", "init"], self.root)
        code, _, _ = run(["--slug", "vid", "set", "timeline", "--as", "x", "--json", "{}"], self.root)
        self.assertEqual(code, 4)
        code, out, _ = run(["--slug", "vid", "get", "timeline", "--version"], self.root)
        self.assertEqual(out.strip(), "0")
        run(["--slug", "vid", "set", "timeline", "--as", "sync-editor", "--json", '{"total_s": 1}'], self.root)
        code, out, _ = run(["--slug", "vid", "get", "timeline"], self.root)
        self.assertNotIn("version", json.loads(out))  # version lives in _meta: use --version / keys


def _proj(markers, regions, timeline=None, w=1280, h=720):
    data = {"events": {"clips": {"s01": {"w": w, "h": h, "fps": 25, "offset_ms": 0, "duration_ms": 5000}},
                       "markers": [{"t": 0, "scene": "s01", "type": "scene_start", "bbox": None}]
                       + markers + [{"t": 4000, "scene": "s01", "type": "scene_end", "bbox": None}]},
            "blur": {"schema": 1, "space": "source", "time": "scene", "regions": regions}}
    if timeline is not None:
        data["timeline"] = {"scenes": timeline}
    return data


def _sens(t, bbox, label="email"):
    return {"t": t, "scene": "s01", "type": "sensitive", "bbox": bbox, "label": label}


def _reg(t0, t1, bbox, rid="b1", pad=0, margin=0, strength=25, mode="boxblur"):
    return {"id": rid, "scene": "s01", "t_start": t0, "t_end": t1, "bbox": bbox, "pad": pad,
            "margin_ms": margin, "mode": mode, "strength": strength, "keyframes": None}


class CheckBlurTests(unittest.TestCase):
    def test_static_marker_covered_passes(self):
        r = project.check_blur(_proj([_sens(100, [100, 100, 200, 40])],
                                     [_reg(100, 4000, [100, 100, 200, 40], pad=4)]))
        self.assertTrue(r["pass"], r)
        self.assertGreater(r["frames_checked"], 0)

    def test_region_ending_early_is_a_gap_with_its_span(self):
        r = project.check_blur(_proj([_sens(100, [100, 100, 200, 40])],
                                     [_reg(100, 2000, [100, 100, 200, 40])]))
        self.assertFalse(r["pass"])
        [g] = r["gaps"]
        self.assertEqual((g["t_from"], g["t_to"], g["owner"]), (2040, 4000, "privacy"))
        self.assertEqual(g["frames"], 50)  # 25 fps clip: 2040, 2080, ... 4000

    def test_transit_needs_the_hull_not_only_the_endpoints(self):
        marks = [_sens(1000, [80, 600, 170, 40]), _sens(1300, [80, 100, 170, 40])]
        ends = [_reg(1000, 1150, [80, 600, 170, 40], "a"), _reg(1150, 4000, [80, 100, 170, 40], "b")]
        self.assertFalse(project.check_blur(_proj(marks, ends))["pass"])
        hull = [_reg(1000, 1300, [80, 100, 170, 540], "a"), _reg(1300, 4000, [80, 100, 170, 40], "b")]
        self.assertTrue(project.check_blur(_proj(marks, hull))["pass"])

    def test_sensitive_end_stops_the_requirement(self):
        marks = [_sens(100, [10, 10, 50, 20]), _sens(900, None)]
        self.assertTrue(project.check_blur(_proj(marks, [_reg(100, 900, [10, 10, 50, 20])]))["pass"])

    def test_bbox_outside_frame_is_invalid_for_capture_operator(self):
        r = project.check_blur(_proj([_sens(0, [1250, 10, 100, 20])], []))
        self.assertFalse(r["pass"])
        self.assertEqual(r["invalid"][0]["owner"], "capture-operator")
        self.assertEqual(r["gaps"], [])

    def test_weak_strength_for_tall_text(self):
        r = project.check_blur(_proj([_sens(0, [0, 0, 400, 120])],
                                     [_reg(0, 4000, [0, 0, 400, 120], strength=20)]))
        self.assertEqual([w["region"] for w in r["weak"]], ["b1"])
        self.assertEqual(r["weak"][0]["needed"], 36.0)
        ok = project.check_blur(_proj([_sens(0, [0, 0, 400, 120])],
                                      [_reg(0, 4000, [0, 0, 400, 120], strength=25, mode="pixelate")]))
        self.assertTrue(ok["pass"], ok)  # pixelate radius = 25 * 1.6 = 40

    def test_only_the_rendered_window_counts(self):
        marks = [_sens(0, [10, 10, 50, 20])]
        regs = [_reg(0, 2000, [10, 10, 50, 20])]
        self.assertFalse(project.check_blur(_proj(marks, regs))["pass"])
        cut = [{"id": "s01", "in": 0, "out": 1900, "start": 0, "end": 1900, "speed": 1}]
        self.assertTrue(project.check_blur(_proj(marks, regs, timeline=cut))["pass"])

    def test_every_rendered_frame_is_checked(self):
        # gap 31..49 ms holds the 40 ms frame of a 25 fps render; 20 ms steps from 15 (15/35/55) missed it
        marks = [_sens(15, [10, 10, 50, 20])]
        regs = [_reg(0, 30, [10, 10, 50, 20], "a"), _reg(50, 4000, [10, 10, 50, 20], "b")]
        r = project.check_blur(_proj(marks, regs))
        self.assertFalse(r["pass"])
        self.assertEqual([(g["t_from"], g["t_to"], g["frames"]) for g in r["gaps"]], [(40, 40, 1)])

    def test_frames_follow_the_timeline_mapping(self):
        # offset 100, in 300 (clip ms), speed 2 at 25 fps: scene ms 200, 280, 360, ...
        data = _proj([_sens(0, [10, 10, 50, 20])], [_reg(0, 4000, [10, 10, 50, 20])],
                     timeline=[{"id": "s01", "in": 300, "out": 1300, "start": 1000, "end": 1500, "speed": 2}])
        data["events"]["clips"]["s01"]["offset_ms"] = 100
        clip = data["events"]["clips"]["s01"]
        self.assertEqual(project._frame_times(clip, data["timeline"]["scenes"][0], 3900, 25)[:3],
                         [220.0, 300.0, 380.0])  # round(300 ms at 25 fps) = frame 8 = 320 ms clip
        r = project.check_blur(data)
        self.assertTrue(r["pass"], r)
        self.assertEqual(r["frames_checked"], 13)  # round(500 ms * 25 fps / 1000) = 12.5 -> 13

    def test_cli_exit_codes(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pj = os.path.join(tmp.name, "project.json")
        data = _proj([_sens(0, [10, 10, 50, 20])], [_reg(0, 1000, [10, 10, 50, 20])])
        with open(pj, "w", encoding="utf-8") as f:
            json.dump(data, f)
        code, out, _ = run(["--project", pj, "check-blur"], tmp.name)
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["pass"])
        del data["blur"]
        with open(pj, "w", encoding="utf-8") as f:
            json.dump(data, f)
        code, _, err = run(["--project", pj, "check-blur"], tmp.name)
        self.assertEqual(code, 2)
        self.assertIn("privacy", err)


if __name__ == "__main__":
    unittest.main()
