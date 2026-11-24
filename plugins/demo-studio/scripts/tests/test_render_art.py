"""Runs the Node tests of `render.mjs --art` (lint, size, paths, PNG IHDR) from the Python suite.

Skipped when `node` is missing. Needs no Remotion, no node_modules and no network.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTION = os.path.normpath(os.path.join(HERE, "..", "..", "remotion"))
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed")
class RenderArtTests(unittest.TestCase):
    def test_node_suite(self):
        r = subprocess.run(
            [NODE, "--test", os.path.join(REMOTION, "tests", "art.test.mjs")],
            capture_output=True, text=True, timeout=120, cwd=REMOTION,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_only_cli_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            slug = os.path.join(tmp, ".demo", "s", "art")
            os.makedirs(slug)
            svg = os.path.join(slug, "t.svg")
            with open(svg, "w", encoding="utf8") as fh:
                fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630"></svg>')
            out = os.path.join(slug, "t.png")
            base = [NODE, os.path.join(REMOTION, "render.mjs"), "--art", "--check-only",
                    "--layer", svg, "--out", out]
            ok = subprocess.run(base + ["--size", "1200x630"], capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            data = json.loads(ok.stdout)
            self.assertEqual((data["ok"], data["mode"], data["w"], data["h"]), (True, "art", 1200, 630))
            for extra in (["--size", "1280x720"], ["--size", "1200x630", "--ratio", "16x9"]):
                bad = subprocess.run(base + extra, capture_output=True, text=True)
                self.assertEqual(bad.returncode, 2, bad.stderr)


if __name__ == "__main__":
    unittest.main()
