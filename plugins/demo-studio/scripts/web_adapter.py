#!/usr/bin/env python3
"""web_adapter.py - the fixed recorder adapter for web scenes (redesign 4.2 / 6.2; fix round F-CAPTURE).

Shipped with the plugin, never written per project. capture.py spawns it (run_bounded, jsonl heartbeat on stderr):

  python web_adapter.py <spec.json>

The scene script (`.demo/<slug>/scenes.web.py`: `SCENES = {sid: fn(ctx)}`, optional `prepare(sid, page)`) is the
single source of scene steps: it only does actions + `ctx.mark(...)`; it runs UNMODIFIED. This adapter owns
everything around it (Python Playwright, no Node):
  1. launches Chromium; injects privacy_mask.js + privacy_oracle.js with add_init_script BEFORE any navigation and
     exposes `__dsMaskSink` (expose_function) so the page streams its mask log out;
  2. NON-recording preflight context: goto url -> prepare -> mask ready -> `assertMasked()`. Not ok -> exit 11, nothing
     is ever recorded; an invalid regex (compiled by the browser, JS semantics) -> exit 2;
  3. recording context (record_video_dir = a TEMP dir, size == viewport): 5 calibration pulses on about:blank, goto,
     prepare, assertMasked again, start-state check, `ctx.start()`, scene function, `ctx.end()`, final assertMasked;
  4. typed text is checked against the regexes BEFORE the first keystroke (Keyboard/Locator/Page type, fill,
     press_sequentially, insert_text): on a match the target field is masked first, or the run is refused (exit 2);
  5. writes, into spec.tmp_dir: <sid>.raw.webm, <sid>.mask.jsonl, <sid>.sync.json (t_flashes, scene_start_epoch,
     scene_end_epoch, markers, assertion summaries), optional <sid>.probe.jsonl; prints ONE JSON line.
It decides nothing about the clip: capture.py's gate re-verifies everything from the files.

Exit: 0 ok | 2 bad spec / refused typed text / invalid regex | 3 over budget | 10 scene step failed |
11 mask assertion failed (nothing kept) | 70 environment/unexpected.
"""
import importlib.util
import json
import os
import shutil
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TAIL_MS = 400


class Refused(Exception):
    pass


class StepError(Exception):
    pass


_current = "init"


def hb(step=None):
    global _current
    if step:
        _current = step
    sys.stderr.write(json.dumps({"hb": int(time.time() * 1000), "step": _current}) + "\n")
    sys.stderr.flush()


def _heartbeat_loop():
    while True:
        time.sleep(2)
        hb()


def now_ms():
    return time.time() * 1000.0


class Ctx:
    """Same API as demo_ctx.Ctx (platform-automation), markers kept in-process."""

    def __init__(self, scene, page, vo_ms, markers):
        self.scene, self.target, self.vo_ms = scene, page, vo_ms
        self.scale, self.origin, self.dry = 1.0, (0, 0), False
        self._t0 = time.monotonic()
        self._markers = markers

    def now(self):
        return int((time.monotonic() - self._t0) * 1000)

    def _bbox(self, b):
        if b is None:
            return None
        ox, oy = self.origin
        return [round((b[0] - ox) * self.scale), round((b[1] - oy) * self.scale),
                round(b[2] * self.scale), round(b[3] * self.scale)]

    def mark(self, type, bbox=None, label=""):
        self._markers.append({"t": self.now(), "scene": self.scene, "type": type, "bbox": self._bbox(bbox), "label": label})

    def sensitive(self, bbox, label):
        self.mark("sensitive", bbox, label)

    def sensitive_end(self, label):
        self.mark("sensitive", None, label)

    def hold_until(self, ms):       # the ONLY way to wait; pumps Playwright so the mask sink keeps draining
        left = ms - self.now()
        if left > 0:
            self.target.wait_for_timeout(left)

    def start(self):
        self._t0 = time.monotonic()
        self.mark("scene_start")

    def end(self):
        self.hold_until(self.vo_ms + TAIL_MS)
        self.mark("scene_end")


