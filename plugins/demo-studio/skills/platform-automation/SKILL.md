---
name: platform-automation
description: Load when writing scene scripts or recording a demo on web, desktop (Windows/macOS/Electron) or mobile (Android/iOS) (scene-automator, app-scout). Scene script shape, pacing rules, failure handling, per-platform recorders.
---

# Platform automation

Read the section for `platform` in `demo.yaml` (`references/<web|desktop|mobile>.md` next to this file); skip the others.

## Scene script shape (web)
`.demo/<slug>/scenes.web.py` exports `SCENES = {"s01": s01, ...}`. Each scene function is `def s01(page, vo_ms):` with a Playwright sync `page`; `capture.py` opens the browser, applies the CSS mask, records one clip per scene and calls the function. The function resets its own start state first (navigate, log in with the demo account), then acts.

```python
def s03(page, vo_ms):
    page.goto(URL + "/invoices"); page.wait_for_load_state()
    page.wait_for_timeout(500)                       # no input in the first 500 ms
    btn = page.get_by_role("button", name="Create invoice")
    b = btn.bounding_box()
    page.mouse.move(b["x"] + b["width"]/2, b["y"] + b["height"]/2, steps=25)   # visible cursor travel
    btn.click()
    page.wait_for_timeout(max(0, vo_ms - 2000))      # hold to the end of the voice
```

## Pacing
- Scene length = `vo_ms` + hold (storyboard, default 0.4 s). Spread actions over the voice; narration leads the action by 0.3-0.5 s.
- Wait on elements, not fixed sleeps, except to fill time up to the voice length.
- Actions do not fit the voice: return `needs-input` (story adjusts); never speed up.
- Do not `scroll_into_view_if_needed` on sticky/fixed elements (the page jumps before the click).

## Privacy while recording
Use seeded data only. `capture.py --mask-selector` hides the selectors from `demo.yaml privacy.mask`. Never type real values; no scene may reveal a field that is not in the app-map sensitive list without adding it there.

## Failures
- **step** (selector not found, UI changed, unexpected dialog): fix the script.
- **environment** (timeout, crash, 0-byte clip): retry the scene, max 2, then `blocked`.
- Same step failure twice: report to the director with a screenshot, do not loop.

## Clip checks
After recording: `ffprobe` (size, fps, duration), not black, no padding, clip ends soon after the last action.
