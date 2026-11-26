#!/usr/bin/env python3
"""On-demand tool installer for the demo-studio plugin.

Installs ONLY the feature sets a demo job needs, into a project-local venv
(default ``.demo/.venv``), and records what was installed in ``.demo/toolkit.json``.
Non-interactive: never prompts. The agent asks the user first (using ``--plan``),
then runs ``--install``.

    setup_tools.py --list
    setup_tools.py --options [voice|render] [--json]
    setup_tools.py --plan capture,blur [--json]
    setup_tools.py --install capture,blur [--dry-run] [--json] [--venv PATH]
    setup_tools.py --check [capture,blur] [--json] [--smoke]
    setup_tools.py --python [--json] [--venv PATH]
    setup_tools.py --stage <name> [--platform web|desktop|android|ios] [--choose cap=value,...] [--with f,...] [--json]
    setup_tools.py --stages [--json]

--options lists, per capability (a job several features can do: voice, render), the alternatives
with tool, effect, size, needs, installed/missing/blocked and which one is recommended, plus the
demo.yaml setting that records the user's choice. The plugin never picks silently: the director shows
this table and the user chooses.

--stage <name> (read-only) answers "what does this pipeline stage need": required features, the
capabilities it needs a choice for (alternatives, recommended first), optional features, each with
installed/missing/blocked, plus the suggested --plan for what is missing. --choose records the user's
choice per capability (value from demo.yaml or `none`), --with adds optional features to the plan.
--stage with no name, or --stages, prints the overview of all stages (information only, nothing
installed). Always exit 0; `ready` in the output says whether the stage can run as is.

--python prints the absolute path of the venv interpreter (Windows Scripts/python.exe, POSIX
bin/python) for agent briefs: exit 0 if it exists, exit 3 (one line on stderr) if not.
--json prints {"python": path, "exists": bool}.

Workspace = ``.demo`` under the current directory (``--workspace`` overrides).
Feature ``remotion`` (the default render engine) copies the plugin's ``remotion/`` source into
<workspace>/remotion/ and runs ``npm install`` there; the plugin itself never holds node_modules.
The copy is stamped with a hash of the source (``.sync.json``): after a plugin update ``--check``
reports it out of date and ``--install remotion`` re-syncs it.
``--install remotion`` ends with a render smoke test on every OS (a 64x64 PNG through render.mjs
--art, 90 s limit, the whole node + Chrome process tree is killed on timeout). If Remotion's downloaded
headless Chrome hangs (observed on macOS 2026-11-25: every render timed out while a plain copy of the
same files rendered at once; cause not confirmed), the browser is copied to a per-user cache
(macOS ~/Library/Caches, Windows %LOCALAPPDATA%, Linux $XDG_CACHE_HOME or ~/.cache, then
demo-studio/chrome-headless-shell/<remotion version>/; env DEMO_STUDIO_BROWSER_CACHE overrides),
tested again and recorded as ``browser_executable`` in toolkit.json and in <workspace>/remotion/
.browser.json, which render.mjs reads (so it also works with --workspace). Any other
failure fails the install with an OS hint (Linux: missing system libraries). ``--check remotion
--smoke`` runs the test on demand; plain ``--check`` does not launch Chrome.
Appium is used only by capture-desktop on macOS (Mac2 driver), installed in <workspace>/appium/
(APPIUM_HOME). capture-android / capture-ios install nothing: they need adb, or xcrun + axe, on
PATH and are driven by scripts/mobile_driver.py. Env DEMO_STUDIO_OS=win|mac|linux
overrides OS detection (testing only).

Exit codes: 0 ok, 3 --python: venv not found, 1 a requested feature is missing / blocked / failed, 2 usage error
(e.g. unknown feature key). Stdlib only, Python 3.10+.
"""
from __future__ import annotations

