#!/usr/bin/env python3
"""On-demand tool installer for the demo-studio plugin.

Installs ONLY the feature sets a demo job needs, into a project-local venv
(default ``.demo/.venv``), and records what was installed in ``.demo/toolkit.json``.
Non-interactive: never prompts. The agent asks the user first (using ``--plan``),
then runs ``--install``.

    setup_tools.py --list
    setup_tools.py --plan capture,blur [--json]
    setup_tools.py --install capture,blur [--dry-run] [--json] [--venv PATH]
    setup_tools.py --check [capture,blur] [--json]
    setup_tools.py --python [--json] [--venv PATH]

--python prints the absolute path of the venv interpreter (Windows Scripts/python.exe, POSIX
bin/python) for agent briefs: exit 0 if it exists, exit 3 (one line on stderr) if not.
--json prints {"python": path, "exists": bool}.

Appium-based features (capture-desktop on macOS, capture-android, capture-ios) share one
Appium install in <workspace>/appium/ (APPIUM_HOME). Env DEMO_STUDIO_OS=win|mac|linux
overrides OS detection (testing only).

Exit codes: 0 ok, 3 --python: venv not found, 1 a requested feature is missing / blocked / failed, 2 usage error
(e.g. unknown feature key). Stdlib only, Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.version_info < (3, 10):
    sys.stderr.write("setup_tools.py needs Python 3.10 or newer.\n")
    raise SystemExit(2)

REQ_DIR = Path(__file__).resolve().parent / "requirements"
MIN_NODE_MAJOR = 18
REMOTION_PKGS = ["remotion", "@remotion/cli", "@remotion/captions"]
APPIUM_CORE_MB = 250  # shared Appium npm install (counted once per plan)
APPIUM_DRIVER_PKGS = {  # driver id -> npm package (node_modules detection)
    "uiautomator2": "appium-uiautomator2-driver",
    "xcuitest": "appium-xcuitest-driver",
    "mac2": "appium-mac2-driver",
}

# ---------------------------------------------------------------------------
# Feature catalog: single source of truth.
#   effect   what it enables in the finished video
#   reqs     requirements file (scripts/requirements/<reqs>) or None
#   modules  top-level import names used to detect "installed" (find_spec)
#   post     post-install steps (ids handled in post_commands)
#   requires other features auto-included (ffmpeg comes from `capture`)
#   env      env var that must be set at run time (warning only)
#   node     needs Node >= 18
#   size_mb  rough download size (planning only), size_note extra text
#   agents   owning agents
# Optional keys: <key>_by_os {win|mac|linux: value} overrides reqs/modules/node/size_mb/
#   appium per OS; os (allowed OSes) + os_reason; bins {exe: reason-if-missing} (hard,
#   must be on PATH); opt_bins {exe: warning} (soft); appium [driver ids] installed into
#   the shared <workspace>/appium/.
# ---------------------------------------------------------------------------
CATALOG: dict[str, dict] = {
    "capture": {
        "effect": "Record the app in a real browser (Playwright Chromium) + bundled ffmpeg for video/audio processing",
        "reqs": "capture.txt",
        "modules": ["playwright", "imageio_ffmpeg"],
        "post": ["playwright-chromium"],
        "requires": [],
        "env": None,
        "node": False,
        "size_mb": 250,
        "size_note": "",
        "agents": ["scene-automator", "capture-operator"],
    },
    "capture-desktop": {
        "effect": "Record a desktop app window (Windows: pywinauto UI automation; macOS: Appium Mac2)",
        "reqs": None,
        "reqs_by_os": {"win": "capture-desktop-win.txt"},
        "modules": [],
        "modules_by_os": {"win": ["pywinauto"]},
        "post": [],
        "requires": ["capture"],
        "env": None,
        "node": False,
        "node_by_os": {"mac": True},
        "appium_by_os": {"mac": ["mac2"]},
        "os": ["win", "mac"],
        "os_reason": "desktop capture supports Windows and macOS only",
        "size_mb": 15,
        "size_mb_by_os": {"win": 15, "mac": 270},
        "size_note": "Windows: pywinauto; macOS: Appium + mac2 driver",
        "agents": ["scene-automator", "capture-operator"],
    },
    "capture-android": {
        "effect": "Record an Android app on a device/emulator (Appium UiAutomator2, scrcpy or adb screenrecord)",
        "reqs": "capture-android.txt",
        "modules": ["appium"],
        "post": [],
        "requires": ["capture"],
        "env": None,
        "node": True,
        "appium": ["uiautomator2"],
        "bins": {"adb": "adb not found on PATH (install Android platform-tools)"},
        "opt_bins": {"scrcpy": "scrcpy not found; recording falls back to adb screenrecord"},
        "size_mb": 280,
        "size_note": "Appium + uiautomator2 driver; shares Appium with other mobile/desktop features",
        "agents": ["scene-automator", "capture-operator"],
    },
    "capture-ios": {
        "effect": "Record an iOS app in the Simulator/device (Appium XCUITest)",
        "reqs": "capture-ios.txt",
        "modules": ["appium"],
        "post": [],
        "requires": ["capture"],
        "env": None,
        "node": True,
        "appium": ["xcuitest"],
        "os": ["mac"],
        "os_reason": "requires macOS + Xcode",
        "bins": {"xcrun": "xcrun not found (install Xcode and its command line tools)"},
        "size_mb": 300,
        "size_note": "Appium + xcuitest driver; Xcode installed separately",
        "agents": ["scene-automator", "capture-operator"],
    },
    "voice-edge": {
        "effect": "Narration with Microsoft Edge neural voices (online, free, light)",
        "reqs": "voice-edge.txt",
        "modules": ["edge_tts"],
        "post": [],
        "requires": [],
        "env": None,
        "node": False,
        "size_mb": 5,
        "size_note": "needs internet at run time",
        "agents": ["voice-producer"],
    },
    "voice-kokoro": {
        "effect": "Narration with Kokoro TTS, fully offline (pulls PyTorch)",
        "reqs": "voice-kokoro.txt",
        "modules": ["kokoro", "soundfile"],
        "post": [],
        "requires": [],
        "env": None,
        "node": False,
        "size_mb": 2000,
        "size_note": "pulls torch; model downloads on first run",
        "agents": ["voice-producer"],
    },
    "voice-elevenlabs": {
        "effect": "Narration with ElevenLabs studio-quality voices (paid API)",
        "reqs": "voice-elevenlabs.txt",
        "modules": ["elevenlabs"],
        "post": [],
        "requires": [],
        "env": "ELEVENLABS_API_KEY",
        "node": False,
        "size_mb": 5,
        "size_note": "needs internet + API key at run time",
        "agents": ["voice-producer"],
    },
    "captions": {
        "effect": "Transcribe narration for timed subtitles (faster-whisper) and write SRT/ASS (pysubs2)",
        "reqs": "captions.txt",
        "modules": ["faster_whisper", "pysubs2"],
        "post": [],
        "requires": [],
        "env": None,
        "node": False,
        "size_mb": 150,
        "size_note": "+ Whisper model download on first run",
        "agents": ["caption-writer"],
    },
    "mix": {
        "effect": "Mix narration + music: ducking and loudness normalisation",
        "reqs": "mix.txt",
        "modules": ["pyloudnorm", "soundfile", "numpy"],
        "post": [],
        "requires": ["capture"],
        "env": None,
        "node": False,
        "size_mb": 30,
        "size_note": "ducking/loudnorm run through ffmpeg from capture",
        "agents": ["sound-mixer"],
    },
    "blur": {
        "effect": "Blur/redact sensitive regions (emails, tokens, faces) in recorded frames",
        "reqs": "blur.txt",
        "modules": ["cv2", "numpy"],
        "post": [],
        "requires": ["capture"],
        "env": None,
        "node": False,
        "size_mb": 60,
        "size_note": "",
        "agents": ["privacy-blurrer"],
    },
    "motion-basic": {
        "effect": "Zoom/pan, overlays and fades via ffmpeg filters (no extra packages)",
        "reqs": None,
        "modules": ["imageio_ffmpeg"],
        "post": [],
        "requires": ["capture"],
        "env": None,
        "node": False,
        "size_mb": 0,
        "size_note": "uses ffmpeg from capture",
        "agents": ["motion-designer"],
    },
    "motion-cinematic": {
        "effect": "Cinematic titles, transitions and animated captions rendered with Remotion",
        "reqs": None,
        "modules": [],
        "post": ["remotion"],
        "requires": [],
        "env": None,
        "node": True,
        "size_mb": 400,
        "size_note": "npm packages in <workspace>/remotion/",
        "agents": ["motion-designer", "render-engineer"],
    },
    "qa-ocr": {
        "effect": "OCR the finished video to verify on-screen text, captions and redactions",
        "reqs": "qa-ocr.txt",
        "modules": ["rapidocr_onnxruntime", "cv2"],
        "post": [],
        "requires": [],
        "env": None,
        "node": False,
        "size_mb": 120,
        "size_note": "",
        "agents": ["demo-qa"],
    },
    "package": {
        "effect": "Thumbnails, posters and cover images for delivery",
        "reqs": "package.txt",
        "modules": ["PIL"],
        "post": [],
        "requires": [],
        "env": None,
        "node": False,
        "size_mb": 10,
        "size_note": "",
        "agents": ["packager"],
    },
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, venv: str | None, workspace: str | None):
        self.cwd = Path.cwd()
        self.demo_dir = self.cwd / ".demo"
        self.toolkit = self.demo_dir / "toolkit.json"
        self.venv = Path(venv).expanduser().resolve() if venv else (self.demo_dir / ".venv")
        self.workspace = Path(workspace).expanduser().resolve() if workspace else self.cwd
        self.remotion_dir = self.workspace / "remotion"
        self.appium_dir = self.workspace / "appium"
        self.appium_queued = False  # core npm install already scheduled in this run
        sub = "Scripts" if os.name == "nt" else "bin"
        exe = "python.exe" if os.name == "nt" else "python"
        self.vpy = self.venv / sub / exe

    @property
    def venv_exists(self) -> bool:
        return self.vpy.exists()


def current_os() -> str:
    forced = os.environ.get("DEMO_STUDIO_OS", "").strip().lower()
    if forced in ("win", "mac", "linux"):
        return forced
    if sys.platform.startswith("win"):
        return "win"
    return "mac" if sys.platform == "darwin" else "linux"


def pos(f: dict, key: str, default=None):
    """Feature value for the current OS: <key>_by_os[os] if present, else <key>."""
    by = f.get(key + "_by_os")
    if by and current_os() in by:
        return by[current_os()]
    return f.get(key, default)


def is_remotion(f: dict) -> bool:
    return "remotion" in f["post"]


def fmt_size(mb: int) -> str:
    if mb <= 0:
        return "~0 MB"
    if mb >= 1000:
        return f"~{mb / 1000:.1f} GB".replace(".0 GB", " GB")
    return f"~{mb} MB"


def needs_text(f: dict) -> str:
    parts = []
    if f["env"]:
        parts.append(f"env {f['env']}")
    if f["node"] or f.get("node_by_os"):
        parts.append(f"Node>={MIN_NODE_MAJOR}" + ("" if f["node"] else " (macOS)"))
    parts += [f"{b} on PATH" for b in f.get("bins", {})]
    if f.get("os"):
        names = {"win": "Windows", "mac": "macOS", "linux": "Linux"}
        parts.append("OS: " + "/".join(names[o] for o in f["os"]))
    parts += [f"{r} (ffmpeg)" for r in f["requires"]]
    return ", ".join(parts) or "-"


def parse_features(raw: str | None, *, allow_empty: bool) -> list[str]:
    keys: list[str] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part and part not in keys:
            keys.append(part)
    unknown = [k for k in keys if k not in CATALOG]
    if unknown:
        raise UsageError(
            f"Unknown feature(s): {', '.join(unknown)}. Valid keys: {', '.join(CATALOG)}"
        )
    if not keys and not allow_empty:
        raise UsageError(f"No features given. Valid keys: {', '.join(CATALOG)}")
    return keys


class UsageError(Exception):
    pass


def resolve(keys: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Return ordered keys with dependencies first, plus {dep: [requested-by...]} for auto-added."""
    order: list[str] = []
    auto: dict[str, list[str]] = {}

    def visit(k: str, parent: str | None) -> None:
        for d in CATALOG[k]["requires"]:
            if d not in keys:
                auto.setdefault(d, [])
                if k not in auto[d]:
                    auto[d].append(k)
            visit(d, k)
        if k not in order:
            order.append(k)

    for k in keys:
        visit(k, None)
    return order, auto