# ------------------------------------------------------------------ typed-text guard (S-08)
class TypeGuard:
    """While privacy regexes are configured, EVERY field that receives typing is masked before the first key (S-08,
    fail closed: no regex has to match, so split calls and prefixes cannot show). If the target cannot be pre-masked
    (not an input/textarea/contenteditable) and the text (or the text typed so far) matches a regex, the run is
    refused. Covered paths: Keyboard.type/press/down/insert_text, Locator/Page/Frame type, fill, press,
    press_sequentially, ElementHandle type/fill/press."""

    def __init__(self, get_page):
        self.get_page = get_page
        self.buf = ""
        self.active = False
        self._orig = []

    def _hit(self, text):
        return bool(self.get_page().evaluate("t => !!(window.__dsMask && window.__dsMask.testText(t))", text))

    def before(self, text, locator=None, handle=None):
        if not self.active or not isinstance(text, str) or not text:
            return
        buf = (self.buf + text)[-400:]
        page = self.get_page()
        if handle is not None:
            r = handle.evaluate("el => window.__dsMask.forceMask(el)")
        elif locator is not None:
            r = locator.first.evaluate("el => window.__dsMask.forceMask(el)")
        else:
            r = page.evaluate("() => window.__dsMask.forceMask(document.activeElement)")
        if not r:
            if self._hit(text) or self._hit(buf):
                raise Refused("typed text matches a privacy regex but the target cannot be masked before the first key "
                              "(not an input/textarea/contenteditable): not typed")
        elif r == 2:    # newly masked: the overlay is drawn by the mask loop on its next frame; wait until it has painted
            page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r))))")
        self.buf = buf

    def install(self):
        from playwright.sync_api import ElementHandle, Frame, Keyboard, Locator, Page
        guard = self

        def wrap(cls, name, kind, reset=False):
            orig = getattr(cls, name, None)
            if orig is None:
                return

            def f(self_, *a, **kw):
                if kind == "kb":
                    text = a[0] if a else kw.get("text") or kw.get("key")
                    if isinstance(text, str) and (len(text) == 1 or name in ("type", "insert_text")):
                        guard.before(text)
                elif kind == "loc":
                    text = a[0] if a else kw.get("text") or kw.get("value") or kw.get("key")
                    if name != "press" or (isinstance(text, str) and len(text) == 1):
                        guard.before(text, locator=self_)
                elif kind == "handle":
                    text = a[0] if a else kw.get("text") or kw.get("value") or kw.get("key")
                    if name != "press" or (isinstance(text, str) and len(text) == 1):
                        guard.before(text, handle=self_)
                else:   # Page / Frame: (selector, text)
                    text = a[1] if len(a) > 1 else kw.get("text") or kw.get("value") or kw.get("key")
                    if name != "press" or (isinstance(text, str) and len(text) == 1):
                        guard.before(text, locator=self_.locator(a[0] if a else kw.get("selector")))
                if reset:
                    guard.buf = ""
                return orig(self_, *a, **kw)
            setattr(cls, name, f)
            self._orig.append((cls, name, orig))

        for n in ("type", "press_sequentially", "press"):
            wrap(Locator, n, "loc")
            wrap(ElementHandle, n, "handle")
        wrap(Locator, "fill", "loc", reset=True)
        wrap(ElementHandle, "fill", "handle", reset=True)
        for cls in (Page, Frame):
            for n in ("type", "press"):
                wrap(cls, n, "pf")
            wrap(cls, "fill", "pf", reset=True)
        for n in ("type", "insert_text", "press", "down"):
            wrap(Keyboard, n, "kb")

    def uninstall(self):
        for cls, name, orig in reversed(self._orig):
            setattr(cls, name, orig)
        self._orig = []


