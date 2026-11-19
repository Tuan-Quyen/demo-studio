#!/usr/bin/env python3
"""Read, validate and diff .demo/<slug>/demo.yaml (the user-editable video properties).

Usage:
  config.py (--project PATH | --slug SLUG) <command> ...
    init                 copy templates/demo.yaml if the file is missing
    validate             schema check: types, enums, ranges, unknown keys
    get [<dotted.path>]  value as JSON, defaults applied (no path = everything)
    diff [--json]        compare with the last applied snapshot; print changed fields
                         and the project.json keys + agents to re-run
    apply                validate, then write the snapshot (.demo.applied.json)
    apply-lexicon [--text T | --file P | stdin] [--json]
                         print TTS input with voice.lexicon applied (whole-word, case-sensitive,
                         longest first, single pass); --json = {text, applied:[{term,spoken,count}]}
  --project PATH is the demo.yaml file; --slug uses .demo/<slug>/demo.yaml under cwd.
  The snapshot lives next to demo.yaml as .demo.applied.json.

Exit codes:
  0  ok
  2  usage / validation / parse error (message names the line when known)

diff mapping (field -> pre agents; first project.json keys; downstream follows project.py deps):
  platform                 pre app-scout, storyboarder, scriptwriter (G2); ALL keys (full re-record)
  length_s                 pre storyboarder (G2); timeline + downstream (motion, captions, mix, checks, delivery);
                           NOT voice/events; needs_user. scriptwriter only if the new word budget is
                           below the current narration word count; voice only if narration changes
  formats                  motion, captions (+ checks, delivery)
  language                 source language (null = voice.language). pre scriptwriter, localizer (G2);
                           voice + downstream; needs_user. No-op if the effective source language
                           (language or voice.language) is unchanged
  voice.language           pre localizer if language is set and differs from the new voice.language,
                           else scriptwriter (G2); voice + downstream; needs_user
  voice.lexicon.<term>     voice + downstream; no pre, no G2; diff lists terms added/changed/removed
  voice.engine / .name     voice + downstream (the only non-language fields that re-run voice)
  motion.*                 motion (+ checks, delivery)
  music.*                  mix (+ checks, delivery)
  captions.burn_in         checks only (+ delivery): burn-in happens in the render
  captions.*               captions (+ checks, delivery)
  targets.lufs/true_peak   mix (+ checks, delivery)
  targets.max_drift_ms     timeline (+ motion, captions, mix, checks, delivery)
  targets.caption_offset_ms captions (+ checks, delivery)
  privacy.*                blur (+ checks, delivery)
  install.*                nothing
  Only platform re-runs events; only voice.* (and platform) re-run voice.

Parser: one built-in strict parser (stdlib only, so validation never depends on what is installed) for a documented subset:
block maps (spaces only; keys may be "quoted"), flow maps {"term": "text"} (quoted keys only),
block lists ("- item") and flow lists ([a, b]) of scalars,
scalars str/int/float/bool/null, "#" comments, "double" and 'single' quoted strings.
Anything else (tabs, anchors, tags, multi-line strings, unquoted-key flow maps, maps inside lists,
multi-line flow lists, duplicate keys, documents) is an error with the line number.
"""
import argparse
import copy
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402  (dependency graph: OWNERS, RUN_ORDER, downstream)

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(PLUGIN_ROOT, "templates", "demo.yaml")
SNAPSHOT_NAME = ".demo.applied.json"
SNAPSHOT_SCHEMA = 1


class CliError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


# --------------------------------------------------------------------------- schema
def leaf(kind, default, **kw):
    d = {"kind": kind, "default": default}
    d.update(kw)
    return d


