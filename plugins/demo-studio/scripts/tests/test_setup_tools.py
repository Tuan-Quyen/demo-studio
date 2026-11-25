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


class MobileFeatures(unittest.TestCase):
    """Android/iOS use adb / AXe via mobile_driver.py: no Appium, nothing to pip-install."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.venv = os.path.join(self._tmp.name, "nov")
        self._os = os.environ.get("DEMO_STUDIO_OS")
        self.addCleanup(self.restore_os)

    def restore_os(self):
        if self._os is None:
            os.environ.pop("DEMO_STUDIO_OS", None)
        else:
            os.environ["DEMO_STUDIO_OS"] = self._os

    def plan(self, os_name):
        os.environ["DEMO_STUDIO_OS"] = os_name
        code, out, _ = run("--plan", "capture-android,capture-ios", "--json", "--venv", self.venv,
                           "--workspace", self._tmp.name)
        return {f["key"]: f for f in json.loads(out)["features"]}

    def test_no_appium_or_pip(self):
        for k in ("capture-android", "capture-ios"):
            f = setup_tools.CATALOG[k]
            self.assertIsNone(f["reqs"], k)
            self.assertEqual(f["modules"], [], k)
            self.assertFalse(f.get("appium") or f["node"], k)
            self.assertIn("app-scout", f["agents"], k)
        self.assertIn("axe", setup_tools.CATALOG["capture-ios"]["bins"])

    def test_ios_blocked_off_mac_even_when_capture_is_pending(self):
        feats = self.plan("win")
        self.assertEqual(feats["capture-ios"]["action"], "blocked")
        self.assertEqual(feats["capture"]["action"], "install")

    def test_driver_ships_and_is_stdlib(self):
        src = (setup_tools.REQ_DIR.parent / "mobile_driver.py").read_text(encoding="utf-8")
        self.assertNotIn("appium", src.split('"""', 2)[2].lower())


