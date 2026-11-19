"""Dry-run adapter for scenes.web.py (no recorder). Same sequence as the web capture adapter
(platform-automation web.md): new context -> prepare(sid, page) -> record scrollX/Y ->
ctx.start() -> assert start state unchanged -> SCENES[sid](ctx) -> ctx.end(). Virtual clock by default.

usage: <toolkit python> scenes.web.dryrun.py [--realtime] [--show] [s01 s02 ...]
Exit 0 = PASS, 10 = step failure. Summary on stderr.
"""
import contextlib, importlib.util, io, json, pathlib, sys, tempfile
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("scenes_web", HERE / "scenes.web.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
from demo_ctx import Ctx  # noqa: E402  (scenes.web.py put HERE on sys.path)

VIEW = {"width": 1280, "height": 720}
CURSOR_JS = """(()=>{const d=document.createElement('div');d.style.cssText='position:fixed;z-index:2147483647;pointer-events:none;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(255,80,60,.55);border:2px solid #fff;transition:transform .08s';
addEventListener('DOMContentLoaded',()=>document.documentElement.appendChild(d));
addEventListener('mousemove',e=>{d.style.left=e.clientX+'px';d.style.top=e.clientY+'px'},true);
addEventListener('mousedown',()=>d.style.transform='scale(.7)',true);addEventListener('mouseup',()=>d.style.transform='scale(1)',true)})()"""
API_IN_TRANSIT = {"s08", "s10"}        # storyboard: API key passes through the frame


def vo_ms():
    pj = json.loads((HERE / "project.json").read_text(encoding="utf-8"))
    return {s["id"]: round(s["duration_s"] * 1000) for s in pj["voice"]["scenes"]}


def api_visible(page):
    b = page.get_by_test_id("api-key").bounding_box()
    return bool(b) and b["y"] < VIEW["height"] - 1 and b["y"] + b["height"] > 1


def run_scene(p, sid, vo, dry):
    browser = p.chromium.launch()
    context = browser.new_context(viewport=VIEW)
    context.add_init_script(CURSOR_JS)
    page = context.new_page()
    buf, info = io.StringIO(), {}
    try:
        with contextlib.redirect_stdout(buf):
            ctx = Ctx(sid, page, vo, scale=1.0, dry=dry)
            mod.prepare(sid, page)
            before = page.evaluate("[scrollX, scrollY]")
            info["start"], info["api_start"] = before, api_visible(page)
            ctx.start()
            if page.evaluate("[scrollX, scrollY]") != before:
                raise mod.StepError("start state moved between prepare and start")
            try:
                mod.SCENES[sid](ctx)
            finally:
                ctx.end()
            info["api_end"] = api_visible(page)
            info["end_state"] = page.evaluate("[scrollX, scrollY]")
    except Exception as e:
        shot = pathlib.Path(tempfile.gettempdir()) / f"{sid}-dryrun-fail.png"
        try: page.screenshot(path=str(shot))
        except Exception: shot = None
        print(json.dumps({"error_class": "step", "scene": sid, "detail": str(e)[:300],
                          "screenshot": str(shot) if shot else None}), file=sys.stderr)
        return None, info
    finally:
        context.close(); browser.close()
    return [json.loads(l) for l in buf.getvalue().splitlines() if l.startswith("{")], info


def check(sid, ms, vo, info):
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
    if "signed-in email" not in labels: errs.append("pill not marked")
    need_api = info.get("api_start") or info.get("api_end") or sid in API_IN_TRANSIT
    if need_api and "API key" not in labels: errs.append("API key in frame but not marked")
    if not need_api and "API key" in labels: errs.append("API key marked but never in frame?")
    end = ms[-1]["t"] if ms else 0
    want = mod.SCENE_LEN[sid]
    if not (want - 60 <= end <= want + 60) or end < vo + 400:
        errs.append(f"length {end} != storyboard {want} (vo {vo})")
    return errs, end, need_api


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--realtime" not in sys.argv
    vos = vo_ms(); sids = args or list(mod.SCENES)
    ok = total = 0
    with sync_playwright() as p:
        for sid in sids:
            ms, info = run_scene(p, sid, vos[sid], dry)
            if ms is None:
                print(f"FAIL {sid} step error", file=sys.stderr); continue
            errs, end, need_api = check(sid, ms, vos[sid], info)
            n = lambda typ, lab=None: sum(m["type"] == typ and (lab is None or m["label"] == lab) for m in ms)
            total += len(ms); ok += not errs
            print(f"{'PASS' if not errs else 'FAIL'} {sid} start={info['start']} end={info['end_state']} "
                  f"len={end}ms vo={vos[sid]} markers={len(ms)} click={n('click')} "
                  f"pill={n('sensitive', 'signed-in email')} apikey={n('sensitive', 'API key')}"
                  + ("" if not errs else " :: " + "; ".join(errs)), file=sys.stderr)
            if "--show" in sys.argv:
                for m in ms: print("   ", json.dumps(m), file=sys.stderr)
    print(f"DRY-RUN {'PASS' if ok == len(sids) else 'FAIL'} {ok}/{len(sids)} scenes, {total} markers "
          f"({'virtual' if dry else 'realtime'} clock)", file=sys.stderr)
    sys.exit(0 if ok == len(sids) else 10)


if __name__ == "__main__":
    main()