FORMATS = ["16:9", "9:16", "1:1"]
LANG_RE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$")
FEATURE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Defaults mirror skills/media-specs, skills/motion-fx and run-kits.
SCHEMA = {
    "platform": leaf("enum", None, enum=["web", "desktop", "android", "ios"], nullable=True),
    "length_s": leaf("int", None, min=5, max=600, nullable=True),
    "language": leaf("str", None, nullable=True, pattern=LANG_RE),
    "formats": leaf("list", ["16:9"], enum=FORMATS, min_items=1, unique=True),
    "voice": {
        "engine": leaf("enum", "edge", enum=["edge", "kokoro", "elevenlabs", "recorded"]),
        "name": leaf("str", None, nullable=True),
        "rate": leaf("str", "+0%", pattern=re.compile(r"^[+-]\d{1,2}%$"), range=(-30, 30),
                     hint="+0%, -10%, +15%"),
        "pitch": leaf("str", "+0Hz", pattern=re.compile(r"^[+-]\d{1,3}Hz$"), range=(-50, 50),
                      hint="+0Hz, -5Hz, +20Hz"),
        "language": leaf("str", "en", pattern=LANG_RE),
        "lexicon": leaf("map", {}, max_len=60),
    },
    "motion": {
        "level": leaf("enum", None, enum=["none", "basic", "cinematic"], nullable=True),
    },
    "music": {
        "style": leaf("str", None, nullable=True),
        "duck_db": leaf("num", -20, min=-40, max=0),
    },
    "captions": {
        "burn_in": leaf("bool", False),
        "max_chars": leaf("int", 42, min=10, max=80),
    },
    "targets": {
        "lufs": leaf("num", -14, min=-30, max=-5),
        "true_peak": leaf("num", -1, min=-6, max=0),
        "max_drift_ms": leaf("int", 80, min=0, max=1000),
        "caption_offset_ms": leaf("int", 200, min=0, max=2000),
    },
    "privacy": {
        "blur": leaf("list", [], min_items=0),
        "real_data": leaf("bool", False),
    },
    "install": {
        "approved": leaf("list", [], pattern=FEATURE_RE, unique=True),
        "declined": leaf("list", [], pattern=FEATURE_RE, unique=True),
    },
}


def is_leaf(node):
    return "kind" in node and isinstance(node.get("kind"), str)


def defaults(schema=SCHEMA):
    out = {}
    for k, v in schema.items():
        out[k] = copy.deepcopy(v["default"]) if is_leaf(v) else defaults(v)
    return out


