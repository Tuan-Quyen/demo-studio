#!/usr/bin/env python3
"""android_webview_adapter.py - recorder adapter for Android hybrid / WebView and Chrome-on-Android scenes
(redesign 6.7.2 rows "Android hybrid / WebView" and "Mobile web"; P1, rev 3 scope 8.0).

STATUS: UNTESTED ON DEVICE. No emulator or phone existed when this was written. Everything marked
"untested on device" below (adb/scrcpy/screenrecord/uiautomator/CDP-over-adb) follows the documented behaviour of
those tools but has never run against Android. What IS tested (scripts/tests/test_android_webview.py) is the
CDP -> injection -> sidecar -> transform -> gate path, against a SIMULATED device: a local Chromium started with
--remote-debugging-port, a CDP Page.startScreencast stand-in for scrcpy, and ffmpeg composing the "device screen".

Same contract as web_adapter.py (capture.py spawns it, run_bounded, jsonl heartbeat on stderr):

  python android_webview_adapter.py <spec.json>          # intended: capture.py run --adapter android-webview

Spec = the web spec (scene, tmp_dir, scene_script, vo_ms, mask, probes, timeouts; `url` optional: the app is already
running on the device) plus an `android` object:
  serial, adb (path), package (pick the right webview process), socket ("webview" | "chrome"), pid, port (0 = adb picks),
  page_match (substring of the page URL), recorder ("auto" | "scrcpy" | "screenrecord"), max_size, max_fps,
  webview_rect [x,y,w,h] (device px; skips uiautomator), simulate {...} (test-only SimDevice, see below).

Flow (every adb/scrcpy call is bounded by run_bounded / Bounded):
  1. tools: adb (+ scrcpy when asked) missing -> exit 4 with the reason. Nothing is touched.
  2. `adb forward tcp:<port> localabstract:webview_devtools_remote_<pid>` (pid looked up in /proc/net/unix, <= 10 s;
     or `chrome_devtools_remote`), Playwright `chromium.connect_over_cdp`. [untested on device]
  3. privacy_mask.js + privacy_oracle.js: context.add_init_script (future documents) AND one evaluate in the current
     document; preflight assertMasked() BEFORE the recorder starts; not ok -> exit 11, nothing recorded.
  4. recorder (scrcpy --record, or `adb shell screenrecord` fallback, hard 180 s limit) started/stopped bounded.
  5. calibration pulses INSIDE the current document (a full-viewport magenta overlay: the app cannot be navigated to
     about:blank). The gate looks for the magenta at the CLIP CENTRE; if the centre is not inside the WebView the
     pulses are not sent (t_flashes=[]) and the gate falls back to t_page_epoch (recorder-ready time) + its refine pass.
  6. assertMasked again, scene, assertMasked at the end, recorder stop, ffmpeg probe of the clip size.
  7. sidecars in spec.tmp_dir: <sid>.raw.mkv|mp4|webm, <sid>.mask.jsonl, <sid>.sync.json. Prints ONE JSON line.

TRANSFORM (the point of this adapter): privacy_mask.js logs rects in WebView CSS px. The gate checks pixels of the
clip, so this adapter writes the mask log ALREADY IN CLIP PX (outward-rounded, original kept as `rects_css`) and puts
the mapping in sync.json["transform"]:
    clip = (css * devicePixelRatio + webview_rect_origin_device_px) * clip_scale        (sx = dpr*cs, tx = wx*cs)
  webview_rect: uiautomator `android.webkit.WebView` bounds (device px) [untested on device]; clip_scale =
  clip_w / device_w (scrcpy --max-size makes it < 1; the clip size is probed after recording). The mapping is refused
  (exit 70, status "geometry") when the WebView rect does not equal innerWidth/Height * dpr (2 px), when the page is
  pinch-zoomed (visualViewport.scale != 1), or when the clip aspect differs from the device's. sync.viewport is the
  CLIP size (capture.gate's viewport_ne_clip_size check), the page viewport is in transform.viewport_css.

VFR: scrcpy/screenrecord write a frame only when the screen changes. Nothing here converts to CFR (the gate reads
real pts with -fps_mode passthrough; the renderer normalises later). Clock domain: every epoch in the sidecars is the
PAGE clock (performance.timeOrigin + now), read on the device, never the host clock (they differ on a phone).
Static screen => long frame gaps and a clip that ends before scene_end; the gate's carry logic covers repeated pixels.

Exit: 0 ok | 2 bad spec / ambiguous webview / refused typed text / invalid regex | 3 over budget | 4 missing tool
(adb, scrcpy, ffmpeg, playwright) | 10 scene step failed | 11 mask assertion failed (nothing kept) |
70 environment/unexpected (no device, no socket, geometry mismatch).
"""
import json
import math
import os
import re
import shutil
import signal
import socket as _socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_bounded as rbm  # noqa: E402
import web_adapter as wa  # noqa: E402  (Ctx, TypeGuard, load_scene, summarize, present, hb: the shared recorder contract)

Refused, StepError = wa.Refused, wa.StepError
ADB_WALL_S = 10          # every single adb call
PID_LOOKUP_S = 10        # redesign 6.7.2: pid lookup bounded <= 10 s
SCREENRECORD_LIMIT_S = 180
PULSES = 5


