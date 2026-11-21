import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

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


def legacy_blur():
    base = {"scene": "s01", "bbox": [968, 3, 284, 58], "pad": 12, "margin_ms": 150,
            "mode": "boxblur", "strength": 25, "keyframes": None, "preview": None}
    regs = [dict(base, id="b%d" % i, scene="s%02d" % i, t_start=0, t_end=5000,
                 source="events:sensitive:signed-in email") for i in range(1, 4)]
    return {"schema": 1, "space": "source", "time": "scene", "regions": regs}


SCHEMA1 = {
    "_meta": {"schema": 1, "keys": {
        "events": {"version": 2, "owner": "capture-operator", "updated": "2026-11-19T04:05:00Z"},
        "blur": {"version": 2, "owner": "privacy-blurrer", "updated": "2026-11-19T05:48:40Z"},
    }},
    "events": {"schema": 1, "clips": {"s01": {"file": "media/s01.raw.webm", "w": 1280, "h": 720},
                                       "s02": {"file": "media/s02.raw.webm", "w": 1280, "h": 720}}},
    "blur": legacy_blur(),
}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.dir = os.path.join(self.root, ".demo", "vid")
        os.makedirs(self.dir)
        self.pj = os.path.join(self.dir, "project.json")

    def write(self, data):
        with open(self.pj, "w") as f:
            json.dump(data, f)

    def load(self):
        with open(self.pj) as f:
            return json.load(f)


class MigrateTests(Base):
    def test_init_creates_schema_2(self):
        self.assertEqual(run(["--slug", "vid", "init"], self.root)[0], 0)
        self.assertEqual(self.load()["_meta"]["schema"], 2)

    def test_migrate_upgrades_and_keeps_every_region(self):
        self.write(SCHEMA1)
        code, out, _ = run(["--slug", "vid", "migrate"], self.root)
        self.assertEqual(code, 0, out)
        res = json.loads(out)
        self.assertTrue(res["migrated"])
        self.assertEqual((res["clips_masked_false"], res["blur_regions_kept"]), (2, 3))
        self.assertEqual(res["data_mode"], "real-redacted")
        d = self.load()
        self.assertEqual(d["_meta"]["schema"], 2)
        self.assertTrue(all(e["inputs"] == {} for e in d["_meta"]["keys"].values()))
        self.assertTrue(all(c["masked"] is False for c in d["events"]["clips"].values()))
        regs = d["blur"]["regions"]
        self.assertEqual(len(regs), 3)  # identical bbox in 3 scenes: NOT merged by migrate
        self.assertTrue(all(r["source"] == "legacy" for r in regs))
        self.assertEqual(regs[0]["label"], "events:sensitive:signed-in email")
        self.assertEqual(regs[0]["bbox"], [968, 3, 284, 58])  # untouched
        with open(self.pj + ".schema1.bak") as f:
            self.assertEqual(json.load(f), SCHEMA1)

    def test_migrate_idempotent_and_backup_not_overwritten(self):
        self.write(SCHEMA1)
        run(["--slug", "vid", "migrate"], self.root)
        before = self.load()
        code, out, _ = run(["--slug", "vid", "migrate"], self.root)
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["migrated"])
        self.assertEqual(self.load(), before)
        with open(self.pj + ".schema1.bak") as f:
            self.assertEqual(json.load(f)["_meta"]["schema"], 1)

    def test_dry_run_writes_nothing(self):
        self.write(SCHEMA1)
        code, out, _ = run(["--slug", "vid", "migrate", "--dry-run"], self.root)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["dry_run"])
        self.assertEqual(self.load(), SCHEMA1)
        self.assertFalse(os.path.exists(self.pj + ".schema1.bak"))

    def test_migrate_without_file_exit_2(self):
        self.assertEqual(run(["--slug", "vid", "migrate"], self.root)[0], 2)

    def test_schema1_file_stays_readable_and_writable(self):
        self.write(SCHEMA1)
        code, out, _ = run(["--slug", "vid", "set", "blur", "--as", "privacy-blurrer",
                            "--json", '{"regions": []}'], self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.load()["_meta"]["schema"], 1)  # only `migrate` changes the schema
        self.assertEqual(run(["--slug", "vid", "keys"], self.root)[0], 0)


