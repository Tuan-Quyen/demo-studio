#!/usr/bin/env python3
"""Safe shared access to .demo/<slug>/project.json (one owner per top-level key).

Usage:
  project.py (--project PATH | --slug SLUG) [--timeout SEC] <command> ...
    init
    get <key> [--version]   --version prints the stored version (the value itself has no
                            version field; also see `keys`, which lists all versions)
    set <key> --as <agent> [--file PATH | --json TEXT | (stdin)] [--expect-version N]
        [--input-file PATH ...]   record a fingerprint (size, mtime_ns, inode) of each input file
                                  (path relative to the project folder) in _meta.keys.<key>.inputs;
                                  sha256 is computed only when that triple changed (cache/hashes.json)
    keys
    deps <key> [--json]   keys to re-run after <key> changes (transitive, run order)
    owner <key>           agent that owns <key>
    migrate [--dry-run]   upgrade a schema 1 project to schema 2 (backup first, see below)
  (deps/owner need no project file)
  --slug walks up from cwd to the nearest `.demo/<slug>`; inside `.demo/` with none above it, or
  with a path containing `.demo/.demo`, it refuses (exit 2). `set` prints "<key> version N (<path>)"
  after reading the file back: quote that line in the handoff.

Exit codes:
  0  ok
  2  usage / validation error (bad JSON, unknown key, missing/corrupt file)
  3  version conflict (--expect-version differs from the stored version)
  4  owner mismatch (--as agent does not own the key; `set checks` always, see below)
  5  lock timeout

Schema 2 (docs/redesign §4.5): `_meta.keys.<k>.inputs` = versions of the keys it was built from plus
file fingerprints. `checks` is written ONLY by write_checks() (imported by checks.py / blur.py
verify); `project.py set checks` is always refused (exit 4). `migrate` (schema 1 -> 2): backs up to
project.json.schema1.bak, sets inputs {} on every key, marks every existing clip
events.clips.*.masked=false, keeps every #blur region unmerged (source "legacy", the old source text
moves to "label"), reports data_mode real-redacted. Schema 1 files stay readable and writable.

Writes take an exclusive lock file "<project>.lock" (O_CREAT|O_EXCL), re-read the
file under the lock, change only the target key and its _meta entry, and replace
the file atomically (temp file in the same directory + os.replace).
"""
import argparse
import hashlib
import json
import os
import shutil
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

# direct inputs of each key (reverse of DOWNSTREAM); recorded as versions in _meta.keys.<k>.inputs
UPSTREAM = {}
for _k, _ds in DOWNSTREAM.items():
    for _d in _ds:
        UPSTREAM.setdefault(_d, []).append(_k)

STALE_LOCK_SECONDS = 30.0
SCHEMA = 2          # schema written for new projects
LEGACY_SCHEMA = 1   # a file without _meta.schema is a schema 1 file
CHECKS_WRITERS = ("checks.py", "blur.py")  # the only callers of write_checks()


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
    meta.setdefault("schema", LEGACY_SCHEMA)
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