class ToolMissing(Exception):
    def __init__(self, missing, why=""):
        super().__init__("missing tools: %s%s" % (", ".join(missing), (" (%s)" % why) if why else ""))
        self.missing = missing


class GeometryError(Exception):
    pass


class DeviceError(Exception):
    pass


def now_ms():
    return time.time() * 1000.0


# ------------------------------------------------------------------ transform (pure)
def make_transform(dpr, webview_rect, device_px, clip_px, viewport_css, zoom=1.0):
    """CSS px of the WebView -> clip px. Raises GeometryError when the geometry cannot be trusted (fail closed)."""
    wx, wy, ww, wh = webview_rect
    dw, dh = device_px
    cw, ch = clip_px
    if abs(zoom - 1.0) > 0.001:
        raise GeometryError("page is pinch-zoomed (visualViewport.scale=%s): css->device mapping not valid" % zoom)
    vw, vh = viewport_css
    if abs(vw * dpr - ww) > 2 or abs(vh * dpr - wh) > 2:
        raise GeometryError("webview rect %sx%s device px != viewport %sx%s css px * dpr %s" % (ww, wh, vw, vh, dpr))
    cx, cy = cw / float(dw), ch / float(dh)
    if abs(cx - cy) > 0.01 * max(cx, cy):
        raise GeometryError("clip %sx%s has a different aspect than the device %sx%s (rotation / --crop?)" % (cw, ch, dw, dh))
    tr = {"schema": 1, "map": "css -> device px -> clip px", "dpr": dpr, "webview_rect_device": [wx, wy, ww, wh],
            "device_px": [dw, dh], "clip_px": [cw, ch], "clip_scale": cx, "viewport_css": [vw, vh],
            "sx": dpr * cx, "sy": dpr * cy, "tx": wx * cx, "ty": wy * cy, "rounding": "outward"}
    tr["gate_inset_px"] = gate_inset(tr)
    return tr


def gate_inset(t):
    """capture.check_rect insets every rect by a FIXED 2 clip px. That is enough at 1 clip px per css px, but an input's
    ~2 css px border / the sentinel and antialiasing are 2*s px wide at s = dpr*clip_scale > 1 and leak into the checked
    interior (measured in the simulation at dpr 2: std 20-40 at every input rect). So for s > 1 the log carries rects
    shrunk by ceil(3*s - 1) px per side (= ~3 css px band excluded). The page still masks the full element; only the
    gate's sampled interior moves inward. Proper fix (backlog): make capture.check_rect scale-aware. 0 when s <= 1."""
    s = max(t["sx"], t["sy"])
    return int(math.ceil(3 * s - 1 - 1e-6)) if s > 1.0001 else 0


def apply_rect(t, r, shrink=0):
    """[x,y,w,h] css -> [x,y,w,h] clip px, rounded OUTWARD (never smaller than the true rect), clamped to the clip, then
    `shrink` px off each side when the rect is big enough to keep an interior (see gate_inset)."""
    cw, ch = t["clip_px"]
    x0 = max(0, math.floor(r[0] * t["sx"] + t["tx"] - 1e-6))
    y0 = max(0, math.floor(r[1] * t["sy"] + t["ty"] - 1e-6))
    x1 = min(cw, math.ceil((r[0] + r[2]) * t["sx"] + t["tx"] + 1e-6))
    y1 = min(ch, math.ceil((r[1] + r[3]) * t["sy"] + t["ty"] + 1e-6))
    w, h = max(0, x1 - x0), max(0, y1 - y0)
    if shrink and w >= 2 * shrink + 8 and h >= 2 * shrink + 8:
        x0, y0, w, h = x0 + shrink, y0 + shrink, w - 2 * shrink, h - 2 * shrink
    return [x0, y0, w, h]


PULSE_PAD_MS = 60


def transform_log(entries, t, pulse_window=None):
    """Mask log -> clip px. Entries inside the calibration-pulse window get skip=[all rects]: the pulse is a fully opaque
    full-viewport overlay on top of everything (same mechanism as the oracle's DOM-proven opaque occluder), so the frame
    shows nothing but magenta there and the gate must not look for mask pixels. Outside that window nothing is skipped."""
    out = []
    for e in entries:
        e = dict(e)
        if pulse_window and e.get("kind") in ("masked", "oracle") and pulse_window[0] <= e.get("t", 0) <= pulse_window[1] and e.get("rects"):
            e["skip"] = sorted(set(e.get("skip") or []) | set(range(len(e["rects"]))))
            e["skip_reason"] = "calibration pulse overlay"
        if isinstance(e.get("rects"), list):
            e["rects_css"] = e["rects"]
            e["rects"] = [apply_rect(t, r, gate_inset(t)) for r in e["rects"]]
        if isinstance(e.get("rect"), list) and len(e["rect"]) == 4:
            e["rect_css"] = e["rect"]
            e["rect"] = apply_rect(t, e["rect"])
        out.append(e)
    return out