def type_name(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    return type(v).__name__


def check_leaf(path, spec, v, errs):
    kind = spec["kind"]
    if v is None:
        if not spec.get("nullable"):
            errs.append("%s: must not be null" % path)
        return
    if kind == "enum":
        if not isinstance(v, str) or v not in spec["enum"]:
            errs.append("%s: must be one of %s (got %r)" % (path, " | ".join(spec["enum"]), v))
    elif kind == "str":
        if not isinstance(v, str):
            errs.append("%s: must be text (got %s %r; quote it)" % (path, type_name(v), v))
        elif not v.strip():
            errs.append("%s: must not be empty (use null)" % path)
        elif "pattern" in spec and not spec["pattern"].match(v):
            errs.append("%s: %r is not a valid value (e.g. %s)" % (path, v, spec.get("hint", "en, vi, pt-BR")))
        elif "range" in spec and not spec["range"][0] <= int(re.sub(r"[^0-9+-]", "", v)) <= spec["range"][1]:
            errs.append("%s: must be between %+d and %+d (got %s)"
                        % (path, spec["range"][0], spec["range"][1], v))
    elif kind == "bool":
        if not isinstance(v, bool):
            errs.append("%s: must be true or false (got %s %r)" % (path, type_name(v), v))
    elif kind in ("int", "num"):
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        if ok and kind == "int" and isinstance(v, float):
            ok = False
        if not ok:
            errs.append("%s: must be %s (got %s %r)"
                        % (path, "a whole number" if kind == "int" else "a number", type_name(v), v))
        else:
            if "min" in spec and v < spec["min"] or "max" in spec and v > spec["max"]:
                errs.append("%s: must be between %s and %s (got %s)"
                            % (path, spec["min"], spec["max"], v))
    elif kind == "map":
        if not isinstance(v, dict):
            errs.append("%s: must be a map of written term -> spoken spelling (got %s %r)"
                        % (path, type_name(v), v))
            return
        limit = spec.get("max_len", 60)
        for term, spoken in v.items():
            ip = "%s[%r]" % (path, term)
            if not isinstance(term, str) or not term.strip():
                errs.append("%s: term must be non-empty text" % path)
            elif len(term) > limit:
                errs.append("%s: term is longer than %d chars" % (ip, limit))
            if not isinstance(spoken, str):
                errs.append("%s: spoken spelling must be text (got %s %r; quote it)"
                            % (ip, type_name(spoken), spoken))
            elif not spoken.strip():
                errs.append("%s: spoken spelling must not be empty" % ip)
            elif len(spoken) > limit:
                errs.append("%s: spoken spelling is longer than %d chars" % (ip, limit))
    elif kind == "list":
        if not isinstance(v, list):
            errs.append("%s: must be a list (got %s %r)" % (path, type_name(v), v))
            return
        if len(v) < spec.get("min_items", 0):
            errs.append("%s: needs at least %d item(s)" % (path, spec["min_items"]))
        seen = set()
        for i, item in enumerate(v):
            ip = "%s[%d]" % (path, i)
            if not isinstance(item, str) or not item.strip():
                errs.append("%s: must be non-empty text (got %s %r; quote it)"
                            % (ip, type_name(item), item))
                continue
            if "enum" in spec and item not in spec["enum"]:
                errs.append("%s: must be one of %s (got %r)" % (ip, " | ".join(spec["enum"]), item))
            if "pattern" in spec and not spec["pattern"].match(item):
                errs.append("%s: %r is not a valid feature name" % (ip, item))
            if spec.get("unique") and item in seen:
                errs.append("%s: duplicate %r" % (ip, item))
            seen.add(item)


def validate_tree(raw, schema=SCHEMA, prefix=""):
    """Return error strings for raw (a parsed dict) against schema."""
    errs = []
    if not isinstance(raw, dict):
        return ["%s: must be a map of fields" % (prefix.rstrip(".") or "root")]
    for k in raw:
        if k not in schema:
            errs.append("%s%s: unknown key (valid: %s)" % (prefix, k, ", ".join(schema)))
    for k, spec in schema.items():
        if k not in raw:
            continue
        v = raw[k]
        path = prefix + k
        if is_leaf(spec):
            check_leaf(path, spec, v, errs)
        elif v is None:
            continue  # "voice:" with nothing below = all defaults
        else:
            errs.extend(validate_tree(v, spec, path + "."))
    return errs


def cross_check(cfg):
    errs = []
    both = set(cfg["install"]["approved"]) & set(cfg["install"]["declined"])
    if both:
        errs.append("install: %s in both approved and declined" % ", ".join(sorted(both)))
    return errs


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = merge(out[k], v)
        elif isinstance(out.get(k), dict) and v is None:
            continue
        else:
            out[k] = copy.deepcopy(v)
    return out


# ------------------------------------------------------------------ built-in parser
class ParseError(Exception):
    def __init__(self, line, msg):
        super().__init__("line %d: %s" % (line, msg))
        self.line = line
        self.msg = msg


KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)[ ]*:(?:[ ]+(.*))?$")
INT_RE = re.compile(r"^[+-]?[0-9]+$")
FLOAT_RE = re.compile(r"^[+-]?([0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)([eE][+-]?[0-9]+)?$")
NULLS = {"", "~", "null", "Null", "NULL"}
TRUES = {"true", "True", "TRUE"}
FALSES = {"false", "False", "FALSE"}
ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/"}


def strip_comment(s, lineno):
    """Remove a trailing # comment (outside quotes); reject unterminated quotes."""
    quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote == '"':
            if c == "\\":
                i += 1
            elif c == '"':
                quote = None
        elif quote == "'":
            if c == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    i += 1
                else:
                    quote = None
        else:
            prev = s[i - 1] if i else " "
            if c in "\"'" and prev in " \t[{,:":
                quote = c
            elif c == "#" and prev in " \t":
                return s[:i].rstrip()
        i += 1
    if quote:
        raise ParseError(lineno, "unterminated %s-quoted string" % ("double" if quote == '"' else "single"))
    return s.rstrip()


