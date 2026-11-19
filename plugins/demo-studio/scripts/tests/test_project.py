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
        code, out, _ = run(["--slug", "vid", "set", "blur", "--as", "privacy-blurrer",
                            "--json", '{"regions": []}'], self.root)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("blur version 1 ("), out)
        self.assertIn(self.pj, out)

    def test_run_from_inside_demo_dir_uses_same_file(self):
        run(["--slug", "vid", "init"], self.root)
        code, out, _ = run(["--slug", "vid", "set", "blur", "--as", "privacy-blurrer",
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

    def test_owner_mismatch_and_get_version_unset(self):
        run(["--slug", "vid", "init"], self.root)
        code, _, _ = run(["--slug", "vid", "set", "timeline", "--as", "x", "--json", "{}"], self.root)
        self.assertEqual(code, 4)
        code, out, _ = run(["--slug", "vid", "get", "timeline", "--version"], self.root)
        self.assertEqual(out.strip(), "0")
        run(["--slug", "vid", "set", "timeline", "--as", "sync-editor", "--json", '{"total_s": 1}'], self.root)
        code, out, _ = run(["--slug", "vid", "get", "timeline"], self.root)
        self.assertNotIn("version", json.loads(out))  # version lives in _meta: use --version / keys


if __name__ == "__main__":
    unittest.main()
