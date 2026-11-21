"""config.py privacy block (redesign §4.5, §6.1, RT-4): data_mode, seed_confirmation, lists."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import config  # noqa: E402


class PrivacyConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "demo.yaml")

    def run_cfg(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = config.main(["--project", self.path] + list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_defaults(self):
        self.write("")
        code, out, _ = self.run_cfg("get", "privacy")
        self.assertEqual(code, 0)
        p = json.loads(out)
        self.assertEqual(p["data_mode"], "real-redacted")
        self.assertIsNone(p["seed_confirmation"])
        self.assertEqual((p["selectors"], p["regexes"], p["seed_values"]), ([], [], []))
        self.assertEqual((p["mask_style"], p["raw_retention"], p["capture_mask"]),
                         ("opaque", "delete-after-delivery", True))

    def test_seeded_without_confirmation_rejected(self):
        self.write("privacy:\n  data_mode: seeded\n")
        code, _, err = self.run_cfg("validate")
        self.assertEqual(code, 2)
        self.assertIn("seed_confirmation", err)

    def test_seeded_with_blank_confirmation_rejected(self):
        self.write('privacy:\n  data_mode: seeded\n  seed_confirmation: " "\n')
        self.assertEqual(self.run_cfg("validate")[0], 2)

    def test_seeded_with_confirmation_ok(self):
        self.write('privacy:\n  data_mode: seeded\n  seed_confirmation: "user: yes, invented (2026-11-20)"\n')
        self.assertEqual(self.run_cfg("validate")[0], 0)

    def test_real_redacted_needs_no_confirmation(self):
        self.write("privacy:\n  data_mode: real-redacted\n")
        self.assertEqual(self.run_cfg("validate")[0], 0)

    def test_bad_data_mode_rejected(self):
        self.write("privacy:\n  data_mode: fake\n")
        code, _, err = self.run_cfg("validate")
        self.assertEqual(code, 2)
        self.assertIn("real-redacted", err)

    def test_bad_regex_rejected(self):
        self.write('privacy:\n  regexes: ["sk-[A-Z"]\n')
        code, _, err = self.run_cfg("validate")
        self.assertEqual(code, 2)
        self.assertIn("regexes[0]", err)

    def test_lists_and_enums(self):
        self.write('privacy:\n  selectors: [".email"]\n  regexes: ["sk-[A-Za-z0-9]{8,}"]\n'
                   '  seed_values: ["demo@example.com"]\n  mask_style: blur\n  raw_retention: keep\n'
                   '  capture_mask: false\n')
        self.assertEqual(self.run_cfg("validate")[0], 0)
        self.write("privacy:\n  mask_style: pixelate\n")
        self.assertEqual(self.run_cfg("validate")[0], 2)
        self.write("privacy:\n  raw_retention: forever\n")
        self.assertEqual(self.run_cfg("validate")[0], 2)

    def test_template_validates_and_is_real_redacted(self):
        code, out, _ = self.run_cfg("init")
        self.assertEqual(code, 0)
        self.assertEqual(self.run_cfg("validate")[0], 0)
        self.assertEqual(json.loads(self.run_cfg("get", "privacy.data_mode")[1]), "real-redacted")

    def test_gitignore_template_lists_sensitive_dirs(self):
        with open(os.path.join(HERE, "..", "..", "templates", "gitignore"), encoding="utf-8") as f:
            lines = f.read().split("\n")
        for want in (".demo/*/media/preview/", ".demo/*/.secret/", ".demo/*/raw/"):
            self.assertIn(want, lines)


if __name__ == "__main__":
    unittest.main()