def prune_os_blocked(order: list[str], auto: dict[str, list[str]], states: dict[str, dict]) -> list[str]:
    """Drop auto-included deps wanted only by OS-blocked features (nothing to install for them)."""
    def os_blocked(k: str) -> bool:
        return states[k]["status"] == "blocked" and states[k].get("hard") and not states[k].get("env_block")

    keep = list(order)
    for k in reversed(order):
        if k in auto and all(r not in keep or os_blocked(r) for r in auto[k]):
            keep.remove(k)
    return keep


def read_toolkit(ctx: Ctx) -> dict:
    try:
        data = json.loads(ctx.toolkit.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("features"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"schema": 1, "features": {}}


def write_toolkit(ctx: Ctx, data: dict) -> None:
    ctx.demo_dir.mkdir(parents=True, exist_ok=True)
    data["schema"] = 1
    data["venv"] = str(ctx.venv)
    data["updated_at"] = now()
    tmp = ctx.toolkit.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, ctx.toolkit)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_capture(cmd: list[str], cwd: Path | None = None, timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def probe_modules(ctx: Ctx, modules: list[str]) -> dict[str, bool]:
    """find_spec each top-level module inside the venv (no heavy imports)."""
    mods = sorted(set(modules))
    if not mods:
        return {}
    if not ctx.venv_exists:
        return {m: False for m in mods}
    code = (
        "import importlib.util as u, json, sys\n"
        "out = {}\n"
        "for m in sys.argv[1:]:\n"
        "    try: out[m] = u.find_spec(m) is not None\n"
        "    except Exception: out[m] = False\n"
        "print(json.dumps(out))\n"
    )
    rc, out = run_capture([str(ctx.vpy), "-I", "-c", code, *mods])
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {m: False for m in mods}


def req_names(reqs_file: str | None) -> list[str]:
    if not reqs_file:
        return []
    names = []
    for line in (REQ_DIR / reqs_file).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"[A-Za-z0-9][A-Za-z0-9_.\-]*", line)
        if m:
            names.append(m.group(0))
    return names


