#!/usr/bin/env python3
"""Where is this demo? (docs/redesign §4.2, P1 subset: `status` only; read-only, writes nothing.)

Usage:
  demo.py status [--slug SLUG | --project PATH] [--demo-dir DIR] [--json]

Reads `.demo/STATE.md` (pipeline, current step, gates, next action, step counts), `project.json`
(per key: version, owner, updated, stale = upstream keys that changed since it was written) and the last
#checks (pass, failed checks with owners), plus `.demo/<slug>/hook-state.json` (stages the fix-loop hook
gave up on: `blocked`). Without --slug the slug comes from STATE.md `- Slug:`, else the only project in
`.demo/`. One JSON line with --json, else a few lines of text.

Exit codes: 0 ok | 2 no .demo folder, no unique project, or unreadable project.json | 70 unexpected error.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project  # noqa: E402
import run_bounded as rbm  # noqa: E402


def find_demo_dir(start):
    """Nearest `.demo` folder at or above `start` (a start inside `.demo` returns that folder), or None."""
    d = os.path.abspath(start)
    while True:
        if os.path.basename(d) == ".demo" and os.path.isdir(d):
            return d
        if os.path.isdir(os.path.join(d, ".demo")):
            return os.path.join(d, ".demo")
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def read_state(demo_dir):
    """Parse .demo/STATE.md into {slug, pipeline, current_step, gates, tools, next_action, steps}."""
    out = {"present": False}
    try:
        with open(os.path.join(demo_dir, "STATE.md"), encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        return out
    out["present"] = True
    for key, label in (("slug", "Slug"), ("pipeline", "Pipeline"), ("current_step", "Current step"),
                       ("gates", "Gates"), ("tools", "Tools approved")):
        m = re.search(r"^-\s*%s:\s*(.+?)\s*$" % label, text, re.M)
        out[key] = m.group(1) if m else None
    m = re.search(r"^##\s*Next action\s*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    out["next_action"] = m.group(1).strip() if m else None
    counts = {}
    for row in re.findall(r"^\|\s*\d+\s*\|.*\|\s*$", text, re.M):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) >= 4:
            counts[cells[3]] = counts.get(cells[3], 0) + 1
    out["steps"] = counts
    return out


def resolve_slug(demo_dir, args, state):
    if args.slug:
        return args.slug
    slug = (state.get("slug") or "").split()[0] if state.get("slug") else ""
    if slug and os.path.isfile(os.path.join(demo_dir, slug, "project.json")):
        return slug
    found = sorted(d for d in os.listdir(demo_dir)
                   if os.path.isfile(os.path.join(demo_dir, d, "project.json")))
    if len(found) == 1:
        return found[0]
    raise project.CliError(2, "cannot pick a project: pass --slug (found: %s)" % (", ".join(found) or "none"))


def read_hook_state(sdir):
    try:
        with open(os.path.join(sdir, "hook-state.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def build_status(args):
    if args.project:
        path = os.path.abspath(args.project)
        sdir = os.path.dirname(path)
        demo_dir = os.path.dirname(sdir)
        state = read_state(demo_dir)
        slug = os.path.basename(sdir)
    else:
        demo_dir = args.demo_dir or find_demo_dir(os.getcwd())
        if not demo_dir or not os.path.isdir(demo_dir):
            raise project.CliError(2, "no .demo folder at or above %s" % os.getcwd())
        state = read_state(demo_dir)
        slug = resolve_slug(demo_dir, args, state)
        path = os.path.join(demo_dir, slug, "project.json")
        sdir = os.path.dirname(path)
    data = project.read_project(path)
    keys = {}
    for k, e in sorted(data["_meta"]["keys"].items()):
        e = e if isinstance(e, dict) else {}
        keys[k] = {"version": e.get("version"), "owner": e.get("owner"), "updated": e.get("updated"),
                   "stale": project.stale_inputs(data, k) if k in project.OWNERS else []}
    c = data.get("checks") if isinstance(data.get("checks"), dict) else None
    checks = None
    if c is not None:
        res = c.get("results") if isinstance(c.get("results"), dict) else {}
        checks = {"pass": bool(c.get("pass")), "version": keys.get("checks", {}).get("version"),
                  "stale": keys.get("checks", {}).get("stale", []),
                  "failed": [{"id": i, "owner": r.get("owner")} for i, r in sorted(res.items())
                             if isinstance(r, dict) and not r.get("pass")]}
    hook = {a: {"blocks": v.get("blocks"), "reason": v.get("reason")}
            for a, v in read_hook_state(sdir).items() if isinstance(v, dict) and v.get("blocked")}
    return {"status": "ok", "slug": slug, "project": path, "state": state, "keys": keys,
            "stale_keys": sorted(k for k, v in keys.items() if v["stale"]), "checks": checks,
            "blocked_stages": hook}


def render_text(r):
    s = r["state"]
    lines = ["%s: %s" % (r["slug"], s.get("pipeline") or "(no STATE.md)"),
             "step: %s" % (s.get("current_step") or "-"), "gates: %s" % (s.get("gates") or "-")]
    lines += ["keys: " + (", ".join("%s v%s%s" % (k, v["version"], " STALE(%s)" % ",".join(v["stale"])
                                                  if v["stale"] else "") for k, v in r["keys"].items()) or "none")]
    c = r["checks"]
    lines.append("checks: " + ("not run" if c is None else "v%s pass=%s%s" % (
        c["version"], str(c["pass"]).lower(),
        " failed: " + ", ".join("%s(%s)" % (f["id"], f["owner"]) for f in c["failed"]) if c["failed"] else "")))
    if r["blocked_stages"]:
        lines.append("blocked by fix-loop hook: " + ", ".join(r["blocked_stages"]))
    lines.append("next: %s" % ((s.get("next_action") or "-").splitlines() or ["-"])[0])
    return "\n".join(lines)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Demo status (read-only).", allow_abbrev=False)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--slug")
    s.add_argument("--project")
    s.add_argument("--demo-dir", dest="demo_dir")
    s.add_argument("--json", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        r = build_status(args)
    except project.CliError as e:
        sys.stderr.write("error: %s\n" % e.msg)
        return e.code
    print(json.dumps(r, ensure_ascii=False) if args.json else render_text(r))
    return 0


if __name__ == "__main__":
    sys.exit(rbm.guard_main(main))
