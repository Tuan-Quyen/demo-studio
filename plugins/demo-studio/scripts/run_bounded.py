#!/usr/bin/env python3
"""Run a subprocess with a hard wall-clock timeout and a no-progress (stall) timeout.

Usage:
  run_bounded.py --wall S [--stall S] [--label L] [--heartbeat ffmpeg|jsonl|none] [--cwd D]
                 [--tail-bytes N] -- cmd [args...]

The command runs in its own session / process group (stdin = /dev/null). On timeout the whole
group gets SIGTERM, then (after polling killpg(pgid, 0) for 2 s) SIGKILL: never just wait() on
the leader. Orphans left in the group after the leader exited are killed too.

Heartbeat (what counts as progress for --stall):
  ffmpeg  adds `-nostdin -progress pipe:1 -nostats` to an ffmpeg command; progress = a changed
          frame / out_time / total_size value in the progress stream.
  jsonl   progress = a JSON-object line on the child's stderr (the protocol of every script
          in this plugin, see `Heartbeat`).
  none    wall clock only; the result says `"stall_disabled": true`.
Without --stall only the wall clock applies.

Output: ONE JSON line on stdout:
  {"status": "ok|wall|stall|error", "exit": 0|124|125|70, "tool_rc": N|null, "elapsed_s": F,
   "label": L, "heartbeat": H, "killed": bool, "orphans_killed": bool, "stdout_tail": "...",
   "stderr_tail": "...", ...}
Exit codes (the wrapped tool's own exit code is NOT forwarded, it is `tool_rc` in the JSON):
  0    the tool ran to completion (look at tool_rc)
  2    usage error
  70   could not start the command / unexpected exception (class "bug")
  124  wall timeout
  125  stall (no heartbeat for --stall seconds)

Importable: run_bounded(cmd, wall=..., stall=..., heartbeat=...) -> dict (same fields);
Bounded(cmd, ...) is a context manager for streaming a child's stdout (see blur.py verify),
the reader calls .touch() as progress. Windows: group kill is `taskkill /T /F` (best effort,
UNTESTED: this repo is developed and tested on Linux only).
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

EXIT_OK, EXIT_USAGE, EXIT_BUG, EXIT_WALL, EXIT_STALL = 0, 2, 70, 124, 125
IS_WINDOWS = os.name == "nt"
TERM_GRACE_S = 2.0
HEARTBEAT_MODES = ("ffmpeg", "jsonl", "none")


# --------------------------------------------------------------------------- shared helpers
class Heartbeat:
    """Emit a JSON progress line on stderr at most every `interval` s (call .beat() often;
    or use as a context manager to get a background ticker)."""

    def __init__(self, label="", interval=2.0, stream=None):
        self.label, self.interval = label, interval
        self.stream = stream or sys.stderr
        self.state = {}
        self._last = 0.0
        self._stop = None

    def beat(self, **state):
        self.state.update(state)
        if time.monotonic() - self._last >= self.interval:
            self.force()

    def force(self):
        self._last = time.monotonic()
        try:
            self.stream.write(json.dumps(dict(self.state, hb=self.label, t=round(time.time(), 1)))
                              + "\n")
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def __enter__(self):
        self._stop = threading.Event()

        def tick():
            while not self._stop.wait(self.interval):
                self.force()

        threading.Thread(target=tick, daemon=True).start()
        self.force()
        return self

    def __exit__(self, *exc):
        if self._stop:
            self._stop.set()
        return False


# flags whose value is sensitive by nature (regex literals, seed data, URLs with tokens)
SENSITIVE_FLAGS = ("--pattern", "--regex", "--regexes", "--seed", "--seed-value", "--seed-values",
                   "--selector", "--selectors", "--token", "--secret", "--password", "--key",
                   "--cookie", "--header", "--text", "--value")
_URL_RX = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/?#\s]*@)?([^?#\s]*)(\?[^#\s]*)?(#\S*)?")


def redact_url(s):
    """Hide credentials and the query string / fragment of every URL in `s`
    (`https://u:p@h/p?token=x#f` -> `https://h/p?<redacted>`). Shared with capture.py."""
    def sub(m):
        out = m.group(1) + m.group(3)
        if m.group(4):
            out += "?<redacted>"
        if m.group(5):
            out += "#<redacted>"
        return out
    return _URL_RX.sub(sub, s)


def _is_sensitive_flag(name):
    """`--pattern`, and also any abbreviation of it (`--pat`, `--rege`): argparse accepted those
    before allow_abbrev=False, and a log line must not leak through them either."""
    if not name.startswith("--") or len(name) < 4:
        return False
    return any(f == name or f.startswith(name) for f in SENSITIVE_FLAGS)


def redact_argv(argv, secrets=(), flags=True):
    """Redact an argv before it is logged: every literal secret (privacy.regexes / seed_values /
    --pattern values) -> <redacted:N>; the value of a sensitive flag (also abbreviated or `--flag=v`)
    -> <redacted>; URL query strings, fragments and credentials hidden."""
    uniq = list(dict.fromkeys(s for s in secrets if s))   # stable numbering: order of first appearance
    secrets = sorted(enumerate(uniq), key=lambda ns: len(ns[1]), reverse=True)  # longest literal first
    out, hide_next = [], False
    for a in argv:
        a = str(a)
        if hide_next:
            hide_next = False
            lit = a
            for n, s in secrets:
                lit = lit.replace(s, "<redacted:%d>" % n)
            out.append(lit if lit != a else "<redacted>")
            continue
        if flags and a.startswith("--"):
            name, eq, _ = a.partition("=")
            if _is_sensitive_flag(name):
                if eq:
                    out.append(name + "=<redacted>")
                else:
                    out.append(a)
                    hide_next = True
                continue
        for n, s in secrets:
            a = a.replace(s, "<redacted:%d>" % n)
        out.append(redact_url(a))
    return out


def append_run(slug_dir, script, argv, result, secrets=()):
    """Append one line to <slug_dir>/runs.jsonl (argv redacted, result kept small)."""
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "script": script,
           "argv": redact_argv(argv, secrets),
           "status": result.get("status"), "elapsed_s": result.get("elapsed_s")}
    if result.get("failures"):
        rec["failures"] = result["failures"]
    try:
        os.makedirs(slug_dir, exist_ok=True)
        with open(os.path.join(slug_dir, "runs.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def guard_main(fn, *args):
    """Top-level handler: any unexpected exception -> exit 70 + JSON class "bug" (never Python's 1)."""
    try:
        return fn(*args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        return 130
    except BaseException as e:  # noqa: BLE001 - this is the catch-all by design
        sys.stdout.write(json.dumps({"status": "bug", "class": "bug", "error": "%s: %s"
                                     % (type(e).__name__, e)}) + "\n")
        return EXIT_BUG


# --------------------------------------------------------------------------- process group kill
def _group_alive(pgid):
    if IS_WINDOWS:
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_group(proc, grace=TERM_GRACE_S):
    """TERM the whole group, poll killpg(pgid, 0) up to `grace` s, then KILL. Returns True if a
    signal was needed. The leader is reaped (poll) so a zombie does not look alive."""
    if IS_WINDOWS:  # best effort, UNTESTED
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.wait(5)
        except Exception:
            pass
        return True
    pgid = proc.pid  # start_new_session: the leader's pid is the group id
    proc.poll()
    if not _group_alive(pgid):
        return False
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    end = time.monotonic() + grace
    while time.monotonic() < end:
        proc.poll()
        if not _group_alive(pgid):
            return True
        time.sleep(0.02)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    end = time.monotonic() + 5
    while time.monotonic() < end:
        proc.poll()
        if not _group_alive(pgid):
            break
        time.sleep(0.02)
    return True


def with_ffmpeg_progress(cmd):
    """Add -nostdin -progress pipe:1 -nostats to an ffmpeg command (once)."""
    if not os.path.basename(cmd[0]).lower().startswith("ffmpeg"):
        return list(cmd)
    extra = [] if "-nostdin" in cmd else ["-nostdin"]
    if "-progress" not in cmd:
        extra += ["-progress", "pipe:1", "-nostats"]
    return [cmd[0]] + extra + list(cmd[1:])


# --------------------------------------------------------------------------- core
class Bounded:
    """Context manager: start `cmd` in its own process group and watch it from a thread.

    .proc is the Popen; call .touch() whenever progress is seen; .reason becomes "wall" or "stall"
    when the watchdog killed the group. Leaving the block always reaps the group."""

    def __init__(self, cmd, wall, stall=None, label="", cwd=None, env=None,
                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE):
        self.cmd, self.wall, self.stall, self.label = list(cmd), wall, stall, label
        self.cwd, self.env = cwd, env
        self.stdin, self.stdout, self.stderr = stdin, stdout, stderr
        self.proc = None
        self.reason = None
        self.killed = False
        self.orphans_killed = False
        self._last = 0.0
        self._t0 = 0.0
        self._done = threading.Event()
        self._thread = None
        self._closed = False

    def touch(self):
        self._last = time.monotonic()

    @property
    def elapsed(self):
        return time.monotonic() - self._t0

    def __enter__(self):
        kw = dict(stdin=self.stdin, stdout=self.stdout, stderr=self.stderr, cwd=self.cwd,
                  env=self.env)
        if IS_WINDOWS:
            kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kw["start_new_session"] = True
        self._t0 = self._last = time.monotonic()
        self.proc = subprocess.Popen(self.cmd, **kw)
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def _watch(self):
        while not self._done.wait(0.05):
            now = time.monotonic()
            if now - self._t0 > self.wall:
                self.reason = "wall"
            elif self.stall and now - self._last > self.stall:
                self.reason = "stall"
            if self.reason:
                self.killed = kill_group(self.proc)
                return

    def __exit__(self, *exc):
        if self._closed:
            return False
        self._closed = True
        self._done.set()
        self._thread.join()
        if not self.reason and kill_group(self.proc):
            self.orphans_killed = True  # leader gone (or we left early) but the group lived on
        for s in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        return False


def _tail_reader(stream, buf, limit, on_line):
    def run():
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace")
                buf.append(line)
                size = sum(len(x) for x in buf)
                while size > limit and len(buf) > 1:
                    size -= len(buf.pop(0))
                on_line(line)
        except (OSError, ValueError):
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def run_bounded(cmd, wall, stall=None, label="", heartbeat="none", cwd=None, env=None,
                tail_bytes=8192):
    """Run `cmd` bounded; return the result dict (see module doc). Never raises for a tool failure."""
    if heartbeat not in HEARTBEAT_MODES:
        raise ValueError("heartbeat must be one of %s" % ", ".join(HEARTBEAT_MODES))
    cmd = with_ffmpeg_progress(cmd) if heartbeat == "ffmpeg" else list(cmd)
    res = {"label": label, "heartbeat": heartbeat, "wall_s": wall, "stall_s": stall,
           "tool_rc": None, "killed": False, "orphans_killed": False}
    if heartbeat == "none":
        res["stall_disabled"] = True
        stall = None
    out_buf, err_buf, seen = [], [], {}
    t0 = time.monotonic()
    b = Bounded(cmd, wall, stall, label, cwd=cwd, env=env)
    try:
        b.__enter__()
    except OSError as e:
        res.update(status="error", exit=EXIT_BUG, error="cannot start: %s" % e, elapsed_s=0.0,
                   stdout_tail="", stderr_tail="")
        res["class"] = "bug"
        return res

    def on_out(line):
        if heartbeat == "ffmpeg":
            k, _, v = line.strip().partition("=")
            if k in ("frame", "out_time_us", "out_time_ms", "total_size") and v not in ("", "N/A"):
                if seen.get(k) != v:
                    seen[k] = v
                    b.touch()

    def on_err(line):
        if heartbeat == "jsonl":
            s = line.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    json.loads(s)
                    b.touch()
                except ValueError:
                    pass

    threads = [_tail_reader(b.proc.stdout, out_buf, tail_bytes, on_out),
               _tail_reader(b.proc.stderr, err_buf, tail_bytes, on_err)]
    try:
        while b.proc.poll() is None and not b.reason:
            time.sleep(0.02)
        for t in threads:
            t.join(3)
    finally:
        b.__exit__(None, None, None)
    res.update(elapsed_s=round(time.monotonic() - t0, 3), killed=b.killed,
               orphans_killed=b.orphans_killed,
               stdout_tail="".join(out_buf), stderr_tail="".join(err_buf))
    if b.reason == "wall":
        res.update(status="wall", exit=EXIT_WALL)
        res["class"] = "timeout"
    elif b.reason == "stall":
        res.update(status="stall", exit=EXIT_STALL)
        res["class"] = "stall"
    else:
        res.update(status="ok", exit=EXIT_OK, tool_rc=b.proc.returncode)
    return res


# --------------------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(description="Run a command with wall and stall timeouts.", allow_abbrev=False,
                                usage="run_bounded.py --wall S [--stall S] [--label L] "
                                      "[--heartbeat ffmpeg|jsonl|none] -- cmd [args...]")
    p.add_argument("--wall", type=float, required=True, help="hard wall-clock limit, seconds")
    p.add_argument("--stall", type=float, default=None, help="max seconds without a heartbeat")
    p.add_argument("--label", default="")
    p.add_argument("--heartbeat", choices=HEARTBEAT_MODES, default="none")
    p.add_argument("--cwd", default=None)
    p.add_argument("--tail-bytes", type=int, default=8192)
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        sys.stderr.write("error: no command given (put it after --)\n")
        return EXIT_USAGE
    if args.wall <= 0 or (args.stall is not None and args.stall <= 0):
        sys.stderr.write("error: --wall and --stall must be > 0\n")
        return EXIT_USAGE
    if args.stall is not None and args.heartbeat == "none":
        sys.stderr.write("note: --heartbeat none: --stall ignored, wall clock only\n")
    res = run_bounded(cmd, args.wall, args.stall, args.label, args.heartbeat, args.cwd,
                      tail_bytes=args.tail_bytes)
    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
    return res["exit"]


if __name__ == "__main__":
    sys.exit(guard_main(main))
