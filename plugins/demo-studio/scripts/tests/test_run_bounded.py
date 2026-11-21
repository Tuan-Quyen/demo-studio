import contextlib
import io
import json
import os
import shutil
import signal
import sys
import tempfile
import textwrap
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import run_bounded as rb  # noqa: E402

PY = sys.executable
POSIX = os.name != "nt"


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie still answers kill(0); read its state
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = rb.main(argv)
    return code, json.loads(out.getvalue())


class BasicTests(unittest.TestCase):
    def test_ok_reports_tool_rc_not_forwarded(self):
        r = rb.run_bounded([PY, "-c", "import sys; print('hi'); sys.exit(3)"], wall=10)
        self.assertEqual((r["status"], r["exit"], r["tool_rc"]), ("ok", 0, 3))
        self.assertIn("hi", r["stdout_tail"])
        self.assertTrue(r["stall_disabled"])  # heartbeat none must be explicit in the JSON

    def test_cli_exit_zero_even_if_tool_fails(self):
        code, j = cli(["--wall", "10", "--label", "x", "--", PY, "-c", "raise SystemExit(7)"])
        self.assertEqual(code, 0)
        self.assertEqual(j["tool_rc"], 7)
        self.assertEqual(j["label"], "x")

    def test_missing_binary_is_bug_70(self):
        code, j = cli(["--wall", "5", "--", "/nonexistent/binary-xyz"])
        self.assertEqual(code, 70)
        self.assertEqual(j["class"], "bug")

    def test_usage_errors(self):
        self.assertEqual(rb.main(["--wall", "5", "--"]), 2)
        self.assertEqual(rb.main(["--wall", "0", "--", "true"]), 2)

    def test_wall_timeout_124(self):
        t = time.monotonic()
        code, j = cli(["--wall", "0.5", "--", PY, "-c", "import time; time.sleep(60)"])
        self.assertEqual((code, j["status"]), (124, "wall"))
        self.assertLess(time.monotonic() - t, 8)

    def test_stall_jsonl_125_and_alive_ok(self):
        hung = "import time; time.sleep(60)"
        r = rb.run_bounded([PY, "-c", hung], wall=30, stall=0.6, heartbeat="jsonl")
        self.assertEqual((r["status"], r["exit"]), ("stall", 125))
        beating = ("import sys, time, json\n"
                   "for i in range(8):\n"
                   "    sys.stderr.write(json.dumps({'i': i}) + '\\n'); sys.stderr.flush()\n"
                   "    time.sleep(0.2)\n")
        r = rb.run_bounded([PY, "-c", beating], wall=30, stall=1.0, heartbeat="jsonl")
        self.assertEqual((r["status"], r["tool_rc"]), ("ok", 0))

    def test_non_json_stderr_is_not_a_heartbeat(self):
        noisy = ("import sys, time\n"
                 "for i in range(60):\n"
                 "    sys.stderr.write('log line\\n'); sys.stderr.flush(); time.sleep(0.1)\n")
        r = rb.run_bounded([PY, "-c", noisy], wall=30, stall=0.8, heartbeat="jsonl")
        self.assertEqual(r["status"], "stall")

    def test_ffmpeg_command_gets_progress_flags(self):
        cmd = rb.with_ffmpeg_progress(["ffmpeg", "-i", "a", "-f", "null", "-"])
        self.assertEqual(cmd[:4], ["ffmpeg", "-nostdin", "-progress", "pipe:1"])
        self.assertEqual(rb.with_ffmpeg_progress(cmd), cmd)  # idempotent
        self.assertEqual(rb.with_ffmpeg_progress(["echo", "x"]), ["echo", "x"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg missing")
    def test_ffmpeg_heartbeat_real_run(self):
        r = rb.run_bounded(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc=s=64x64:r=25:d=2", "-f", "null", "-"],
                           wall=30, stall=10, heartbeat="ffmpeg")
        self.assertEqual((r["status"], r["tool_rc"]), ("ok", 0))
        self.assertIn("progress=end", r["stdout_tail"])


@unittest.skipUnless(POSIX, "process groups: POSIX only (Windows taskkill branch is untested)")
class KillTreeTests(unittest.TestCase):
    """A hung child (and its own children) must be gone, not just the leader."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _spawner(self, body):
        script = textwrap.dedent("""
            import os, subprocess, sys, time
            pidfile = sys.argv[1]
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
            with open(pidfile, 'w') as f:
                f.write('%d %d' % (os.getpgid(0), child.pid))
            """) + textwrap.dedent(body)
        return [PY, "-c", script, os.path.join(self.tmp, "pids")]

    def _pids(self):
        with open(os.path.join(self.tmp, "pids")) as f:
            return [int(x) for x in f.read().split()]

    def _assert_gone(self, pgid, child):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and (alive(child) or _pg_alive(pgid)):
            time.sleep(0.05)
        self.assertFalse(alive(child), "grandchild survived")
        self.assertFalse(_pg_alive(pgid), "process group %d still has members" % pgid)

    def test_hung_leader_and_child_killed_on_wall(self):
        r = rb.run_bounded(self._spawner("time.sleep(120)"), wall=1.0)
        self.assertEqual(r["status"], "wall")
        self.assertTrue(r["killed"])
        pgid, child = self._pids()
        self._assert_gone(pgid, child)

    def test_sigterm_ignoring_leader_gets_sigkill(self):
        body = "signal = __import__('signal'); signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" \
               "time.sleep(120)"
        t = time.monotonic()
        r = rb.run_bounded(self._spawner(body), wall=0.8)
        self.assertEqual(r["status"], "wall")
        self.assertLess(time.monotonic() - t, 10)
        pgid, child = self._pids()
        self._assert_gone(pgid, child)

    def test_hung_on_fifo_read_is_killed(self):
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        r = rb.run_bounded([PY, "-c", "import sys; open(sys.argv[1]).read()", fifo], wall=0.8)
        self.assertEqual(r["status"], "wall")

    def test_orphan_left_after_leader_exit_is_killed(self):
        script = ("import subprocess, sys; p = subprocess.Popen([sys.executable, '-c', "
                  "'import time; time.sleep(120)']); open(sys.argv[1], 'w').write(str(p.pid))")
        r = rb.run_bounded([PY, "-c", script, os.path.join(self.tmp, "pid")], wall=10)
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["orphans_killed"])
        with open(os.path.join(self.tmp, "pid")) as f:
            child = int(f.read())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and alive(child):
            time.sleep(0.05)
        self.assertFalse(alive(child))


def _pg_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    # members may all be zombies awaiting reap by init
    try:
        for name in os.listdir("/proc"):
            if name.isdigit():
                with open("/proc/%s/stat" % name) as f:
                    rest = f.read().rsplit(")", 1)[1].split()
                if int(rest[2]) == pgid and rest[0] != "Z":
                    return True
        return False
    except OSError:
        return True


class HelperTests(unittest.TestCase):
    def test_redact_argv(self):
        out = rb.redact_argv(["x", "--re", r"sk-[A-Z]+", "mail bob@x.com"], ["sk-[A-Z]+", "bob@x.com"])
        self.assertEqual(out, ["x", "--re", "<redacted:0>", "mail <redacted:1>"])

    def test_append_run_redacts(self):
        with tempfile.TemporaryDirectory() as d:
            rb.append_run(d, "blur.py", ["verify", "--re", "SECRET"], {"status": "ok", "elapsed_s": 1},
                          ["SECRET"])
            line = open(os.path.join(d, "runs.jsonl")).read()
            self.assertNotIn("SECRET", line)
            self.assertIn("<redacted:0>", line)

    def test_guard_main_maps_exception_to_70(self):
        def boom():
            raise RuntimeError("x")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rb.guard_main(boom)
        self.assertEqual(code, 70)
        self.assertEqual(json.loads(out.getvalue())["class"], "bug")

    def test_streaming_bounded_stall_via_touch(self):
        with rb.Bounded([PY, "-c", "import time; time.sleep(60)"], wall=30, stall=0.5) as b:
            deadline = time.monotonic() + 8
            while b.proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
        self.assertEqual(b.reason, "stall")


if __name__ == "__main__":
    unittest.main()
