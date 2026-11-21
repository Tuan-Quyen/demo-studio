#!/usr/bin/env python3
"""Safe shared access to .demo/<slug>/project.json (one owner per top-level key).

Usage:
  project.py (--project PATH | --slug SLUG) [--timeout SEC] <command> ...
    init
    get <key> [--version]   --version prints the stored version (the value itself has no
                            version field; also see `keys`, which lists all versions)
    set <key> --as <agent> [--file PATH | --json TEXT | (stdin)] [--expect-version N]
    keys
    deps <key> [--json]   keys to re-run after <key> changes (transitive, run order)
    owner <key>           agent that owns <key>
    check-blur            geometric privacy check (read-only, no OCR), at every rendered frame: every `sensitive`
                          marker of #events is covered by #blur in space and time; prints JSON,
                          exit 0 pass / 1 fail
  (deps/owner need no project file)
  --slug walks up from cwd to the nearest `.demo/<slug>`; inside `.demo/` with none above it, or
  with a path containing `.demo/.demo`, it refuses (exit 2). `set` prints "<key> version N (<path>)"
  after reading the file back: quote that line in the handoff.

Exit codes:
  0  ok
  1  check-blur found a gap, an invalid bbox or a weak blur
  2  usage / validation error (bad JSON, unknown key, missing/corrupt file)
  3  version conflict (--expect-version differs from the stored version)
  4  owner mismatch (--as agent does not own the key)
  5  lock timeout

Writes take an exclusive lock file "<project>.lock" (O_CREAT|O_EXCL), re-read the
file under the lock, change only the target key and its _meta entry, and replace
the file atomically (temp file in the same directory + os.replace).
"""
import argparse
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

OWNERS = {
    "events": "capture-operator",
    "voice": "voice-producer",
    "blur": "privacy-blurrer",
    "timeline": "sync-editor",
    "motion": "motion-designer",
    "captions": "caption-writer",
    "mix": "sound-mixer",
    "checks": "render-engineer",
    "delivery": "packager",
}

# key -> keys that must be re-run when it changes (direct dependents)
DOWNSTREAM = {
    "voice": ["timeline", "captions", "mix"],
    "events": ["blur", "timeline"],
    "timeline": ["motion", "captions", "mix"],
    "blur": ["checks"],
    "motion": ["checks"],
    "captions": ["checks"],
    "mix": ["checks"],
    "checks": ["delivery"],
    "delivery": [],
}
# a valid run order of all keys (every key comes after the keys it depends on)
RUN_ORDER = ["voice", "events", "timeline", "blur", "motion", "captions", "mix",
             "checks", "delivery"]

STALE_LOCK_SECONDS = 30.0
SCHEMA = 1


class CliError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_key(key):
    if key not in OWNERS:
        raise CliError(2, "unknown key %r; valid keys: %s" % (key, ", ".join(OWNERS)))


def _parts(path):
    return [p.lower() for p in os.path.normpath(path).split(os.sep)]


def _nested_demo(path):
    p = _parts(path)
    return any(a == b == ".demo" for a, b in zip(p, p[1:]))


def project_path(args, creating=False):
    """Resolve project.json. --slug walks up from cwd to the nearest `.demo/<slug>`, so running
    from inside `.demo/` (or any subfolder) hits the same file; a nested `.demo/.demo` is refused."""
    if args.project:
        path = os.path.abspath(args.project)
        if _nested_demo(path):
            raise CliError(2, "refusing nested .demo/.demo path: %s" % path)
        return path
    if not args.slug:
        raise CliError(2, "one of --project or --slug is required")
    cwd = os.path.abspath(os.getcwd())
    d = cwd
    while True:
        if os.path.isdir(os.path.join(d, ".demo", args.slug)):
            return os.path.join(d, ".demo", args.slug, "project.json")
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    if ".demo" in _parts(cwd):
        raise CliError(2, "cwd %s is inside .demo and no .demo/%s was found above it; "
                          "run from the project root" % (cwd, args.slug))
    return os.path.join(cwd, ".demo", args.slug, "project.json")


