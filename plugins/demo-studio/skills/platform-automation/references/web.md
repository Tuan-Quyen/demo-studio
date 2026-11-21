# Platform: web (Playwright, Python)

Feature `capture` (playwright + chromium + ffmpeg). One browser context **per scene** so each scene is its own clip.

## Automation (scene-automator)
```python
def glide_click(ctx, locator, label):
    page = ctx.target
    b = locator.bounding_box()                       # CSS px, relative to main frame viewport
    vh = page.viewport_size["height"]
    if b["y"] < 0 or b["y"] + b["height"] > vh:      # scroll ONLY when off-screen
        locator.scroll_into_view_if_needed(); b = locator.bounding_box()
    cx, cy = b["x"] + b["width"]/2, b["y"] + b["height"]/2
    page.mouse.move(cx, cy, steps=25)                # visible cursor travel
    ctx.mark("click", [b["x"], b["y"], b["width"], b["height"]], label)
    page.mouse.click(cx, cy)

def s03(ctx):
    page = ctx.target
    ctx.hold_until(500)
    glide_click(ctx, page.get_by_role("button", name="Create invoice"), "Create invoice button")
    email = page.get_by_test_id("customer-email")
    email.wait_for()
    b = email.bounding_box(); ctx.sensitive([b["x"], b["y"], b["width"], b["height"]], "customer email")
    ctx.hold_until(ctx.vo_ms // 2)
    page.keyboard.type("Q4 retainer", delay=60); ctx.mark("key", None, "typed invoice title")
```
Never call `scroll_into_view_if_needed()` on an element in a sticky/fixed header or footer: Chromium scrolls the page to the element's in-flow position (observed: 1801 -> 1435 px) and with CSS `scroll-behavior:smooth` it animates, so the clip shows a jump before the click. Prefer role/test-id locators. `locator.click()` teleports the pointer and the video has no cursor, so use `glide_click` and the overlay below.

## Recorder adapter (capture-operator)
```python
from playwright.sync_api import sync_playwright
import shutil, pathlib, time
VIEW = {"width": 1280, "height": 720}                # the clip size: recordVideo size MUST equal the viewport
CURSOR_JS = """(()=>{const d=document.createElement('div');d.style.cssText='position:fixed;z-index:2147483647;pointer-events:none;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(255,80,60,.55);border:2px solid #fff;transition:transform .08s';
addEventListener('DOMContentLoaded',()=>document.documentElement.appendChild(d));
addEventListener('mousemove',e=>{d.style.left=e.clientX+'px';d.style.top=e.clientY+'px'},true);
addEventListener('mousedown',()=>d.style.transform='scale(.7)',true);addEventListener('mouseup',()=>d.style.transform='scale(1)',true)})()"""

def view_state(page): return page.evaluate("[scrollX, scrollY]")

def record_scene(p, mod, sid, out, vo_ms, dry=False):   # mod = scene module (SCENES, optional prepare)
    browser = p.chromium.launch()
    kw = dict(viewport=VIEW)                          # device_scale_factor 1: the clip is viewport-sized anyway
    if not dry:
        kw.update(record_video_dir=str(out/"tmp"), record_video_size=VIEW)
    context = browser.new_context(**kw)
    context.add_init_script(CURSOR_JS)
    page = context.new_page(); t_page = time.monotonic()
    ctx = Ctx(sid, page, vo_ms, scale=1.0, dry=dry)   # Ctx from SKILL.md
    if hasattr(mod, "prepare"): mod.prepare(sid, page)  # SAME sequence in the dry-run; no goto/reload after this
    before = view_state(page)
    offset_ms = round((time.monotonic() - t_page) * 1000)   # recorded as clips[sid].offset_ms (verify with the frame check)
    ctx.start()
    if view_state(page) != before: raise StepError("start state moved between prepare and start")
    try:    mod.SCENES[sid](ctx)
    finally:
        ctx.end()                                     # scene_end; NOTHING after this but the close
        vpath = page.video.path() if not dry else None
        context.close()                               # stop recording now; video is finalized only on close
        browser.close()
    if vpath: shutil.move(vpath, out/f"media/{sid}.raw.webm")
```
Then `ffprobe` the clip, record `w,h,fps,duration_ms,offset_ms` in `#events` (the video starts at page creation, so `offset_ms` covers `prepare`; confirm with a frame at `offset_ms` showing the start state). Login/consent/cookie banners: do them in a **setup** context outside the recording and reuse `storage_state` so the clip starts on the target screen.