# ------------------------------------------------------------------ adb (bounded) [untested on device]
class Adb:
    def __init__(self, exe, serial=None, wall=ADB_WALL_S):
        self.exe, self.serial, self.wall = exe, serial, wall

    def cmd(self, *args):
        return [self.exe] + (["-s", self.serial] if self.serial else []) + list(args)

    def run(self, *args, wall=None, ok_rc=(0,)):
        r = rbm.run_bounded(self.cmd(*args), wall=wall or self.wall, label="adb:" + (args[0] if args else ""),
                            tail_bytes=4000000)
        if r["status"] != "ok":
            raise DeviceError("adb %s: %s" % (" ".join(args[:2]), r.get("error") or r["status"]))
        if r["tool_rc"] not in ok_rc:
            raise DeviceError("adb %s failed rc=%s: %s" % (" ".join(args[:2]), r["tool_rc"], (r["stderr_tail"] or r["stdout_tail"]).strip()[:200]))
        return r["stdout_tail"]

    def find_pids(self, prefix="webview_devtools_remote_", package=None, budget_s=PID_LOOKUP_S):
        """pids that own an abstract devtools socket; polled until the budget is spent."""
        end = time.monotonic() + budget_s
        pids = []
        while True:
            pids = parse_unix_sockets(self.run("shell", "cat", "/proc/net/unix", wall=max(1, min(ADB_WALL_S, end - time.monotonic()))), prefix)
            if package and pids:
                mine = set(re.findall(r"\d+", self.run("shell", "pidof", package, ok_rc=(0, 1))))
                pids = [p for p in pids if p in mine]
            if pids or time.monotonic() >= end:
                return pids
            time.sleep(0.5)


def parse_unix_sockets(text, prefix="webview_devtools_remote_"):
    return sorted(set(re.findall(r"@" + re.escape(prefix) + r"(\d+)", text)), key=int)


def parse_webview_rects(xml_text, package=None):
    """uiautomator dump -> [[x,y,w,h]] of android.webkit.WebView nodes (device px). [untested on device]"""
    i = xml_text.find("<?xml")
    j = xml_text.rfind("</hierarchy>")
    if i < 0 or j < 0:
        raise DeviceError("uiautomator dump unreadable")
    root = ET.fromstring(xml_text[i:j + len("</hierarchy>")])
    out = []
    for n in root.iter("node"):
        if n.get("class") != "android.webkit.WebView" or (package and n.get("package") != package):
            continue
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds") or "")
        if m:
            l, t, r, b = map(int, m.groups())
            out.append([l, t, r - l, b - t])
    return out


def parse_wm_size(text):
    m = re.findall(r"(?:Override|Physical) size:\s*(\d+)x(\d+)", text)
    if not m:
        raise DeviceError("cannot read `wm size`")
    return [int(m[-1][0]), int(m[-1][1])]          # Override wins over Physical


# ------------------------------------------------------------------ recorders
class Recorder:
    """start(page) -> after the file exists and grows; stop() -> path of the finished clip. Bounded."""
    ext = "mkv"

    def start(self, page, out_base):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class ScrcpyRecorder(Recorder):
    """scrcpy --record: untested on device. SIGINT finalises the mkv (documented scrcpy behaviour)."""
    ext = "mkv"

    def __init__(self, adb, exe, max_size=None, max_fps=None, limit_s=600):
        self.adb, self.exe, self.max_size, self.max_fps, self.limit = adb, exe, max_size, max_fps, limit_s
        self.b = None

    def start(self, page, out_base):
        self.path = out_base + "." + self.ext
        cmd = [self.exe] + (["-s", self.adb.serial] if self.adb.serial else []) + [
            "--no-playback", "--no-audio", "--no-control", "--record=" + self.path, "--time-limit=%d" % self.limit]
        if self.max_size:
            cmd.append("--max-size=%d" % self.max_size)
        if self.max_fps:
            cmd.append("--max-fps=%d" % self.max_fps)
        self.b = rbm.Bounded(cmd, wall=self.limit + 15, label="scrcpy")
        self.b.__enter__()
        wait_growing(self.path, self.b.proc)

    def stop(self):
        stop_group(self.b, signal.SIGINT)
        return self.path


class ScreenrecordRecorder(Recorder):
    """adb shell screenrecord: hard 180 s limit on the device. untested on device."""
    ext = "mp4"

    def __init__(self, adb, size=None):
        self.adb, self.size = adb, size
        self.b = None

    def start(self, page, out_base):
        self.path = out_base + "." + self.ext
        self.remote = "/sdcard/ds_%d.mp4" % os.getpid()
        cmd = self.adb.cmd("shell", "screenrecord", "--time-limit", str(SCREENRECORD_LIMIT_S), "--bit-rate", "20000000") \
            + (["--size", self.size] if self.size else []) + [self.remote]
        self.b = rbm.Bounded(cmd, wall=SCREENRECORD_LIMIT_S + 15, label="screenrecord")
        self.b.__enter__()
        time.sleep(1.0)          # no local file to watch: the clip only exists after the pull
        if self.b.proc.poll() is not None:
            raise DeviceError("screenrecord exited at start: " + (self.b.proc.stderr.read() or b"").decode("utf-8", "replace")[:200])

    def stop(self):
        try:
            self.adb.run("shell", "pkill", "-2", "screenrecord", ok_rc=(0, 1))      # SIGINT finalises the mp4
            time.sleep(1.5)
            self.adb.run("pull", self.remote, self.path, wall=60)
            self.adb.run("shell", "rm", "-f", self.remote, ok_rc=(0, 1))
        finally:
            stop_group(self.b, signal.SIGTERM)
        return self.path