def retry_fs(fn, attempts=20, delay=0.02):
    """Retry transient Windows sharing violations (PermissionError)."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def read_project(path):
    def _read():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    try:
        text = retry_fs(_read)
    except FileNotFoundError:
        raise CliError(2, "project file not found: %s (run init)" % path)
    try:
        data = json.loads(text)
    except ValueError as e:
        raise CliError(2, "project file is not valid JSON: %s" % e)
    if not isinstance(data, dict):
        raise CliError(2, "project file root must be a JSON object")
    meta = data.get("_meta")
    if not isinstance(meta, dict):
        meta = data["_meta"] = {}
    meta.setdefault("schema", SCHEMA)
    if not isinstance(meta.get("keys"), dict):
        meta["keys"] = {}
    return data


def atomic_write(path, data):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".project-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        retry_fs(lambda: os.replace(tmp, path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class FileLock:
    def __init__(self, path, timeout):
        self.lock_path = path + ".lock"
        self.timeout = timeout
        self.held = False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        deadline = time.monotonic() + self.timeout
        delay = 0.01
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode("ascii"))
                finally:
                    os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                pass
            except PermissionError:
                pass  # Windows: lock file being deleted by another process
            try:
                age = time.time() - os.stat(self.lock_path).st_mtime
                if age > STALE_LOCK_SECONDS:
                    try:
                        os.unlink(self.lock_path)
                    except OSError:
                        pass
                    continue
            except FileNotFoundError:
                continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise CliError(5, "timed out after %gs waiting for lock %s"
                               % (self.timeout, self.lock_path))
            time.sleep(delay)
            delay = min(delay * 1.5, 0.1)

    def __exit__(self, *exc):
        if self.held:
            self.held = False
            try:
                os.unlink(self.lock_path)
            except OSError:
                pass
        return False


def empty_project():
    return {"_meta": {"schema": SCHEMA, "keys": {}}}


def cmd_init(args, path):
    with FileLock(path, args.timeout):
        if os.path.exists(path):
            read_project(path)  # validate only
            print("exists: %s" % path)
        else:
            atomic_write(path, empty_project())
            print("created: %s" % path)
    return 0


def cmd_get(args, path):
    check_key(args.key)
    data = read_project(path)
    entry = data["_meta"]["keys"].get(args.key)
    if args.version:
        print(entry.get("version", 0) if isinstance(entry, dict) else 0)
    else:
        print(json.dumps(data.get(args.key), ensure_ascii=False, indent=2))
    return 0


def load_value(args):
    given = [x for x in (args.file, args.json) if x is not None]
    if len(given) > 1:
        raise CliError(2, "use only one of --file / --json (or stdin)")
    try:
        if args.file is not None:
            with open(args.file, "rb") as f:
                text = f.read().decode("utf-8-sig")
        elif args.json is not None:
            text = args.json
        else:
            text = sys.stdin.buffer.read().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise CliError(2, "cannot read value: %s" % e)
    try:
        return json.loads(text)
    except ValueError as e:
        raise CliError(2, "invalid JSON value: %s" % e)


def cmd_set(args, path):
    check_key(args.key)
    owner = OWNERS[args.key]
    if args.agent != owner:
        raise CliError(4, "owner mismatch: key %r is owned by %r, not %r"
                       % (args.key, owner, args.agent))
    value = load_value(args)
    with FileLock(path, args.timeout):
        data = read_project(path) if os.path.exists(path) else empty_project()
        keys = data["_meta"]["keys"]
        entry = keys.get(args.key)
        current = entry.get("version", 0) if isinstance(entry, dict) else 0
        if args.expect_version is not None and args.expect_version != current:
            raise CliError(3, "version conflict on %r: expected %d, current version is %d"
                           % (args.key, args.expect_version, current))
        data[args.key] = value
        keys[args.key] = {"version": current + 1, "owner": owner, "updated": now_iso()}
        atomic_write(path, data)
        back = read_project(path)  # read back under the lock: report what is really stored
        stored = back["_meta"]["keys"].get(args.key, {}).get("version")
        if back.get(args.key) != value or stored != current + 1:
            raise CliError(2, "read-back mismatch after writing %r to %s" % (args.key, path))
    print("%s version %d (%s)" % (args.key, stored, path))
    return 0


def cmd_keys(args, path):
    data = read_project(path)
    keys = data["_meta"]["keys"]
    if not keys:
        print("(no keys set)")
    for k in sorted(keys):
        e = keys[k] if isinstance(keys[k], dict) else {}
        print("%s\tv%s\t%s\t%s" % (k, e.get("version", "?"), e.get("owner", "?"),
                                   e.get("updated", "?")))
    return 0


def downstream(key):
    seen = set()
    stack = list(DOWNSTREAM[key])
    while stack:
        k = stack.pop()
        if k not in seen:
            seen.add(k)
            stack.extend(DOWNSTREAM[k])
    return [k for k in RUN_ORDER if k in seen]


def cmd_deps(args, path):
    check_key(args.key)
    keys = downstream(args.key)
    if args.json:
        print(json.dumps({"key": args.key, "rerun": [
            {"key": k, "owner": OWNERS[k]} for k in keys]}, ensure_ascii=False, indent=2))
    else:
        for k in keys:
            print(k)
    return 0


def cmd_owner(args, path):
    check_key(args.key)
    print(OWNERS[args.key])
    return 0


# --- check-blur: geometric privacy check (media-specs "Render checks", row blur) ---------------
# Both renderers blur on the source frame before zoom/reframe, so source px + scene ms suffice.
BLUR_MIN_STRENGTH = 8        # px, any region
BLUR_STRENGTH_PER_H = 0.3    # effective strength >= 0.3 x height of the covered sensitive box
PIXELATE_FACTOR = 1.6        # remotion/src/DemoVideo.tsx: pixelate radius = strength * 1.6
EDGE_TOLERANCE_PX = 1        # rounding slack on each side of the sensitive box


def _lerp_box(a, b, k):
    return [a[i] + (b[i] - a[i]) * k for i in range(4)]


def _region_box_at(r, t):
    """Region bbox at scene time t (same interpolation as remotion layout.ts blurBoxAt)."""
    kf = r.get("keyframes") or []
    if not kf:
        return r["bbox"]
    if t <= kf[0]["t"]:
        return kf[0]["bbox"]
    for a, b in zip(kf, kf[1:]):
        if t <= b["t"]:
            return _lerp_box(a["bbox"], b["bbox"], (t - a["t"]) / max(1, b["t"] - a["t"]))
    return kf[-1]["bbox"]


def _rect(box, grow=0.0):
    x, y, w, h = box
    return (x - grow, y - grow, x + w + grow, y + h + grow)


def _subtract(r, c):
    """r minus c, both (x0, y0, x1, y1); returns up to 4 rectangles."""
    x0, y0, x1, y1 = r
    cx0, cy0, cx1, cy1 = c
    if cx0 >= x1 or cx1 <= x0 or cy0 >= y1 or cy1 <= y0:
        return [r]
    out = []
    if cy0 > y0:
        out.append((x0, y0, x1, cy0))
    if cy1 < y1:
        out.append((x0, cy1, x1, y1))
    my0, my1 = max(y0, cy0), min(y1, cy1)
    if cx0 > x0:
        out.append((x0, my0, cx0, my1))
    if cx1 < x1:
        out.append((cx1, my0, x1, my1))
    return out


def _uncovered_area(req, covers):
    left = [req]
    for c in covers:
        left = [p for u in left for p in _subtract(u, c)]
        if not left:
            return 0.0
    return sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in left)


def sensitive_tracks(events):
    """{(scene, label): [(t, bbox|None), ...]} plus scene end times, from #events markers."""
    tracks, ends = {}, {}
    for m in events.get("markers") or []:
        if m.get("type") == "sensitive":
            tracks.setdefault((m["scene"], m.get("label", "")), []).append((m["t"], m.get("bbox")))
        elif m.get("type") == "scene_end":
            ends[m["scene"]] = m["t"]
    for v in tracks.values():
        v.sort(key=lambda x: x[0])
    return tracks, ends


