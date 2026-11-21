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


if __name__ == "__main__":
    unittest.main()
