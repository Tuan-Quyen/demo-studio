---
name: platform-automation
description: Load when writing scene scripts or recording a demo on web, desktop or mobile (scene-automator, capture-operator, app-scout). Scene contract sNN(ctx), pacing, failures, per-platform recorders.
---

# Platform automation

Read the section for `platform` in `demo.yaml` (`references/<web|desktop|mobile>.md` next to this file); skip the others.

## Scene script shape (scene-automator writes, capture-operator records)
`.demo/<slug>/scenes.<platform>.py` defines one function per scene id: `def s01(ctx):`. `capture.py` opens the browser, injects the CSS mask, records one clip per scene and calls the function with `ctx`:
- `ctx.page`: the Playwright sync `Page`.
- `ctx.mark("name")`: records a key moment (time in ms from the start of the clip) into `media/sNN.marks.json`; sync-editor and motion-designer use it for trims and zooms.

Each scene resets its own start state first (navigate, log in with the demo account), then acts.

```python
def s03(ctx):
    page = ctx.page
    page.goto(URL + "/invoices"); page.wait_for_load_state()
    page.wait_for_timeout(500)                       # no input in the first 500 ms
    btn = page.get_by_role("button", name="Create invoice")
    b = btn.bounding_box()
    page.mouse.move(b["x"] + b["width"]/2, b["y"] + b["height"]/2, steps=25)   # visible cursor travel
    ctx.mark("create-click"); btn.click()
    page.wait_for_timeout(2000)                      # fill up to the voice length
```

## Pacing
- Scene length = VO duration (from voice-producer) + hold (storyboard, default 0.4 s). Spread actions over the voice; narration leads the action by 0.3-0.5 s.
- Wait on elements, not fixed sleeps, except to fill time up to the voice length.
- Actions do not fit the voice: return `needs-input` (scriptwriter/storyboarder adjust); never speed up.
- Do not `scroll_into_view_if_needed` on sticky/fixed elements (the page jumps before the click).

## Privacy while recording
Use seeded data only. capture-operator passes `capture.py --mask-selector`; it hides the selectors from `demo.yaml privacy.mask`. Never type real values; a sensitive field not in the app-map list goes back to app-scout / privacy-guard.

## Failures
- **step** (selector not found, UI changed, unexpected dialog): fix the script.
- **environment** (timeout, crash, 0-byte clip): retry the scene, max 2, then `blocked`.
- Same step failure twice: report to the director with a screenshot, do not loop.

## Clip checks
After recording: `ffprobe` (size, fps, duration), not black, no padding, clip ends soon after the last action.