def parse_scalar(tok, lineno):
    tok = tok.strip()
    if tok[:1] == '"':
        if len(tok) < 2 or tok[-1] != '"':
            raise ParseError(lineno, "text after a closing quote is not supported: %s" % tok)
        out, i, body = [], 0, tok[1:-1]
        while i < len(body):
            c = body[i]
            if c == "\\":
                i += 1
                if i >= len(body) or body[i] not in ESCAPES:
                    raise ParseError(lineno, "unsupported escape in double-quoted string")
                out.append(ESCAPES[body[i]])
            elif c == '"':
                raise ParseError(lineno, 'unescaped " inside double-quoted string')
            else:
                out.append(c)
            i += 1
        return "".join(out)
    if tok[:1] == "'":
        if len(tok) < 2 or tok[-1] != "'":
            raise ParseError(lineno, "text after a closing quote is not supported: %s" % tok)
        body = tok[1:-1]
        if re.search(r"(?<!')'(?!')", body.replace("''", "")):
            raise ParseError(lineno, "stray ' inside single-quoted string (write '')")
        return body.replace("''", "'")
    if tok in NULLS:
        return None
    if tok in TRUES:
        return True
    if tok in FALSES:
        return False
    if tok[0] in "&*!|>@`%{}[]":
        raise ParseError(lineno, "unsupported YAML syntax %r (anchors, tags, multi-line strings, "
                                 "flow maps are not allowed; quote the text)" % tok[0])
    if ": " in tok or tok.endswith(":"):
        raise ParseError(lineno, "unexpected ':' in %r (a map inside a list or value is not "
                                 "supported; quote the text)" % tok)
    if INT_RE.match(tok):
        return int(tok)
    if FLOAT_RE.match(tok):
        return float(tok)
    return tok


def split_flow(body, lineno, mapmode=False):
    items, cur, quote, i = [], [], None, 0
    while i < len(body):
        c = body[i]
        if quote:
            cur.append(c)
            if quote == '"' and c == "\\" and i + 1 < len(body):
                i += 1
                cur.append(body[i])
            elif c == quote:
                if quote == "'" and i + 1 < len(body) and body[i + 1] == "'":
                    i += 1
                    cur.append("'")
                else:
                    quote = None
        elif c in "\"'" and (not "".join(cur).strip()
                              or (mapmode and "".join(cur).rstrip().endswith(":"))):
            quote = c
            cur.append(c)
        elif c in "[{":
            raise ParseError(lineno, "nested flow collections are not supported")
        elif c == ",":
            items.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    items.append("".join(cur))
    return items


def parse_flow_list(tok, lineno):
    if not tok.endswith("]"):
        raise ParseError(lineno, "flow list must open and close on one line")
    body = tok[1:-1]
    if not body.strip():
        return []
    items = split_flow(body, lineno)
    out = []
    for it in items:
        if not it.strip():
            raise ParseError(lineno, "empty item in flow list")
        out.append(parse_scalar(it, lineno))
    return out


def split_quoted_key(text, lineno):
    """Parse '"key": rest' / "'key': rest" -> (key, rest or None); None if text is not one."""
    q = text[:1]
    if q not in ("'", '"'):
        return None
    i = 1
    while i < len(text):
        c = text[i]
        if q == '"' and c == "\\":
            i += 2
            continue
        if c == q:
            if q == "'" and text[i + 1:i + 2] == "'":
                i += 2
                continue
            break
        i += 1
    else:
        raise ParseError(lineno, "unterminated quoted key")
    m = re.match(r"^[ ]*:(?:[ ]+(.*))?$", text[i + 1:])
    if not m:
        return None
    return parse_scalar(text[:i + 1], lineno), m.group(1)


def parse_flow_map(tok, lineno):
    if not tok.endswith("}"):
        raise ParseError(lineno, "flow map must open and close on one line")
    body = tok[1:-1]
    out = {}
    if not body.strip():
        return out
    for it in split_flow(body, lineno, mapmode=True):
        it = it.strip()
        kv = split_quoted_key(it, lineno) if it else None
        if not kv or not kv[1] or not kv[1].strip():
            raise ParseError(lineno, 'flow maps need quoted keys and values: {"term": "spoken"}')
        key, rest = kv
        if key in out:
            raise ParseError(lineno, "duplicate key %r" % key)
        if rest.lstrip()[:1] in ("[", "{"):
            raise ParseError(lineno, "nested flow collections are not supported")
        out[key] = parse_scalar(rest, lineno)
    return out


def parse_value(rest, lineno):
    if rest[:1] == "[":
        return parse_flow_list(rest, lineno)
    if rest[:1] == "{":
        return parse_flow_map(rest, lineno)
    return parse_scalar(rest, lineno)