def _frame_times(clip, tl, end_t, fps_out):
    """Scene-ms times of the frames that reach the picture, mirroring remotion/src/DemoVideo.tsx:
    with a #timeline scene, output frames round(start)..round(start)+round(end-start)-1 at fps_out,
    each showing clip ms round(in)/fps + k*speed/fps; without one, every clip frame of the scene."""
    off = clip.get("offset_ms", 0)
    if tl:
        fr = lambda ms: int(math.floor(ms * fps_out / 1000.0 + 0.5))  # JS Math.round, not banker's
        n = max(1, fr(tl["end"] - tl["start"]))
        base = fr(tl["in"]) * 1000.0 / fps_out
        speed = tl.get("speed") or 1
        return [base + k * 1000.0 / fps_out * speed - off for k in range(n)]
    cf = clip.get("fps") or fps_out
    out, k = [], 0
    while True:
        t = k * 1000.0 / cf - off
        if t > end_t:
            return out
        if t >= 0:
            out.append(t)
        k += 1


def check_blur(data):
    events, blur = data.get("events"), data.get("blur")
    if not isinstance(events, dict) or not isinstance(events.get("clips"), dict):
        raise CliError(2, "#events with clips is required (owner capture-operator)")
    if not isinstance(blur, dict):
        raise CliError(2, "#blur is required (owner privacy-blurrer)")
    clips = events["clips"]
    regions = blur.get("regions") or []
    tracks, ends = sensitive_tracks(events)
    # Checked at every frame that reaches the picture (render fps = lowest clip fps, as render.mjs).
    # With #timeline only the selected in..out counts; without it (blur runs in parallel with
    # sync-editor) every clip frame of the scene does.
    fps_out = min([c["fps"] for c in clips.values() if isinstance(c, dict) and c.get("fps")] or [25])
    tl_by_id = {s["id"]: s for s in (data.get("timeline") or {}).get("scenes") or []
                if all(k in s for k in ("id", "in", "start", "end"))}
    invalid, weak, gaps = [], {}, {}
    samples = 0
    for (scene, label), pts in sorted(tracks.items()):
        clip = clips.get(scene)
        if not clip or not clip.get("w") or not clip.get("h"):
            invalid.append({"scene": scene, "label": label, "why": "no clip w/h in #events.clips",
                            "owner": "capture-operator"})
            continue
        fw, fh = clip["w"], clip["h"]
        bad = [(t, b) for t, b in pts if b is not None and not (
            len(b) == 4 and b[2] > 0 and b[3] > 0 and b[0] >= 0 and b[1] >= 0
            and b[0] + b[2] <= fw and b[1] + b[3] <= fh)]
        for t, b in bad:
            invalid.append({"scene": scene, "label": label, "t": t, "bbox": b,
                            "why": "bbox empty or outside the %dx%d frame" % (fw, fh),
                            "owner": "capture-operator"})
        if bad:
            continue
        end_t = ends.get(scene, clip.get("duration_ms", 0) - clip.get("offset_ms", 0))
        mine = [r for r in regions if r.get("scene") == scene]
        frames = _frame_times(clip, tl_by_id.get(scene), end_t, fps_out)
        for i, (t0, b0) in enumerate(pts):
            if b0 is None:
                continue
            nxt = pts[i + 1] if i + 1 < len(pts) else None
            t1 = nxt[0] if nxt else end_t
            b1 = nxt[1] if nxt and nxt[1] is not None else b0  # next bbox = element moved there
            # Markers are samples: between two of them the element is anywhere on the way
            # (and marker timestamps can lag the video), so the whole hull must stay covered.
            box = [min(b0[0], b1[0]), min(b0[1], b1[1])]
            box += [max(b0[0] + b0[2], b1[0] + b1[2]) - box[0], max(b0[1] + b0[3], b1[1] + b1[3]) - box[1]]
            need = max(BLUR_MIN_STRENGTH, BLUR_STRENGTH_PER_H * max(b0[3], b1[3]))
            last = nxt is None or nxt[1] is None
            for fi, t in enumerate(frames):
                if t < t0 or t > t1 or (t == t1 and not last):
                    continue
                req = _rect(box, -EDGE_TOLERANCE_PX)
                req = (max(0, req[0]), max(0, req[1]), min(fw, req[2]), min(fh, req[3]))
                if req[2] <= req[0] or req[3] <= req[1]:
                    continue
                samples += 1
                active = [r for r in mine
                          if r["t_start"] - r.get("margin_ms", 0) <= t <= r["t_end"] + r.get("margin_ms", 0)]
                covers = [_rect(_region_box_at(r, t), r.get("pad", 0)) for r in active]
                left = _uncovered_area(req, covers)
                if left > 0:
                    spans = gaps.setdefault((scene, label), [])
                    if not spans or spans[-1]["_i"] != fi - 1:
                        spans.append({"scene": scene, "label": label, "t_from": round(t), "t_to": round(t),
                                      "frames": 0, "max_uncovered_px": 0, "at": None})
                    g = spans[-1]
                    g["t_to"], g["_i"] = round(t), fi
                    g["frames"] += 1
                    if left > g["max_uncovered_px"]:
                        g["max_uncovered_px"], g["at"] = round(left), [round(v) for v in box]
                for r in active:
                    c = _rect(_region_box_at(r, t), r.get("pad", 0))
                    if _uncovered_area(req, [c]) >= (req[2] - req[0]) * (req[3] - req[1]):
                        continue  # this region does not touch the box
                    eff = r.get("strength", 25) * (PIXELATE_FACTOR if r.get("mode") == "pixelate" else 1)
                    if eff < need:
                        rid = r.get("id", "?")
                        w = weak.setdefault(rid, {"region": rid, "strength": r.get("strength", 25),
                                                  "mode": r.get("mode", "boxblur"), "needed": 0})
                        w["needed"] = max(w["needed"], round(need, 1))
    gap_list = [dict({k: v for k, v in g.items() if k != "_i"}, owner="privacy-blurrer")
                for spans in gaps.values() for g in spans]
    weak_list = [dict(w, owner="privacy-blurrer") for w in weak.values()]
    return {"pass": not (invalid or gap_list or weak_list), "tracks": len(tracks),
            "regions": len(regions), "frames_checked": samples, "fps": fps_out,
            "gaps": gap_list, "invalid": invalid, "weak": weak_list}