def pkg_versions(ctx: Ctx, names: list[str]) -> dict[str, str]:
    if not names or not ctx.venv_exists:
        return {}
    code = (
        "import importlib.metadata as m, json, sys\n"
        "out = {}\n"
        "for n in sys.argv[1:]:\n"
        "    try: out[n] = m.version(n)\n"
        "    except Exception: out[n] = None\n"
        "print(json.dumps(out))\n"
    )
    rc, out = run_capture([str(ctx.vpy), "-I", "-c", code, *names])
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def node_info() -> dict:
    """{'ok': bool, 'version': str|None, 'npm': str|None, 'reason': str|None}"""
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node:
        return {"ok": False, "version": None, "npm": npm, "reason": f"Node.js not found (need >= {MIN_NODE_MAJOR})"}
    rc, out = run_capture([node, "--version"])
    m = re.search(r"v?(\d+)\.", out) if rc == 0 else None
    if not m:
        return {"ok": False, "version": None, "npm": npm, "reason": "could not run `node --version`"}
    ver = out.strip()
    if int(m.group(1)) < MIN_NODE_MAJOR:
        return {"ok": False, "version": ver, "npm": npm, "reason": f"Node {ver} is too old (need >= {MIN_NODE_MAJOR})"}
    if not npm:
        return {"ok": False, "version": ver, "npm": None, "reason": "npm not found on PATH"}
    return {"ok": True, "version": ver, "npm": npm, "reason": None}