def wait_growing(path, proc, budget_s=10.0):
    end = time.monotonic() + budget_s
    last = -1
    while time.monotonic() < end:
        if proc.poll() is not None:
            raise DeviceError("recorder exited at start (rc=%s)" % proc.returncode)
        sz = os.path.getsize(path) if os.path.exists(path) else 0
        if sz > 0 and sz == last:
            return
        last = sz if sz > 0 else -1
        time.sleep(0.4)
    raise DeviceError("recorder produced no growing file in %.0f s" % budget_s)


def stop_group(b, sig):
    """Signal the recorder's process group, wait <= 5 s for a clean exit (file finalised), then Bounded reaps."""
    if b is None or b.proc is None:
        return
    if b.proc.poll() is None:
        try:
            os.killpg(b.proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            b.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
    b.__exit__(None, None, None)


# ------------------------------------------------------------------ real device
class AdbDevice:
    """Real Android device through adb. UNTESTED ON DEVICE."""

    def __init__(self, cfg, tmp):
        self.cfg, self.tmp = cfg, tmp
        self.adb = Adb(cfg.get("adb") or shutil.which("adb"), cfg.get("serial"))
        self.port = None
        self.kind = "webview" if cfg.get("socket", "webview") == "webview" else "chrome"

    def check_tools(self):
        missing = []
        if not self.adb.exe or not shutil.which(self.adb.exe):
            missing.append("adb")
        rec = self.cfg.get("recorder", "auto")
        if rec == "scrcpy" and not shutil.which(self.cfg.get("scrcpy") or "scrcpy"):
            missing.append("scrcpy")
        if missing:
            raise ToolMissing(missing, "Android SDK platform-tools / scrcpy on PATH, or android.adb / android.scrcpy")

    def connect(self, p, timeout_ms):
        wa.hb("adb")
        self.adb.run("get-state")
        if self.kind == "webview":
            pids = [str(self.cfg["pid"])] if self.cfg.get("pid") else self.adb.find_pids(package=self.cfg.get("package"))
            if not pids:
                raise DeviceError("no webview_devtools_remote_<pid> socket within %ds: is WebView.setWebContentsDebuggingEnabled(true) "
                                  "set in this build (it is off by default, also in debuggable builds)?" % PID_LOOKUP_S)
            if len(pids) > 1:
                raise Refused("several webview devtools sockets (pids %s): set android.package or android.pid" % ", ".join(pids))
            sock = "webview_devtools_remote_" + pids[0]
        else:
            sock = "chrome_devtools_remote"
        out = self.adb.run("forward", "tcp:%d" % int(self.cfg.get("port", 0)), "localabstract:" + sock)
        self.port = int(out.strip()) if out.strip().isdigit() else int(self.cfg["port"])
        return p.chromium.connect_over_cdp("http://127.0.0.1:%d" % self.port, timeout=timeout_ms)

    def geometry(self, page_viewport_css, dpr):
        size = self.cfg.get("device_px") or parse_wm_size(self.adb.run("shell", "wm", "size"))
        rect = self.cfg.get("webview_rect")
        if not rect:
            xml = self.adb.run("exec-out", "uiautomator", "dump", "/dev/tty", wall=20)
            rects = parse_webview_rects(xml, self.cfg.get("package"))
            if len(rects) != 1:
                raise DeviceError("uiautomator found %d WebView nodes (need exactly 1): pass android.webview_rect" % len(rects))
            rect = rects[0]
        return size, rect

    def recorder(self, spec_android):
        mode = self.cfg.get("recorder", "auto")
        exe = shutil.which(self.cfg.get("scrcpy") or "scrcpy")
        if mode in ("auto", "scrcpy") and exe:
            return ScrcpyRecorder(self.adb, exe, self.cfg.get("max_size"), self.cfg.get("max_fps"))
        return ScreenrecordRecorder(self.adb)

    def max_scene_s(self):
        return SCREENRECORD_LIMIT_S - 5 if not shutil.which(self.cfg.get("scrcpy") or "scrcpy") or self.cfg.get("recorder") == "screenrecord" else 590

    def close(self):
        if self.port:
            try:
                self.adb.run("forward", "--remove", "tcp:%d" % self.port)
            except Exception:  # noqa: BLE001
                pass


# ------------------------------------------------------------------ SIMULATION (test-only)
class CdpScreencastRecorder(Recorder):
    """SIMULATION stand-in for scrcpy: CDP Page.startScreencast change events -> captureScreenshot (VFR, real timestamps) composed by ffmpeg onto a
    'device screen' (padding = native chrome) at the WebView rect, optionally downscaled like scrcpy --max-size."""
    ext = "mkv"

    def __init__(self, ffmpeg, device_px, rect, clip_scale, dpr=1.0):
        self.ffmpeg, self.device_px, self.rect, self.clip_scale, self.dpr = ffmpeg, device_px, rect, clip_scale, dpr
        self.frames, self.cdp = [], None

    def start(self, page, out_base):
        self.path = out_base + "." + self.ext
        self.dir = out_base + ".frames"
        os.makedirs(self.dir, exist_ok=True)
        self.cdp = page.context.new_cdp_session(page)

        import base64
        vw, vh = int(round(self.rect[2] / self.dpr)), int(round(self.rect[3] / self.dpr))

        def on_frame(ev):
            # screencast frames are css-px sized (no dpr): use them only as the "screen changed" trigger and grab a
            # device-px screenshot (clip.scale = dpr) at that moment; stamp = midpoint of the grab. This is what limits the
            # simulated recorder to ~13 fps (VFR, like scrcpy on a mostly static screen).
            self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            t0 = time.time()
            r = self.cdp.send("Page.captureScreenshot", {"format": "png", "clip": {"x": 0, "y": 0, "width": vw, "height": vh, "scale": self.dpr}})
            t1 = time.time()
            fp = os.path.join(self.dir, "f%06d.png" % len(self.frames))
            with open(fp, "wb") as f:
                f.write(base64.b64decode(r["data"]))
            self.frames.append(((t0 + t1) / 2.0, fp))
        self.cdp.on("Page.screencastFrame", on_frame)
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 10, "maxWidth": 64, "maxHeight": 64, "everyNthFrame": 1})
        self.page = page
        end = time.monotonic() + 10
        while not self.frames and time.monotonic() < end:
            page.wait_for_timeout(50)
        if not self.frames:       # a static page emits nothing until it repaints: nudge it
            page.evaluate("() => { document.documentElement.style.outline = '1px solid transparent'; }")
            for _ in range(100):
                page.wait_for_timeout(50)
                if self.frames:
                    break
        if not self.frames:
            raise DeviceError("simulated recorder got no frame")

    def stop(self):
        self.page.wait_for_timeout(150)
        stop_ts = time.time()
        try:
            self.cdp.send("Page.stopScreencast")
        finally:
            self.cdp.detach()
        if not self.frames:
            raise DeviceError("simulated recorder got no frame")
        lst = os.path.join(self.dir, "list.txt")
        with open(lst, "w") as f:
            for i, (ts, fp) in enumerate(self.frames):
                nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else max(stop_ts, ts + 0.04)
                f.write("file '%s'\nduration %.6f\n" % (fp, max(0.001, nxt - ts)))
            f.write("file '%s'\n" % self.frames[-1][1])
        dw, dh = self.device_px
        x, y, w, h = self.rect
        cs = self.clip_scale
        ow, oh = int(round(dw * cs / 2.0)) * 2, int(round(dh * cs / 2.0)) * 2
        vf = "scale=%d:%d,pad=%d:%d:%d:%d:color=0x303030" % (w, h, dw, dh, x, y)
        if cs != 1.0:
            vf += ",scale=%d:%d" % (ow, oh)
        r = rbm.run_bounded([self.ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                             "-vf", vf + ",format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10",
                             "-fps_mode", "vfr", self.path], wall=120, label="sim-compose")
        if r["status"] != "ok" or r["tool_rc"] != 0:
            raise DeviceError("sim compose failed: " + r["stderr_tail"][-200:])
        shutil.rmtree(self.dir, ignore_errors=True)
        return self.path