def cmd_check_blur(args, path):
    res = check_blur(read_project(path))
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["pass"] else 1


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(2)


def build_parser():
    def add_common(parser, sub):
        d = argparse.SUPPRESS if sub else None
        parser.add_argument("--project", default=d, help="path to project.json")
        parser.add_argument("--slug", default=d,
                            help="use .demo/<slug>/project.json under cwd")
        parser.add_argument("--timeout", type=float, default=argparse.SUPPRESS if sub else 10.0,
                            help="lock wait timeout in seconds (default 10)")

    common = argparse.ArgumentParser(add_help=False)
    add_common(common, True)
    p = Parser(description="Shared project.json access with per-key ownership. "
                           "--project/--slug/--timeout may go before or after the command.")
    add_common(p, False)
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    sub.add_parser("init", parents=[common], help="create project file if missing")
    g = sub.add_parser("get", parents=[common], help="print a key's JSON")
    g.add_argument("key")
    g.add_argument("--version", action="store_true", help="print only the version")
    s = sub.add_parser("set", parents=[common], help="write a key (owner only)")
    s.add_argument("key")
    s.add_argument("--as", dest="agent", required=True, help="calling agent name")
    s.add_argument("--file", help="read JSON value from file")
    s.add_argument("--json", help="JSON value as text")
    s.add_argument("--expect-version", type=int, dest="expect_version",
                   help="fail with exit 3 if stored version differs")
    sub.add_parser("keys", parents=[common], help="list keys with version/owner/updated")
    d = sub.add_parser("deps", parents=[common],
                       help="keys to re-run after <key> changes (transitive, in run order)")
    d.add_argument("key")
    d.add_argument("--json", action="store_true", help="JSON output")
    o = sub.add_parser("owner", parents=[common], help="print the agent that owns <key>")
    o.add_argument("key")
    sub.add_parser("check-blur", parents=[common],
                       help="geometric privacy check at every rendered frame: #blur covers every "
                            "sensitive marker (exit 1 = fail)")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    handlers = {"init": cmd_init, "get": cmd_get, "set": cmd_set, "keys": cmd_keys,
                "deps": cmd_deps, "owner": cmd_owner, "check-blur": cmd_check_blur}
    try:
        path = None if args.cmd in ("deps", "owner") else project_path(args)
        return handlers[args.cmd](args, path)
    except CliError as e:
        sys.stderr.write("error: %s\n" % e.msg)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