def remotion_installed(ctx: Ctx) -> str | None:
    pj = ctx.remotion_dir / "node_modules" / "remotion" / "package.json"
    try:
        return json.loads(pj.read_text(encoding="utf-8")).get("version") or "unknown"
    except (OSError, ValueError):
        return None


def _pkg_version(pj: Path) -> str | None:
    try:
        return json.loads(pj.read_text(encoding="utf-8")).get("version") or "unknown"
    except (OSError, ValueError):
        return None


def appium_core_version(ctx: Ctx) -> str | None:
    return _pkg_version(ctx.appium_dir / "node_modules" / "appium" / "package.json")


def appium_driver_version(ctx: Ctx, driver: str) -> str | None:
    pkg = APPIUM_DRIVER_PKGS.get(driver, f"appium-{driver}-driver")
    return _pkg_version(ctx.appium_dir / "node_modules" / pkg / "package.json")


def appium_missing(ctx: Ctx, drivers: list[str]) -> list[str]:
    """What is absent from the shared Appium dir (node_modules check, no subprocess)."""
    out = [] if appium_core_version(ctx) else ["appium"]
    out += [f"driver {d}" for d in drivers if not appium_driver_version(ctx, d)]
    return out


def appium_bin() -> list[str]:
    return [shutil.which("npx") or "npx", "--no-install", "appium"]


def missing_bins(f: dict) -> list[str]:
    return [reason for exe, reason in f.get("bins", {}).items() if not shutil.which(exe)]