class SimDevice:
    """SIMULATED device (test-only; spec.android.simulate): a local headless Chromium with --remote-debugging-port plays
    the WebView, forced to dpr `dpr`; the 'screen' is composed by ffmpeg. Proves CDP + injection + sidecars + transform +
    gate, NOT adb/scrcpy/uiautomator. simulate: {dpr, device_px, webview_rect, clip_scale, chrome_args}."""

    def __init__(self, cfg, tmp, url):
        self.cfg, self.tmp, self.url = cfg, tmp, url
        self.sim = cfg["simulate"]
        self.dpr = float(self.sim.get("dpr", 2))
        self.device_px = self.sim.get("device_px", [720, 1280])
        self.rect = self.sim.get("webview_rect", [0, 96, 720, 1000])
        self.clip_scale = float(self.sim.get("clip_scale", 1.0))
        self.b = None
        self.ffmpeg = shutil.which("ffmpeg")

    def check_tools(self):
        if not self.ffmpeg:
            raise ToolMissing(["ffmpeg"], "simulation composes the clip with ffmpeg")

    def connect(self, p, timeout_ms):
        s = _socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        vw, vh = int(round(self.rect[2] / self.dpr)), int(round(self.rect[3] / self.dpr))
        cmd = [p.chromium.executable_path, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
               "--remote-debugging-port=%d" % self.port, "--window-size=%d,%d" % (max(vw, 500), max(vh, 400)), "--user-data-dir=" + os.path.join(self.tmp, "sim-profile"),
               "--no-first-run", "--disable-extensions"] + list(self.sim.get("chrome_args", [])) + [self.url or "about:blank"]
        self.b = rbm.Bounded(cmd, wall=600, label="sim-chromium")
        self.b.__enter__()
        end = time.monotonic() + 10
        while time.monotonic() < end:
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/json/version" % self.port, timeout=1).read()
                break
            except OSError:
                if self.b.proc.poll() is not None:
                    raise DeviceError("simulated chromium exited")
                time.sleep(0.2)
        else:
            raise DeviceError("simulated chromium: no CDP endpoint in 10 s")
        return p.chromium.connect_over_cdp("http://127.0.0.1:%d" % self.port, timeout=timeout_ms)

    def prepare(self, page):
        """Headless Chromium has a minimum window size: emulate the WebView viewport at the simulated dpr instead."""
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": int(round(self.rect[2] / self.dpr)), "height": int(round(self.rect[3] / self.dpr)),
                                                        "deviceScaleFactor": self.dpr, "mobile": False})
        page.wait_for_timeout(200)

    def geometry(self, page_viewport_css, dpr):
        return list(self.device_px), list(self.rect)

    def recorder(self, spec_android):
        return CdpScreencastRecorder(self.ffmpeg, self.device_px, self.rect, self.clip_scale, self.dpr)

    def max_scene_s(self):
        return 590

    def close(self):
        if self.b:
            stop_group(self.b, signal.SIGTERM)