## bbox source
`locator.bounding_box()` -> CSS px relative to the main frame viewport; `scale` converts to recorded pixels. Re-read it right before the click (layout shifts). Element inside iframes: check the box against the main-frame viewport (verify in dry-run).

## Capture-time masking (privacy_mask.js, default for web)
Sensitive data is masked while recording, not blurred afterwards. `scripts/privacy_mask.js` is injected with `add_init_script` before any navigation; it never changes the app DOM (CSS Custom Highlight API for text, stylesheet rules for inputs, cover boxes in a closed shadow root for the rest; the only node it may add is that overlay host on `<html>`). It reads `window.__DS_MASK_CONFIG = {selectors, regexes, mask_style}` (`[data-sensitive]` is always included; `mask_style` `"solid"` default | `"blur"`).
```python
mask = (SCRIPTS/"privacy_mask.js").read_text()
context.add_init_script(script="window.__DS_MASK_CONFIG = " + json.dumps(cfg) + ";\n" + mask)
# before ctx.start(): fail closed, do not record when this is not ok
r = page.evaluate("window.__dsMaskReady === true && window.__dsMask.assertMasked()")
if not r or not r["ok"]: raise LeakError(r)      # exit 11; failures[] = {selector, reason, tag}
```
- `capture.py --url U --scene s03 --out-dir D --config mask.json [--actions a.json]` does all of it (Node recorder `capture_recorder.js`): non-recording preflight assertion, assertion again before the scene starts, recordVideo, `<sid>.mask.jsonl`, pixel cross-check, `<sid>.events.json` with `clips.<sid>.masked` and `unmaskable[]`. Exit: 0 ok, 2 bad input, 3 over budget, 4 missing tool, 11 leak (nothing is recorded when the assertion fails), 70 bug/env. The clip starts with ~1 s of calibration pulses (included in `offset_ms`). With `--slug S` it adds `demo.yaml` `privacy.selectors/regexes/mask_style/capture_mask` to the config and merges the clip + markers (scene-tagged, `masked` flags) into `.demo/S/project.json#events` as capture-operator; the action list is the JSON `--actions` file (`scenes.web.actions.sNN.json`).
- Log per rAF: `{t (epoch ms), kind:"masked", selector, count, rects:[[x,y,w,h]] (viewport CSS px, clipped by scroll containers, occluded rects dropped), state}`; `boxes` marks cover boxes (1 px sentinel border), `partial` rects half hidden.
- Rects that matter are in the clip's pixel space only when `scale` is 1 and the viewport equals the video size (already required above). `masked:true` is only written when 0 frames fail the pixel check.
- Limits (go to `unmaskable[]` / the post-hoc tier): regexes match one text node or one input value, so a value typed character by character shows its prefix until the regex matches (never type real secrets); cross-origin iframes, canvas/WebGL, closed or open shadow DOM, `title` tooltips and autofill are not masked; `mask_style:"blur"` is checked by assertion and log only.
- Do not wrap sensitive text in extra elements and do not add classes to app nodes for masking.

## Pitfalls
- `recordVideo` is capped at **25 fps** (all browsers) and **a `size` larger than the viewport does not scale**: the page is drawn 1:1 in the top-left of a grey canvas (a "crisp" clip with grey padding is a bug). So `size == viewport`, web raw = 25 fps, and render upscales without faking 60 fps (`media-specs` Encode). A bigger clip needs a bigger viewport (only if the app layout allows). `ffprobe` every clip and run the full-frame check.
- Stop right after `ctx.end()`: no wait, screenshot, ffprobe or logging before `context.close()` (held tails of 1.5-2 s were recorded past `scene_end`; report `tail_ms` = clip duration - `offset_ms` - `scene_end` `t` per clip). capture-operator records the real `duration_ms` and compares it with `offset_ms` + `scene_end` `t`; sync-editor trims `out` to that as the fallback.
- Video is empty if the context is not closed; a crash mid-scene loses the clip (environment error -> retry).
- No cursor, no hover-only tooltips from OS: use the overlay; keep animations on (do not set `reduced_motion`) unless they jitter.
- Cookie banners, chat widgets, autofill prompts, update toasts: dismiss in setup or block via `add_init_script` CSS.
- Real data on screen -> `ctx.sensitive` on every private element, including tab titles and URLs (hide the URL bar by recording page content only; headless has none).
- Headless fonts differ from headed: keep one mode for all scenes.
