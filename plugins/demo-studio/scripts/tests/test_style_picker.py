"""Tests for scripts/style_picker.py and the key-art picker template. Run: python -m unittest discover -s scripts/tests -v"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import style_picker  # noqa: E402

HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
UNIVERSAL = {"#FFFFFF", "#000000"}


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = style_picker.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def template_tokens():
    with open(style_picker.TEMPLATE, encoding="utf-8") as f:
        page = f.read()
    m = re.search(r"/\*RECIPES-START\*/(.*?)/\*RECIPES-END\*/", page, re.S)
    return page, json.loads(m.group(1))


def recipe_rows():
    with open(style_picker.STYLES, encoding="utf-8") as f:
        lines = f.read().splitlines()
    rows = {}
    for line in style_picker._section(lines, "## Core recipes"):
        if line.startswith("### "):
            break
        if line.startswith("|"):
            c = style_picker._cells(line)
            rows[c[0]] = line
    return rows


class CatalogueTests(unittest.TestCase):
    def test_catalogue_parses(self):
        cat = style_picker.load_catalogue()
        self.assertEqual(len(cat["recipes"]), 12)
        self.assertEqual([g["letter"] for g in cat["groups"]], list("ABCDEFG"))
        codes = {c["code"]: c for g in cat["groups"] for c in g["codes"]}
        self.assertEqual(codes["B3"]["recipe"], "isometric")
        self.assertEqual(codes["C4"]["recipe"], "minimal-type")  # first id named
        self.assertEqual(codes["D15"]["recipe"], "isometric")
        self.assertIsNone(codes["A3"]["recipe"])
        a = next(g for g in cat["groups"] if g["letter"] == "A")
        self.assertTrue(any(u["nearest"] == "A12" for u in a["unavailable"]))

    def test_template_tokens_match_catalogue(self):
        _, tokens = template_tokens()
        self.assertEqual(sorted(tokens), sorted(style_picker.load_catalogue()["recipes"]))

    def test_template_hex_values_come_from_recipe_rows(self):
        _, tokens = template_tokens()
        rows = recipe_rows()
        for rid, tok in tokens.items():
            allowed = set(h.upper() for h in HEX.findall(rows[rid]))
            if tok.get("base"):
                allowed |= set(h.upper() for h in HEX.findall(rows[tok["base"]]))
            used = set(h.upper() for h in HEX.findall(json.dumps(tok)))
            self.assertEqual(used - allowed - UNIVERSAL, set(), rid)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "artifact_design", "key_design_picker.html")

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_then_updates(self):
        code, out, err = run("--out", self.out, "--lang", "vi", "--title", "Demo Studio",
                             "--recommend", "B3 + C4 | team of 19 agents", "--recommend", "a14,b5,d1")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertFalse(res["updated"])
        self.assertEqual(res["recommend"], [["B3", "C4"], ["A14", "B5", "D1"]])
        with open(self.out, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn(style_picker.PLACEHOLDER, html)
        data = json.loads(re.search(r"const DATA = (.*?);\nconst RECIPES", html, re.S).group(1))
        self.assertEqual(data["lang"], "vi")
        self.assertEqual(data["recommend"][0]["reason"], "team of 19 agents")
        self.assertNotIn("http://", html.replace("http://www.w3.org/2000/svg", ""))
        self.assertNotIn("https://", html)
        code, out, _ = run("--out", self.out, "--current", "C4 B3")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["updated"])
        self.assertEqual(json.loads(out)["current"], ["B3", "C4"])

    def test_script_close_tag_escaped(self):
        code, _, _ = run("--out", self.out, "--title", "</script><b>x")
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as f:
            self.assertEqual(f.read().count("</script>"), 1)

    def test_invalid_combos_exit2(self):
        for bad in ("B3 + B4", "A1 + B3 + C4 + D1", "Z9", "B999", ""):
            code, _, err = run("--out", self.out, "--recommend", bad)
            self.assertEqual(code, 2, bad)
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(run("--out", self.out, "--current", "A1 A2")[0], 2)
        self.assertEqual(run("--out", self.out, "--lang", "fr")[0], 2)


if __name__ == "__main__":
    unittest.main()