class ChecksOwnershipTests(Base):
    def setUp(self):
        super().setUp()
        run(["--slug", "vid", "init"], self.root)

    def test_cli_set_checks_always_refused(self):
        for agent in ("render-engineer", "checks.py", "blur.py"):
            code, _, err = run(["--slug", "vid", "set", "checks", "--as", agent,
                                "--json", "{}"], self.root)
            self.assertEqual(code, 4, agent)
            self.assertIn("write_checks", err)
        self.assertNotIn("checks", self.load())

    def test_write_checks_only_for_known_writers(self):
        with self.assertRaises(project.CliError) as cm:
            project.write_checks(self.pj, {"x": 1}, writer="privacy-blurrer")
        self.assertEqual(cm.exception.code, 4)
        self.assertEqual(project.write_checks(self.pj, {"x": 1}, writer="checks.py"), 1)
        self.assertEqual(self.load()["checks"], {"x": 1})

    def test_write_checks_merge_keeps_other_aspects(self):
        project.write_checks(self.pj, {"blur": {"16x9": {"verdict": "pass"}}}, writer="blur.py")
        project.write_checks(self.pj, {"blur": {"9x16": {"verdict": "leak"}}}, writer="blur.py",
                             merge=True)
        self.assertEqual(self.load()["checks"]["blur"],
                         {"16x9": {"verdict": "pass"}, "9x16": {"verdict": "leak"}})

    def test_other_keys_unaffected(self):
        code, out, _ = run(["--slug", "vid", "set", "voice", "--as", "voice-producer",
                            "--json", '{"a": 1}'], self.root)
        self.assertEqual(code, 0, out)


class FingerprintTests(Base):
    def setUp(self):
        super().setUp()
        run(["--slug", "vid", "init"], self.root)
        os.makedirs(os.path.join(self.dir, "raw"))
        self.clip = os.path.join(self.dir, "raw", "s01.webm")
        with open(self.clip, "wb") as f:
            f.write(b"x" * 5000)

    def set_blur(self, *extra):
        return run(["--slug", "vid", "set", "blur", "--as", "privacy-blurrer", "--json", "{}",
                    *extra], self.root)

    def test_input_fingerprint_triple_recorded(self):
        code, out, err = self.set_blur("--input-file", "raw/s01.webm")
        self.assertEqual(code, 0, err)
        entry = self.load()["_meta"]["keys"]["blur"]
        fp = entry["inputs"]["file:raw/s01.webm"]
        st = os.stat(self.clip)
        self.assertEqual(fp, {"size": 5000, "mtime_ns": st.st_mtime_ns, "ino": st.st_ino})

    def test_upstream_versions_recorded(self):
        run(["--slug", "vid", "set", "events", "--as", "capture-operator", "--json", "{}"], self.root)
        self.set_blur()
        self.assertEqual(self.load()["_meta"]["keys"]["blur"]["inputs"], {"events": 1})

    def test_hash_only_when_triple_changes(self):
        with mock.patch.object(project.hashlib, "sha256", wraps=project.hashlib.sha256) as sha:
            self.set_blur("--input-file", "raw/s01.webm")
            self.assertEqual(sha.call_count, 1)
            self.set_blur("--input-file", "raw/s01.webm")
            self.assertEqual(sha.call_count, 1)  # same size/mtime/inode: no re-hash
            with open(self.clip, "ab") as f:
                f.write(b"y")
            self.set_blur("--input-file", "raw/s01.webm")
            self.assertEqual(sha.call_count, 2)
        with open(os.path.join(self.dir, "cache", "hashes.json")) as f:
            cache = json.load(f)
        self.assertEqual(len(cache["raw/s01.webm"]["sha256"]), 64)

    def test_missing_input_file_exit_2(self):
        self.assertEqual(self.set_blur("--input-file", "raw/nope.webm")[0], 2)


if __name__ == "__main__":
    unittest.main()
