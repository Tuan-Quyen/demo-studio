"""Shared helpers for the demo-studio scripts: bounded subprocess, ffmpeg lookup, demo.yaml, JSON output."""
import json
import os
import re
import shutil
import signal
import subprocess
import sys


def _run(cmd, timeout, cwd=None):
    """Run cmd in its own process group; kill the whole group on timeout. Returns (rc, stdout, stderr); rc 124 = timeout."""
    cmd = [str(c) for c in cmd]
    if os.path.basename(cmd[0]).startswith("ffmpeg") and "-nostdin" not in cmd:
        cmd.insert(1, "-nostdin")
    p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            p.kill()
        out, err = p.communicate()
        return 124, out, err + b"\ntimeout after %ss" % str(timeout).encode()
    return p.returncode, out, err


def find_ffmpeg(name="ffmpeg"):
    """Path of ffmpeg/ffprobe: PATH first, then imageio-ffmpeg's bundled ffmpeg (no ffprobe there). None if missing."""
    p = shutil.which(name)
    if p or name != "ffmpeg":
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def media_duration(path, ffmpeg):
    """Duration in seconds, read from `ffmpeg -i` (works without ffprobe); None if unknown."""
    _, _, err = _run([ffmpeg, "-hide_banner", "-i", path], 30)
    m = re.search(rb"Duration: (\d+):(\d+):([\d.]+)", err)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def out(obj, code=0):
    """Print JSON and exit."""
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)


# ---- demo.yaml: a small YAML subset (nested maps, "- " lists, [a, b] lists, scalars, # comments)
def _scalar(t):
    t = t.strip()
    if t[:1] in "\"'" and t[-1:] == t[:1] and len(t) > 1:
        return t[1:-1]
    if t[:1] == "[" and t[-1:] == "]":
        return [_scalar(x) for x in re.findall(r"""(?:"[^"]*"|'[^']*'|[^,])+""", t[1:-1]) if x.strip()]
    if t == "{}":
        return {}
    if t in ("", "~", "null"):
        return None
    if t in ("true", "false"):
        return t == "true"
    for conv in (int, float):
        try:
            return conv(t)
        except ValueError:
            pass
    return t


def _uncomment(s):
    q = None
    for i, c in enumerate(s):
        if q:
            q = None if c == q else q
        elif c in "\"'":
            q = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i]
    return s


def parse_yaml(text):
    lines = []
    for raw in text.splitlines():
        s = _uncomment(raw).rstrip()
        if s.strip():
            lines.append((len(s) - len(s.lstrip(" ")), s.strip()))
    pos = [0]

    def block(indent):
        if lines[pos[0]][1].startswith("- "):
            items = []
            while pos[0] < len(lines) and lines[pos[0]][0] == indent and lines[pos[0]][1].startswith("- "):
                items.append(_scalar(lines[pos[0]][1][2:]))
                pos[0] += 1
            return items
        m = {}
        while pos[0] < len(lines) and lines[pos[0]][0] == indent:
            k, sep, v = lines[pos[0]][1].partition(":")
            if not sep:
                raise ValueError("bad line: %r" % lines[pos[0]][1])
            pos[0] += 1
            k = k.strip().strip("\"'")
            if v.strip():
                m[k] = _scalar(v)
            elif pos[0] < len(lines) and lines[pos[0]][0] > indent:
                m[k] = block(lines[pos[0]][0])
            elif pos[0] < len(lines) and lines[pos[0]][0] == indent and lines[pos[0]][1].startswith("- "):
                m[k] = block(indent)
            else:
                m[k] = None
        return m

    return block(lines[0][0]) if lines else {}


def _dig(d, path, default=None):
    for k in path.split("."):
        d = d.get(k) if isinstance(d, dict) else None
    return default if d is None else d


def load_config(path):
    """Read + validate demo.yaml; returns a dict with defaults filled. Raises ValueError with a readable message."""
    try:
        raw = parse_yaml(open(path, encoding="utf-8").read())
    except OSError as e:
        raise ValueError("cannot read %s: %s" % (path, e))
    if not isinstance(raw, dict):
        raise ValueError("demo.yaml must be a map")
    g = lambda p, d=None: _dig(raw, p, d)  # noqa: E731
    top = {"platform", "length_s", "language", "formats", "voice", "captions", "music", "privacy", "tools", "targets"}
    if set(raw) - top:
        raise ValueError("unknown demo.yaml key(s): %s" % ", ".join(sorted(set(raw) - top)))
    pkeys = {"data_mode", "real_confirmation", "mask", "patterns", "seed_values"}
    if set(g("privacy", {})) - pkeys:
        raise ValueError("unknown privacy key(s): %s" % ", ".join(sorted(set(g("privacy", {})) - pkeys)))
    mode = g("privacy.data_mode", "seeded")
    if mode not in ("seeded", "real"):
        raise ValueError("privacy.data_mode must be seeded or real")
    if mode == "real" and not g("privacy.real_confirmation"):
        raise ValueError("privacy.real_confirmation is required when data_mode is real")
    cfg = {
        "platform": g("platform", "web"), "length_s": g("length_s", 60), "formats": [str(f).replace(":", "x") for f in g("formats", ["16x9"])] if isinstance(g("formats", ["16x9"]), list) else g("formats"),
        "language": g("language", "en"), "voice": g("voice", {}), "captions": g("captions", {}), "music": {"file": g("music.file"), "gain_db": g("music.gain_db", -20)},
        "targets": {"lufs": g("targets.lufs", -16), "true_peak": g("targets.true_peak", -1.5)},
        "ocr": g("tools.ocr", "qa-ocr"),
        "privacy": {"data_mode": mode, "mask": g("privacy.mask", []), "patterns": g("privacy.patterns", []),
                    "seed_values": g("privacy.seed_values", [])},
    }
    if not isinstance(cfg["length_s"], (int, float)) or cfg["length_s"] <= 0:
        raise ValueError("length_s must be a positive number")
    for k in ("formats",):
        if not isinstance(cfg[k], list):
            raise ValueError("%s must be a list" % k)
    for k in ("mask", "patterns", "seed_values"):
        if not isinstance(cfg["privacy"][k], list):
            raise ValueError("privacy.%s must be a list" % k)
    for rx in cfg["privacy"]["patterns"]:
        try:
            re.compile(str(rx))
        except re.error as e:
            raise ValueError("privacy.patterns: bad regex %r: %s" % (rx, e))
    return cfg
