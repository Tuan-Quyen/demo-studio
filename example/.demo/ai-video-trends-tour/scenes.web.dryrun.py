"""Dry-run adapter for scenes.web.py: same ctx, NO recorder, virtual clock.

Usage (from the workspace root):
  .demo/.venv/Scripts/python.exe .demo/ai-video-trends-tour/scenes.web.dryrun.py [--runs 2] [--height 720] [s01 ...]
Marks go to stdout (JSON lines); PASS/FAIL summary and errors go to stderr.
Exit 0 = PASS, 10 = step failure (JSON line with error_class on stderr + screenshot).
Viewport here is only for the dry run; the real one is capture-operator's.
"""
import argparse, importlib.util, json, pathlib, sys, time

HERE = pathlib.Path(__file__).resolve().parent
SLUG = HERE.name

# --- Ctx: reference core from skill platform-automation (verbatim) ---
TAIL_MS = 400
class Ctx:
    def __init__(self, scene, target, vo_ms, scale=1.0, origin=(0, 0), dry=False):
        self.scene, self.target, self.vo_ms = scene, target, vo_ms
        self.scale, self.origin, self.dry = scale, origin, dry
        self._t0, self._virt = time.monotonic(), 0
    def now(self):
        return max(int((time.monotonic() - self._t0) * 1000), self._virt)
    def _bbox(self, b):
        if b is None: return None
        ox, oy = self.origin
        return [round((b[0]-ox)*self.scale), round((b[1]-oy)*self.scale),
                round(b[2]*self.scale), round(b[3]*self.scale)]
    def mark(self, type, bbox=None, label=""):
        print(json.dumps({"t": self.now(), "scene": self.scene, "type": type,
                          "bbox": self._bbox(bbox), "label": label}), flush=True)
    def sensitive(self, bbox, label): self.mark("sensitive", bbox, label)
    def sensitive_end(self, label):   self.mark("sensitive", None, label)
    def hold_until(self, ms):
        if self.dry: self._virt = max(self._virt, ms); return
        left = ms - self.now()
        if left > 0: time.sleep(left / 1000)
    def start(self): self._t0 = time.monotonic(); self.mark("scene_start")
    def end(self):
        self.hold_until(self.vo_ms + TAIL_MS); self.mark("scene_end")


class RecCtx(Ctx):
    """Ctx that also keeps the marks for the PASS checks."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.marks = []
    def mark(self, type, bbox=None, label=""):
        m = {"t": self.now(), "scene": self.scene, "type": type, "bbox": self._bbox(bbox), "label": label}
        self.marks.append(m); print(json.dumps(m), flush=True)


REQUIRED_SENSITIVE = {"s01": ["signed-in email pill"], "s02": ["signed-in email pill"],
                      "s03": ["signed-in email pill", "API key"], "s04": ["signed-in email pill", "API key"]}


def load_scenes():
    spec = importlib.util.spec_from_file_location("scenes_web", HERE / "scenes.web.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def vo_ms_map():
    pj = json.loads((HERE / "project.json").read_text(encoding="utf-8"))
    return {s["id"]: round(s["duration_s"] * 1000) for s in pj["voice"]["scenes"]}


def check(sid, marks, vo_ms, W, H):
    errs = []
    if not marks or marks[0]["type"] != "scene_start" or marks[-1]["type"] != "scene_end":
        errs.append("missing scene_start/scene_end")
    ts = [m["t"] for m in marks]
    if ts != sorted(ts): errs.append("t not non-decreasing")
    labels = {m["label"] for m in marks if m["type"] == "sensitive"}
    for need in REQUIRED_SENSITIVE.get(sid, []):
        if need not in labels: errs.append(f"sensitive not marked: {need}")
    for m in marks:
        b = m["bbox"]
        if b is None: continue
        x, y, w, h = b
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > W or y + h > H:
            errs.append(f"bbox outside frame/empty: {m}")
    if not any(m["type"] == "click" for m in marks) and sid != "s01":
        errs.append("no click mark")
    end = marks[-1]["t"] if marks else 0
    if not (vo_ms + 400 <= end <= vo_ms + 1500 + 50):
        errs.append(f"scene length {end} ms outside [vo+400, vo+1500] (vo {vo_ms})")
    if any(m["t"] < 500 for m in marks if m["type"] == "click"):
        errs.append("input in first 500 ms")
    return errs, end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes", nargs="*")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--realtime", action="store_true", help="real pauses (timing check), still no recorder")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    mod = load_scenes(); vo = vo_ms_map()
    ids = a.scenes or list(mod.SCENES)
    W, H = a.width, a.height
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for run in range(1, a.runs + 1):
            total = 0
            for sid in ids:
                context = browser.new_context(viewport={"width": W, "height": H})
                page = context.new_page()
                ctx = RecCtx(sid, page, vo[sid], scale=1.0, dry=not a.realtime)
                try:
                    mod.prepare(sid, page)
                    ctx.start(); mod.SCENES[sid](ctx); ctx.end()
                except Exception as e:
                    shot = HERE / "logs" / f"{sid}-fail.png"; shot.parent.mkdir(exist_ok=True)
                    try: page.screenshot(path=str(shot))
                    except Exception: pass
                    print(json.dumps({"error_class": "step", "scene": sid, "detail": f"{type(e).__name__}: {e}",
                                      "screenshot": f"logs/{sid}-fail.png"}), file=sys.stderr)
                    context.close(); browser.close(); sys.exit(10)
                context.close()
                errs, end = check(sid, ctx.marks, vo[sid], W, H)
                n = {k: sum(m["type"] == k for m in ctx.marks) for k in ("click", "sensitive")}
                print(f"[run {run}] {sid}: {'ok' if not errs else 'FAIL'} len={end}ms vo={vo[sid]}ms "
                      f"marks={len(ctx.marks)} clicks={n['click']} sensitive={n['sensitive']}", file=sys.stderr)
                if errs:
                    print(json.dumps({"error_class": "step", "scene": sid, "detail": "; ".join(errs)}), file=sys.stderr)
                    browser.close(); sys.exit(10)
                total += 1
            print(f"DRY-RUN PASS run {run}: {total}/{len(ids)} scenes ({W}x{H})", file=sys.stderr)
        browser.close()


if __name__ == "__main__":
    main()
