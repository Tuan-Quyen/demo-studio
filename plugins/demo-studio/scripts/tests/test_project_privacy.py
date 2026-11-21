"""S-11 (gitignore, raw_retention), S-13 (migrate resets pass), R-13 (stale inputs, fingerprints),
S-12 (shared redaction helpers), S-06 helper."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import project  # noqa: E402
import run_bounded as rb  # noqa: E402


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


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.demo = os.path.join(self.root, ".demo")
        self.sdir = os.path.join(self.demo, "vid")
        self.pj = os.path.join(self.sdir, "project.json")

    def init(self):
        self.assertEqual(run(["--slug", "vid", "init"], self.root)[0], 0)

    def touch(self, rel, text="x"):
        p = os.path.join(self.sdir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p


class GitignoreTests(Base):
    def test_init_writes_demo_gitignore_with_sensitive_paths(self):
        self.init()
        text = open(os.path.join(self.demo, ".gitignore")).read()
        for must in ("*/.secret/", "*/media/preview/", "*/media/.tmp-*/", "*/media/*.mask.jsonl", "*/media/*.sync.json",
                     "*/media/*.probe.jsonl", "*/media/tmp-video/",
                     "*/runs.jsonl", "*/*.schema1.bak", "*/cache/", "*/raw/", "*/media/*.raw.*"):
            self.assertIn(must, text.splitlines())

    def test_init_is_idempotent_and_keeps_user_lines(self):
        os.makedirs(self.demo)
        with open(os.path.join(self.demo, ".gitignore"), "w") as f:
            f.write("mine.txt")
        self.init()
        self.init()
        lines = open(os.path.join(self.demo, ".gitignore")).read().splitlines()
        self.assertIn("mine.txt", lines)
        self.assertEqual(lines.count("*/cache/"), 1)

    def test_template_has_the_same_paths_with_demo_prefix(self):
        tpl = open(os.path.join(HERE, "..", "..", "templates", "gitignore")).read().splitlines()
        for l in project.GITIGNORE_LINES:
            self.assertIn(".demo/" + l, tpl)


class RetentionTests(Base):
    def setup_raw(self, delivered):
        self.init()
        self.touch("media/s01.raw.webm")
        self.touch("media/s01.mask.jsonl")
        self.touch("media/s01.sync.json")
        self.touch("media/s01.probe.jsonl")
        self.touch("media/.tmp-s02-123/video.webm")
        self.touch("media/tmp-video/a.webm")
        self.touch("media/final-16x9.mp4")
        self.touch("media/preview/contact-s01.png")
        project.store_key(self.pj, "events", "capture-operator",
                          {"clips": {"s01": {"file": "media/s01.raw.webm"}}}, 5)
        if delivered:
            project.store_key(self.pj, "delivery", "packager", {"files": ["media/final-16x9.mp4"]}, 5)

    def test_lists_without_apply(self):
        self.setup_raw(True)
        code, out, _ = run(["--slug", "vid", "retention"], self.root)
        res = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(res["deleted"], [])
        self.assertIn("media/s01.raw.webm", res["candidates"])
        self.assertTrue(os.path.exists(os.path.join(self.sdir, "media", "s01.raw.webm")))

    def test_apply_after_delivery_deletes_raw_keeps_finals(self):
        self.setup_raw(True)
        code, out, _ = run(["--slug", "vid", "retention", "--apply"], self.root)
        self.assertEqual(code, 0, out)
        for gone in ("media/s01.raw.webm", "media/s01.mask.jsonl", "media/s01.sync.json", "media/s01.probe.jsonl",
                     "media/.tmp-s02-123", "media/tmp-video"):
            self.assertFalse(os.path.exists(os.path.join(self.sdir, gone)), gone)
        for kept in ("media/final-16x9.mp4", "media/preview/contact-s01.png", "project.json"):
            self.assertTrue(os.path.exists(os.path.join(self.sdir, kept)), kept)

    def test_apply_before_delivery_is_refused_exit_3(self):
        self.setup_raw(False)
        code, out, err = run(["--slug", "vid", "retention", "--apply"], self.root)
        self.assertEqual(code, 3)
        self.assertTrue(os.path.exists(os.path.join(self.sdir, "media", "s01.raw.webm")))
        self.assertEqual(run(["--slug", "vid", "retention", "--apply", "--force"], self.root)[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.sdir, "media", "s01.raw.webm")))

    def test_clip_outside_media_is_found_through_its_event_record(self):   # --out-dir
        self.init()
        out = os.path.join(self.root, "elsewhere")
        os.makedirs(os.path.join(out, ".tmp-s01-9"))
        for n in ("s01.raw.webm", "s01.mask.jsonl", ".tmp-s01-9/v.webm"):
            open(os.path.join(out, n), "w").write("x")
        project.store_key(self.pj, "events", "capture-operator",
                          {"clips": {"s01": {"file": "../../elsewhere/s01.raw.webm"}}}, 5)
        code, o, _ = run(["--slug", "vid", "retention", "--apply", "--force"], self.root)
        res = json.loads(o)      # default: outside files are listed and kept
        self.assertTrue(any(p.endswith("s01.raw.webm") for p in res["outside_project"]))
        self.assertIn("s01.raw.webm", os.listdir(out))
        run(["--slug", "vid", "retention", "--apply", "--force", "--include-outside"], self.root)
        self.assertEqual(sorted(os.listdir(out)), [])

    def test_symlink_pointing_outside_is_never_followed_by_default(self):
        self.init()
        outside = os.path.join(self.root, "precious")
        os.makedirs(outside)
        target = os.path.join(outside, "keep.raw.webm")
        open(target, "w").write("x")
        os.makedirs(os.path.join(self.sdir, "media"))
        os.symlink(target, os.path.join(self.sdir, "media", "s01.raw.webm"))
        os.symlink(outside, os.path.join(self.sdir, "media", ".tmp-s01-5"))
        code, o, _ = run(["--slug", "vid", "retention", "--apply", "--force"], self.root)
        res = json.loads(o)
        self.assertEqual(res["deleted"], [])
        self.assertEqual(len(res["outside_project"]), 2)
        self.assertTrue(os.path.exists(target))
        self.assertTrue(os.path.islink(os.path.join(self.sdir, "media", "s01.raw.webm")))

    def test_doctor_flags_and_cleans_stale_tmp_capture_dirs(self):
        self.init()
        self.touch("media/.tmp-s01-42/video.webm")
        code, out, _ = run(["--slug", "vid", "doctor"], self.root)
        self.assertEqual((code, json.loads(out)["stale_tmp"]), (10, ["media/.tmp-s01-42"]))
        code, out, _ = run(["--slug", "vid", "doctor", "--clean"], self.root)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.sdir, "media", ".tmp-s01-42")))

    def test_keep_deletes_nothing(self):
        self.setup_raw(True)
        with open(os.path.join(self.sdir, "demo.yaml"), "w") as f:
            f.write("privacy:\n  raw_retention: keep\n")
        code, out, _ = run(["--slug", "vid", "retention", "--apply"], self.root)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["deleted"], [])
        self.assertTrue(os.path.exists(os.path.join(self.sdir, "media", "s01.raw.webm")))


class MigrateAndInputsTests(Base):
    def test_migrate_resets_schema1_checks_pass_but_keeps_results(self):
        os.makedirs(self.sdir)
        d = {"_meta": {"schema": 1, "keys": {}}, "checks": {"pass": True, "results": {"blur": {"pass": True}}}}
        json.dump(d, open(self.pj, "w"))
        code, out, _ = run(["--slug", "vid", "migrate"], self.root)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["checks_pass_reset"])
        ck = project.read_project(self.pj)["checks"]
        self.assertIs(ck["pass"], False)
        self.assertEqual(ck["results"], {"blur": {"pass": True}})

    def test_stale_inputs_detects_changed_upstream(self):
        self.init()
        project.store_key(self.pj, "blur", "privacy-blurrer", {"regions": []}, 5)
        project.store_key(self.pj, "checks", "render-engineer", {"pass": True}, 5)
        self.assertEqual(project.stale_inputs(project.read_project(self.pj), "checks"), [])
        project.store_key(self.pj, "blur", "privacy-blurrer", {"regions": [1]}, 5)
        self.assertEqual(project.stale_inputs(project.read_project(self.pj), "checks"), ["blur"])
        code, out, _ = run(["--slug", "vid", "stale", "checks"], self.root)
        self.assertEqual((code, json.loads(out)["stale"]), (10, ["blur"]))

    def test_fingerprint_sha_is_cached_and_recomputed_only_when_triple_changes(self):
        self.init()
        self.touch("media/f.mp4", "abc")
        a = project.file_fingerprint(self.sdir, "media/f.mp4", with_sha=True)
        cache = os.path.join(self.sdir, "cache", "hashes.json")
        self.assertEqual(json.load(open(cache))["media/f.mp4"]["sha256"], a["sha256"])
        self.assertFalse(os.path.exists(cache + ".lock"))      # lock released
        self.touch("media/f.mp4", "abcd")
        b = project.file_fingerprint(self.sdir, "media/f.mp4", with_sha=True)
        self.assertNotEqual(a["sha256"], b["sha256"])
        self.assertTrue(project.same_fingerprint(b, project.stat_fingerprint(os.path.join(self.sdir, "media/f.mp4"))))
        self.assertFalse(project.same_fingerprint(a, b))

    def test_store_key_transform_runs_on_the_locked_read(self):
        self.init()
        project.store_key(self.pj, "checks", "render-engineer", {"pass": True, "x": 1}, 5)
        project.write_checks(self.pj, None, writer="blur.py",
                             transform=lambda d: dict(d["checks"], **{"pass": False}))
        self.assertEqual(project.read_project(self.pj)["checks"], {"pass": False, "x": 1})

    def test_unsafe_scenes(self):
        tl = {"scenes": [{"id": "s01", "in": 100}, {"id": "s02", "in": 900}, {"id": "s03", "in": 0}]}
        clips = {"s01": {"safe_from_ms": 500}, "s02": {"safe_from_ms": 500}}
        self.assertEqual(project.unsafe_scenes(tl, clips),
                         [{"scene": "s01", "in": 100, "safe_from_ms": 500}])


class RedactionTests(unittest.TestCase):
    def test_abbreviated_and_equals_flags_are_redacted(self):
        out = rb.redact_argv(["verify", "--pat", "hunter2", "--rege=hunter2", "--regex", "a+b",
                              "--video", "x.mp4"], [])
        self.assertEqual(out, ["verify", "--pat", "<redacted>", "--rege=<redacted>", "--regex",
                               "<redacted>", "--video", "x.mp4"])

    def test_literal_secrets_inside_other_arguments(self):
        out = rb.redact_argv(["--seed", "Acme Corp", "note Acme Corp"], ["Acme Corp"])
        self.assertEqual(out, ["--seed", "<redacted:0>", "note <redacted:0>"])

    def test_url_query_fragment_and_credentials(self):
        self.assertEqual(rb.redact_url("go https://u:p@app.test/a/b?token=abc&x=1#frag now"),
                         "go https://app.test/a/b?<redacted>#<redacted> now")
        out = rb.redact_argv(["--url", "https://app.test/x?session=zzz"], [])
        self.assertNotIn("zzz", " ".join(out))
        self.assertEqual(rb.redact_url("https://app.test/plain"), "https://app.test/plain")


if __name__ == "__main__":
    unittest.main()