import argparse
import hashlib
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
REMOTION_SRC = Path(__file__).resolve().parent.parent / "remotion"  # plugin source, no node_modules
REMOTION_SKIP = {"node_modules", "package-lock.json", "out", ".sync.json"}
APPIUM_CORE_MB = 250  # shared Appium npm install (counted once per plan)
APPIUM_DRIVER_PKGS = {  # driver id -> npm package (node_modules detection)
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
# Optional: capability (job this feature does; features sharing one are alternatives, see CAPABILITIES),
#   tool (short name of the underlying tool, shown in --options).
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
        "agents": ["scene-automator", "capture-operator", "privacy", "demo-qa"],
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
        "effect": "Drive and record an Android app on an emulator/device (adb + scripts/mobile_driver.py, "
                  "scrcpy or adb screenrecord); no Appium",
        "reqs": None,
        "modules": [],
        "post": [],
        "requires": ["capture"],
        "env": None,
        "node": False,
        "bins": {"adb": "adb not found on PATH (install Android platform-tools)"},
        "opt_bins": {"scrcpy": "scrcpy not found; recording falls back to adb screenrecord"},
        "size_mb": 0,
        "size_note": "uses adb (and scrcpy) from PATH; nothing downloaded",
        "agents": ["app-scout", "scene-automator", "capture-operator"],
    },
    "capture-ios": {
        "effect": "Drive and record an iOS app in the Simulator (AXe + simctl via scripts/mobile_driver.py); "
                  "no Appium, no real devices",
        "reqs": None,
        "modules": [],
        "post": [],
        "requires": ["capture"],
        "env": None,
        "node": False,
        "os": ["mac"],
        "os_reason": "requires macOS + Xcode (iOS Simulator)",
        "bins": {"xcrun": "xcrun not found (install Xcode and its command line tools)",
                 "axe": "axe not found on PATH (brew install cameroncooke/axe/axe)"},
        "size_mb": 0,
        "size_note": "uses Xcode simctl and AXe from PATH; nothing downloaded",
        "agents": ["app-scout", "scene-automator", "capture-operator"],
    },
    "voice-edge": {
        "capability": "voice",
        "tool": "edge-tts (Microsoft Edge voices)",
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
        "capability": "voice",
        "tool": "Kokoro TTS (PyTorch)",
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
        "capability": "voice",
        "tool": "ElevenLabs API",
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
        "effect": "Moving-region blur (OpenCV) for the ffmpeg fallback renderer; Remotion blurs by itself",
        "reqs": "blur.txt",
        "modules": ["cv2", "numpy"],
        "post": [],
        "requires": ["capture"],
        "env": None,
        "node": False,
        "size_mb": 60,
        "size_note": "",
        "agents": ["render-engineer"],
    },
    "motion-basic": {
        "capability": "render",
        "tool": "ffmpeg filters",
        "effect": "Fallback render engine (ffmpeg filters) when Remotion is declined or Node is missing: motion none/basic only",
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
    "remotion": {
        "capability": "render",
        "tool": "Remotion (Node + headless Chrome)",
        "effect": "Default render engine: blur, motion, captions and audio in one pass (all motion levels)",
        "reqs": None,
        "modules": [],
        "post": ["remotion"],
        "requires": [],
        "env": None,
        "node": True,
        "size_mb": 550,
        "size_note": "npm packages + headless Chrome in .demo/remotion/ (+~300 MB in the per-user cache only when the downloaded Chrome hangs in the render test)",
        "agents": ["art-designer", "motion-designer", "render-engineer"],
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
# Capabilities: a job that several features can do. The user chooses; the catalog only lists.
#   setting  demo.yaml field that records the choice
#   default  recommended feature (listed first)
#   values   feature -> value written to `setting`
#   none     optional: value meaning "no tool", with what that costs (render has none: every video
#            needs an engine)
# ---------------------------------------------------------------------------
CAPABILITIES: dict[str, dict] = {
    "voice": {
        "title": "Narration voice",
        "setting": "voice.engine",
        "default": "voice-edge",
        "values": {"voice-edge": "edge", "voice-kokoro": "kokoro", "voice-elevenlabs": "elevenlabs"},
        "none": {"value": "recorded", "effect": "you record your own WAVs; no TTS feature"},
    },
    "render": {
        "title": "Render engine (blur, motion, captions, audio in one pass)",
        "setting": "install.approved / install.declined (remotion)",
        "default": "remotion",
        "values": {"remotion": "remotion", "motion-basic": "ffmpeg"},
    },
}


# ---------------------------------------------------------------------------
# Stages: which features each pipeline stage needs (single source of truth for --stage/--stages).
#   step      pipeline step (commands/new.md); agents  owners of the stage
#   needs     features always required; needs_by_platform replaces it per demo.yaml `platform`
#   choices   capabilities (see CAPABILITIES) the user decides; the chosen option is required
#   optional  [(feature, when)] only in the stated case; added to the plan with --with
# Stage order = pipeline order. Agents still run their own --check as a safety net.
# ---------------------------------------------------------------------------
PLATFORMS = ["web", "desktop", "android", "ios"]
PLATFORM_FEATURES = {
    "web": ["capture"],
    "desktop": ["capture", "capture-desktop"],
    "android": ["capture", "capture-android"],
    "ios": ["capture", "capture-ios"],
}
STAGES: dict[str, dict] = {
    "scout": {"step": "Map", "agents": ["app-scout"],
              "needs_by_platform": {**PLATFORM_FEATURES, "desktop": ["capture"]},
              "note": "web: the browser from capture; android/ios: mobile_driver.py on the device"},
    "art": {"step": "Art", "agents": ["art-designer"], "choices": ["render"],
            "note": "PNG needs remotion; on ffmpeg art stays SVG-only (KART-E1)"},
    "voice": {"step": "Voice", "agents": ["voice-producer"], "choices": ["voice"],
              "optional": [("captions", "voice.lexicon is set (round-trip check)"),
                           ("capture", "voice.engine is recorded (ffmpeg only)")]},
    "scenes": {"step": "Scenes", "agents": ["scene-automator"], "needs_by_platform": PLATFORM_FEATURES},
    "capture": {"step": "Capture", "agents": ["capture-operator"], "needs_by_platform": PLATFORM_FEATURES},
    "blur": {"step": "Post", "agents": ["privacy"], "needs": ["capture"],
             "note": "geometric check (project.py check-blur) + ffmpeg placement frames; no OCR"},
    "sync": {"step": "Post", "agents": ["sync-editor"], "needs": ["capture"], "note": "ffmpeg comes with capture"},
    "motion": {"step": "Post", "agents": ["motion-designer"], "choices": ["render"]},
    "captions": {"step": "Post", "agents": ["caption-writer"], "needs": ["captions"]},
    "mix": {"step": "Post", "agents": ["sound-mixer"], "needs": ["mix"]},
    "render": {"step": "Render", "agents": ["render-engineer"], "needs": ["capture"], "choices": ["render"],
               "optional": [("blur", "engine is ffmpeg and #blur has moving regions (keyframes)")]},
    "qa": {"step": "QA", "agents": ["demo-qa"], "needs": ["capture"], "note": "frames by eye; no OCR"},
    "package": {"step": "Package", "agents": ["packager"], "needs": ["package"]},
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
        self.workspace = Path(workspace).expanduser().resolve() if workspace else self.demo_dir
        self.remotion_dir = self.workspace / "remotion"
        self.appium_dir = self.workspace / "appium"
        self.appium_queued = False  # core npm install already scheduled in this run
        self.browser_exe: str | None = None  # set by ensure_render_works during --install remotion
        self.smoke = False  # --check --smoke
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


def remotion_source_files() -> list[Path]:
    out = []
    for f in sorted(REMOTION_SRC.rglob("*")):
        rel = f.relative_to(REMOTION_SRC)
        if f.is_file() and not (set(rel.parts) & REMOTION_SKIP):
            out.append(f)
    return out


def remotion_source_hash() -> str:
    h = hashlib.sha256()
    for f in remotion_source_files():
        h.update(f.relative_to(REMOTION_SRC).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def remotion_synced(ctx: Ctx) -> bool:
    try:
        data = json.loads((ctx.remotion_dir / ".sync.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("hash") == remotion_source_hash()


def sync_remotion(ctx: Ctx) -> None:
    """Copy the plugin's remotion/ source into the workspace (node_modules stay there)."""
    dst = ctx.remotion_dir
    dst.mkdir(parents=True, exist_ok=True)
    keep = {f.relative_to(REMOTION_SRC) for f in remotion_source_files()}
    for f in sorted(dst.rglob("*"), reverse=True):  # drop files the plugin no longer ships
        rel = f.relative_to(dst)
        if set(rel.parts) & REMOTION_SKIP:
            continue
        if f.is_file() and rel not in keep:
            f.unlink()
        elif f.is_dir() and not any(f.iterdir()):
            f.rmdir()
    for rel in sorted(keep):
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REMOTION_SRC / rel, dst / rel)
    (dst / ".sync.json").write_text(json.dumps({"hash": remotion_source_hash(), "source": str(REMOTION_SRC),
                                                "synced_at": now()}, indent=2) + "\n", encoding="utf-8")


def remotion_installed(ctx: Ctx) -> str | None:
    pj = ctx.remotion_dir / "node_modules" / "remotion" / "package.json"
    try:
        return json.loads(pj.read_text(encoding="utf-8")).get("version") or "unknown"
    except (OSError, ValueError):
        return None


SMOKE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
             '<rect width="64" height="64" fill="#336699"/></svg>\n')
SMOKE_TIMEOUT = 90


def browser_exe_name(os_name: str | None = None) -> str:
    return "chrome-headless-shell.exe" if (os_name or current_os()) == "win" else "chrome-headless-shell"


def remotion_browser_dir(ctx: Ctx) -> Path | None:
    """The chrome-headless-shell-<platform> folder Remotion downloaded (mac-arm64, mac-x64, linux64,
    linux-arm64, win64, ...); a symlinked folder is returned as is."""
    base = ctx.remotion_dir / "node_modules" / ".remotion" / "chrome-headless-shell"
    exe = browser_exe_name()
    hits = sorted(h for h in base.glob(f"*/chrome-headless-shell-*/{exe}") if h.is_file())
    return hits[0].parent if hits else None


def browser_cache_root(os_name: str | None = None, env: dict | None = None, home: Path | None = None) -> Path:
    """Per-user cache for a copied headless Chrome: macOS ~/Library/Caches, Windows %LOCALAPPDATA%,
    Linux $XDG_CACHE_HOME or ~/.cache; env DEMO_STUDIO_BROWSER_CACHE overrides."""
    env = os.environ if env is None else env
    if env.get("DEMO_STUDIO_BROWSER_CACHE"):
        return Path(env["DEMO_STUDIO_BROWSER_CACHE"]).expanduser()
    home = home or Path.home()
    osn = os_name or current_os()
    if osn == "mac":
        base = home / "Library" / "Caches"
    elif osn == "win":
        base = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else home / "AppData" / "Local"
    else:
        base = Path(env["XDG_CACHE_HOME"]) if env.get("XDG_CACHE_HOME") else home / ".cache"
    return base / "demo-studio" / "chrome-headless-shell"


def copy_browser_out(ctx: Ctx) -> str:
    """Copy Remotion's headless Chrome to the browser cache (once per remotion version); return the executable."""
    src = remotion_browser_dir(ctx)
    if src is None:
        raise OSError("headless Chrome not found under node_modules/.remotion (remotion browser ensure)")
    exe = browser_exe_name()
    dst = browser_cache_root() / (remotion_installed(ctx) or "unknown") / src.name
    if not (dst / exe).is_file():
        tmp = dst.with_name(dst.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src.resolve(), tmp, symlinks=True)
        shutil.rmtree(dst, ignore_errors=True)
        os.replace(tmp, dst)
    return str(dst / exe)


def ensure_render_works(ctx: Ctx) -> None:
    """Install step, every OS: smoke-test the downloaded Chrome. A hang (timeout) is retried once with a
    copy in the per-user browser cache; any other failure is reported with an OS hint. Sets ctx.browser_exe
    (None = Remotion's default copy works). Raises OSError when nothing renders."""
    src = remotion_browser_dir(ctx)
    default = str(src / browser_exe_name()) if src else None
    first = render_smoke(ctx, default)
    if first is None:
        ctx.browser_exe = None
        write_browser_pin(ctx, None)
        return
    if "timed out" not in first:
        raise OSError(first + smoke_hint())
    exe = copy_browser_out(ctx)
    second = render_smoke(ctx, exe)
    if second is not None:
        raise OSError(f"{first}; the copy in {browser_cache_root()} also failed: {second}{smoke_hint()}")
    ctx.browser_exe = exe
    write_browser_pin(ctx, exe)


def write_browser_pin(ctx: Ctx, exe: str | None) -> None:
    """render.mjs reads the browser from <remotion_dir>/.browser.json (next to itself), so it works with
    --workspace too, where toolkit.json lives elsewhere. None removes the pin (Remotion's default)."""
    pin = ctx.remotion_dir / ".browser.json"
    if exe:
        pin.write_text(json.dumps({"browser_executable": exe, "written_at": now()}, indent=2) + "\n", encoding="utf-8")
    elif pin.exists():
        pin.unlink()


def smoke_hint(os_name: str | None = None) -> str:
    osn = os_name or current_os()
    if osn == "linux":
        return (" (Linux: headless Chrome needs system libraries such as libnss3, libatk-bridge2.0-0, "
                "libgbm1, libasound2; see Remotion's Linux dependencies)")
    if osn == "win":
        return " (Windows: antivirus or Controlled Folder Access may block chrome-headless-shell.exe)"
    return " (macOS: a freshly downloaded Chrome has hung before; re-run --install remotion)"


def _run_bounded(cmd: list[str], cwd: str, env: dict, timeout: int) -> tuple[int | None, str]:
    """Run cmd; on timeout kill its whole process tree (node + headless Chrome), on every OS.
    Returns (exit code or None on timeout, output)."""
    kw: dict = {"cwd": cwd, "env": env, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                "text": True, "encoding": "utf-8", "errors": "replace"}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(cmd, **kw)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or ""
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            import signal
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            out, _ = p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            out = ""
        return None, out or ""


def render_smoke(ctx: Ctx, browser: str | None, timeout: int = SMOKE_TIMEOUT) -> str | None:
    """Render a 64x64 PNG through render.mjs --art. Returns None when it works, else the reason."""
    node = shutil.which("node")
    script = ctx.remotion_dir / "render.mjs"
    if not node or not script.is_file():
        return "node or render.mjs not found"
    d = ctx.demo_dir / ".smoke"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    svg, png = d / "probe.svg", d / "probe.png"
    svg.write_text(SMOKE_SVG, encoding="utf-8")
    env = {**os.environ}
    if browser:
        env["DEMO_STUDIO_BROWSER"] = browser
    try:
        rc, out = _run_bounded([node, str(script), "--art", "--size", "64x64", "--layer", str(svg), "--out", str(png)],
                               str(ctx.cwd), env, timeout)
        if rc is None:
            return f"render smoke test timed out after {timeout} s (headless Chrome hangs)"
        if rc != 0 or not png.is_file():
            tail = " ".join(out.strip().splitlines()[-2:])
            return f"render smoke test failed (exit {rc}): {tail}"[:400]
        return None
    except OSError as e:
        return f"render smoke test could not start: {e}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
            if not (ver and k in record):
                return {"status": "missing", "reason": f"remotion not installed in {ctx.remotion_dir}"}
            if not remotion_synced(ctx):
                return {"status": "missing",
                        "reason": "remotion source out of date (plugin changed); re-run --install remotion"}
            browser = record[k].get("browser_executable")
            if browser and not Path(browser).is_file():
                return {"status": "missing",
                        "reason": f"headless Chrome missing at {browser} (cache cleared?); re-run --install remotion"}
            if ctx.smoke:
                bad = render_smoke(ctx, browser)
                if bad:
                    return {"status": "missing", "reason": bad}
            res = {"status": "installed", "reason": f"remotion {ver} in {ctx.remotion_dir}"}
            if browser:
                res["reason"] += f"; browser {browser}"
            if ctx.smoke:
                res["reason"] += "; render smoke test ok"
            return res
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
            npx = shutil.which("npx") or "npx"
            rdir = str(ctx.remotion_dir)
            cmds.append({"label": "copy remotion source", "cmd": ["copy", str(REMOTION_SRC), rdir],
                         "cwd": None, "fn": lambda: sync_remotion(ctx)})
            cmds.append({"label": "npm install (remotion)",
                         "cmd": [npm, "install", "--no-audit", "--no-fund"], "cwd": rdir})
            cmds.append({"label": "remotion browser ensure",
                         "cmd": [npx, "--no-install", "remotion", "browser", "ensure"], "cwd": rdir})
            cmds.append({"label": "render smoke test (a hanging Chrome falls back to a copy in the user cache)",
                         "cmd": ["node", "render.mjs", "--art", "--size", "64x64", "(smoke)"],
                         "cwd": None, "fn": lambda: ensure_render_works(ctx)})
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
        # (hard blocks: OS, Node, a binary missing from PATH - installing the dep does not lift them)
        if st["status"] == "blocked" and CATALOG[k]["requires"] and not st.get("hard"):
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
    rows = [{"key": k, "capability": f.get("capability"), "effect": f["effect"], "size": fmt_size(pos(f, "size_mb", 0)) + (f" ({f['size_note']})" if f["size_note"] else ""),
             "needs": needs_text(f), "agents": f["agents"]} for k, f in CATALOG.items()]
    if args.json:
        print(json.dumps({"features": rows}, indent=2))
        return 0
    hdr = ("KEY", "CHOICE", "EFFECT", "SIZE", "NEEDS", "AGENTS")
    table = [hdr] + [(r["key"], r["capability"] or "-", r["effect"], r["size"], r["needs"], ", ".join(r["agents"]))
                     for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(6)]
    for i, row in enumerate(table):
        print("  ".join(c.ljust(widths[j]) for j, c in enumerate(row)).rstrip())
        if i == 0:
            print("  ".join("-" * w for w in widths))
    return 0


def capability_members(cap: str) -> list[str]:
    """Features of a capability: the recommended one first, then catalog order."""
    keys = [k for k, f in CATALOG.items() if f.get("capability") == cap]
    default = CAPABILITIES[cap]["default"]
    return sorted(keys, key=lambda k: k != default)


def cmd_options(args, ctx: Ctx, cap: str) -> int:
    if cap and cap not in CAPABILITIES:
        raise UsageError(f"Unknown capability: {cap}. Valid: {', '.join(CAPABILITIES)}")
    caps = [cap] if cap else list(CAPABILITIES)
    members = {c: capability_members(c) for c in caps}
    states = feature_states(ctx, [k for c in caps for k in members[c]])
    out = []
    for c in caps:
        spec = CAPABILITIES[c]
        opts = []
        for k in members[c]:
            f, st = CATALOG[k], states[k]
            opts.append({"feature": k, "value": spec["values"][k], "tool": f.get("tool", k), "effect": f["effect"],
                         "size": fmt_size(pos(f, "size_mb", 0)) + (f" ({f['size_note']})" if f["size_note"] else ""),
                         "needs": needs_text(f), "status": st["status"], "reason": st.get("reason"),
                         "recommended": k == spec["default"]})
        out.append({"capability": c, "title": spec["title"], "setting": spec["setting"],
                    "default": spec["values"][spec["default"]], "none": spec.get("none"), "options": opts})
    if args.json:
        print(json.dumps({"capabilities": out}, indent=2))
        return 0
    for item in out:
        print(f"{item['capability']}: {item['title']}  [demo.yaml: {item['setting']}]")
        for o in item["options"]:
            tag = " (recommended)" if o["recommended"] else ""
            why = f" - {o['reason']}" if o["reason"] and o["status"] != "installed" else ""
            print(f"  {o['value']:<18} {o['feature']:<18} {o['status']:<9} {o['size']}{tag}")
            print(f"  {'':<18} {o['tool']}: {o['effect']}{why}")
            if o["needs"] != "-":
                print(f"  {'':<18} needs: {o['needs']}")
        if item["none"]:
            print(f"  {item['none']['value']:<18} {'-':<18} {'-':<9} {item['none']['effect']}")
    return 0


def _feature_row(k: str, st: dict) -> dict:
    f = CATALOG[k]
    return {"feature": k, "tool": f.get("tool", k), "effect": f["effect"], "status": st["status"], "reason": st.get("reason"),
            "size": fmt_size(pos(f, "size_mb", 0)) + (f" ({f['size_note']})" if f["size_note"] else ""),
            "needs": needs_text(f)}


def parse_choices(raw: str | None, stage: dict, name: str) -> dict[str, str]:
    """`voice=kokoro,render=ffmpeg` -> {capability: feature or "none"}."""
    out: dict[str, str] = {}
    for part in [p.strip() for p in (raw or "").split(",") if p.strip()]:
        cap, sep, val = part.partition("=")
        cap, val = cap.strip(), val.strip()
        if not sep or not val:
            raise UsageError(f"--choose expects capability=value, got: {part}")
        if cap not in stage.get("choices", []):
            raise UsageError(f"Stage {name} has no choice {cap!r}. Valid: {', '.join(stage.get('choices', [])) or 'none'}")
        spec = CAPABILITIES[cap]
        none = spec.get("none")
        if none and val == none["value"]:
            out[cap] = "none"
            continue
        match = [k for k, v in spec["values"].items() if val in (k, v)]
        if not match:
            valid = ", ".join(list(spec["values"].values()) + ([none["value"]] if none else []))
            raise UsageError(f"Unknown value {val!r} for {cap}. Valid: {valid}")
        out[cap] = match[0]
    return out


def stage_report(ctx: Ctx, name: str, platform: str | None, chosen: dict[str, str], with_: list[str],
                 states: dict[str, dict] | None = None) -> dict:
    st = STAGES[name]
    plat = platform or "web"
    req = list(st["needs_by_platform"][plat]) if "needs_by_platform" in st else list(st.get("needs", []))
    caps = st.get("choices", [])
    opt = st.get("optional", [])
    bad = [w for w in with_ if w not in [o[0] for o in opt]]
    if bad:
        raise UsageError(f"--with {', '.join(bad)}: not optional for stage {name}. Optional: {', '.join(o[0] for o in opt) or 'none'}")
    want = req + [k for c in caps for k in capability_members(c)] + [o[0] for o in opt]
    if states is None or any(k not in states for k in want):
        states = {**(states or {}), **feature_states(ctx, want)}
    required = [_feature_row(k, states[k]) for k in req]
    choices = []
    for c in caps:
        spec = CAPABILITIES[c]
        opts = [{**_feature_row(k, states[k]), "value": spec["values"][k], "recommended": k == spec["default"]}
                for k in capability_members(c)]
        pick = chosen.get(c)
        if pick == "none":
            status = "skipped"
        elif pick:
            status = states[pick]["status"]
        else:
            status = "ok" if any(o["status"] == "installed" for o in opts) else "needs_choice"
        choices.append({"capability": c, "title": spec["title"], "setting": spec["setting"],
                        "recommended": spec["values"][spec["default"]], "chosen": spec["none"]["value"] if pick == "none"
                        else (spec["values"][pick] if pick else None),
                        "status": status, "options": opts, "none": spec.get("none")})
    optional = [{**_feature_row(k, states[k]), "when": when, "included": k in with_} for k, when in opt]
    ready = all(r["status"] == "installed" for r in required) and all(c["status"] in ("ok", "installed", "skipped") for c in choices)
    # suggested plan: missing required + chosen (or best available recommended) option + requested optional
    feats: list[str] = [r["feature"] for r in required if r["status"] == "missing"]
    blocked = [{"feature": r["feature"], "reason": r["reason"]} for r in required if r["status"] == "blocked"]
    for c in choices:
        if c["status"] == "skipped" or c["status"] == "ok":
            continue
        by_val = {o["value"]: o for o in c["options"]}
        o = by_val[c["chosen"]] if c["chosen"] else next((o for o in c["options"] if o["status"] != "blocked"), None)
        if o and o["status"] == "missing":
            feats.append(o["feature"])
        elif o and o["status"] == "blocked":
            blocked.append({"feature": o["feature"], "reason": o["reason"]})
        elif o is None:
            blocked.append({"feature": c["capability"], "reason": "every option is blocked on this machine"})
    feats += [o["feature"] for o in optional if o["included"] and o["status"] == "missing"]
    blocked += [{"feature": o["feature"], "reason": o["reason"]} for o in optional if o["included"] and o["status"] == "blocked"]
    feats = list(dict.fromkeys(feats))
    plan = build_plan(ctx, feats) if feats else None
    return {"stage": name, "step": st["step"], "agents": st["agents"], "platform": plat,
            "platform_assumed": platform is None and "needs_by_platform" in st, "note": st.get("note"),
            "required": required, "choices": choices, "optional": optional, "ready": ready,
            "blocked": blocked, "suggested_features": feats,
            "plan_command": f"setup_tools.py --plan {','.join(feats)}" if feats else None, "plan": plan}


def cmd_stage(args, ctx: Ctx, name: str) -> int:
    if not name:
        return cmd_stages(args, ctx)
    if name not in STAGES:
        raise UsageError(f"Unknown stage: {name}. Valid: {', '.join(STAGES)}")
    if args.platform and args.platform not in PLATFORMS:
        raise UsageError(f"Unknown platform: {args.platform}. Valid: {', '.join(PLATFORMS)}")
    with_ = [w.strip() for w in (args.with_ or "").split(",") if w.strip()]
    rep = stage_report(ctx, name, args.platform, parse_choices(args.choose, STAGES[name], name), with_)
    if args.json:
        print(json.dumps(rep, indent=2))
        return 0
    plat = f", platform {rep['platform']}{' (assumed, pass --platform)' if rep['platform_assumed'] else ''}" if "needs_by_platform" in STAGES[name] else ""
    print(f"Stage {name} ({rep['step']}; {', '.join(rep['agents'])}{plat}): {'READY' if rep['ready'] else 'NEEDS TOOLS'}")
    if rep["note"]:
        print(f"  note: {rep['note']}")
    for r in rep["required"]:
        why = f" - {r['reason']}" if r["reason"] and r["status"] != "installed" else ""
        print(f"  needs  {r['feature']:<18} {r['status']:<9} {r['size']}{why}")
    for c in rep["choices"]:
        print(f"  choice {c['capability']}: {c['title']} [{c['setting']}] "
              f"chosen: {c['chosen'] or 'not chosen'} ({c['status']}), recommended: {c['recommended']}")
        for o in c["options"]:
            tag = " (recommended)" if o["recommended"] else ""
            why = f" - {o['reason']}" if o["reason"] and o["status"] != "installed" else ""
            print(f"    {o['value']:<12} {o['feature']:<18} {o['status']:<9} {o['size']}{tag}{why}")
            print(f"    {'':<12} {o['tool']}: {o['effect']}" + (f"; needs: {o['needs']}" if o["needs"] != "-" else ""))
        if c["none"]:
            print(f"    {c['none']['value']:<12} {'-':<18} {'-':<9} {c['none']['effect']}")
    for o in rep["optional"]:
        mark = " [in plan]" if o["included"] else ""
        print(f"  option {o['feature']:<18} {o['status']:<9} {o['size']}  when {o['when']}{mark}")
    for b in rep["blocked"]:
        print(f"  BLOCKED {b['feature']}: {b['reason']}")
    if rep["plan"]:
        print(f"Suggested: {rep['plan_command']}  (total {rep['plan']['total_size']})")
    return 0


def cmd_stages(args, ctx: Ctx) -> int:
    if args.platform and args.platform not in PLATFORMS:
        raise UsageError(f"Unknown platform: {args.platform}. Valid: {', '.join(PLATFORMS)}")
    keys = list(dict.fromkeys(
        [k for n in STAGES for k in (STAGES[n].get("needs", []) + [x for v in STAGES[n].get("needs_by_platform", {}).values() for x in v]
                                      + [x for c in STAGES[n].get("choices", []) for x in capability_members(c)]
                                      + [o[0] for o in STAGES[n].get("optional", [])])]))
    states = feature_states(ctx, keys)
    reps = [stage_report(ctx, n, args.platform, {}, [], states) for n in STAGES]
    if args.json:
        print(json.dumps({"stages": reps}, indent=2))
        return 0
    print("Stages in pipeline order (information only; nothing is installed). Details: --stage <name>")
    for r in reps:
        need = [f"{x['feature']}:{x['status']}" for x in r["required"]]
        need += [f"{c['capability']}:{c['status']} (rec. {c['recommended']})" for c in r["choices"]]
        print(f"  {r['stage']:<9} {r['step']:<8} {'ready' if r['ready'] else 'needs tools':<11} " + ("; ".join(need) or "-"))
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
    if step.get("fn"):
        try:
            step["fn"]()
            return 0, ""
        except OSError as e:
            return 1, str(e)
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
        extra = {}
        if is_remotion(f):
            versions = {"remotion": remotion_installed(ctx)}
            if ctx.browser_exe:
                extra["browser_executable"] = ctx.browser_exe
        elif pos(f, "appium"):
            versions["appium"] = appium_core_version(ctx)
            versions.update({f"driver:{d}": appium_driver_version(ctx, d) for d in pos(f, "appium")})
        record["features"][k] = {"installed_at": now(), "versions": versions, **extra}
        write_toolkit(ctx, record)
        entry.update(status="installed", versions=versions, **extra)
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
        if not remotion_installed(ctx):
            return "remotion not found in node_modules after install"
        return None if remotion_synced(ctx) else "remotion source copy does not match the plugin"
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
    g.add_argument("--options", metavar="CAPABILITY", nargs="?", const="",
                   help="alternatives per capability (%s) with status and recommended default" % ", ".join(CAPABILITIES))
    g.add_argument("--plan", metavar="A,B", help="show what --install would do (no changes)")
    g.add_argument("--install", metavar="A,B", help="install features (dependencies auto-included)")
    g.add_argument("--check", metavar="A,B", nargs="?", const="", help="status of features (default: all)")
    g.add_argument("--python", action="store_true", help="print the venv interpreter path (exit 3 if missing)")
    g.add_argument("--stage", metavar="NAME", nargs="?", const="",
                   help="read-only: what a pipeline stage needs (%s); no name = overview" % ", ".join(STAGES))
    g.add_argument("--stages", action="store_true", help="read-only overview of all stages")
    ap.add_argument("--platform", help="with --stage/--stages: web|desktop|android|ios (default web)")
    ap.add_argument("--choose", metavar="CAP=VALUE,...", help="with --stage: the user's choice per capability, e.g. voice=kokoro,render=ffmpeg")
    ap.add_argument("--with", dest="with_", metavar="A,B", help="with --stage: optional features to include in the plan")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--dry-run", action="store_true", help="with --install: print commands only")
    ap.add_argument("--smoke", action="store_true", help="with --check: also render a 64x64 PNG through remotion (up to 90 s)")
    ap.add_argument("--venv", help="venv directory (default: .demo/.venv under the current directory)")
    ap.add_argument("--workspace", help="workspace root; Remotion and Appium go in <workspace>/remotion and "
                    "<workspace>/appium (default: .demo under the current directory)")
    args = ap.parse_args(argv)
    ctx = Ctx(args.venv, args.workspace)
    ctx.smoke = args.smoke
    try:
        if args.python:
            return cmd_python(args, ctx)
        if args.list:
            return cmd_list(args, ctx)
        if args.stages:
            return cmd_stages(args, ctx)
        if args.stage is not None:
            return cmd_stage(args, ctx, args.stage.strip())
        if args.options is not None:
            return cmd_options(args, ctx, args.options.strip())
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