def parse_builtin(text):
    raw_lines = text.lstrip("﻿").splitlines()
    lines = []  # (lineno, indent, content)
    for n, raw in enumerate(raw_lines, 1):
        if raw.strip() == "---" or raw.strip() == "...":
            raise ParseError(n, "document markers are not supported")
        body = raw.rstrip()
        stripped = body.lstrip(" ")
        if "\t" in body[:len(body) - len(stripped)] or body.startswith("\t"):
            raise ParseError(n, "tabs are not allowed for indentation; use spaces")
        content = strip_comment(stripped, n)
        if not content:
            continue
        lines.append((n, len(body) - len(stripped), content))
    if not lines:
        return {}
    if lines[0][1] != 0:
        raise ParseError(lines[0][0], "top level must start at column 0")
    pos = [0]

    def parse_list(indent):
        out = []
        while pos[0] < len(lines):
            n, ind, c = lines[pos[0]]
            if ind != indent or not (c == "-" or c.startswith("- ")):
                break
            item = c[1:].strip()
            out.append(parse_value(item, n) if item[:1] == "[" else parse_scalar(item, n)
                       if item else None)
            pos[0] += 1
        return out

    def parse_map(indent):
        out = {}
        while pos[0] < len(lines):
            n, ind, c = lines[pos[0]]
            if ind < indent:
                break
            if ind > indent:
                raise ParseError(n, "unexpected indentation")
            if c == "-" or c.startswith("- "):
                raise ParseError(n, "list item without a key above it")
            qk = split_quoted_key(c, n)
            if qk:
                key, rest = qk
            else:
                m = KEY_RE.match(c)
                if not m:
                    raise ParseError(n, "expected 'key: value', got %r" % c)
                key, rest = m.group(1), m.group(2)
            if key in out:
                raise ParseError(n, "duplicate key %r" % key)
            pos[0] += 1
            if rest is not None and rest.strip():
                out[key] = parse_value(rest.strip(), n)
                continue
            nxt = lines[pos[0]] if pos[0] < len(lines) else None
            if nxt and nxt[1] > indent:
                if nxt[2] == "-" or nxt[2].startswith("- "):
                    out[key] = parse_list(nxt[1])
                else:
                    out[key] = parse_map(nxt[1])
            elif nxt and nxt[1] == indent and (nxt[2] == "-" or nxt[2].startswith("- ")):
                out[key] = parse_list(indent)
            else:
                out[key] = None
        return out

    result = parse_map(0)
    if pos[0] < len(lines):
        n, _, c = lines[pos[0]]
        raise ParseError(n, "unexpected content %r" % c)
    return result


def load_text(text):
    try:
        return parse_builtin(text)
    except ParseError as e:
        raise CliError(2, "invalid YAML: %s" % e)


# ------------------------------------------------------------------------ file I/O
def config_path(args):
    if args.project:
        return os.path.abspath(args.project)
    if args.slug:
        return os.path.abspath(os.path.join(".demo", args.slug, "demo.yaml"))
    raise CliError(2, "one of --project or --slug is required")


def snapshot_path(path):
    return os.path.join(os.path.dirname(path), SNAPSHOT_NAME)