def ffmpeg_path(ctx: Ctx) -> str | None:
    if not ctx.venv_exists:
        return None
    rc, out = run_capture([str(ctx.vpy), "-I", "-c",
                           "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"])
    path = out.strip().splitlines()[-1] if rc == 0 and out.strip() else None
    return path if path and Path(path).exists() else None


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------
def feature_states(ctx: Ctx, keys: list[str]) -> dict[str, dict]:
    """status per key: installed | missing | blocked (+ reason, note)."""
    record = read_toolkit(ctx)["features"]
    mods = probe_modules(ctx, [m for k in keys for m in pos(CATALOG[k], "modules", [])])
    node = node_info() if any(pos(CATALOG[k], "node") for k in keys) else None
    states: dict[str, dict] = {}

    def own(k: str) -> dict:
        f = CATALOG[k]
        if f.get("os") and current_os() not in f["os"]:
            return {"status": "blocked", "reason": f.get("os_reason", "not supported on this OS"), "hard": True}
        if pos(f, "node") and not node["ok"]:
            return {"status": "blocked", "reason": node["reason"], "hard": True, "env_block": True}
        bins = missing_bins(f)
        if bins:
            return {"status": "blocked", "reason": "; ".join(bins), "hard": True, "env_block": True}
        if is_remotion(f):
            ver = remotion_installed(ctx)
            if ver and k in record:
                return {"status": "installed", "reason": f"remotion {ver}"}
            return {"status": "missing", "reason": f"remotion not installed in {ctx.remotion_dir}"}
        if not ctx.venv_exists:
            return {"status": "missing", "reason": f"venv not found at {ctx.venv}"}
        absent = [m for m in pos(f, "modules", []) if not mods.get(m)]
        if absent:
            return {"status": "missing", "reason": f"not importable: {', '.join(absent)}"}
        gone = appium_missing(ctx, pos(f, "appium")) if pos(f, "appium") else []
        if gone:
            return {"status": "missing", "reason": f"not installed in {ctx.appium_dir}: {', '.join(gone)}"}
        if f["post"] and k not in record:
            return {"status": "missing", "reason": "post-install step not recorded"}
        res = {"status": "installed", "reason": None}
        if k == "motion-basic":
            ff = ffmpeg_path(ctx)
            if not ff:
                return {"status": "missing", "reason": "ffmpeg from imageio-ffmpeg does not resolve"}
            res["reason"] = f"ffmpeg: {ff}"
        notes = []
        if f["env"] and not os.environ.get(f["env"]):
            notes.append(f"{f['env']} is not set (needed at run time)")
        notes += [w for exe, w in f.get("opt_bins", {}).items() if not shutil.which(exe)]
        if notes:
            res["note"] = "; ".join(notes)
        if pos(f, "appium"):
            res["reason"] = f"appium {appium_core_version(ctx)}; drivers: {', '.join(pos(f, 'appium'))}"
        return res

    for k in keys:
        states[k] = own(k)
    # a feature whose ffmpeg provider is missing is blocked, not usable
    need_deps = [d for k in keys for d in CATALOG[k]["requires"] if d not in states]
    if need_deps:
        states.update(feature_states(ctx, sorted(set(need_deps))))
    for k in keys:
        if states[k]["status"] == "installed":
            bad = [d for d in CATALOG[k]["requires"] if states[d]["status"] != "installed"]
            if bad:
                states[k] = {"status": "blocked", "reason": f"requires {', '.join(bad)} (ffmpeg)"}
    return states


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def venv_command(ctx: Ctx) -> dict:
    return {"label": "create venv", "cmd": [sys.executable, "-m", "venv", str(ctx.venv)], "cwd": None}