# ------------------------------------------------------------------ helpers
def ffmpeg_exe():
    return shutil.which("ffmpeg")


def probe_size(path):
    """(w, h) of the first video stream, one bounded ffmpeg call."""
    r = rbm.run_bounded([ffmpeg_exe(), "-nostdin", "-hide_banner", "-i", path], wall=30, label="probe", tail_bytes=200000)
    m = re.search(r"Stream #0:\d.*?Video:.*?,\s*(\d{2,5})x(\d{2,5})", r["stderr_tail"])
    if not m:
        raise DeviceError("ffmpeg could not read the clip: " + r["stderr_tail"][-160:])
    return int(m.group(1)), int(m.group(2))


PAGE_EPOCH = "() => performance.timeOrigin + performance.now()"
PULSE_ON = ("() => new Promise(res => requestAnimationFrame(ts => { let d = document.getElementById('__ds_pulse'); "
            "if (!d) { d = document.createElement('div'); d.id = '__ds_pulse'; d.style.cssText = 'position:fixed;inset:0;"
            "z-index:2147483647;pointer-events:none;background:#ff00ff'; document.documentElement.appendChild(d); } "
            "d.style.background = '#ff00ff'; res(performance.timeOrigin + ts); }))")
PULSE_OFF = "() => { const d = document.getElementById('__ds_pulse'); if (d) d.remove(); }"


def pick_page(browser, match):
    pages = [pg for c in browser.contexts for pg in c.pages if not pg.url.startswith(("chrome://", "devtools://", "about:"))]
    if match:
        pages = [pg for pg in pages if match in pg.url]
    vis = []
    for pg in pages:
        try:
            if pg.evaluate("document.visibilityState") == "visible":
                vis.append(pg)
        except Exception:  # noqa: BLE001
            pass
    if len(vis) != 1:
        raise Refused("%d visible webview pages (%s): set android.page_match" % (len(vis), ", ".join(pg.url[:60] for pg in vis) or "none"))
    return vis[0]