def load_config(path):
    """Parse + validate demo.yaml; return the effective config (defaults applied)."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except FileNotFoundError:
        raise CliError(2, "config file not found: %s (run init)" % path)
    except (OSError, UnicodeDecodeError) as e:
        raise CliError(2, "cannot read %s: %s" % (path, e))
    raw = load_text(text)
    errs = validate_tree(raw)
    if not errs:
        cfg = merge(defaults(), raw)
        errs = cross_check(cfg)
    if errs:
        raise CliError(2, "%s is invalid:\n  - %s" % (path, "\n  - ".join(errs)))
    return cfg


def atomic_write_json(path, data):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".applied-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        project.retry_fs(lambda: os.replace(tmp, path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_snapshot(path):
    sp = snapshot_path(path)
    if not os.path.exists(sp):
        return None
    try:
        with open(sp, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = data["config"]
        if not isinstance(cfg, dict):
            raise ValueError("config is not an object")
        return cfg
    except (OSError, ValueError, KeyError) as e:
        raise CliError(2, "snapshot %s is unreadable (%s); delete it to start over" % (sp, e))


# --------------------------------------------------------------------------- diff
# field (exact path or "section.*") -> what it invalidates.
#   keys:  first affected project.json keys (downstream expanded via project.downstream)
#   pre:   agents that run before the keys (outside project.json), with the gate they reopen
#   all:   whole re-record (every key)
FIELD_MAP = [
    ("platform", {"pre": ["app-scout", "storyboarder", "scriptwriter"], "gates": ["G2"], "all": True,
                  "note": "platform changed: whole re-record from app-scout"}),
    ("length_s", {"pre": ["storyboarder"], "gates": ["G2"], "keys": ["timeline"],
                  "needs_user": True,
                  "note": "length changed: storyboarder re-plans scene timing (reopens G2); "
                          "scriptwriter re-runs only if the new word budget is below the current "
                          "narration word count; voice re-runs only if narration changes"}),
    ("formats", {"keys": ["motion", "captions"]}),
    ("language", {"dynamic": "localization"}),
    ("voice.language", {"dynamic": "localization"}),
    ("voice.lexicon.*", {"keys": ["voice"],
                         "note": "lexicon changed: voice re-synthesised with the new spellings "
                                 "(narration text unchanged, no G2)"}),
    ("voice.*", {"keys": ["voice"]}),
    ("motion.*", {"keys": ["motion"]}),
    ("music.*", {"keys": ["mix"]}),
    ("captions.burn_in", {"keys": ["checks"],
                          "note": "burn-in only changes the render, captions are not rewritten"}),
    ("captions.*", {"keys": ["captions"]}),
    ("targets.lufs", {"keys": ["mix"]}),
    ("targets.true_peak", {"keys": ["mix"]}),
    ("targets.max_drift_ms", {"keys": ["timeline"]}),
    ("targets.caption_offset_ms", {"keys": ["captions"]}),
    ("privacy.*", {"keys": ["blur"]}),
    ("install.*", {"note": "install choices only: nothing to re-run"}),
]


def lookup_rule(path):
    for pat, rule in FIELD_MAP:
        if pat == path or (pat.endswith(".*") and path.startswith(pat[:-1])):
            return rule
    raise CliError(2, "internal: no diff rule for %s" % path)  # guarded by a test


def localization_pre(path, old, new):
    """Pre agents for a language / voice.language change, or None when nothing is invalidated."""
    vo, vn = (old.get("voice") or {}).get("language"), (new.get("voice") or {}).get("language")
    lo, ln = old.get("language"), new.get("language")
    if path == "language":
        if (lo or vo) == (ln or vn):
            return None  # same effective source language
        return ["scriptwriter", "localizer"]
    return ["localizer"] if ln and ln != vn else ["scriptwriter"]


def flatten(cfg, prefix=""):
    out = {}
    for k, v in cfg.items():
        p = prefix + k
        if isinstance(v, dict):
            out.update(flatten(v, p + "."))
        else:
            out[p] = v
    return out


def compute_diff(old, new):
    """old: snapshot config or None; new: effective config. Returns a result dict."""
    res = {"baseline": old is not None, "changed": [], "pre": [], "gates": [],
           "rerun": [], "needs_user": False, "notes": []}
    if old is None:
        return res
    fo, fn = flatten(old), flatten(new)
    keys, pre, gates = set(), [], []
    for path in sorted(set(fo) | set(fn)):
        a, b = fo.get(path), fn.get(path)
        if a == b:
            continue
        res["changed"].append({"path": path, "old": a, "new": b})
        rule = lookup_rule(path)
        if rule.get("dynamic") == "localization":
            lpre = localization_pre(path, old, new)
            src, tgt = new.get("language") or new["voice"]["language"], new["voice"]["language"]
            res["localization"] = {"source": src, "target": tgt, "needed": src != tgt}
            if lpre is None:
                note = "language set to its effective value: nothing to re-run"
                if note not in res["notes"]:
                    res["notes"].append(note)
                continue
            rule = {"pre": lpre, "gates": ["G2"], "keys": ["voice"], "needs_user": True}
        if rule.get("all"):
            keys.update(project.RUN_ORDER)
        for k in rule.get("keys", []):
            keys.add(k)
            keys.update(project.downstream(k))
        for a_ in rule.get("pre", []):
            if a_ not in pre:
                pre.append(a_)
        for g in rule.get("gates", []):
            if g not in gates:
                gates.append(g)
        if rule.get("needs_user"):
            res["needs_user"] = True
        if rule.get("note") and rule["note"] not in res["notes"]:
            res["notes"].append(rule["note"])
    lo = (old.get("voice") or {}).get("lexicon") or {}
    ln = (new.get("voice") or {}).get("lexicon") or {}
    lex = {"added": {t: ln[t] for t in ln if t not in lo},
           "changed": {t: {"old": lo[t], "new": ln[t]} for t in ln if t in lo and lo[t] != ln[t]},
           "removed": {t: lo[t] for t in lo if t not in ln}}
    if any(lex.values()):
        res["lexicon"] = lex
    loc = res.get("localization")
    if loc and any(c["path"] in ("language", "voice.language") for c in res["changed"]) and (
            "scriptwriter" in pre or "localizer" in pre):
        res["notes"].append(
            "localization: narration is written in %s, voice speaks %s: localizer translates "
            "narration, captions and on-screen text" % (loc["source"], loc["target"])
            if loc["needed"] else
            "localization: none needed (source language = voice language %s)" % loc["target"])
    order = ["app-scout", "storyboarder", "scriptwriter", "localizer"]
    res["pre"] = [a for a in order if a in pre]
    res["gates"] = sorted(gates)
    res["rerun"] = [{"key": k, "owner": project.OWNERS[k]} for k in project.RUN_ORDER if k in keys]
    return res


# ---------------------------------------------------------------------- lexicon
WORD_CH = r"[\ẁ-ͯ]"  # letters/digits/_ plus combining marks (decomposed Vietnamese)


def apply_lexicon(text, lexicon):
    """Replace written terms by their spoken spelling; return (text, [{term, spoken, count}]).

    Whole-word (Unicode word boundaries), case-sensitive, longest match first, non-overlapping,
    one pass over the original text (a replacement is never substituted again). A term only needs
    a boundary on a side where it starts/ends with a word character (so "C++" or "#1" still hit).
    """
    if not lexicon:
        return text, []
    alts = []
    for term in sorted(lexicon, key=lambda t: (-len(t), t)):
        pre = "(?<!%s)" % WORD_CH if re.match(WORD_CH, term[0]) else ""
        post = "(?!%s)" % WORD_CH if re.match(WORD_CH, term[-1]) else ""
        alts.append(pre + re.escape(term) + post)
    counts = {}

    def sub(m):
        counts[m.group(0)] = counts.get(m.group(0), 0) + 1
        return lexicon[m.group(0)]

    out = re.sub("|".join(alts), sub, text)
    applied = [{"term": t, "spoken": lexicon[t], "count": counts[t]}
               for t in sorted(counts, key=lambda t: (-len(t), t))]
    return out, applied


def cmd_apply_lexicon(args, path):
    cfg = load_config(path)
    if args.text is not None:
        text = args.text
    elif args.file:
        try:
            with open(args.file, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise CliError(2, "cannot read %s: %s" % (args.file, e))
    else:
        if sys.stdin is None or sys.stdin.isatty():
            raise CliError(2, "apply-lexicon needs --text, --file or text on stdin")
        try:
            sys.stdin.reconfigure(encoding="utf-8")
        except Exception:
            pass
        text = sys.stdin.read()
    out, applied = apply_lexicon(text, cfg["voice"]["lexicon"])
    if args.json:
        print(json.dumps({"text": out, "applied": applied}, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(out)
    return 0


# ------------------------------------------------------------------------ commands
def cmd_init(args, path):
    if os.path.exists(path):
        load_config(path)
        print("exists: %s" % path)
        return 0
    if not os.path.exists(TEMPLATE):
        raise CliError(2, "template missing: %s" % TEMPLATE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copyfile(TEMPLATE, path)
    print("created: %s" % path)
    return 0


def cmd_validate(args, path):
    cfg = load_config(path)
    unset = [p for p in ("platform", "length_s", "motion.level") if flatten(cfg).get(p) is None]
    print("ok: %s%s" % (path, " (not set yet: %s)" % ", ".join(unset) if unset else ""))
    return 0


def cmd_get(args, path):
    cfg = load_config(path)
    node = cfg
    if args.path not in (None, "", "."):
        for part in args.path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                raise CliError(2, "unknown path %r (e.g. voice.engine, targets)" % args.path)
    print(json.dumps(node, ensure_ascii=False, indent=2))
    return 0


def render_diff(res):
    if not res["baseline"]:
        return "no applied snapshot: first run, nothing to invalidate"
    if not res["changed"]:
        return "no changes since the last applied snapshot"
    out = ["changed:"]
    for c in res["changed"]:
        if c["path"].startswith("voice.lexicon."):
            continue  # listed per term below
        out.append("  %s: %s -> %s" % (c["path"], json.dumps(c["old"], ensure_ascii=False),
                                      json.dumps(c["new"], ensure_ascii=False)))
    lex = res.get("lexicon", {})
    j = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
    for t, v in lex.get("added", {}).items():
        out.append("  lexicon + %s -> %s" % (j(t), j(v)))
    for t, v in lex.get("changed", {}).items():
        out.append("  lexicon ~ %s: %s -> %s" % (j(t), j(v["old"]), j(v["new"])))
    for t, v in lex.get("removed", {}).items():
        out.append("  lexicon - %s (was %s)" % (j(t), j(v)))
    if res["pre"]:
        out.append("re-run first: %s (reopens %s)" % (", ".join(res["pre"]),
                                                       ", ".join(res["gates"]) or "no gate"))
    if res["rerun"]:
        out.append("re-run project.json keys (in order): " + ", ".join(
            "%s (%s)" % (r["key"], r["owner"]) for r in res["rerun"]))
    else:
        out.append("re-run project.json keys: none")
    for n in res["notes"]:
        out.append("note: " + n)
    if res["needs_user"]:
        out.append("ask the user before re-running")
    return "\n".join(out)


def cmd_diff(args, path):
    new = load_config(path)
    res = compute_diff(read_snapshot(path), new)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render_diff(res))
    return 0


def cmd_apply(args, path):
    cfg = load_config(path)
    atomic_write_json(snapshot_path(path), {
        "schema": SNAPSHOT_SCHEMA,
        "applied": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": cfg,
    })
    print("applied: %s" % snapshot_path(path))
    return 0


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(2)


def build_parser():
    def add_common(parser, sub):
        d = argparse.SUPPRESS if sub else None
        parser.add_argument("--project", default=d, help="path to demo.yaml")
        parser.add_argument("--slug", default=d, help="use .demo/<slug>/demo.yaml under cwd")

    common = argparse.ArgumentParser(add_help=False)
    add_common(common, True)
    p = Parser(description="Read, validate and diff demo.yaml. "
                           "--project/--slug may go before or after the command.")
    add_common(p, False)
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    sub.add_parser("init", parents=[common], help="create demo.yaml from the template if missing")
    sub.add_parser("validate", parents=[common], help="check types, enums, ranges, unknown keys")
    g = sub.add_parser("get", parents=[common], help="print a value as JSON, defaults applied")
    g.add_argument("path", nargs="?", help="dotted path, e.g. voice.engine (default: everything)")
    d = sub.add_parser("diff", parents=[common],
                       help="changes since the last applied snapshot and what to re-run")
    d.add_argument("--json", action="store_true", help="JSON output")
    sub.add_parser("apply", parents=[common], help="validate and write the applied snapshot")
    al = sub.add_parser("apply-lexicon", parents=[common],
                        help="print TTS input with voice.lexicon applied (text, file or stdin)")
    src = al.add_mutually_exclusive_group()
    src.add_argument("--text", default=None, help="text to convert")
    src.add_argument("--file", default=None, help="UTF-8 file to convert")
    al.add_argument("--json", action="store_true", help='JSON: {"text", "applied": [...]}')
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    handlers = {"init": cmd_init, "validate": cmd_validate, "get": cmd_get,
                "diff": cmd_diff, "apply": cmd_apply, "apply-lexicon": cmd_apply_lexicon}
    try:
        return handlers[args.cmd](args, config_path(args))
    except CliError as e:
        sys.stderr.write("error: %s\n" % e.msg)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