def feature_commands(ctx: Ctx, key: str) -> list[dict]:
    f = CATALOG[key]
    cmds: list[dict] = []
    reqs = pos(f, "reqs")
    if reqs:
        cmds.append({
            "label": f"pip install ({key})",
            "cmd": [str(ctx.vpy), "-m", "pip", "install", "--disable-pip-version-check",
                    "-r", str(REQ_DIR / reqs)],
            "cwd": None,
        })
    for step in f["post"]:
        if step == "playwright-chromium":
            cmds.append({"label": "install Chromium for Playwright",
                         "cmd": [str(ctx.vpy), "-m", "playwright", "install", "chromium"], "cwd": None})
        elif step == "remotion":
            npm = shutil.which("npm") or "npm"
            if not (ctx.remotion_dir / "package.json").exists():
                cmds.append({"label": "npm init", "cmd": [npm, "init", "-y"], "cwd": str(ctx.remotion_dir)})
            cmds.append({"label": "npm install remotion",
                         "cmd": [npm, "install", *REMOTION_PKGS], "cwd": str(ctx.remotion_dir)})
    drivers = pos(f, "appium") or []
    if drivers:
        npm = shutil.which("npm") or "npm"
        adir = str(ctx.appium_dir)
        if not appium_core_version(ctx) and not ctx.appium_queued:
            if not (ctx.appium_dir / "package.json").exists():
                cmds.append({"label": "npm init (appium)", "cmd": [npm, "init", "-y"], "cwd": adir})
            cmds.append({"label": "npm install appium", "cmd": [npm, "install", "appium"], "cwd": adir})
            ctx.appium_queued = True
        for d in drivers:
            if not appium_driver_version(ctx, d):
                cmds.append({"label": f"appium driver install {d}",
                             "cmd": [*appium_bin(), "driver", "install", d],
                             "cwd": adir, "env": {"APPIUM_HOME": adir}})
    return cmds


def warnings_for(keys: list[str], ctx: Ctx) -> list[str]:
    warns = []
    for k in keys:
        f = CATALOG[k]
        if f["env"] and not os.environ.get(f["env"]):
            warns.append(f"{k}: environment variable {f['env']} is not set (needed when the voice is generated)")
        if pos(f, "node"):
            n = node_info()
            if not n["ok"]:
                warns.append(f"{k}: {n['reason']}; this feature will be skipped (other features unaffected)")
        if not (f.get("os") and current_os() not in f["os"]):
            warns += [f"{k}: {r}" for r in missing_bins(f)]
            warns += [f"{k}: {w}" for exe, w in f.get("opt_bins", {}).items() if not shutil.which(exe)]
    return warns


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------
def build_plan(ctx: Ctx, keys: list[str]) -> dict:
    order, auto = resolve(keys)
    states = feature_states(ctx, order)
    order = prune_os_blocked(order, auto, states)
    items = []
    total = 0
    core_counted = bool(appium_core_version(ctx))
    for k in order:
        st = states[k]
        action = "skip" if st["status"] == "installed" else "blocked" if st["status"] == "blocked" else "install"
        # a blocked-by-dependency item is still installable once its dep is installed in this run
        if st["status"] == "blocked" and CATALOG[k]["requires"] and not CATALOG[k]["node"]:
            if any(states[d]["status"] != "installed" and d in order for d in CATALOG[k]["requires"]):
                action = "install"
        size = pos(CATALOG[k], "size_mb", 0) if action == "install" else 0
        if size and pos(CATALOG[k], "appium"):
            if core_counted:
                size = max(size - APPIUM_CORE_MB, 0)
            core_counted = True
        total += size
        items.append({
            "key": k, "action": action, "status": st["status"], "reason": st.get("reason"),
            "size_mb": size, "auto_included": k in auto, "required_by": auto.get(k, []),
            "agents": CATALOG[k]["agents"],
        })
    return {
        "requested": keys, "venv": str(ctx.venv), "venv_exists": ctx.venv_exists,
        "features": items, "total_size_mb": total, "total_size": fmt_size(total),
        "warnings": warnings_for(order, ctx),
    }


def cmd_python(args, ctx: Ctx) -> int:
    exists = ctx.venv_exists
    if args.json:
        print(json.dumps({"python": str(ctx.vpy), "exists": exists}, indent=2))
    elif exists:
        print(ctx.vpy)
    if not exists:
        print(f"venv not found at {ctx.venv}; run --install", file=sys.stderr)
        return 3
    return 0


def cmd_list(args, ctx: Ctx) -> int:
    rows = [{"key": k, "effect": f["effect"], "size": fmt_size(pos(f, "size_mb", 0)) + (f" ({f['size_note']})" if f["size_note"] else ""),
             "needs": needs_text(f), "agents": f["agents"]} for k, f in CATALOG.items()]
    if args.json:
        print(json.dumps({"features": rows}, indent=2))
        return 0
    hdr = ("KEY", "EFFECT", "SIZE", "NEEDS", "AGENTS")
    table = [hdr] + [(r["key"], r["effect"], r["size"], r["needs"], ", ".join(r["agents"])) for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(5)]
    for i, row in enumerate(table):
        print("  ".join(c.ljust(widths[j]) for j, c in enumerate(row)).rstrip())
        if i == 0:
            print("  ".join("-" * w for w in widths))
    return 0


