# Platform: web (Playwright, Python)

Feature `capture` (python playwright + chromium + numpy + ffmpeg; no Node). One browser context **per scene** so each scene is its own clip.

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

## Recorder adapter (fixed: `scripts/web_adapter.py`, run by `capture.py`)
Never written per project, never copied. The Python scene script is the **single source of scene steps**: it exports `SCENES` and optional `prepare(sid, page)` and uses only `ctx` (actions + `mark()`); it runs unmodified. `capture.py run` spawns the adapter (Python Playwright, no Node; `run_bounded`, jsonl heartbeat) which does, per scene and in this order:
1. launch Chromium; `add_init_script` injects `privacy_mask.js` (mask) and `privacy_oracle.js` (independent DOM oracle) before any navigation; `expose_function("__dsMaskSink")` streams the page's mask log out;
2. **non-recording preflight context**: goto `--url` -> `prepare(sid, page)` (same sequence as the dry-run; it must be re-runnable) -> `assertMasked()`. Not ok -> exit 11 and nothing is recorded; a regex the browser (JS semantics) cannot compile -> exit 2;
3. **recording context** (`record_video_dir` = a TEMP dir, `size == viewport`, 25 fps): 5 calibration pulses on about:blank -> goto -> `prepare` -> `assertMasked()` -> start-state check -> `ctx.start()` -> `SCENES[sid](ctx)` -> `ctx.end()` -> final `assertMasked()` -> close (nothing after `ctx.end()` but those two calls and the close);
4. **typed text**: while regexes are configured, EVERY field that receives typing is masked before the first key (fail closed, no regex has to match, so split calls and prefixes cannot show): `Keyboard.type/press/down/insert_text`, `Locator/Page/Frame/ElementHandle` `type/fill/press/press_sequentially`. When the target cannot be pre-masked (not an input/textarea/contenteditable) and the text (or the text typed so far) matches a regex, the run is refused (exit 2). Never type real secrets anyway. Programmatic `.value` writes (v-model, prefill, `page.evaluate`) are caught too: the value setters are hooked and every input is re-tested each frame in both scripts, and the gate fails (`regex_hits_not_logged`) when the page's own assertions saw a regex hit the log never had;
5. sidecars in the temp dir: `sNN.raw.webm`, `sNN.mask.jsonl` (mask + oracle + unmaskable + tick entries), `sNN.sync.json` (`t_flashes`, `scene_start_epoch`, `scene_end_epoch`, markers, assertion summaries), optional `sNN.probe.jsonl`.
The adapter decides nothing: `capture.py gate` re-verifies from the files and only then renames the clip into `media/` and writes `#events`. The scene's `ctx.hold_until` uses `page.wait_for_timeout` (keeps the mask sink draining); pass `--vo-ms` (from `project.json#voice`) so scene length = VO. Scene step errors exit 10 (`step`, scene-automator's), Playwright timeouts exit 3.
Login/consent/cookie banners: do them in `prepare`, or in a setup context outside the recording that reuses `storage_state`, so the clip starts on the target screen.

## bbox source
`locator.bounding_box()` -> CSS px relative to the main frame viewport; `scale` converts to recorded pixels. Re-read it right before the click (layout shifts). Element inside iframes: check the box against the main-frame viewport (verify in dry-run).