def file_fingerprint(project_dir, rel):
    """(size, mtime_ns, inode) of a file under the project folder. sha256 is computed (and cached in
    cache/hashes.json) only when that triple differs from the cached one: a plain `set` never
    re-hashes hundreds of MB [RT-17]."""
    full = os.path.join(project_dir, rel)
    try:
        st = os.stat(full)
    except OSError as e:
        raise CliError(2, "cannot fingerprint input %r: %s" % (rel, e))
    triple = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "ino": st.st_ino}
    cache_path = os.path.join(project_dir, "cache", "hashes.json")
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    old = cache.get(rel)
    if not (isinstance(old, dict) and all(old.get(k) == v for k, v in triple.items())):
        h = hashlib.sha256()
        with open(full, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        cache[rel] = dict(triple, sha256=h.hexdigest())
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        atomic_write(cache_path, cache)
    return triple


def build_inputs(data, key, project_dir, input_files):
    """Versions of the keys `key` is built from (those that exist) + fingerprints of input files."""
    keys = data["_meta"]["keys"]
    inputs = {}
    for up in UPSTREAM.get(key, []):
        e = keys.get(up)
        if isinstance(e, dict) and "version" in e:
            inputs[up] = e["version"]
    for rel in input_files:
        inputs["file:" + rel.replace(os.sep, "/")] = file_fingerprint(project_dir, rel)
    return inputs


def deep_merge(base, over, depth=2):
    """Merge dicts `depth` levels deep; below that the new value replaces the old one."""
    if depth > 0 and isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = deep_merge(base[k], v, depth - 1) if k in base else v
        return out
    return over


def store_key(path, key, owner, value, timeout, expect_version=None, input_files=(), merge=False):
    """Lock, re-read, replace/merge one key and its _meta entry, write atomically, read back.
    Returns the stored version."""
    with FileLock(path, timeout):
        data = read_project(path) if os.path.exists(path) else empty_project()
        keys = data["_meta"]["keys"]
        entry = keys.get(key)
        current = entry.get("version", 0) if isinstance(entry, dict) else 0
        if expect_version is not None and expect_version != current:
            raise CliError(3, "version conflict on %r: expected %d, current version is %d"
                           % (key, expect_version, current))
        if merge and isinstance(data.get(key), dict):
            value = deep_merge(data[key], value)
        inputs = build_inputs(data, key, os.path.dirname(path), input_files)
        data[key] = value
        keys[key] = {"version": current + 1, "owner": owner, "updated": now_iso(), "inputs": inputs}
        atomic_write(path, data)
        back = read_project(path)  # read back under the lock: report what is really stored
        stored = back["_meta"]["keys"].get(key, {}).get("version")
        if back.get(key) != value or stored != current + 1:
            raise CliError(2, "read-back mismatch after writing %r to %s" % (key, path))
    return stored


def write_checks(path, value, writer, timeout=10.0, merge=False):
    """The ONLY way to write `checks` (RT-11). `writer` must be checks.py or blur.py (blur.py verify
    passes merge=True with {"blur": {<aspect>: {...}}}: merged two levels deep, so a new
    verdict for one aspect replaces that aspect's entry and keeps the others). `project.py set checks` is always refused."""
    if writer not in CHECKS_WRITERS:
        raise CliError(4, "owner mismatch: #checks is written only by %s, not %r"
                       % (" / ".join(CHECKS_WRITERS), writer))
    return store_key(path, "checks", OWNERS["checks"], value, timeout, merge=merge)


def cmd_set(args, path):
    check_key(args.key)
    if args.key == "checks":
        raise CliError(4, "#checks cannot be written with `set`: it is written only by checks.py / "
                          "blur.py verify through project.write_checks()")
    owner = OWNERS[args.key]
    if args.agent != owner:
        raise CliError(4, "owner mismatch: key %r is owned by %r, not %r"
                       % (args.key, owner, args.agent))
    value = load_value(args)
    stored = store_key(path, args.key, owner, value, args.timeout, args.expect_version,
                       args.input_file or ())
    print("%s version %d (%s)" % (args.key, stored, path))
    return 0


def migrate_data(data):
    """Pure schema 1 -> 2 upgrade of a parsed project (see module doc). Returns a change summary."""
    summary = {"keys": 0, "clips_masked_false": 0, "blur_regions_kept": 0,
               "data_mode": "real-redacted"}
    for e in data["_meta"]["keys"].values():
        if isinstance(e, dict):
            e["inputs"] = {}  # unknown fingerprint = stale on the next run of its downstream keys
            summary["keys"] += 1
    clips = (data.get("events") or {}).get("clips") if isinstance(data.get("events"), dict) else None
    if isinstance(clips, dict):
        for clip in clips.values():
            if isinstance(clip, dict):
                clip["masked"] = False  # recorded before v0.3: no capture-time mask
                summary["clips_masked_false"] += 1
    blur = data.get("blur")
    if isinstance(blur, dict) and isinstance(blur.get("regions"), list):
        for r in blur["regions"]:  # keep every region, unmerged
            if isinstance(r, dict):
                if r.get("source") != "legacy":
                    if r.get("source") is not None:
                        r.setdefault("label", r["source"])
                    r["source"] = "legacy"
                summary["blur_regions_kept"] += 1
    data["_meta"]["schema"] = SCHEMA
    return summary


def cmd_migrate(args, path):
    with FileLock(path, args.timeout):
        data = read_project(path)
        if data["_meta"].get("schema", LEGACY_SCHEMA) >= SCHEMA:
            print(json.dumps({"status": "ok", "migrated": False, "schema": data["_meta"]["schema"]}))
            return 0
        summary = migrate_data(data)
        res = dict(status="ok", migrated=not args.dry_run, dry_run=bool(args.dry_run), schema=SCHEMA,
                   **summary)
        if not args.dry_run:
            bak = path + ".schema1.bak"
            if not os.path.exists(bak):
                shutil.copyfile(path, bak)
            atomic_write(path, data)
            res["backup"] = bak
    print(json.dumps(res))
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
    s.add_argument("--input-file", action="append", dest="input_file", metavar="PATH",
                   help="input file (relative to the project folder) to fingerprint; repeatable")
    sub.add_parser("keys", parents=[common], help="list keys with version/owner/updated")
    d = sub.add_parser("deps", parents=[common],
                       help="keys to re-run after <key> changes (transitive, in run order)")
    d.add_argument("key")
    d.add_argument("--json", action="store_true", help="JSON output")
    o = sub.add_parser("owner", parents=[common], help="print the agent that owns <key>")
    o.add_argument("key")
    m = sub.add_parser("migrate", parents=[common], help="upgrade a schema 1 project to schema 2")
    m.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="print what would change, write nothing")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    handlers = {"init": cmd_init, "get": cmd_get, "set": cmd_set, "keys": cmd_keys,
                "deps": cmd_deps, "owner": cmd_owner, "migrate": cmd_migrate}
    try:
        path = None if args.cmd in ("deps", "owner") else project_path(args)
        return handlers[args.cmd](args, path)
    except CliError as e:
        sys.stderr.write("error: %s\n" % e.msg)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
