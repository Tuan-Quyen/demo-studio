import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
HOOK = os.path.join(PLUGIN, "hooks", "demo_hook.py")
sys.path.insert(0, os.path.join(PLUGIN, "hooks"))
sys.path.insert(0, os.path.dirname(HERE))
import demo_hook  # noqa: E402
import project  # noqa: E402


def fire(payload, env=None, raw=None):
    p = subprocess.run([sys.executable, HOOK], input=raw if raw is not None else json.dumps(payload),
                       capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=60)
    return p.returncode, p.stderr


def pre(tool, tool_input, agent=None, cwd="/w"):
    d = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": cwd,
         "session_id": "s"}
    if agent is not None:
        d["agent_type"] = agent
    return d


class PreToolUseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hook-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sdir = os.path.join(self.tmp, ".demo", "demo")
        os.makedirs(self.sdir)
        self.pj = os.path.join(self.sdir, "project.json")
        self.yaml = os.path.join(self.sdir, "demo.yaml")

    def ok(self, payload, **kw):
        rc, err = fire(payload, **kw)
        self.assertEqual((rc, err), (0, ""))

    def deny(self, payload, word=None):
        rc, err = fire(payload)
        self.assertEqual(rc, 2, err)
        if word:
            self.assertIn(word, err)

    def test_project_json_write_edit_multiedit_denied(self):
        for tool, ti in (("Write", {"file_path": self.pj, "content": "{}"}),
                         ("Edit", {"file_path": self.pj, "old_string": "a", "new_string": "b"}),
                         ("MultiEdit", {"file_path": self.pj, "edits": [{"old_string": "a", "new_string": "b"}]})):
            for agent in (None, "capture-operator", "demo-studio:sync-editor"):
                self.deny(pre(tool, ti, agent), "project.py")

    def test_other_files_are_free(self):
        self.ok(pre("Write", {"file_path": os.path.join(self.sdir, "brief.md"), "content": "x"}))
        self.ok(pre("Write", {"file_path": os.path.join(self.tmp, "project.json"), "content": "{}"}))  # not under .demo
        self.ok(pre("Read", {"file_path": self.pj}))

    def test_foreign_agent_is_never_touched(self):
        self.ok(pre("Write", {"file_path": self.pj, "content": "{}"}, agent="other-plugin:builder"))
        self.ok(pre("Bash", {"command": "project.py --slug d set checks --json {}"}, agent="reviewer"))

    def test_accepted_key_cannot_be_edited(self):
        with open(self.yaml, "w") as f:
            f.write("platform: web\nprivacy:\n  data_mode: real-redacted\n  accepted: []\n")
        evil = '{"scene": "s01", "decided_by": "user"}'
        self.deny(pre("Edit", {"file_path": self.yaml, "old_string": "accepted: []",
                               "new_string": "accepted: [%r]" % evil}), "config.py accept")
        self.deny(pre("Write", {"file_path": self.yaml,
                                "content": "privacy:\n  accepted:\n    - x\n"}), "config.py accept")
        self.deny(pre("Edit", {"file_path": self.yaml, "old_string": "nothing here", "new_string": "accepted: [1]"}))
        # the other keys stay editable, and a rewrite that keeps `accepted` as it was is fine
        self.ok(pre("Edit", {"file_path": self.yaml, "old_string": "platform: web", "new_string": "platform: android"}))
        self.ok(pre("Write", {"file_path": self.yaml,
                              "content": "platform: web\nprivacy:\n  accepted: []\n  data_mode: seeded\n"}))
        self.ok(pre("Write", {"file_path": os.path.join(self.sdir, "new", "demo.yaml"), "content": "platform: web\n"}))

    def test_existing_accepted_entries_survive_a_rewrite(self):
        with open(self.yaml, "w") as f:
            f.write('privacy:\n  accepted: ["{\\"scene\\": \\"s01\\"}"]\n')
        self.ok(pre("Write", {"file_path": self.yaml,
                              "content": 'platform: web\nprivacy:\n  accepted: ["{\\"scene\\": \\"s01\\"}"]\n'}))
        self.deny(pre("Write", {"file_path": self.yaml, "content": "platform: web\nprivacy:\n  accepted: []\n"}))

    def test_bash_set_checks(self):
        for c in ("python project.py --slug d set checks --as render-engineer --json '{\"pass\": true}'",
                  "cd x && python3 ${CLAUDE_PLUGIN_ROOT}/scripts/project.py set checks --file c.json"):
            self.deny(pre("Bash", {"command": c}), "set checks")
        self.ok(pre("Bash", {"command": "python project.py --slug d set voice --as voice-producer --file v.json"}))
        self.ok(pre("Bash", {"command": "python project.py --slug d get checks"}))

    def test_bash_hand_edits_of_project_json(self):
        p = ".demo/d/project.json"
        for c in ("sed -i 's/false/true/' %s" % p, "echo '{}' > %s" % p, "echo x >> %s" % p,
                  "jq .checks.pass=true %s | tee %s" % (p, p), "cp /tmp/x.json %s" % p, "mv %s /tmp/p" % p,
                  "python3 -c \"import json;json.dump({}, open('%s','w'))\"" % p):
            self.deny(pre("Bash", {"command": c}), "project.json")
        for c in ("cat %s | jq .checks" % p, "grep -n pass %s" % p, "ls .demo/d/project.json.lock",
                  "python project.py --slug d keys", "cp %s /tmp/backup.json" % "foo",
                  "python3 checks.py --slug d --json > out.json"):
            self.ok(pre("Bash", {"command": c}))

    def test_bash_accepted_and_config_accept(self):
        self.deny(pre("Bash", {"command": "sed -i 's/accepted: \\[\\]/accepted: [1]/' .demo/d/demo.yaml"}), "config.py")
        self.deny(pre("Bash", {"command": "python config.py --slug d accept --scene s01 --reason 'user said yes' "
                                          "--decided-by user"}, agent="capture-operator"), "demo-director")
        self.deny(pre("Bash", {"command": "python config.py --slug d accept --scene s01 --reason x"},
                      agent="demo-studio:privacy-blurrer"))
        self.ok(pre("Bash", {"command": "python config.py --slug d accept --scene s01 --reason 'user said yes' "
                                        "--decided-by user"}, agent="demo-director"))
        self.ok(pre("Bash", {"command": "python config.py --slug d accept --scene s01 --reason 'user said yes' "
                                        "--decided-by user"}))     # main session = the user's own session
        self.ok(pre("Bash", {"command": "sed -i 's/web/android/' .demo/d/demo.yaml"}))

    def test_bad_input_fails_open(self):
        self.assertEqual(fire(None, raw="not json")[0], 0)
        self.assertEqual(fire(None, raw="[]")[0], 0)
        self.ok({"hook_event_name": "PreToolUse", "tool_name": "Glob", "tool_input": {"pattern": "*"}})
        self.ok({"hook_event_name": "Notification"})

    def test_privacy_rules_fail_closed_others_open(self):
        def boom(_):
            raise RuntimeError("bug")
        old = demo_hook.FILE_RULES
        demo_hook.FILE_RULES = (boom,)
        try:
            why = demo_hook.pre_tool_use(pre("Write", {"file_path": self.pj, "content": "{}"}))
            self.assertIn("fail closed", why)
            self.assertIsNone(demo_hook.pre_tool_use(pre("Write", {"file_path": "/w/readme.md", "content": "hi"})))
        finally:
            demo_hook.FILE_RULES = old

    def test_hooks_json_matches_the_documented_schema(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as f:
            h = json.load(f)["hooks"]
        self.assertEqual(sorted(h), ["PreToolUse", "SubagentStop"])
        self.assertEqual(h["PreToolUse"][0]["matcher"], "Write|Edit|MultiEdit|Bash")
        for ev in h.values():
            for g in ev:
                for c in g["hooks"]:
                    self.assertEqual(c["type"], "command")
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/demo_hook.py", c["command"])
                    self.assertIsInstance(c["timeout"], int)


class SubagentStopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hook-stop-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sdir = os.path.join(self.tmp, ".demo", "demo")
        os.makedirs(self.sdir)
        project.main(["--project", os.path.join(self.sdir, "project.json"), "init"])
        with open(os.path.join(self.tmp, ".demo", "STATE.md"), "w") as f:
            f.write("# Demo studio state\n\n- Slug: demo\n- Pipeline: new\n")

    def stop(self, agent="demo-qa", env=None, **kw):
        d = {"hook_event_name": "SubagentStop", "agent_type": agent, "cwd": self.tmp,
             "stop_hook_active": False, "last_assistant_message": "done"}
        d.update(kw)
        return fire(d, env=env)

    def state(self):
        with open(os.path.join(self.sdir, "hook-state.json")) as f:
            return json.load(f)

    def test_blocks_twice_then_lets_go_and_marks_blocked(self):
        rc, err = self.stop()
        self.assertEqual(rc, 2)
        self.assertIn("qa.md", err)
        self.assertIn("stage 'qa'", err)
        self.assertEqual(self.stop()[0], 2)
        self.assertEqual(self.stop()[0], 0)                       # limit reached: no endless loop
        st = self.state()["demo-qa"]
        self.assertTrue(st["blocked"])
        self.assertEqual(st["blocks"], 2)

    def test_limit_is_configurable_and_pass_resets_counter(self):
        self.assertEqual(self.stop(env={"DEMO_HOOK_MAX_BLOCKS": "0"})[0], 0)
        self.assertTrue(self.state()["demo-qa"]["blocked"])
        os.remove(os.path.join(self.sdir, "hook-state.json"))
        self.assertEqual(self.stop()[0], 2)
        with open(os.path.join(self.sdir, "qa.md"), "w") as f:
            f.write("## Verdict: PASS\n")
        self.assertEqual(self.stop()[0], 0)
        self.assertNotIn("demo-qa", self.state())

    def test_plugin_prefixed_name_and_per_agent_counter(self):
        self.assertEqual(self.stop("demo-studio:demo-qa")[0], 2)
        self.assertEqual(self.stop("packager")[0], 2)
        self.assertEqual(sorted(self.state()), ["demo-qa", "packager"])

    def test_foreign_unmapped_and_missing_project_are_not_blocked(self):
        self.assertEqual(self.stop("other-plugin:reviewer")[0], 0)
        self.assertEqual(self.stop("")[0], 0)                      # internal Claude Code agent
        self.assertEqual(self.stop("demo-director")[0], 0)         # no machine DoD
        self.assertEqual(self.stop("toolsmith")[0], 0)
        os.remove(os.path.join(self.sdir, "project.json"))
        self.assertEqual(self.stop()[0], 0)                        # fail open
        self.assertFalse(os.path.exists(os.path.join(self.sdir, "hook-state.json")))

    def test_parallel_post_agents_judged_on_own_key(self):
        project.store_key(os.path.join(self.sdir, "project.json"), "mix", "sound-mixer", {"preview": {}}, 5)
        self.assertEqual(self.stop("sound-mixer")[0], 0)           # #timeline etc. are not its job
        self.assertEqual(self.stop("sync-editor")[0], 2)


if __name__ == "__main__":
    unittest.main()