def cmd_plan(args, ctx: Ctx, keys: list[str]) -> int:
    plan = build_plan(ctx, keys)
    if args.json:
        print(json.dumps(plan, indent=2))
        return 0
    print(f"Venv: {plan['venv']} ({'exists' if plan['venv_exists'] else 'will be created'})")
    for it in plan["features"]:
        extra = ""
        if it["auto_included"]:
            extra = f"  [auto-included: required by {', '.join(it['required_by'])}]"
        why = f"  ({it['reason']})" if it["reason"] and it["action"] != "install" else ""
        print(f"  {it['action'].upper():8} {it['key']:18} {fmt_size(it['size_mb']) if it['action'] == 'install' else '-':>9}{extra}{why}")
    print(f"Total download: {plan['total_size']}")
    for w in plan["warnings"]:
        print(f"WARNING: {w}")
    return 0


def cmd_check(args, ctx: Ctx, keys: list[str]) -> int:
    requested = keys or list(CATALOG)
    states = feature_states(ctx, requested)
    rows = []
    for k in requested:
        st = states[k]
        row = {"key": k, "status": st["status"], "reason": st.get("reason")}
        if st.get("note"):
            row["note"] = st["note"]
        rows.append(row)
    ok = all(r["status"] == "installed" for r in rows)
    if args.json:
        print(json.dumps({"ok": ok, "venv": str(ctx.venv), "features": rows}, indent=2))
    else:
        for r in rows:
            line = f"{r['status']:10} {r['key']:18}"
            if r["reason"]:
                line += f" {r['reason']}"
            if r.get("note"):
                line += f"  NOTE: {r['note']}"
            print(line)
    return 0 if ok else 1


def run_step(step: dict, capture: bool) -> tuple[int, str]:
    cwd = step["cwd"]
    if cwd:
        Path(cwd).mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **step["env"]} if step.get("env") else None
    try:
        if capture:
            p = subprocess.run(step["cmd"], cwd=cwd, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            tail = "\n".join(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-15:])
            return p.returncode, tail
        print(f"$ {' '.join(step['cmd'])}", flush=True)
        return subprocess.run(step["cmd"], cwd=cwd, env=env).returncode, ""
    except OSError as e:
        return 127, str(e)