## Capture-time masking (privacy_mask.js, default for web)
Sensitive data is masked while recording, not blurred afterwards. `privacy_mask.js` never changes the app DOM (CSS Custom Highlight API for text, stylesheet rules for inputs, cover boxes in a closed shadow root for the rest; the only node it may add is that overlay host on `<html>`). Config `window.__DS_MASK_CONFIG = {selectors, regexes, mask_style}` (`[data-sensitive]` always included).
- `python scripts/capture.py run --url U --scene s03 --scene-script .demo/<slug>/scenes.web.py --vo-ms N --slug S [--config mask.json] [--selector S] [--regex R]` (with `--slug`, `demo.yaml` `privacy.selectors/regexes/mask_style/capture_mask` are added). `capture.py gate --clip F --mask-log F --sync F [--slug S]` re-verifies an existing clip. Exit: 0 ok, 2 bad input (also refused typed text, invalid regex), 3 over budget, 4 missing tool (python playwright, numpy, ffmpeg; `setup_tools.py --plan capture`), 10 scene step failed, 11 leak / unverifiable / unmaskable (needs-input), 70 env.
- Top layer: `<dialog>.showModal()` / popovers paint above any z-index, so the overlay host is itself a manual popover re-shown (moved on top) whenever the set of top-layer elements changes; without popover support a modal over sensitive items is reported as unmaskable `top-layer`.
- The gate (pixels, trusts nothing from the adapter) fails when: the mask log is missing/empty; sensitive rects were on screen but none could be pixel-checked; any frame shows glyph edges or the wrong colour at a logged **or oracle** rect, or the log says `unmasked` (no grace for lead-in or appearing elements); soft (uniform, not mask-coloured, in steady state; appearing/disappearing elements are not soft) or resynced frames exceed `--max-soft` / `--max-resync` (**default 0**: secrets get no tolerance; alignment is re-calibrated once, then fails); no frame is strictly verified although rects were on screen (`no_strict_evidence`); the entry nearest in time (within 37 ms: video pts are quantised to 40 ms) shows glyph edges (a strict neighbour further away only counts as resync); soft frames within 100 ms (`EDGE_MS`) of the start or end of an element's run of log entries are not counted (it is appearing or disappearing); a frame is *carried* only when pixel-identical at the failing rects to the last strictly verified frame (the anchor: no drift) for at most 6 consecutive frames (a log gap needs a whole-frame repeat); viewport != clip size. Frames before the page was fully parsed or first painted are *unverified*: `clips[sid].safe_from_ms` = first verified clip time, the timeline must not use earlier frames (and `offset_ms >= safe_from_ms` is required).
- Occlusion is never inferred: overlays are always drawn, occluded rects are logged (`occluded`) and checked from pixels; only a DOM-proven opaque occluder (opacity chain 1, opaque first background) lets a rect be skipped (`skip`). A dimming modal backdrop over highlight-masked text gives uniform-but-dim pill frames (soft): use `--force-overlay` (overlay above the backdrop) or accept `--max-soft N` knowingly.
- The opacity proof ignores the owner's own ancestors and needs the occluder above the owner; an owner that is not hit-testable (`pointer-events:none`) never gets a proof.
- Independent oracle (S-09): `privacy_oracle.js` re-discovers sensitive text from the live DOM (selectors + regexes, own clipping/occlusion code, separate frame timing) and the gate checks pixels at those rects too, so overlays are not self-verified. What remains: it shares the selector/regex config, and the oracle measures after paint, the mask before paint; a lagging overlay is only caught inside the nearest-entry window (37 ms) plus the 90 ms resync window. Headless screencast frames can freeze for several frames during a fast scroll and then jump ahead (backpressure): the gate carries up to 6 frozen frames and fails `frames_unmasked` / `alignment_unstable` beyond that: re-record with a gentler scroll.
- `#events` `clips.<sid>`: `masked`, `safe_from_ms`, `unmaskable[]`, `mask{style, status, rects_checked, oracle_rects_checked, frames_unmasked, frames_soft, frames_resynced, thresholds{max_soft, max_resync, accepted_unmaskable}, ...}` (non-default thresholds are recorded so the verdict can flag them). `mask_style:"blur"` or `capture_mask:false`/`--no-mask` always give `masked:false` (post-hoc blur covers everything).
- **Unmaskable surfaces** are detected, never silent: `clips.<sid>.unmaskable[] = {surface, selector, reason, t_start, t_end (clip ms, padded by 300 ms: detection runs on mutation, at most every 60 ms, and every 250 ms), bbox:[x,y,w,h] clip px}` for iframes, canvas/video/object/embed, shadow DOM (open or closed) holding sensitive text/selectors, pseudo-element `content`, broken-image alt, hovered `title` tooltips (and `scan-budget` for DOM > 30000 nodes). Any live entry makes `capture.py` exit 11 / `needs-input` and the clip `masked:false` (clip kept) so privacy-blurrer covers it (`blur.py plan` fails closed without a covering region). `--accept-unmaskable <selector-or-surface>` lists an item as accepted (not blocking) - only on the user's recorded decision.
- Failure never leaves state: the clip is recorded to a temp dir and renamed only after the gate passes; on failure the temp dir is deleted and an existing `#events` clip entry becomes `masked:false`. The spec (regexes, typed text) lives in a private temp dir removed on every exit path; `runs.jsonl` and dry-run output never hold regex literals or URL query strings.
- Remaining untested/uncovered: native `<select>` popups, autofill dropdowns, background-image text, WebGL, text typed piecewise across separate calls (prefix shows until the regex matches), cross-document navigation mid-scene (re-asserted only at the end), cursors/OS overlays, headed mode.
- Do not wrap sensitive text in extra elements and do not add classes to app nodes for masking.

## Pitfalls
- `recordVideo` is capped at **25 fps** (all browsers) and **a `size` larger than the viewport does not scale**: the page is drawn 1:1 in the top-left of a grey canvas (a "crisp" clip with grey padding is a bug). So `size == viewport`, web raw = 25 fps, and render upscales without faking 60 fps (`media-specs` Encode). A bigger clip needs a bigger viewport (only if the app layout allows). `ffprobe` every clip and run the full-frame check.
- Stop right after `ctx.end()`: no wait, screenshot, ffprobe or logging before `context.close()` (held tails of 1.5-2 s were recorded past `scene_end`; report `tail_ms` = clip duration - `offset_ms` - `scene_end` `t` per clip). capture-operator records the real `duration_ms` and compares it with `offset_ms` + `scene_end` `t`; sync-editor trims `out` to that as the fallback.
- Video is empty if the context is not closed; a crash mid-scene loses the clip (environment error -> retry).
- No cursor, no hover-only tooltips from OS: use the overlay; keep animations on (do not set `reduced_motion`) unless they jitter.
- Cookie banners, chat widgets, autofill prompts, update toasts: dismiss in setup or block via `add_init_script` CSS.
- Real data on screen -> `ctx.sensitive` on every private element, including tab titles and URLs (hide the URL bar by recording page content only; headless has none).
- Headless fonts differ from headed: keep one mode for all scenes.