# ------------------------------------------------------------------ run
def run(spec):
    from playwright.sync_api import Error as PWError, TimeoutError as PWTimeout, sync_playwright
    tmo = dict({"load_ms": 15000, "assert_ms": 5000, "step_ms": 15000, "total_ms": 90000}, **(spec.get("timeouts") or {}))
    sid = spec["scene"]
    acfg = spec.get("android") or {}
    mask = spec.get("mask") or {}
    mask_on = bool(mask.get("enabled"))
    tmp = spec["tmp_dir"]
    os.makedirs(tmp, exist_ok=True)
    result = {"ok": False, "status": "error", "mask_enabled": mask_on, "untested_on_device": "simulate" not in acfg,
              "simulated": "simulate" in acfg}
    mask_js = open(os.path.join(HERE, "privacy_mask.js"), encoding="utf-8").read()
    oracle_js = open(os.path.join(HERE, "privacy_oracle.js"), encoding="utf-8").read()
    cfg = {k: v for k, v in mask.items() if k != "enabled"}
    ocfg = {"selectors": mask.get("selectors", []), "regexes": mask.get("regexes", []), "probes": spec.get("probes") or []}
    mod = fn = None
    if spec.get("scene_script"):
        mod, fn = wa.load_scene(spec["scene_script"], sid)
    prepare = getattr(mod, "prepare", None) if mod else None
    dev = SimDevice(acfg, tmp, spec.get("url")) if "simulate" in acfg else AdbDevice(acfg, tmp)
    dev.check_tools()
    if not ffmpeg_exe():
        raise ToolMissing(["ffmpeg"], "needed to probe the clip size")
    if int(spec.get("vo_ms") or 0) / 1000.0 + 30 > dev.max_scene_s():
        raise Refused("scene (vo %d ms) does not fit the recorder limit (%d s; screenrecord is hard-limited to 180 s)"
                      % (int(spec.get("vo_ms") or 0), dev.max_scene_s()))
    sink, probes = [], []

    def on_batch(batch):
        for e in batch:
            (probes if e.get("kind") == "probe" else sink).append(e)

    def assert_mask(page):
        page.wait_for_function("window.__dsMaskReady === true", timeout=tmo["assert_ms"])
        return page.evaluate("window.__dsMask.assertMasked()")

    rec = None
    guard = None
    browser = None
    page = None
    with sync_playwright() as p:
        try:
            wa.hb("connect")
            browser = dev.connect(p, tmo["load_ms"])
            page = pick_page(browser, acfg.get("page_match"))
            if hasattr(dev, "prepare"):
                dev.prepare(page)
            ctx = page.context
            ctx.set_default_timeout(tmo["step_ms"])
            ctx.expose_function("__dsMaskSink", on_batch)
            mask_src = "window.__DS_MASK_CONFIG = " + json.dumps(cfg) + ";\n" + mask_js
            oracle_src = "window.__DS_ORACLE_CONFIG = " + json.dumps(ocfg) + ";\n" + oracle_js
            use_oracle = mask.get("oracle", True) and (ocfg["selectors"] or ocfg["regexes"] or ocfg["probes"] or mask_on)
            if mask_on:                      # future documents AND the current one (the app is already loaded)
                ctx.add_init_script(script=mask_src)
                page.evaluate("(() => {\n" + mask_src + "\n})()")
            if use_oracle:
                ctx.add_init_script(script=oracle_src)
                page.evaluate("(() => {\n" + oracle_src + "\n})()")
            # 1) preflight: BEFORE the recorder exists, a failure records nothing
            if prepare:
                wa.hb("prepare")
                prepare(sid, page)
            if mask_on:
                wa.hb("preflight")
                result["preflight"] = wa.summarize(assert_mask(page))
                bad_re = [f for f in (result["preflight"] or {}).get("failures") or [] if f.get("reason") == "invalid_regex"]
                if bad_re:
                    raise Refused("invalid regex (JS semantics): %s" % ", ".join(f["selector"] for f in bad_re))
                if not result["preflight"]["ok"]:
                    result.update(status="leak", reason="preflight assertion failed: nothing recorded")
                    return 11, result
                sink.clear()
                probes.clear()
            geo = page.evaluate("() => ({w: innerWidth, h: innerHeight, dpr: devicePixelRatio, "
                                "zoom: window.visualViewport ? visualViewport.scale : 1})")
            device_px, wv_rect = dev.geometry([geo["w"], geo["h"]], geo["dpr"])
            make_transform(geo["dpr"], wv_rect, device_px, device_px, [geo["w"], geo["h"]], geo["zoom"])   # fail before recording
            # 2) record
            wa.hb("record")
            rec = dev.recorder(acfg)
            rec.start(page, os.path.join(tmp, sid + ".raw"))
            t_page = page.evaluate(PAGE_EPOCH)
            result["t_page_epoch"] = t_page
            flashes = []
            pulse_window = None
            cx_dev, cy_dev = device_px[0] / 2.0, device_px[1] / 2.0
            center_in = wv_rect[0] <= cx_dev < wv_rect[0] + wv_rect[2] and wv_rect[1] <= cy_dev < wv_rect[1] + wv_rect[3]
            if center_in:
                for _ in range(PULSES):
                    flashes.append(page.evaluate(PULSE_ON))
                    page.wait_for_timeout(110)
                    page.evaluate(PULSE_OFF)
                    page.wait_for_timeout(95)
                page.wait_for_timeout(100)
                pulse_window = (flashes[0] - PULSE_PAD_MS, page.evaluate(PAGE_EPOCH) + PULSE_PAD_MS)
            result["calibration"] = "flash" if center_in else "page-start (WebView does not cover the clip centre)"
            if mask_on:
                result["inline"] = wa.summarize(assert_mask(page))
                if not result["inline"]["ok"]:
                    result.update(status="leak", reason="assertion failed before scene start: clip discarded")
                    _discard(rec)
                    rec = None
                    return 11, result
            before = page.evaluate("[scrollX, scrollY]")
            markers = []
            sctx = _MCtx(sid, page, int(spec.get("vo_ms") or 0), markers)
            guard = wa.TypeGuard(lambda: page)
            guard.active = mask_on and bool(mask.get("regexes"))
            if guard.active:
                guard.install()
            if page.evaluate("[scrollX, scrollY]") != before:
                raise StepError("start state moved between prepare and start")
            wa.hb("scene")
            sctx.start()
            scene_start = page.evaluate(PAGE_EPOCH)
            try:
                if fn:
                    fn(sctx)
            finally:
                guard.uninstall()
            sctx.end()
            scene_end = page.evaluate(PAGE_EPOCH)
            wa.hb("finalize")
            final = perf = None
            if mask_on:
                final = assert_mask(page)
                perf = page.evaluate("window.__dsMask.stats()")
                for e in page.evaluate("window.__dsMask.drain()"):
                    sink.append(e)
            for e in page.evaluate("window.__dsOracle ? window.__dsOracle.drain() : []") or []:
                (probes if e.get("kind") == "probe" else sink).append(e)
            page.wait_for_timeout(200)          # let the last batches reach the sink
            clip = rec.stop()
            rec = None
            cw, ch = probe_size(clip)
            tr = make_transform(geo["dpr"], wv_rect, device_px, [cw, ch], [geo["w"], geo["h"]], geo["zoom"])
            out = clip
            logp = os.path.join(tmp, sid + ".mask.jsonl")
            with open(logp, "w", encoding="utf-8") as f:
                for e in transform_log(sorted(sink, key=lambda e: e.get("t", 0)), tr, pulse_window):
                    f.write(json.dumps(e) + "\n")
            if probes:
                with open(os.path.join(tmp, sid + ".probe.jsonl"), "w", encoding="utf-8") as f:
                    for e in sorted(probes, key=lambda e: e["t"]):
                        f.write(json.dumps({"t": e["t"], "selector": e["selector"], "rect": apply_rect(tr, e["rect"]), "rect_css": e["rect"]}) + "\n")
            for m in markers:
                css = m.pop("_css", None)
                m["bbox"] = apply_rect(tr, css) if css else None
            sync = {"schema": 1, "scene": sid, "viewport": {"width": cw, "height": ch}, "transform": tr,
                    "clock": "page (device) epoch ms", "vfr": True, "t_page_epoch": t_page, "t_flashes": flashes,
                    "calibration": result["calibration"], "scene_start_epoch": scene_start, "scene_end_epoch": scene_end,
                    "mask_enabled": mask_on, "mask_mode": (final or {}).get("mode"),
                    "sensitive_present": wa.present(result.get("preflight"), result.get("inline"), final),
                    "markers": markers, "perf": perf, "preflight": result.get("preflight"), "inline": result.get("inline"),
                    "final": wa.summarize(final),
                    "untested_on_device": result["untested_on_device"], "simulated": result["simulated"]}
            sync["recorder"] = acfg.get("recorder", "auto") if not result["simulated"] else "simulated-cdp-screencast"
            sp = os.path.join(tmp, sid + ".sync.json")
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(sync, f)
            result.update(ok=True, status="ok", video=out, mask_log=logp, sync=sp, mask_log_entries=len(sink), transform=tr,
                          probe_log=os.path.join(tmp, sid + ".probe.jsonl") if probes else None)
            if mask_on and final and not final["ok"]:
                result.update(ok=False, status="leak", reason="final assertion failed")
                return 11, result
            return 0, result
        except PWTimeout as e:
            result.update(status="incomplete", error="timeout: " + str(e).splitlines()[0], at=wa._current)
            return 3, result
        except Refused as e:
            result.update(status="input", error=str(e), at=wa._current)
            return 2, result
        except StepError as e:
            result.update(status="step", error=str(e), error_class="step", at=wa._current)
            return 10, result
        except GeometryError as e:
            result.update(status="geometry", error=str(e), error_class="environment", at=wa._current)
            return 70, result
        except DeviceError as e:
            result.update(status="error", error=str(e), error_class="environment", at=wa._current)
            return 70, result
        except PWError as e:
            step = wa._current in ("scene", "prepare")
            result.update(status="step" if step else "error", error=str(e).splitlines()[0], at=wa._current,
                          error_class="step" if step else "environment")
            return (10 if step else 70), result
        finally:
            if guard:
                guard.uninstall()
            if rec is not None:
                _discard(rec)
            try:
                if page is not None:
                    page.evaluate(PULSE_OFF)
            except Exception:  # noqa: BLE001
                pass
            try:
                if browser:
                    browser.close()        # over CDP this only disconnects: the app keeps running
            except Exception:  # noqa: BLE001
                pass
            dev.close()


