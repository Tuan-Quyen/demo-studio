import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import demo  # noqa: E402
import project  # noqa: E402

STATE = """# Demo studio state

- Slug: demo
- Pipeline: new
- Current step: 7 - sync-editor - align clips
- Gates: G1 approved · G2 pending · G3 pending
- Tools approved: capture

## Steps
| # | Agent | Output | Status (todo/doing/done/blocked) | Note |
|---|---|---|---|---|
| 1 | demo-strategist | brief.md | done | ok |
| 2 | storyboarder | storyboard.md | done | ok |
| 3 | sync-editor | #timeline | doing | none |

## Fix log
- none

## Next action
Wait for sync-editor.
Then render.
"""


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="demo-status-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dd = os.path.join(self.tmp, ".demo")
        self.sdir = os.path.join(self.dd, "demo")
        os.makedirs(self.sdir)
        self.pj = os.path.join(self.sdir, "project.json")
        project.main(["--project", self.pj, "init"])
        with open(os.path.join(self.dd, "STATE.md"), "w") as f:
            f.write(STATE)

    def put(self, key, value):
        project.store_key(self.pj, key, project.OWNERS[key], value, 5)

    def status(self, *extra, cwd=None):
        old = os.getcwd()
        os.chdir(cwd or self.tmp)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = demo.main(["status"] + list(extra))
        finally:
            os.chdir(old)
        return code, out.getvalue()

    def snapshot(self):
        return {os.path.join(r, f): os.stat(os.path.join(r, f)).st_mtime_ns
                for r, _, fs in os.walk(self.tmp) for f in fs}

    def test_status_json_reads_state_keys_stale_and_checks(self):
        self.put("voice", {"scenes": []})
        self.put("timeline", {"scenes": []})
        self.put("captions", {"cues": []})            # built on timeline v1
        self.put("timeline", {"scenes": [1]})         # timeline v2: captions is now stale
        project.write_checks(self.pj, {"pass": False, "results": {
            "loudness": {"pass": False, "owner": "sound-mixer"}, "black": {"pass": True, "owner": "capture-operator"}}},
            writer="checks.py")
        code, out = self.status("--json")
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertEqual(r["slug"], "demo")
        self.assertEqual(r["state"]["pipeline"], "new")
        self.assertEqual(r["state"]["steps"], {"done": 2, "doing": 1})
        self.assertTrue(r["state"]["next_action"].startswith("Wait for sync-editor."))
        self.assertEqual(r["keys"]["timeline"]["version"], 2)
        self.assertEqual(r["keys"]["captions"]["stale"], ["timeline"])
        self.assertEqual(r["stale_keys"], ["captions"])
        self.assertEqual(r["checks"]["failed"], [{"id": "loudness", "owner": "sound-mixer"}])
        self.assertFalse(r["checks"]["pass"])

    def test_status_is_read_only(self):
        self.put("voice", {"scenes": []})
        before = self.snapshot()
        self.status("--json")
        self.status()
        self.assertEqual(self.snapshot(), before)

    def test_hook_blocked_stage_is_reported_and_text_mode(self):
        with open(os.path.join(self.sdir, "hook-state.json"), "w") as f:
            json.dump({"demo-qa": {"blocks": 2, "blocked": True, "reason": "qa.md has no verdict"},
                       "packager": {"blocks": 1, "blocked": False}}, f)
        r = json.loads(self.status("--json")[1])
        self.assertEqual(list(r["blocked_stages"]), ["demo-qa"])
        code, text = self.status()
        self.assertEqual(code, 0)
        self.assertIn("blocked by fix-loop hook: demo-qa", text)
        self.assertIn("checks: not run", text)

    def test_works_from_a_subfolder_without_state_and_with_slug(self):
        os.remove(os.path.join(self.dd, "STATE.md"))
        sub = os.path.join(self.sdir, "media")
        os.makedirs(sub)
        code, out = self.status("--json", cwd=sub)
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertEqual((r["slug"], r["state"]["present"]), ("demo", False))
        self.assertEqual(self.status("--slug", "demo", "--json")[0], 0)

    def test_errors_exit_2(self):
        other = tempfile.mkdtemp(prefix="no-demo-")
        self.addCleanup(shutil.rmtree, other, True)
        self.assertEqual(self.status("--json", cwd=other)[0], 2)
        self.assertEqual(self.status("--slug", "nope")[0], 2)
        os.makedirs(os.path.join(self.dd, "second"))
        project.main(["--project", os.path.join(self.dd, "second", "project.json"), "init"])
        os.remove(os.path.join(self.dd, "STATE.md"))
        self.assertEqual(self.status("--json")[0], 2)      # two projects, no slug: ask


if __name__ == "__main__":
    unittest.main()
