"""Tests for scripts/setup_tools.py --python. Run: python -m unittest discover -s scripts/tests -v"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import setup_tools  # noqa: E402


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = setup_tools.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class PythonPath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.venv = os.path.join(self.dir, "myvenv")
        sub, exe = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
        self.py = os.path.join(self.venv, sub, exe)

    def fake_venv(self, root=None):
        py = self.py if root is None else os.path.join(root, os.path.relpath(self.py, self.venv))
        os.makedirs(os.path.dirname(py), exist_ok=True)
        with open(py, "w") as f:
            f.write("")
        return py

    def test_exists(self):
        self.fake_venv()
        code, out, err = run("--python", "--venv", self.venv)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.strip(), self.py)
        self.assertTrue(os.path.isabs(out.strip()))

    def test_missing(self):
        code, out, err = run("--python", "--venv", self.venv)
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertEqual(err, "venv not found at %s; run --install\n" % self.venv)

    def test_json(self):
        code, out, _ = run("--python", "--json", "--venv", self.venv)
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out), {"python": self.py, "exists": False})
        self.fake_venv()
        code, out, _ = run("--python", "--json", "--venv", self.venv)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"python": self.py, "exists": True})

    def test_default_venv_under_cwd(self):
        default = os.path.join(self.dir, ".demo", ".venv")
        self.fake_venv(default)
        old = os.getcwd()
        os.chdir(self.dir)
        try:
            code, out, _ = run("--python", "--json")
        finally:
            os.chdir(old)
        res = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(res["exists"])
        self.assertTrue(os.path.samefile(res["python"], os.path.join(
            default, os.path.relpath(self.py, self.venv))))
        self.assertTrue(os.path.isabs(res["python"]))

    def test_exclusive_with_other_commands(self):
        self.assertEqual(run("--python", "--list")[0], 2)


class Remotion(unittest.TestCase):
    """remotion/ source ships in the plugin; node_modules live only in <workspace>/remotion."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = setup_tools.Path(os.path.realpath(self._tmp.name))
        self.src = root / "src"
        (self.src / "src").mkdir(parents=True)
        (self.src / "package.json").write_text('{"name": "x"}')
        (self.src / "src" / "index.ts").write_text("registerRoot()")
        (self.src / "node_modules" / "junk").mkdir(parents=True)
        (self.src / "node_modules" / "junk" / "a.js").write_text("")
        self._old = setup_tools.REMOTION_SRC
        setup_tools.REMOTION_SRC = self.src
        self.addCleanup(setattr, setup_tools, "REMOTION_SRC", self._old)
        self.ctx = setup_tools.Ctx(None, str(root / "ws"))

    def test_sync_copies_source_without_node_modules(self):
        setup_tools.sync_remotion(self.ctx)
        dst = self.ctx.remotion_dir
        self.assertTrue((dst / "src" / "index.ts").exists())
        self.assertFalse((dst / "node_modules").exists())
        self.assertTrue(setup_tools.remotion_synced(self.ctx))

    def test_plugin_change_marks_copy_out_of_date(self):
        setup_tools.sync_remotion(self.ctx)
        (self.src / "src" / "index.ts").write_text("registerRoot(Root)")
        self.assertFalse(setup_tools.remotion_synced(self.ctx))
        setup_tools.sync_remotion(self.ctx)
        self.assertTrue(setup_tools.remotion_synced(self.ctx))

    def test_resync_drops_removed_files_keeps_node_modules(self):
        (self.src / "src" / "old.ts").write_text("")
        setup_tools.sync_remotion(self.ctx)
        dst = self.ctx.remotion_dir
        (dst / "node_modules" / "remotion").mkdir(parents=True)
        (self.src / "src" / "old.ts").unlink()
        setup_tools.sync_remotion(self.ctx)
        self.assertFalse((dst / "src" / "old.ts").exists())
        self.assertTrue((dst / "node_modules" / "remotion").exists())

    def test_default_workspace_is_dot_demo(self):
        ctx = setup_tools.Ctx(None, None)
        self.assertEqual(ctx.remotion_dir, setup_tools.Path.cwd() / ".demo" / "remotion")

    def test_plugin_ships_render_entry(self):
        for rel in ("package.json", "render.mjs", "src/index.ts"):
            self.assertTrue((self._old / rel).exists(), rel)
        self.assertFalse((self._old / "node_modules").exists(), "plugin must not keep node_modules")