def _discard(rec):
    try:
        path = rec.stop()
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:  # noqa: BLE001
        pass


class _MCtx(wa.Ctx):
    """web Ctx whose marker bboxes are CSS px of the WebView at mark time; run() maps them to clip px at the end."""

    def _bbox(self, b):
        return None if b is None else list(b)

    def mark(self, type, bbox=None, label=""):
        super().mark(type, bbox, label)
        if bbox is not None:
            self._markers[-1]["_css"] = list(bbox)


def main(argv):
    try:
        with open(argv[0], encoding="utf-8") as f:
            spec = json.load(f)
        if not spec.get("tmp_dir") or not spec.get("scene"):
            raise ValueError("scene and tmp_dir required")
        if not isinstance(spec.get("android", {}), dict):
            raise ValueError("android must be an object")
        spec.setdefault("android", {})
    except (OSError, ValueError, IndexError) as e:
        print(json.dumps({"ok": False, "status": "input", "error": "bad spec: %s" % e}))
        return 2
    threading.Thread(target=wa._heartbeat_loop, daemon=True).start()
    try:
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise ToolMissing(["playwright"])
        code, result = run(spec)
    except ToolMissing as e:
        code, result = 4, {"ok": False, "status": "tool", "error": str(e), "missing": e.missing}
    except Refused as e:
        code, result = 2, {"ok": False, "status": "input", "error": str(e)}
    except StepError as e:
        code, result = 10, {"ok": False, "status": "step", "error": str(e), "error_class": "step"}
    except Exception as e:  # noqa: BLE001 - exit 70, never Python's 1
        if type(e).__name__ == "TimeoutError":
            code, result = 3, {"ok": False, "status": "incomplete", "error": str(e).splitlines()[0]}
        else:
            code, result = 70, {"ok": False, "status": "error", "error": "%s: %s" % (type(e).__name__, e), "at": wa._current}
            sys.stderr.write(traceback.format_exc())
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
