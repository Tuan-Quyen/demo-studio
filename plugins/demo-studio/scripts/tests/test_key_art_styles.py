"""Catalogue integrity checks for key-art styles (KSTY): references/styles.md and the files that cite it."""
import glob
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", ".."))
REPO = os.path.normpath(os.path.join(PLUGIN, "..", ".."))
SKILL_DIR = os.path.join(PLUGIN, "skills", "key-art")
STYLES = os.path.join(SKILL_DIR, "references", "styles.md")
GROUPS = "ABCDEFG"
CODE_RE = re.compile(r"^([A-G])(\d+)$")
SRC_RE = re.compile(r"^S\d+$")
# - S1 · title · https://url · accessed 2026-11-24 · fetched      (S0: repo path · read <date> · repo file)
SOURCE_RE = re.compile(r"^- (S\d+) · (.+?) · (\S+) · (accessed|read) (\d{4}-\d{2}-\d{2}) · (.+)$")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def section(text, heading):
    """Body of the '## heading' or '### heading' section (up to the next heading of the same or higher level)."""
    level = len(heading) - len(heading.lstrip("#"))
    lines = text.splitlines()
    out, on = [], False
    for line in lines:
        m = re.match(r"^(#+) ", line)
        if on and m and len(m.group(1)) <= level:
            break
        if on:
            out.append(line)
        elif line.strip().startswith(heading):
            on = True
    return "\n".join(out)


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def load_catalogue():
    text = read(STYLES)
    tax = section(text, "## Keyword taxonomy")
    groups = {}  # letter -> {"title": str, "rows": [dict]}
    order = []
    cur = None
    for line in tax.splitlines():
        m = re.match(r"^### ([A-G]) · ", line)
        if m:
            cur = m.group(1)
            order.append(cur)
            groups[cur] = []
            continue
        if cur and line.startswith("|"):
            c = cells(line)
            if c[0] in ("Code", "") or set(c[0]) <= set("-: "):
                continue
            groups[cur].append({"cells": c, "line": line})
    return text, order, groups


def coded_rows(groups):
    rows = {}
    for g, items in groups.items():
        for it in items:
            c = it["cells"]
            if c[0] != "–":
                rows.setdefault(c[0], []).append((g, c))
    return rows


def recipe_ids(text):
    ids = []
    for line in section(text, "## Core recipes").splitlines():
        if line.startswith("### "):  # the do/don't table repeats the ids
            break
        if not line.startswith("|"):
            continue
        first = cells(line)[0]
        if first == "id" or set(first) <= set("-: "):
            continue
        ids.append(first)
    return ids


def parse_sources(text):
    out = {}
    for line in section(text, "## Sources").splitlines():
        if not re.match(r"^- S\d+ ", line):  # other bullets are notes
            continue
        m = SOURCE_RE.match(line)
        out[m.group(1) if m else line] = m
    return out


class CatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text, cls.order, cls.groups = load_catalogue()
        cls.coded = coded_rows(cls.groups)
        cls.sources = parse_sources(cls.text)

    def test_groups_a_to_g_in_order(self):
        self.assertEqual(self.order, list(GROUPS))

    def test_every_row_has_six_cells(self):
        for g, items in self.groups.items():
            for it in items:
                self.assertEqual(len(it["cells"]), 6, it["line"])

    def test_codes_unique_and_wellformed(self):
        for code, hits in self.coded.items():
            self.assertEqual(len(hits), 1, "duplicate code " + code)
            m = CODE_RE.match(code)
            self.assertTrue(m, "bad code " + code)
            self.assertEqual(m.group(1), hits[0][0], code + " sits in the wrong group")

    def test_codes_contiguous_per_group(self):
        for g in GROUPS:
            nums = sorted(int(CODE_RE.match(c).group(2)) for c in self.coded if c.startswith(g))
            self.assertTrue(nums, "group %s has no coded rows" % g)
            self.assertEqual(nums, list(range(1, len(nums) + 1)), "group %s not contiguous" % g)

    def test_coded_rows_feasibility_hints_meaning(self):
        for code, hits in self.coded.items():
            c = hits[0][1]
            self.assertIn(c[3], ("yes", "approx"), code)
            self.assertTrue(c[4], code + " has empty hints")
            self.assertTrue(c[1], code + " has no keyword")
            words = c[2].split()
            self.assertTrue(0 < len(words) <= 12, "%s meaning has %d words" % (code, len(words)))

    def test_core_recipes_are_twelve(self):
        self.assertEqual(len(recipe_ids(self.text)), 12)

    def test_hint_recipe_refs_resolve(self):
        ids = set(recipe_ids(self.text))
        n = 0
        for code, hits in self.coded.items():
            for ref in re.findall(r"→\s*([a-z][a-z-]*[a-z])", hits[0][1][4]):
                n += 1
                self.assertIn(ref, ids, "%s hints at unknown recipe %s" % (code, ref))
        self.assertGreater(n, 0)

    def test_every_row_cites_resolvable_source(self):
        for g, items in self.groups.items():
            for it in items:
                c = it["cells"]
                ids = c[5].split()
                self.assertTrue(ids, "no source: " + it["line"])
                for s in ids:
                    self.assertRegex(s, SRC_RE, it["line"])
                    self.assertIn(s, self.sources, "unresolved %s in %s" % (s, c[0] + " " + c[1]))

    def test_sources_well_formed(self):
        self.assertIn("S0", self.sources)
        for sid, m in self.sources.items():
            self.assertTrue(m, "malformed source line: " + sid)
            if sid == "S0":
                self.assertTrue(os.path.isfile(os.path.join(REPO, m.group(3).strip("`"))), "S0 path missing: " + m.group(3))
            else:
                self.assertRegex(m.group(3), r"^https?://", sid)
                self.assertEqual(m.group(4), "accessed", sid)

    def test_s0_only_for_a14(self):
        users = [c[0] for g, items in self.groups.items() for it in items
                 for c in [it["cells"]] if "S0" in c[5].split()]
        self.assertEqual(users, ["A14"])

    def test_not_available_rows_name_existing_nearest(self):
        n = 0
        for g, items in self.groups.items():
            for it in items:
                c = it["cells"]
                if c[0] != "–":
                    continue
                n += 1
                self.assertEqual(c[3], "no", it["line"])
                m = re.match(r"^nearest ([A-G]\d+) · \S", c[4])
                self.assertTrue(m, "bad nearest: " + it["line"])
                self.assertIn(m.group(1), self.coded, it["line"])
                self.assertTrue(c[1] and c[2], it["line"])
        self.assertGreater(n, 0)

    def test_recommendation_rows(self):
        body = section(self.text, "### Recommendation rule")
        n = 0
        for line in body.splitlines():
            if not line.startswith("|"):
                continue
            c = cells(line)
            if c[0] == "Signal" or set(c[0]) <= set("-: "):
                continue
            combos = [x.strip() for x in c[1].split(";") if x.strip()]
            self.assertTrue(1 <= len(combos) <= 3, line)
            for combo in combos:
                codes = [x.strip() for x in combo.split("+")]
                self.assertTrue(1 <= len(codes) <= 3, combo)
                for code in codes:
                    self.assertIn(code, self.coded, "%s in '%s'" % (code, combo))
                letters = [code[0] for code in codes]
                self.assertEqual(len(letters), len(set(letters)), "two codes from one group: " + combo)
                n += 1
        self.assertGreater(n, 0)

    def test_picker_section_present(self):
        self.assertTrue(section(self.text, "## Picker").strip())
        self.assertTrue(section(self.text, "## Combination rule").strip())

    def test_prints_count(self):
        print("\nkey-art catalogue: %d coded keywords, %d not available, %d recipes, %d sources" % (
            len(self.coded),
            sum(1 for items in self.groups.values() for it in items if it["cells"][0] == "–"),
            len(recipe_ids(self.text)), len(self.sources)))


class WiringTests(unittest.TestCase):
    def test_skill_who_loads_what_names_styles(self):
        skill = read(os.path.join(SKILL_DIR, "SKILL.md"))
        body = section(skill, "## Who loads what")
        self.assertIn("styles.md", body)
        self.assertIn("Q1-Q10", skill)

    def test_checks_defines_q10(self):
        checks = read(os.path.join(SKILL_DIR, "references", "checks.md"))
        self.assertTrue(re.search(r"^\| Q10 \|", checks, re.M))

    def test_media_specs_art_names_style(self):
        specs = read(os.path.join(PLUGIN, "skills", "media-specs", "SKILL.md"))
        self.assertRegex(specs, r"`style`")
        self.assertIn("styles.md", specs)

    def test_no_recipe_id_in_agents_or_commands(self):
        ids = recipe_ids(read(STYLES))
        self.assertEqual(len(ids), 12)
        files = glob.glob(os.path.join(PLUGIN, "agents", "*.md")) + glob.glob(os.path.join(PLUGIN, "commands", "*.md"))
        self.assertTrue(files)
        hits = []
        for p in files:
            text = read(p)
            for rid in ids:
                if re.search(r"(?<![\w-])" + re.escape(rid) + r"(?![\w-])", text):
                    hits.append("%s: %s" % (os.path.relpath(p, PLUGIN), rid))
        self.assertEqual(hits, [], "style recipe ids restated outside key-art")


if __name__ == "__main__":
    unittest.main()