class Pins(unittest.TestCase):
    def test_captions_stack_is_pinned(self):
        lines = (setup_tools.REQ_DIR / "captions.txt").read_text().split()
        for name in ("faster-whisper", "av"):
            self.assertTrue(any(l.startswith(name + "==") for l in lines), name)


class Capabilities(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.venv = os.path.join(self._tmp.name, "nov")  # does not exist: nothing installed

    def test_catalog_and_capabilities_agree(self):
        for cap, spec in setup_tools.CAPABILITIES.items():
            members = [k for k, f in setup_tools.CATALOG.items() if f.get("capability") == cap]
            self.assertEqual(sorted(members), sorted(spec["values"]), cap)
            self.assertIn(spec["default"], members)
            self.assertEqual(setup_tools.capability_members(cap)[0], spec["default"])
        for k, f in setup_tools.CATALOG.items():
            self.assertIn(f.get("capability"), (None, *setup_tools.CAPABILITIES), k)

    def test_options_json(self):
        code, out, _ = run("--options", "render", "--json", "--venv", self.venv)
        self.assertEqual(code, 0)
        cap = json.loads(out)["capabilities"][0]
        self.assertEqual([o["feature"] for o in cap["options"]], ["remotion", "motion-basic"])
        self.assertEqual([o["value"] for o in cap["options"]], ["remotion", "ffmpeg"])
        self.assertEqual([o["recommended"] for o in cap["options"]], [True, False])
        self.assertIsNone(cap["none"])  # every video needs a render engine

    def test_options_all_and_text(self):
        code, out, _ = run("--options", "--venv", self.venv)
        self.assertEqual(code, 0)
        for word in ("voice:", "render:", "(recommended)", "recorded"):
            self.assertIn(word, out)

    def test_options_unknown(self):
        code, _, err = run("--options", "nope", "--venv", self.venv)
        self.assertEqual(code, 2)
        self.assertIn("Unknown capability", err)

    def test_no_ocr_feature(self):
        code, out, _ = run("--list", "--json")
        self.assertEqual(code, 0)
        keys = [r["key"] for r in json.loads(out)["features"]]
        self.assertFalse([k for k in keys if "ocr" in k], keys)  # blur is checked by project.py check-blur
        self.assertNotIn("ocr", setup_tools.CAPABILITIES)


class Stages(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.venv = os.path.join(self._tmp.name, "nov")  # missing venv: everything is missing

    def stage(self, *argv):
        code, out, err = run("--stage", *argv, "--json", "--venv", self.venv)
        return code, (json.loads(out) if out else None), err

    def test_map_is_consistent(self):
        order = ["scout", "voice", "scenes", "capture", "blur", "sync", "motion", "captions", "mix", "render", "qa", "package"]
        self.assertEqual(list(setup_tools.STAGES), order)
        for n, st in setup_tools.STAGES.items():
            feats = list(st.get("needs", [])) + [o[0] for o in st.get("optional", [])]
            feats += [f for v in st.get("needs_by_platform", {}).values() for f in v]
            for f in feats:
                self.assertIn(f, setup_tools.CATALOG, n)
            for c in st.get("choices", []):
                self.assertIn(c, setup_tools.CAPABILITIES, n)
            for a in st["agents"]:
                self.assertTrue(any(a in f["agents"] for f in setup_tools.CATALOG.values()) or n in ("sync", "scout"), (n, a))

    def test_every_stage_runs(self):
        for n in setup_tools.STAGES:
            code, rep, _ = self.stage(n)
            self.assertEqual(code, 0, n)
            self.assertEqual(rep["stage"], n)
            code, out, _ = run("--stage", n, "--venv", self.venv)
            self.assertEqual(code, 0)
            self.assertIn("Stage " + n, out)

    def test_required_missing_plan(self):
        code, rep, _ = self.stage("captions")
        self.assertEqual(code, 0)
        self.assertFalse(rep["ready"])
        self.assertEqual(rep["suggested_features"], ["captions"])
        self.assertEqual(rep["plan"]["features"][0]["key"], "captions")
        self.assertEqual(rep["plan_command"], "setup_tools.py --plan captions")

    def test_choice_recommended_first_and_default_plan(self):
        _, rep, _ = self.stage("voice")
        ch = rep["choices"][0]
        self.assertEqual(ch["status"], "needs_choice")
        self.assertEqual([o["value"] for o in ch["options"]], ["edge", "kokoro", "elevenlabs"])
        self.assertTrue(ch["options"][0]["recommended"])
        self.assertEqual(rep["suggested_features"], ["voice-edge"])

    def test_choose_changes_plan(self):
        _, rep, _ = self.stage("voice", "--choose", "voice=kokoro", "--with", "captions")
        self.assertEqual(rep["suggested_features"], ["voice-kokoro", "captions"])
        _, rep, _ = self.stage("voice", "--choose", "voice=recorded")
        self.assertEqual(rep["suggested_features"], [])
        self.assertTrue(rep["ready"])
        self.assertIsNone(rep["plan"])
        _, rep, _ = self.stage("render", "--choose", "render=ffmpeg", "--with", "blur")
        self.assertEqual(rep["choices"][0]["chosen"], "ffmpeg")
        self.assertIn("blur", rep["suggested_features"])

    def test_platform_features(self):
        _, rep, _ = self.stage("capture")
        self.assertEqual([r["feature"] for r in rep["required"]], ["capture"])
        self.assertTrue(rep["platform_assumed"])
        _, rep, _ = self.stage("scenes", "--platform", "android")
        self.assertEqual([r["feature"] for r in rep["required"]], ["capture", "capture-android"])
        self.assertFalse(rep["platform_assumed"])

    def test_installed_is_ready(self):
        real = setup_tools.feature_states
        setup_tools.feature_states = lambda ctx, keys: {k: {"status": "installed", "reason": None} for k in keys}
        self.addCleanup(lambda: setattr(setup_tools, "feature_states", real))
        for n in setup_tools.STAGES:
            _, rep, _ = self.stage(n)
            self.assertTrue(rep["ready"], n)
            self.assertIsNone(rep["plan"], n)

    def test_overview(self):
        for argv in (("--stage",), ("--stages",)):
            code, out, _ = run(*argv, "--json", "--venv", self.venv)
            self.assertEqual(code, 0)
            self.assertEqual([r["stage"] for r in json.loads(out)["stages"]], list(setup_tools.STAGES))
        code, out, _ = run("--stages", "--venv", self.venv)
        self.assertIn("information only", out)

    def test_usage_errors(self):
        self.assertEqual(run("--stage", "nope", "--venv", self.venv)[0], 2)
        self.assertEqual(run("--stage", "voice", "--choose", "render=none", "--venv", self.venv)[0], 2)
        self.assertEqual(run("--stage", "voice", "--choose", "voice=zzz", "--venv", self.venv)[0], 2)
        self.assertEqual(run("--stage", "mix", "--with", "captions", "--venv", self.venv)[0], 2)
        self.assertEqual(run("--stage", "scenes", "--platform", "tv", "--venv", self.venv)[0], 2)
        self.assertEqual(run("--stage", "mix", "--list")[0], 2)

    def test_read_only(self):
        self.stage("voice")
        self.assertFalse(os.path.exists(self.venv))


if __name__ == "__main__":
    unittest.main()
