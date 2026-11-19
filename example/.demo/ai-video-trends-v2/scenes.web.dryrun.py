"""Dry-run adapter for scenes.web.py (no recorder). Same prepare -> start sequence
as the web capture adapter (platform-automation web.md), virtual clock by default.

usage: python scenes.web.dryrun.py [--realtime] [s01 s02 ...]
Exit 0 = PASS. Markers on stdout are checked; summary on stderr.
"""
import importlib.util, json, pathlib, sys, io, contextlib, tempfile
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("scenes_web", HERE / "scenes.web.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

VIEW = {"width": 1280, "height": 720}
CURSOR_JS = """(()=>{const d=document.createElement('div');d.style.cssText='position:fixed;z-index:2147483647;pointer-events:none;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(255,80,60,.55);border:2px solid #fff;transition:transform .08s';
addEventListener('DOMContentLoaded',()=>document.documentElement.appendChild(d));
addEventListener('mousemove',e=>{d.style.left=e.clientX+'px';d.style.top=e.clientY+'px'},true);
addEventListener('mousedown',()=>d.style.transform='scale(.7)',true);addEventListener('mouseup',()=>d.style.transform='scale(1)',true)})()"""
SENSITIVE = {"s01": ["signed-in email"], "s02": ["signed-in email"], "s03": ["signed-in email"],
             "s04": ["signed-in email"], "s05": ["signed-in email"]}


def vo_ms():
    pj = json.loads((HERE / "project.json").read_text(encoding="utf-8"))
    return {s["id"]: round(s["duration_s"] * 1000) for s in pj["voice"]["scenes"]}


def run_scene(p, sid, vo, dry):
    browser = p.chromium.launch()
    context = browser.new_context(viewport=VIEW)
    context.add_init_script(CURSOR_JS)
    page = context.new_page()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            ctx = mod.Ctx(sid, page, vo, scale=1.0, dry=dry)
            if hasattr(mod, "prepare"): mod.prepare(sid, page)
            before = page.evaluate("[scrollX, scrollY]")
            ctx.start()
            if page.evaluate("[scrollX, scrollY]") != before:
                raise mod.StepError("start state moved between prepare and start")
            try:
                mod.SCENES[sid](ctx)
            finally:
                ctx.end()
    except Exception as e:
        shot = pathlib.Path(tempfile.gettempdir()) / f"{sid}-dryrun-fail.png"
        try: page.screenshot(path=str(shot))
        except Exception: shot = None
        print(json.dumps({"error_class": "step", "scene": sid, "detail": str(e)[:300],
                          "screenshot": str(shot) if shot else None}), file=sys.stderr)
        return None, None
    finally:
        context.close(); browser.close()
    return [json.loads(l) for l in buf.getvalue().splitlines() if l.startswith("{")], before


def check(sid, ms, vo):
    errs = []
    if not ms or ms[0]["type"] != "scene_start" or ms[-1]["type"] != "scene_end":
        errs.append("missing scene_start/scene_end")
    ts = [m["t"] for m in ms]
    if ts != sorted(ts): errs.append("t decreasing")
    for m in ms:
        b = m["bbox"]
        if b is not None and (b[2] <= 0 or b[3] <= 0 or b[0] < 0 or b[1] < 0
                              or b[0] + b[2] > VIEW["width"] or b[1] + b[3] > VIEW["height"]):
            errs.append(f"bbox out of frame/empty: {m}")
        if m["type"] in ("click", "key") and m["t"] < 500: errs.append(f"input before 500 ms: {m}")
    labels = {m["label"] for m in ms if m["type"] == "sensitive" and m["bbox"]}
    for need in SENSITIVE[sid]:
        if need not in labels: errs.append(f"sensitive not marked: {need}")
    end = ms[-1]["t"] if ms else 0
    if not (vo + 400 <= end <= vo + 1500): errs.append(f"length {end} outside {vo+400}..{vo+1500}")
    return errs, end


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--realtime" not in sys.argv
    vos = vo_ms(); sids = args or list(mod.SCENES)
    ok = 0; total_marks = 0
    with sync_playwright() as p:
        for sid in sids:
            ms, before = run_scene(p, sid, vos[sid], dry)
            if ms is None:
                print(f"FAIL {sid} step error", file=sys.stderr); continue
            errs, end = check(sid, ms, vos[sid])
            clicks = sum(m["type"] == "click" for m in ms); sens = sum(m["type"] == "sensitive" for m in ms)
            keys = sum(m["type"] == "key" for m in ms)
            total_marks += len(ms)
            st = "PASS" if not errs else "FAIL"
            ok += not errs
            print(f"{st} {sid} start={before} len={end}ms vo={vos[sid]} markers={len(ms)} "
                  f"click={clicks} key={keys} sensitive={sens}"
                  + ("" if not errs else " :: " + "; ".join(errs)), file=sys.stderr)
            if "--show" in sys.argv:
                for m in ms: print("   ", json.dumps(m), file=sys.stderr)
    line = f"DRY-RUN {'PASS' if ok == len(sids) else 'FAIL'} {ok}/{len(sids)} scenes, {total_marks} markers ({'virtual' if dry else 'realtime'} clock)"
    print(line, file=sys.stderr)
    sys.exit(0 if ok == len(sids) else 10)


if __name__ == "__main__":
    main()