# ------------------------------------------------------------------ main
def load_scene(path, sid):
    d = os.path.dirname(os.path.abspath(path))
    sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location("ds_scenes", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    scenes = getattr(mod, "SCENES", None)
    if not isinstance(scenes, dict) or sid not in scenes:
        raise Refused("scene script has no SCENES[%r]" % sid)
    return mod, scenes[sid]


def summarize(a):
    if not a:
        return None
    return {"ok": a.get("ok"), "mode": a.get("mode"), "checked": a.get("checked"), "failures": a.get("failures"),
            "regex_hits": a.get("regex_hits"), "regex_labels": a.get("regex_labels"), "unmaskable": a.get("unmaskable")}


def present(*asserts):
    for a in asserts:
        if not a:
            continue
        if (a.get("regex_hits") or 0) > 0 or any((c.get("rendered") or 0) > 0 for c in a.get("checked") or []):
            return True
    return False


def run(spec):
    from playwright.sync_api import Error as PWError, TimeoutError as PWTimeout, sync_playwright
    tmo = dict({"load_ms": 15000, "assert_ms": 5000, "step_ms": 15000, "total_ms": 90000}, **(spec.get("timeouts") or {}))
    sid, url, vp = spec["scene"], spec["url"], spec["viewport"]
    mask = spec.get("mask") or {}
    mask_on = bool(mask.get("enabled"))
    tmp = spec["tmp_dir"]
    os.makedirs(tmp, exist_ok=True)
    result = {"ok": False, "status": "error", "mask_enabled": mask_on}
    mask_js = open(os.path.join(HERE, "privacy_mask.js"), encoding="utf-8").read()
    oracle_js = open(os.path.join(HERE, "privacy_oracle.js"), encoding="utf-8").read()
    cfg = {k: v for k, v in mask.items() if k != "enabled"}
    ocfg = {"selectors": mask.get("selectors", []), "regexes": mask.get("regexes", []), "probes": spec.get("probes") or []}
    mod = fn = None
    if spec.get("scene_script"):
        mod, fn = load_scene(spec["scene_script"], sid)
    prepare = getattr(mod, "prepare", None) if mod else None

    sink, probes = [], []

    def on_batch(batch):
        for e in batch:
            (probes if e.get("kind") == "probe" else sink).append(e)

    def new_context(browser, record):
        kw = {"viewport": vp}
        if record:
            kw.update(record_video_dir=os.path.join(tmp, "pw"), record_video_size=vp)
        ctx = browser.new_context(**kw)
        ctx.set_default_timeout(tmo["step_ms"])
        ctx.set_default_navigation_timeout(tmo["load_ms"])
        ctx.expose_function("__dsMaskSink", on_batch)
        if mask_on:
            ctx.add_init_script(script="window.__DS_MASK_CONFIG = " + json.dumps(cfg) + ";\n" + mask_js)
        if mask.get("oracle", True) and (ocfg["selectors"] or ocfg["regexes"] or ocfg["probes"] or mask_on):
            ctx.add_init_script(script="window.__DS_ORACLE_CONFIG = " + json.dumps(ocfg) + ";\n" + oracle_js)
        return ctx

    def assert_mask(page):
        page.wait_for_function("window.__dsMaskReady === true", timeout=tmo["assert_ms"])
        return page.evaluate("window.__dsMask.assertMasked()")

    def config_errors(a):
        return [f for f in (a.get("failures") or []) if f.get("reason") == "invalid_regex"]

    with sync_playwright() as p:
        hb("launch")
        browser = p.chromium.launch(headless=spec.get("headless", True))
        guard = TypeGuard(lambda: page)
        page = None
        try:
            # 1) preflight in a NON-recording context: a failure means nothing is ever recorded
            if mask_on and spec.get("preflight", True):
                hb("preflight")
                pctx = new_context(browser, False)
                page = pctx.new_page()
                page.goto(url, wait_until="domcontentloaded")
                if prepare:
                    hb("prepare")
                    prepare(sid, page)
                result["preflight"] = summarize(assert_mask(page))
                bad_re = config_errors(result["preflight"] or {})
                pctx.close()
                sink.clear()
                probes.clear()
                if bad_re:
                    raise Refused("invalid regex (JS semantics): %s" % ", ".join(f["selector"] for f in bad_re))
                if not result["preflight"]["ok"]:
                    result.update(status="leak", reason="preflight assertion failed: nothing recorded")
                    return 11, result

            # 2) record
            hb("record")
            ctx = new_context(browser, True)
            page = ctx.new_page()
            result["t_page_epoch"] = now_ms()
            flashes = []
            for _ in range(5):   # calibration pulses on about:blank (phases vary vs the 25 fps grid)
                flashes.append(page.evaluate("() => new Promise(res => requestAnimationFrame(ts => { "
                                             "document.documentElement.style.background = '#ff00ff'; res(performance.timeOrigin + ts); }))"))
                page.wait_for_timeout(110)
                page.evaluate("() => { document.documentElement.style.background = '#ffffff'; }")
                page.wait_for_timeout(95)
            page.wait_for_timeout(100)
            hb("goto")
            page.goto(url, wait_until="domcontentloaded")
            if mask_on:
                page.wait_for_function("window.__dsMaskReady === true", timeout=tmo["assert_ms"])
            if prepare:
                hb("prepare")
                prepare(sid, page)
            if mask_on:
                result["inline"] = summarize(assert_mask(page))
                if not result["inline"]["ok"]:
                    result.update(status="leak", reason="assertion failed before scene start: clip discarded")
                    ctx.close()
                    return 11, result
            before = page.evaluate("[scrollX, scrollY]")
            markers = []
            sctx = Ctx(sid, page, int(spec.get("vo_ms") or 0), markers)
            guard.active = mask_on and bool(mask.get("regexes"))
            if guard.active:
                guard.install()
            if page.evaluate("[scrollX, scrollY]") != before:
                raise StepError("start state moved between prepare and start")
            hb("scene")
            sctx.start()
            scene_start = now_ms()
            try:
                if fn:
                    fn(sctx)
            finally:
                guard.uninstall()
            sctx.end()
            scene_end = now_ms()
            hb("finalize")
            final = perf = None
            if mask_on:
                final = assert_mask(page)
                perf = page.evaluate("window.__dsMask.stats()")
                for e in page.evaluate("window.__dsMask.drain()"):
                    sink.append(e)
            for e in page.evaluate("window.__dsOracle ? window.__dsOracle.drain() : []") or []:
                (probes if e.get("kind") == "probe" else sink).append(e)
            vid = page.video
            ctx.close()                      # finalizes the video: nothing after this
            vpath = vid.path()
            out = os.path.join(tmp, sid + ".raw.webm")
            shutil.copyfile(vpath, out)
            shutil.rmtree(os.path.join(tmp, "pw"), ignore_errors=True)
            logp = os.path.join(tmp, sid + ".mask.jsonl")
            with open(logp, "w", encoding="utf-8") as f:
                for e in sorted(sink, key=lambda e: e.get("t", 0)):
                    f.write(json.dumps(e) + "\n")
            if probes:
                with open(os.path.join(tmp, sid + ".probe.jsonl"), "w", encoding="utf-8") as f:
                    for e in sorted(probes, key=lambda e: e["t"]):
                        f.write(json.dumps({"t": e["t"], "selector": e["selector"], "rect": e["rect"]}) + "\n")
            sync = {"schema": 1, "scene": sid, "viewport": vp, "t_page_epoch": result["t_page_epoch"], "t_flashes": flashes,
                    "scene_start_epoch": scene_start, "scene_end_epoch": scene_end, "mask_enabled": mask_on,
                    "mask_mode": (final or {}).get("mode"), "sensitive_present": present(result.get("preflight"), result.get("inline"), final),
                    "markers": markers, "perf": perf, "preflight": result.get("preflight"), "inline": result.get("inline"),
                    "final": summarize(final)}
            sp = os.path.join(tmp, sid + ".sync.json")
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(sync, f)
            result.update(ok=True, status="ok", video=out, mask_log=logp, sync=sp, mask_log_entries=len(sink),
                          probe_log=os.path.join(tmp, sid + ".probe.jsonl") if probes else None)
            if mask_on and final and not final["ok"]:
                result.update(ok=False, status="leak", reason="final assertion failed")
                return 11, result
            return 0, result
        except PWTimeout as e:
            result.update(status="incomplete", error="timeout: " + str(e).splitlines()[0], at=_current)
            return 3, result
        except Refused as e:
            result.update(status="input", error=str(e), at=_current)
            return 2, result
        except StepError as e:
            result.update(status="step", error=str(e), error_class="step", at=_current)
            return 10, result
        except PWError as e:
            step = _current in ("scene", "prepare")
            result.update(status="step" if step else "error", error=str(e).splitlines()[0], at=_current,
                          error_class="step" if step else "environment")
            return (10 if step else 70), result
        finally:
            guard.uninstall()
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass


def main(argv):
    try:
        with open(argv[0], encoding="utf-8") as f:
            spec = json.load(f)
        spec.setdefault("viewport", {"width": 1280, "height": 720})
        if not spec.get("url") or not spec.get("tmp_dir") or not spec.get("scene"):
            raise ValueError("url, scene and tmp_dir required")
    except (OSError, ValueError, IndexError) as e:
        print(json.dumps({"ok": False, "status": "input", "error": "bad spec: %s" % e}))
        return 2
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    try:
        code, result = run(spec)
    except Refused as e:
        code, result = 2, {"ok": False, "status": "input", "error": str(e)}
    except StepError as e:
        code, result = 10, {"ok": False, "status": "step", "error": str(e), "error_class": "step"}
    except Exception as e:  # noqa: BLE001 - exit 70, never Python's 1
        if type(e).__name__ == "TimeoutError":
            code, result = 3, {"ok": False, "status": "incomplete", "error": str(e).splitlines()[0]}
        elif _current in ("scene", "prepare"):
            code, result = 10, {"ok": False, "status": "step", "error_class": "step", "error": "%s: %s" % (type(e).__name__, str(e).splitlines()[0] if str(e) else "")}
            sys.stderr.write(traceback.format_exc())
        else:
            code, result = 70, {"ok": False, "status": "error", "error": "%s: %s" % (type(e).__name__, e), "at": _current}
            sys.stderr.write(traceback.format_exc())
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
