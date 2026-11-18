# Platform: web (Playwright, Python)

Feature `capture` (playwright + chromium + ffmpeg). One browser context **per scene** so each scene is its own clip.

## Automation (scene-automator)
```python
def glide_click(ctx, locator, label):
    page = ctx.target
    locator.scroll_into_view_if_needed()
    b = locator.bounding_box()                       # CSS px, relative to main frame viewport
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
Prefer role/test-id locators. `locator.click()` teleports the pointer and the video has no cursor, so use `glide_click` and the overlay below.

## Recorder adapter (capture-operator)
```python
from playwright.sync_api import sync_playwright
import shutil, pathlib
VIEW = {"width": 1280, "height": 720}
REC  = {"width": 2560, "height": 1440}               # 1440p master; scale = REC/VIEW = 2.0
CURSOR_JS = """(()=>{const d=document.createElement('div');d.style.cssText='position:fixed;z-index:2147483647;pointer-events:none;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(255,80,60,.55);border:2px solid #fff;transition:transform .08s';
addEventListener('DOMContentLoaded',()=>document.documentElement.appendChild(d));
addEventListener('mousemove',e=>{d.style.left=e.clientX+'px';d.style.top=e.clientY+'px'},true);
addEventListener('mousedown',()=>d.style.transform='scale(.7)',true);addEventListener('mouseup',()=>d.style.transform='scale(1)',true)})()"""

def record_scene(p, sid, fn, out, vo_ms, dry=False):
    browser = p.chromium.launch()
    kw = dict(viewport=VIEW, device_scale_factor=2)
    if not dry:
        kw.update(record_video_dir=str(out/"tmp"), record_video_size=REC)   # add record_video_fps=60 if supported (see pitfalls)
    context = browser.new_context(**kw)
    context.add_init_script(CURSOR_JS)
    page = context.new_page()
    ctx = Ctx(sid, page, vo_ms, scale=REC["width"]/VIEW["width"], dry=dry)   # Ctx from SKILL.md
    ctx.start()
    try:    fn(ctx)
    finally:
        ctx.end(); vpath = page.video.path() if not dry else None
        context.close()                               # video is finalized only on context.close()
        browser.close()
    if vpath: shutil.move(vpath, out/f"media/{sid}.raw.webm")
```
Then `ffprobe` the clip, record `w,h,fps,duration_ms,offset_ms` (~0 here: the video starts at page creation) in `#events`. Login/consent/cookie banners: do them in a **setup** context outside the recording and reuse `storage_state` so the clip starts on the target screen.

## bbox source
`locator.bounding_box()` -> CSS px relative to the main frame viewport; `scale` converts to recorded pixels. Re-read it right before the click (layout shifts). Element inside iframes: check the box against the main-frame viewport (verify in dry-run).

## Pitfalls
- `recordVideo` default is 25 fps and the picture is only **scaled down** to `size`; Firefox/WebKit are capped at 25 fps (Playwright docs). Use Chromium. 60 fps and 1440p from `new_context` are not guaranteed: `ffprobe` every clip; if it is below spec, fall back to viewport 1920x1080 = record size 1920x1080 and report the real fps in `#events`.
- Video is empty if the context is not closed; a crash mid-scene loses the clip (environment error -> retry).
- No cursor, no hover-only tooltips from OS: use the overlay; keep animations on (do not set `reduced_motion`) unless they jitter.
- Cookie banners, chat widgets, autofill prompts, update toasts: dismiss in setup or block via `add_init_script` CSS.
- Real data on screen -> `ctx.sensitive` on every private element, including tab titles and URLs (hide the URL bar by recording page content only; headless has none).
- Headless fonts differ from headed: keep one mode for all scenes.
