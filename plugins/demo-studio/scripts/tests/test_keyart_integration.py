"""Integration checks for the key-art item (KART): rename, roster/count, owners and exit codes."""
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", ".."))
REPO = os.path.normpath(os.path.join(PLUGIN, "..", ".."))
PROJECT_PY = os.path.join(PLUGIN, "scripts", "project.py")
OLD_NAME = "privacy-" + "blurrer"  # built by concatenation so this file does not hit the rename grep


def run(*args):
    return subprocess.run([sys.executable, PROJECT_PY, *args], capture_output=True, text=True, timeout=60)


def agent_stems():
    return sorted(f[:-3] for f in os.listdir(os.path.join(PLUGIN, "agents")) if f.endswith(".md"))


class RenameTests(unittest.TestCase):
    def test_old_name_absent_outside_team(self):
        hits = []
        for base in (PLUGIN, os.path.join(REPO, "example")):
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", ".venv", "__pycache__")]
                for f in files:
                    p = os.path.join(root, f)
                    try:
                        text = open(p, encoding="utf-8").read()
                    except (UnicodeDecodeError, OSError):
                        continue
                    if OLD_NAME in text or "privacy_" + "blurrer" in text:
                        hits.append(os.path.relpath(p, REPO))
        for f in ("README.md", "CLAUDE.md"):
            if OLD_NAME in open(os.path.join(REPO, f), encoding="utf-8").read():
                hits.append(f)
        self.assertEqual(hits, [])

    def test_owners_and_exit_4(self):
        self.assertEqual(run("owner", "blur").stdout.strip(), "privacy")
        self.assertEqual(run("owner", "art").stdout.strip(), "art-designer")
        with tempfile.TemporaryDirectory() as tmp:
            pj = os.path.join(tmp, "project.json")
            self.assertEqual(run("--project", pj, "init").returncode, 0)
            self.assertEqual(run("--project", pj, "set", "blur", "--as", OLD_NAME, "--json", "{}").returncode, 4)
            self.assertEqual(run("--project", pj, "set", "art", "--as", "packager", "--json", "{}").returncode, 4)
            self.assertEqual(run("--project", pj, "set", "blur", "--as", "privacy", "--json", "{}").returncode, 0)

    def test_deps_art(self):
        self.assertEqual(run("deps", "art").stdout.split(), ["privacy", "motion", "checks", "delivery"])


class RosterTests(unittest.TestCase):
    def test_19_agents_in_docs(self):
        stems = agent_stems()
        self.assertEqual(len(stems), 19)
        for rel in ("skills/run-kits/SKILL.md", "../../README.md"):
            text = open(os.path.join(PLUGIN, rel), encoding="utf-8").read()
            self.assertEqual([s for s in stems if s not in text], [], rel)
        readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
        self.assertIn("19 agents", readme)
        self.assertIsNone(re.search(r"\b18 agents\b", readme))

    def test_versions_match(self):
        import json
        v1 = json.load(open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8"))["version"]
        mk = json.load(open(os.path.join(REPO, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
        self.assertEqual(v1, mk["plugins"][0]["version"])


if __name__ == "__main__":
    unittest.main()
