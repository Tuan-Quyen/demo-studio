#!/usr/bin/env python3
"""Mobile UI driver for demo-studio: read the screen and act on it (stdlib only, Python 3.9+).

No Appium. Android goes through `adb` (`uiautomator dump` for the element tree, `input` for taps,
typing, swipes, keys); it works on emulators and on phones with USB debugging. iOS goes through AXe
(`axe describe-ui`, `axe tap|type|swipe|button|key`) plus `xcrun simctl`; Simulator only (AXe does
not drive real devices).

Library (scene scripts; scene-automator copies this file verbatim to .demo/<slug>/):
    from mobile_driver import connect
    d = connect("android", device="emulator-5554")     # or connect("ios") for the booted Simulator
    el = d.find(id="new_invoice", timeout_ms=5000)     # StepError if it never appears
    ctx.mark("tap", el.bbox, "New invoice"); d.tap(el)

CLI (app-scout while mapping, scene-automator while writing or fixing a scene):
    mobile_driver.py --platform android|ios [--device ID] screen [--png f.png] [--json] [--all]
    mobile_driver.py ... tap (--id X | --label X | --text X | --xy X,Y) [--timeout-ms N]
    mobile_driver.py ... type TEXT | key NAME | swipe X1 Y1 X2 Y2 [--ms 300]
    mobile_driver.py ... launch APP [--activity A] | stop APP | size

Units: Android rects are device pixels; iOS rects are points (recorded frame = points x scale).
Exit codes: 0 ok, 1 element not found / bad input (step), 2 usage, 3 tool or device failure
(environment). Errors raised to scene scripts carry `error_class` = "step" | "environment".
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Callable, List, Optional, Sequence, Tuple

__all__ = ["El", "StepError", "EnvError", "AndroidDriver", "IOSDriver", "connect"]


class DriverError(Exception):
    error_class = "step"


class StepError(DriverError):
    """Element missing, wrong input, UI not as expected: scene-automator fixes the script."""
    error_class = "step"


class EnvError(DriverError):
    """adb/axe/simctl missing or failing, device offline: capture-operator may retry."""
    error_class = "environment"


@dataclass
class El:
    id: str            # Android resource-id (full), iOS AXUniqueId
    label: str         # Android content-desc, iOS AXLabel (the accessibility name)
    text: str          # Android text, iOS AXValue
    cls: str           # Android class, iOS element type
    rect: Tuple[int, int, int, int]   # x, y, w, h in driver units
    clickable: Optional[bool] = None  # None = platform does not say (iOS)
    password: bool = False
    focused: bool = False

    @property
    def center(self) -> Tuple[int, int]:
        x, y, w, h = self.rect
        return x + w // 2, y + h // 2

    @property
    def bbox(self) -> List[int]:
        """[x, y, w, h] in driver units, the form Ctx.mark() expects."""
        return list(self.rect)

    @property
    def short_id(self) -> str:
        return self.id.split(":id/", 1)[-1]


Runner = Callable[..., "subprocess.CompletedProcess"]


def _default_runner(cmd: Sequence[str], timeout: float = 30, binary: bool = False):
    return subprocess.run(list(cmd), capture_output=True, timeout=timeout, text=not binary,
                          stdin=subprocess.DEVNULL)


class _Base:
    platform = ""
    tool = ""

    def __init__(self, device: Optional[str] = None, runner: Optional[Runner] = None):
        self.device = device
        self._runner = runner or _default_runner

    # -- process -----------------------------------------------------------
    def _exec(self, cmd: Sequence[str], timeout: float = 30, binary: bool = False):
        try:
            res = self._runner(cmd, timeout=timeout, binary=binary)
        except FileNotFoundError:
            raise EnvError(f"{cmd[0]} not found on PATH")
        except subprocess.TimeoutExpired:
            raise EnvError(f"timed out after {timeout}s: {' '.join(cmd)}")
        if res.returncode != 0:
            err = res.stderr if isinstance(res.stderr, str) else (res.stderr or b"").decode("utf-8", "replace")
            raise EnvError(f"{' '.join(cmd)} exited {res.returncode}: {err.strip()[:300]}")
        return res.stdout

    # -- queries -----------------------------------------------------------
    def snapshot(self) -> List[El]:
        raise NotImplementedError

    def find(self, id: Optional[str] = None, label: Optional[str] = None, text: Optional[str] = None,
             contains: bool = False, index: int = 0, timeout_ms: int = 5000, poll_ms: int = 300) -> El:
        """First visible element matching every given field; polls until timeout_ms."""
        if not (id or label or text):
            raise StepError("find() needs id, label or text")
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            hits = [e for e in self.snapshot() if _matches(e, id, label, text, contains)]
            if len(hits) > index:
                return hits[index]
            if time.monotonic() >= deadline:
                want = ", ".join(f"{k}={v!r}" for k, v in (("id", id), ("label", label), ("text", text)) if v)
                raise StepError(f"element not found after {timeout_ms} ms: {want}")
            time.sleep(poll_ms / 1000)

    def exists(self, **kw) -> bool:
        try:
            self.find(timeout_ms=kw.pop("timeout_ms", 0), **kw)
            return True
        except StepError:
            return False

    # -- actions (implemented per platform) ---------------------------------
    def tap(self, target) -> None:
        raise NotImplementedError

    def _xy(self, target) -> Tuple[int, int]:
        if isinstance(target, El):
            return target.center
        x, y = target
        return int(x), int(y)


def _matches(e: El, id, label, text, contains: bool) -> bool:
    def ok(have: str, want: Optional[str]) -> bool:
        if want is None:
            return True
        return want in have if contains else have == want
    if id is not None and not (e.id == id or e.short_id == id or (contains and id in e.id)):
        return False
    return ok(e.label, label) and ok(e.text, text)


# ---------------------------------------------------------------------------
# Android (adb)
# ---------------------------------------------------------------------------
_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_SIZE = re.compile(r"(Physical|Override) size:\s*(\d+)x(\d+)")
_ANDROID_KEYS = {"back": "KEYCODE_BACK", "home": "KEYCODE_HOME", "enter": "KEYCODE_ENTER",
                 "tab": "KEYCODE_TAB", "delete": "KEYCODE_DEL", "menu": "KEYCODE_MENU",
                 "recents": "KEYCODE_APP_SWITCH", "escape": "KEYCODE_ESCAPE"}
_SHELL_SPECIAL = set("\\'\"`$&|;<>()*?~#![]{}")
DUMP_PATH = "/sdcard/demo_studio_ui.xml"


def parse_uiautomator(xml_text: str) -> List[El]:
    """Elements from a `uiautomator dump` XML (zero-size nodes dropped)."""
    start = xml_text.find("<?xml")
    if start < 0:
        start = xml_text.find("<hierarchy")
    end = xml_text.rfind("</hierarchy>")
    if start < 0 or end < 0:
        raise EnvError("uiautomator dump returned no hierarchy")
    root = ET.fromstring(xml_text[start:end + len("</hierarchy>")])
    out: List[El] = []
    for n in root.iter("node"):
        m = _BOUNDS.match(n.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        out.append(El(id=n.get("resource-id", ""), label=n.get("content-desc", ""),
                      text=n.get("text", ""), cls=n.get("class", "").rsplit(".", 1)[-1],
                      rect=(x1, y1, x2 - x1, y2 - y1), clickable=n.get("clickable") == "true",
                      password=n.get("password") == "true", focused=n.get("focused") == "true"))
    return out


def escape_input_text(text: str) -> str:
    """Escape for `adb shell input text` (runs in the device shell). ASCII only."""
    if any(ord(c) > 126 or (ord(c) < 32) for c in text):
        raise StepError("adb input text accepts printable ASCII only; use an ASCII seed value "
                        "or put the text on the clipboard in the app's own way")
    if "%s" in text:  # AOSP sendText turns every literal "%s" into a space; no escape exists
        raise StepError("adb input text cannot type a literal '%s' (Android turns it into a space); "
                        "change the seed value")
    out = []
    for c in text:
        if c == " ":
            out.append("%s")
        elif c in _SHELL_SPECIAL:
            out.append("\\" + c)
        else:
            out.append(c)
    return "".join(out)


class AndroidDriver(_Base):
    platform = "android"
    tool = "adb"

    def _adb(self, *args: str, timeout: float = 30, binary: bool = False):
        cmd = ["adb"] + (["-s", self.device] if self.device else []) + list(args)
        return self._exec(cmd, timeout=timeout, binary=binary)

    def _shell(self, command: str, timeout: float = 30) -> str:
        return self._adb("shell", command, timeout=timeout)

    def snapshot(self) -> List[El]:
        last = ""
        for _ in range(3):  # "could not get idle state" while animations run
            out = self._shell(f"uiautomator dump {DUMP_PATH}", timeout=30)
            if "ERROR" not in out:
                return parse_uiautomator(self._adb("exec-out", "cat", DUMP_PATH))
            last = out.strip()
            time.sleep(0.5)
        raise EnvError(f"uiautomator dump failed: {last[:200]}")

    def size(self) -> Tuple[int, int]:
        sizes = {kind: (int(w), int(h)) for kind, w, h in _SIZE.findall(self._shell("wm size"))}
        if not sizes:
            raise EnvError("could not read `wm size`")
        return sizes.get("Override") or sizes["Physical"]

    def tap(self, target) -> None:
        x, y = self._xy(target)
        self._shell(f"input tap {x} {y}")

    def type(self, text: str) -> None:
        self._shell(f"input text {escape_input_text(text)}")

    def key(self, name: str) -> None:
        code = _ANDROID_KEYS.get(name.lower(), name)
        if not re.fullmatch(r"KEYCODE_[A-Z0-9_]+|\d+", code):
            raise StepError(f"unknown key {name!r}; use {', '.join(_ANDROID_KEYS)} or KEYCODE_*")
        self._shell(f"input keyevent {code}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self._shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}")

    def launch(self, app: str, activity: Optional[str] = None) -> None:
        _check_app_id(app)
        if activity:
            _check_app_id(activity.lstrip("."))
            self._shell(f"am start -W -n {app}/{activity}")
        else:
            self._shell(f"monkey -p {app} -c android.intent.category.LAUNCHER 1")

    def stop(self, app: str) -> None:
        _check_app_id(app)
        self._shell(f"am force-stop {app}")

    def screenshot(self, path: str) -> None:
        data = self._adb("exec-out", "screencap", "-p", binary=True)
        with open(path, "wb") as fh:
            fh.write(data)


def _check_app_id(app: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.$/-]+", app):
        raise StepError(f"invalid app id {app!r}")


# ---------------------------------------------------------------------------
# iOS Simulator (AXe + simctl). Not verified on macOS by the plugin authors yet.
# ---------------------------------------------------------------------------
_AXFRAME = re.compile(r"\{\{\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\},\s*\{\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\}\}")
_IOS_HID = {"enter": 40, "escape": 41, "delete": 42, "tab": 43}


def _frame(node: dict) -> Optional[Tuple[int, int, int, int]]:
    fr = node.get("frame")
    if isinstance(fr, dict) and {"x", "y", "width", "height"} <= set(fr):
        vals = (fr["x"], fr["y"], fr["width"], fr["height"])
    else:
        m = _AXFRAME.match(str(node.get("AXFrame", "")))
        if not m:
            return None
        vals = tuple(float(v) for v in m.groups())
    x, y, w, h = (int(round(float(v))) for v in vals)
    return (x, y, w, h) if w > 0 and h > 0 else None


def parse_axe(data) -> List[El]:
    """Elements from `axe describe-ui` JSON (a list of roots or one root, nested `children`)."""
    if isinstance(data, str):
        data = json.loads(data)
    stack = list(data) if isinstance(data, list) else [data]
    out: List[El] = []
    while stack:
        n = stack.pop(0)
        if not isinstance(n, dict):
            continue
        rect = _frame(n)
        if rect:
            kind = str(n.get("type") or n.get("role") or "")
            out.append(El(id=str(n.get("AXUniqueId") or n.get("AXIdentifier") or n.get("identifier") or ""),
                          label=str(n.get("AXLabel") or n.get("label") or ""),
                          text=str(n.get("AXValue") or n.get("value") or ""),
                          cls=kind, rect=rect, clickable=None,
                          password="Secure" in kind))
        stack[0:0] = n.get("children") or []
    return out


class IOSDriver(_Base):
    platform = "ios"
    tool = "axe"

    def udid(self) -> str:
        if self.device and self.device != "booted":
            return self.device
        listing = json.loads(self._exec(["xcrun", "simctl", "list", "devices", "booted", "-j"]))
        for devs in listing.get("devices", {}).values():
            for d in devs:
                if d.get("state") == "Booted":
                    self.device = d["udid"]
                    return self.device
        raise EnvError("no booted iOS Simulator (xcrun simctl boot <udid> first)")

    def _axe(self, *args: str, timeout: float = 30) -> str:
        return self._exec(["axe", *args, "--udid", self.udid()], timeout=timeout)

    def snapshot(self) -> List[El]:
        return parse_axe(self._axe("describe-ui"))

    def size(self) -> Tuple[int, int]:
        els = self.snapshot()
        if not els:
            raise EnvError("axe describe-ui returned no elements")
        x, y, w, h = max(els, key=lambda e: e.rect[2] * e.rect[3]).rect
        return w, h

    def tap(self, target) -> None:
        x, y = self._xy(target)
        self._axe("tap", "-x", str(x), "-y", str(y))

    def type(self, text: str) -> None:
        self._axe("type", text)

    def key(self, name: str) -> None:
        low = name.lower()
        if low in ("home", "lock", "siri"):
            self._axe("button", low)
        elif low in _IOS_HID:
            self._axe("key", str(_IOS_HID[low]))
        elif name.isdigit():
            self._axe("key", name)
        else:
            raise StepError(f"unknown key {name!r}; use home, lock, {', '.join(_IOS_HID)} or a HID keycode")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self._axe("swipe", "--start-x", str(int(x1)), "--start-y", str(int(y1)),
                  "--end-x", str(int(x2)), "--end-y", str(int(y2)), "--duration", f"{ms / 1000:.2f}")

    def launch(self, app: str, activity: Optional[str] = None) -> None:
        _check_app_id(app)
        self._exec(["xcrun", "simctl", "launch", self.udid(), app])

    def stop(self, app: str) -> None:
        _check_app_id(app)
        try:
            self._exec(["xcrun", "simctl", "terminate", self.udid(), app])
        except EnvError as e:
            # Not running (fresh boot): simctl exits nonzero; stopping a stopped app is a no-op.
            msg = str(e).lower()
            if "found nothing to terminate" not in msg and "code=3" not in msg:
                raise

    def screenshot(self, path: str) -> None:
        self._exec(["xcrun", "simctl", "io", self.udid(), "screenshot", path])


def connect(platform: str, device: Optional[str] = None, runner: Optional[Runner] = None):
    if platform == "android":
        return AndroidDriver(device, runner)
    if platform == "ios":
        return IOSDriver(device, runner)
    raise ValueError(f"platform must be android or ios, not {platform!r}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def describe(e: El, i: int) -> str:
    flags = [f for f, on in (("clickable", e.clickable), ("password", e.password), ("focused", e.focused)) if on]
    if e.clickable and not (e.label or e.text or e.id):
        flags.append("UNNAMED")
    parts = [f"[{i}] tap={e.center[0]},{e.center[1]} rect={list(e.rect)}"]
    for k, v in (("id", e.id), ("label", e.label), ("text", e.text)):
        if v:
            parts.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
    parts.append(f"cls={e.cls}")
    return " ".join(parts + flags)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read and drive an Android device (adb) or iOS Simulator (AXe).")
    ap.add_argument("--platform", required=True, choices=["android", "ios"])
    ap.add_argument("--device", help="adb serial / Simulator UDID (default: the only/booted one)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("screen", help="list elements (and optionally save a screenshot)")
    s.add_argument("--png")
    s.add_argument("--json", action="store_true")
    s.add_argument("--all", action="store_true", help="include unnamed, non-clickable containers")
    t = sub.add_parser("tap")
    g = t.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--label")
    g.add_argument("--text")
    g.add_argument("--xy")
    t.add_argument("--timeout-ms", type=int, default=5000)
    sub.add_parser("type").add_argument("text")
    sub.add_parser("key").add_argument("name")
    w = sub.add_parser("swipe")
    for c in ("x1", "y1", "x2", "y2"):
        w.add_argument(c, type=int)
    w.add_argument("--ms", type=int, default=300)
    la = sub.add_parser("launch")
    la.add_argument("app")
    la.add_argument("--activity")
    sub.add_parser("stop").add_argument("app")
    sub.add_parser("size")
    args = ap.parse_args(argv)

    d = connect(args.platform, args.device)
    if shutil.which(d.tool) is None and d._runner is _default_runner:
        print(f"{d.tool} not found on PATH", file=sys.stderr)
        return 3
    try:
        if args.cmd == "screen":
            if args.png:
                d.screenshot(args.png)
            els = d.snapshot()
            shown = els if args.all else [e for e in els if e.id or e.label or e.text or e.clickable]
            if args.json:
                print(json.dumps([dict(asdict(e), center=list(e.center)) for e in shown],
                                 ensure_ascii=False, indent=1))
            else:
                unit = "px" if args.platform == "android" else "pt"
                print(f"{args.platform} elements={len(shown)} unit={unit}"
                      + (f" screenshot={args.png}" if args.png else ""))
                for i, e in enumerate(shown):
                    print(describe(e, i))
        elif args.cmd == "tap":
            if args.xy:
                try:
                    x, y = (int(v) for v in args.xy.split(","))
                except ValueError:
                    print("--xy needs X,Y", file=sys.stderr)
                    return 2
                d.tap((x, y))
            else:
                el = d.find(id=args.id, label=args.label, text=args.text, timeout_ms=args.timeout_ms)
                d.tap(el)
                print(describe(el, 0))
        elif args.cmd == "type":
            d.type(args.text)
        elif args.cmd == "key":
            d.key(args.name)
        elif args.cmd == "swipe":
            d.swipe(args.x1, args.y1, args.x2, args.y2, args.ms)
        elif args.cmd == "launch":
            d.launch(args.app, args.activity)
        elif args.cmd == "stop":
            d.stop(args.app)
        elif args.cmd == "size":
            w_, h_ = d.size()
            print(f"{w_}x{h_}")
    except StepError as e:
        print(json.dumps({"error_class": "step", "detail": str(e)}), file=sys.stderr)
        return 1
    except EnvError as e:
        print(json.dumps({"error_class": "environment", "detail": str(e)}), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