class Stages(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.venv = os.path.join(self._tmp.name, "nov")  # missing venv: everything is missing

    def stage(self, *argv):
        code, out, err = run("--stage", *argv, "--json", "--venv", self.venv)
        return code, (json.loads(out) if out else None), err

    def test_map_is_consistent(self):
        order = ["scout", "art", "voice", "scenes", "capture", "blur", "sync", "motion", "captions", "mix", "render", "qa", "package"]
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

    def test_art_stage_after_scout_uses_render_choice(self):
        names = list(setup_tools.STAGES)
        self.assertEqual(names.index("art"), names.index("scout") + 1)
        _, rep, _ = self.stage("art", "--choose", "render=remotion")
        self.assertEqual(rep["agents"], ["art-designer"])
        self.assertEqual(rep["choices"][0]["chosen"], "remotion")
        self.assertIn("remotion", rep["suggested_features"])
        _, rep, _ = self.stage("art", "--choose", "render=ffmpeg")
        self.assertNotIn("remotion", rep["suggested_features"])

    def test_platform_features(self):
        _, rep, _ = self.stage("capture")
        self.assertEqual([r["feature"] for r in rep["required"]], ["capture"])
        self.assertTrue(rep["platform_assumed"])
        _, rep, _ = self.stage("scenes", "--platform", "android")
        self.assertEqual([r["feature"] for r in rep["required"]], ["capture", "capture-android"])
        self.assertFalse(rep["platform_assumed"])
        _, rep, _ = self.stage("scout", "--platform", "ios")
        self.assertEqual([r["feature"] for r in rep["required"]], ["capture", "capture-ios"])
        _, rep, _ = self.stage("scout", "--platform", "desktop")
        self.assertEqual([r["feature"] for r in rep["required"]], ["capture"])

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



class BrowserFallback(unittest.TestCase):
    """--install remotion smoke-tests Chrome; on macOS a hanging download is replaced by a cached copy."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = setup_tools.Path(os.path.realpath(self._tmp.name))
        ws = self.root / "proj" / ".demo"
        self.ctx = setup_tools.Ctx(None, str(ws))
        self.ctx.demo_dir, self.ctx.toolkit = ws, ws / "toolkit.json"  # never touch the cwd's .demo
        rem = ws / "remotion" / "node_modules"
        (rem / "remotion").mkdir(parents=True)
        (rem / "remotion" / "package.json").write_text('{"version": "4.0.541"}')
        self.chrome = rem / ".remotion" / "chrome-headless-shell" / "mac-arm64" / "chrome-headless-shell-mac-arm64"
        self.chrome.mkdir(parents=True)
        (self.chrome / "chrome-headless-shell").write_text("bin")
        (self.chrome / "icudtl.dat").write_text("icu")
        self.cache = self.root / "cache"
        for k, v in (("DEMO_STUDIO_OS", "mac"), ("DEMO_STUDIO_BROWSER_CACHE", str(self.cache))):
            old = os.environ.get(k)
            os.environ[k] = v
            self.addCleanup(lambda k=k, old=old: os.environ.pop(k, None) if old is None else os.environ.__setitem__(k, old))
        self.calls = []
        self._smoke = setup_tools.render_smoke
        self.addCleanup(setattr, setup_tools, "render_smoke", self._smoke)

    def fake_smoke(self, results):
        def smoke(ctx, browser, timeout=90):
            self.calls.append(browser)
            return results.pop(0)
        setup_tools.render_smoke = smoke

    def test_default_chrome_works_no_copy(self):
        pin = self.ctx.remotion_dir / ".browser.json"
        pin.write_text('{"browser_executable": "/old"}')
        self.fake_smoke([None])
        setup_tools.ensure_render_works(self.ctx)
        self.assertIsNone(self.ctx.browser_exe)
        self.assertFalse(pin.exists())  # stale pin removed
        self.assertEqual(self.calls, [str(self.chrome / "chrome-headless-shell")])
        self.assertFalse(self.cache.exists())

    def test_hang_on_mac_falls_back_to_cache_copy(self):
        self.fake_smoke(["render smoke test timed out after 90 s", None])
        setup_tools.ensure_render_works(self.ctx)
        want = self.cache / "4.0.541" / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell"
        self.assertEqual(self.ctx.browser_exe, str(want))
        self.assertTrue((want.parent / "icudtl.dat").is_file())
        pin = json.loads((self.ctx.remotion_dir / ".browser.json").read_text())
        self.assertEqual(pin["browser_executable"], str(want))  # render.mjs reads it, any --workspace
        self.assertEqual(self.calls[1], str(want))

    def test_copy_reused_and_symlink_followed(self):
        outside = self.root / "elsewhere" / "chrome-headless-shell-mac-arm64"
        outside.parent.mkdir()
        os.rename(self.chrome, outside)
        os.symlink(outside, self.chrome)
        exe = setup_tools.copy_browser_out(self.ctx)
        self.assertTrue(setup_tools.Path(exe).is_file())
        setup_tools.Path(exe).with_name("marker").write_text("kept")
        self.assertEqual(setup_tools.copy_browser_out(self.ctx), exe)
        self.assertTrue(setup_tools.Path(exe).with_name("marker").is_file())

    def test_both_fail_raises(self):
        self.fake_smoke(["timed out", "timed out again"])
        with self.assertRaises(OSError):
            setup_tools.ensure_render_works(self.ctx)

    def test_non_hang_failure_no_copy_with_os_hint(self):
        for osn, word in (("linux", "libnss3"), ("win", "Windows"), ("mac", "macOS")):
            os.environ["DEMO_STUDIO_OS"] = osn
            self.fake_smoke(["render smoke test failed (exit 1): boom"])
            if osn == "win":  # Windows looks for the .exe
                (self.chrome / "chrome-headless-shell.exe").write_text("bin")
            with self.assertRaises(OSError) as cm:
                setup_tools.ensure_render_works(self.ctx)
            self.assertIn(word, str(cm.exception))
        self.assertFalse(self.cache.exists())

    def test_hang_falls_back_on_every_os(self):
        (self.chrome / "chrome-headless-shell.exe").write_text("bin")
        for osn, exe in (("linux", "chrome-headless-shell"), ("win", "chrome-headless-shell.exe")):
            os.environ["DEMO_STUDIO_OS"] = osn
            self.fake_smoke(["render smoke test timed out after 90 s (headless Chrome hangs)", None])
            setup_tools.ensure_render_works(self.ctx)
            self.assertEqual(setup_tools.Path(self.ctx.browser_exe).name, exe)
            self.assertTrue(setup_tools.Path(self.ctx.browser_exe).is_file())

    def test_cache_root_per_os(self):
        home = setup_tools.Path("/h")
        root = setup_tools.browser_cache_root
        tail = ("demo-studio", "chrome-headless-shell")
        self.assertEqual(root("mac", {}, home), home.joinpath("Library", "Caches", *tail))
        self.assertEqual(root("win", {"LOCALAPPDATA": "/la"}, home), setup_tools.Path("/la").joinpath(*tail))
        self.assertEqual(root("win", {}, home), home.joinpath("AppData", "Local", *tail))
        self.assertEqual(root("linux", {"XDG_CACHE_HOME": "/xc"}, home), setup_tools.Path("/xc").joinpath(*tail))
        self.assertEqual(root("linux", {}, home), home.joinpath(".cache", *tail))
        self.assertEqual(root("linux", {"DEMO_STUDIO_BROWSER_CACHE": "/o"}, home), setup_tools.Path("/o"))

    def test_finds_platform_folders(self):
        base = self.chrome.parent.parent
        os.environ["DEMO_STUDIO_OS"] = "win"
        self.assertIsNone(setup_tools.remotion_browser_dir(self.ctx))  # no .exe yet
        w = base / "win64" / "chrome-headless-shell-win64"
        w.mkdir(parents=True)
        (w / "chrome-headless-shell.exe").write_text("bin")
        self.assertEqual(setup_tools.remotion_browser_dir(self.ctx), w)
        os.environ["DEMO_STUDIO_OS"] = "linux"
        self.assertEqual(setup_tools.remotion_browser_dir(self.ctx), self.chrome)

    def test_bounded_run_kills_on_timeout(self):
        import time
        t = time.time()
        rc, _ = setup_tools._run_bounded([sys.executable, "-c", "import time; time.sleep(30)"],
                                         str(self.root), dict(os.environ), 1)
        self.assertIsNone(rc)
        self.assertLess(time.time() - t, 15)
        rc, out = setup_tools._run_bounded([sys.executable, "-c", "print('hi')"], str(self.root), dict(os.environ), 20)
        self.assertEqual((rc, out.strip()), (0, "hi"))

    def test_install_has_smoke_step(self):
        labels = [c["label"] for c in setup_tools.feature_commands(self.ctx, "remotion")]
        self.assertTrue(any(l.startswith("render smoke test") for l in labels))

    def test_recorded_browser_gone_is_missing(self):
        (self.ctx.demo_dir).mkdir(parents=True, exist_ok=True)
        self.ctx.toolkit.write_text(json.dumps({"schema": 1, "features": {"remotion": {
            "versions": {"remotion": "4.0.541"}, "browser_executable": str(self.root / "gone")}}}))
        self._old_synced = setup_tools.remotion_synced
        setup_tools.remotion_synced = lambda ctx: True
        self.addCleanup(setattr, setup_tools, "remotion_synced", self._old_synced)
        st = setup_tools.feature_states(self.ctx, ["remotion"])["remotion"]
        if st["status"] != "blocked":  # node may be missing on the test machine
            self.assertEqual(st["status"], "missing")
            self.assertIn("headless Chrome missing", st["reason"])

    def test_smoke_reports_missing_script(self):
        self.assertEqual(self._smoke(self.ctx, None), "node or render.mjs not found")