def cmd_install(args, ctx: Ctx, keys: list[str]) -> int:
    order, auto = resolve(keys)
    capture = args.json
    dry = args.dry_run
    states = feature_states(ctx, order)
    order = prune_os_blocked(order, auto, states)
    record = read_toolkit(ctx)
    results: list[dict] = []
    failed: set[str] = set()
    venv_ready = ctx.venv_exists

    def say(msg: str) -> None:
        if not args.json:
            print(msg, flush=True)

    for k in order:
        f = CATALOG[k]
        entry = {"key": k, "auto_included": k in auto, "commands": []}
        st = states[k]
        if st["status"] == "installed":
            if k not in record["features"] and not dry:
                record["features"][k] = {"installed_at": now(), "versions": pkg_versions(ctx, req_names(pos(f, "reqs")))}
                write_toolkit(ctx, record)
            entry.update(status="skipped", reason="already installed")
            results.append(entry)
            say(f"[skip] {k}: already installed")
            continue
        # dry-run lists commands even without Node/adb (not for OS blocks)
        lenient = bool(dry and st.get("env_block") and pos(f, "appium"))
        if st["status"] == "blocked" and st.get("hard") and not lenient:
            entry.update(status="blocked", reason=st["reason"])
            results.append(entry)
            say(f"[blocked] {k}: {st['reason']}")
            continue
        dep_bad = [d for d in f["requires"] if d in failed]
        if dep_bad:
            entry.update(status="blocked", reason=f"dependency failed: {', '.join(dep_bad)}")
            failed.add(k)
            results.append(entry)
            say(f"[blocked] {k}: {entry['reason']}")
            continue

        steps: list[dict] = []
        if pos(f, "reqs") and not venv_ready:
            steps.append(venv_command(ctx))
        steps += feature_commands(ctx, k)
        entry["commands"] = [s["cmd"] for s in steps]
        if dry:
            entry["status"] = "dry-run"
            if lenient:
                entry["note"] = f"prerequisite missing, a real install would be blocked: {st['reason']}"
            results.append(entry)
            say(f"[dry-run] {k}:")
            if lenient:
                say(f"  NOTE: {entry['note']}")
            for s in steps:
                envp = "".join(f"{a}={b} " for a, b in (s.get("env") or {}).items())
                say(f"  {envp}{' '.join(s['cmd'])}" + (f"   (cwd {s['cwd']})" if s["cwd"] else ""))
            venv_ready = True  # later features would find the venv created by the first
            continue

        say(f"[install] {k} ({fmt_size(f['size_mb'])})")
        ok = True
        for s in steps:
            rc, tail = run_step(s, capture)
            if s["label"] == "create venv" and rc == 0:
                venv_ready = True
            if rc != 0:
                entry.update(status="failed", reason=f"{s['label']} exited {rc}", output_tail=tail)
                ok = False
                say(f"[failed] {k}: {s['label']} exited {rc}")
                break
        if ok:
            # verify result before recording
            after = feature_states_after_install(ctx, k, record)
            if after is not None:
                entry.update(status="failed", reason=after)
                ok = False
                say(f"[failed] {k}: {after}")
        if not ok:
            failed.add(k)
            ctx.appium_queued = False
            results.append(entry)
            continue
        versions = pkg_versions(ctx, req_names(pos(f, "reqs")))
        if is_remotion(f):
            versions = {"remotion": remotion_installed(ctx)}
        elif pos(f, "appium"):
            versions["appium"] = appium_core_version(ctx)
            versions.update({f"driver:{d}": appium_driver_version(ctx, d) for d in pos(f, "appium")})
        record["features"][k] = {"installed_at": now(), "versions": versions}
        write_toolkit(ctx, record)
        entry.update(status="installed", versions=versions)
        results.append(entry)
        say(f"[ok] {k} installed")

    ok_all = all(r["status"] in ("installed", "skipped", "dry-run") for r in results)
    if args.json:
        print(json.dumps({"ok": ok_all, "dry_run": dry, "venv": str(ctx.venv),
                          "toolkit": str(ctx.toolkit), "results": results}, indent=2))
    else:
        if not dry:
            say(f"Toolkit record: {ctx.toolkit}")
        for w in warnings_for(order, ctx):
            say(f"WARNING: {w}")
    return 0 if ok_all else 1


def feature_states_after_install(ctx: Ctx, key: str, record: dict) -> str | None:
    """Return an error string if the feature is not usable after its steps ran."""
    f = CATALOG[key]
    if is_remotion(f):
        return None if remotion_installed(ctx) else "remotion not found in node_modules after install"
    wanted = pos(f, "modules", [])
    mods = probe_modules(ctx, wanted)
    absent = [m for m in wanted if not mods.get(m)]
    if absent:
        return f"not importable after install: {', '.join(absent)}"
    gone = appium_missing(ctx, pos(f, "appium")) if pos(f, "appium") else []
    if gone:
        return f"not found in {ctx.appium_dir} after install: {', '.join(gone)}"
    if key == "motion-basic" and not ffmpeg_path(ctx):
        return "ffmpeg from imageio-ffmpeg does not resolve"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Install only the demo-video tool features a job needs.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="show the feature catalog")
    g.add_argument("--plan", metavar="A,B", help="show what --install would do (no changes)")
    g.add_argument("--install", metavar="A,B", help="install features (dependencies auto-included)")
    g.add_argument("--check", metavar="A,B", nargs="?", const="", help="status of features (default: all)")
    g.add_argument("--python", action="store_true", help="print the venv interpreter path (exit 3 if missing)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--dry-run", action="store_true", help="with --install: print commands only")
    ap.add_argument("--venv", help="venv directory (default: .demo/.venv under the current directory)")
    ap.add_argument("--workspace", help="workspace root; Remotion goes in <workspace>/remotion (default: cwd)")
    args = ap.parse_args(argv)
    ctx = Ctx(args.venv, args.workspace)
    try:
        if args.python:
            return cmd_python(args, ctx)
        if args.list:
            return cmd_list(args, ctx)
        if args.plan is not None:
            return cmd_plan(args, ctx, parse_features(args.plan, allow_empty=False))
        if args.install is not None:
            return cmd_install(args, ctx, parse_features(args.install, allow_empty=False))
        return cmd_check(args, ctx, parse_features(args.check, allow_empty=True))
    except UsageError as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e), "valid_keys": list(CATALOG)}, indent=2))
        else:
            sys.stderr.write(f"error: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
