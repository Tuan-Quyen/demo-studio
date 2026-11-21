#!/usr/bin/env python3
"""Record one web scene with Playwright (Python).

capture.py --scenes scenes.web.py --scene s01 --url URL --out media/ [--mask-selector S ...] [--viewport 1920x1080] [--timeout 120]
  -> media/<scene>.raw.webm and media/<scene>.marks.json ({"marks":[{"name","t_ms"}]}); JSON summary on stdout.
Scene module: `def s01(ctx)` using ctx.page (Playwright Page) and ctx.mark("name").
Privacy: every --mask-selector (demo.yaml privacy.mask) is hidden by an injected CSS rule (text, input values, svg text).
Exit: 0 ok, 2 error, 3 timeout.
"""
import argparse
import importlib.util
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import out  # noqa: E402

MASK_JS = """(sels) => {
  const css = sels.map(s => s + "{color:transparent!important;-webkit-text-fill-color:transparent!important;" +
    "background:#222!important;text-shadow:none!important;fill:transparent!important;caret-color:transparent!important}").join("\\n");
  const add = () => {
    const root = document.head || document.documentElement;
    if (!root || document.getElementById("__demo_mask")) return;
    const st = document.createElement("style"); st.id = "__demo_mask"; st.textContent = css;
    root.appendChild(st);
  };
  add(); document.addEventListener("DOMContentLoaded", add);
  new MutationObserver(add).observe(document, {childList: true, subtree: true});
}"""


class Ctx:
    def __init__(self, page, t0):
        self.page, self._t0, self.marks = page, t0, []

    def mark(self, name):
        self.marks.append({"name": name, "t_ms": int((time.monotonic() - self._t0) * 1000)})


def load_scene(path, scene):
    spec = importlib.util.spec_from_file_location("scene_module", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, scene, None)
    if not callable(fn):
        raise ValueError("scene function %r not found in %s" % (scene, path))
    return fn


def record(args):
    from playwright.sync_api import sync_playwright
    fn = load_scene(args.scenes, args.scene)
    w, h = (int(x) for x in args.viewport.lower().split("x"))
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="demo-cap-")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            try:
                ctx = browser.new_context(viewport={"width": w, "height": h}, record_video_dir=tmp,
                                          record_video_size={"width": w, "height": h})
                if args.mask_selector:
                    ctx.add_init_script("(" + MASK_JS + ")(" + json.dumps(args.mask_selector) + ")")
                page = ctx.new_page()
                t0 = time.monotonic()
                page.goto(args.url, wait_until="load")
                c = Ctx(page, t0)
                fn(c)
                video = page.video
                ctx.close()  # finalizes the webm
                src = video.path()
            finally:
                browser.close()
        dst = outdir / (args.scene + ".raw.webm")
        shutil.move(src, dst)
        marks = outdir / (args.scene + ".marks.json")
        marks.write_text(json.dumps({"marks": c.marks}, indent=1))
        return {"ok": True, "video": str(dst), "marks": str(marks), "n_marks": len(c.marks),
                "masked": len(args.mask_selector)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenes", required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", default="media")
    ap.add_argument("--mask-selector", action="append", default=[])
    ap.add_argument("--viewport", default="1920x1080")
    ap.add_argument("--timeout", type=int, default=120, help="whole-run limit in seconds")
    args = ap.parse_args(argv)

    def on_alarm(*_):
        raise TimeoutError("capture exceeded %ss" % args.timeout)

    signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(args.timeout)
    # backstop if the alarm handler cannot run (blocked native call)
    guard = threading.Timer(args.timeout + 15, lambda: os._exit(3))
    guard.daemon = True
    guard.start()
    try:
        out(record(args))
    except TimeoutError as e:
        out({"ok": False, "error": str(e)}, 3)
    except Exception as e:  # noqa: BLE001
        out({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 2)


if __name__ == "__main__":
    main()
