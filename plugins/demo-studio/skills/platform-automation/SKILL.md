---
name: platform-automation
description: Load when writing, dry-running or recording scene scripts (scene-automator, capture-operator) or when checking `platform` from demo.yaml. Holds the shared mark() contract, VO-pause rule, dry-run rule, failure classes and recorder-adapter duties. Then load ONLY references/<platform>.md for the `platform` value in demo.yaml.
---

# Platform automation (shared contract)

Load exactly one reference, chosen by `platform` in `.demo/<slug>/demo.yaml` (`config.py --slug <slug> get platform`):
`web` -> `references/web.md` · `desktop` -> `references/desktop.md` (Windows, macOS, Electron) · `android`/`ios` -> `references/mobile.md`.
Path: `${CLAUDE_PLUGIN_ROOT}/skills/platform-automation/references/<file>`. Never load the other two.

Split of ownership: **scene-automator** = what the app does (actions, selectors, pauses, `mark()`, dry-run). **capture-operator** = how it is filmed (recorder adapter, fps, resolution, viewport, DND, markers -> `#events`, retries). The scene script never starts or stops recording.

## Scene script shape
`.demo/<slug>/scenes.<platform>.<py|js>` exports `SCENES` (`{sid: fn}`, one function per scene id `s01`, `s02`, ...) and optionally `prepare(sid, target)`. Each scene function receives a `ctx` built by the adapter (live recorder or dry-run) and uses only `ctx`:
`ctx.target` (page / driver / window), `ctx.vo_ms`, `ctx.mark(type, bbox, label)`, `ctx.hold_until(ms)`, `ctx.sensitive(bbox, label)`, `ctx.sensitive_end(label)`.

**`prepare(sid, target)`** (optional, scene-automator writes it): reaches the scene's start state (navigate, log in, scroll, open a panel) **before** `ctx.start()`. Adapter sequence, identical in the live recorder and the dry-run: create target -> `prepare(sid, target)` -> record the start state (web: scrollX/Y) -> `ctx.start()` -> `SCENES[sid](ctx)` -> `ctx.end()`. Rules: no navigation or reload after `prepare` (it would undo the state); the adapter asserts the start state is unchanged at `ctx.start()` (else `step` failure); the scene function must not move the view before its first intended action (e.g. no `scroll_into_view_if_needed` on a sticky/fixed header element, see the web reference). Without `prepare` the scene starts from the fresh target.
Print nothing else to stdout (logs go to stderr): the collector parses every stdout line that starts with `{`.

## mark() spec
One JSON object per line on stdout:
```
{"t":<int ms since scene start>,"scene":"s03","type":"click|tap|key|sensitive|scene_start|scene_end","bbox":[x,y,w,h],"label":"..."}
```
- `t`: ms since `scene_start` (which is `t:0`), **not** since the clip start. `scene_start` is emitted by the adapter at `ctx.start()`, after `prepare`; `scene_end` after the last action and the VO hold. Clip time = `t + clips[sid].offset_ms`.
- `bbox`: integer pixels in the **recorded frame** (top-left origin, `#events.bbox_space`), `[x,y,w,h]`. The script passes bbox in app units (CSS px / window px / device units); `ctx` converts with `scale` and `origin` set by the adapter (`(v - origin) * scale`). `null` for `scene_start`, `scene_end` and `key` without a focused element.
- `click`/`tap`: bbox of the target element, marked at the instant of the input. Click point = bbox center.
- `key`: typed text or shortcut; `label` = what was typed, **never** the value of a sensitive field.
- `sensitive`: bbox of an element showing real private data (email, name, amount, token), marked when it becomes visible. Re-mark after every scroll/navigation/resize that moves it. `bbox:null` with the same `label` = region gone (otherwise the region lasts to `scene_end`).
- `label`: short human text ("Create invoice button"), no secrets.

Reference core (scene-automator copies it verbatim to `.demo/<slug>/demo_ctx.py`, the one file it may write besides the scenes; JS twin in `references/desktop.md`):
```python
import json, sys, time
TAIL_MS = 400                         # keep scene alive after VO ends
class Ctx:
    def __init__(self, scene, target, vo_ms, scale=1.0, origin=(0, 0), dry=False):
        self.scene, self.target, self.vo_ms = scene, target, vo_ms
        self.scale, self.origin, self.dry = scale, origin, dry
        self._t0, self._virt = time.monotonic(), 0
    def now(self):                    # ms since scene start (virtual clock in dry-run)
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
    def hold_until(self, ms):         # the ONLY way to wait; never bare sleep()
        if self.dry: self._virt = max(self._virt, ms); return
        left = ms - self.now()
        if left > 0: time.sleep(left / 1000)
    def start(self): self._t0 = time.monotonic(); self.mark("scene_start")
    def end(self):
        self.hold_until(self.vo_ms + TAIL_MS); self.mark("scene_end")
```

## VO-pause rule
VO is produced first. Read `python ${CLAUDE_PLUGIN_ROOT}/scripts/project.py --slug <slug> get voice` and take the scene's duration (use the field `get voice` shows; convert to ms) as `vo_ms`.
- Scene length = `vo_ms + hold_ms`; `hold_ms` = the storyboard scene's reading hold (default 400, 1000-2000 only where the storyboard asks), placed after the last action; accept up to `hold_ms + 500` extra. Pad with `ctx.hold_until(...)`, not fixed sleeps. Never the old fixed `vo_ms + 1500`.
- No input in the first 500 ms (narration leads the action); place actions at the beats the storyboard gives, spread over the VO.
- If the real actions cannot fit in `vo_ms`, do not speed up: return `needs-input` to the director (scriptwriter/storyboarder shorten or lengthen) with the measured action time.

## Dry-run rule (scene-automator, before every handoff)
Run every scene through the dry-run adapter: same `ctx`, **no recorder**, virtual clock (pauses are skipped), and the **same prepare -> start sequence** as the live adapter (including the start-state assertion). Actions still really execute, so use the test/seed account and make each scene re-runnable (a reset step at the start). PASS =
1. exit 0 for every scene, 2. each scene emitted `scene_start` ... `scene_end` with non-decreasing `t`, 3. every `sensitive` element from app-map.md is marked in its scenes, 4. every bbox is inside the frame and not empty, 5. the start state is unchanged at `ctx.start()` and (web) an in-viewport click target did not scroll the page before its click. Handoff `facts:` = scenes passed / total, markers count. Only then hand to capture-operator.

## Failure classes
Runner exit code + one JSON line on stderr `{"error_class":"step|environment","scene":"s03","detail":"...","screenshot":"logs/s03-fail.png"}`.
| class | examples | exit | owner / action |
|---|---|---|---|
| step | selector not found, wrong element, UI changed, assertion failed, unexpected dialog | 10 | scene-automator fixes. capture-operator returns `blocked` with log + screenshot, never edits the script. |
| environment | timeout while launching, device/emulator offline, Appium/adb dropped, network blip, recorder failed to start, 0-byte clip | 20 | capture-operator retries the scene, **max 2** times, then `blocked`. |
Same step failure at the same selector twice = report to the director, do not loop. Unsure which class: treat as step and attach evidence.

## Recorder adapter (capture-operator owns)
Per platform it must: set a fixed size/viewport and the native fps of the recorder (record at the largest native size the platform gives; the render scales; never claim a resolution or fps `ffprobe` does not show, see `media-specs` Encode); enable DND / hide notifications where the OS allows (else ask the user); create the target, run `prepare` if exported, then start recording / wait until frames flow as the platform needs, assert the start state, `ctx.start()`; run the scene script unmodified; stop and finalize the file; save `media/sNN.raw.<ext>` (web: webm); `ffprobe` the clip (w, h, fps, duration); check it is non-empty, not black and **not padded** (mandatory full-frame check in capture-operator: grey padding colour and size > viewport), and that it stops right after `ctx.end()` (no held tail); collect stdout markers into `project.json#events`:
```json
{"schema":1,"platform":"web",
 "bbox_space":{"unit":"px","frame":[1280,720],"scale":1.0,"origin":[0,0]},
 "clips":{"s01":{"file":"media/s01.raw.webm","w":1280,"h":720,"fps":25,"scale":1.0,"offset_ms":120,"duration_ms":9800}},
 "markers":[ {"t":0,"scene":"s01","type":"scene_start","bbox":null,"label":""} ],
 "retries":{"s03":1}}
```
`bbox_space` = the space of every marker bbox (`frame` = recorded size, `scale`/`origin` as passed to `Ctx`). `t` = ms since `scene_start`. `clips[sid].offset_ms` = clip time of `scene_start` (measured wall-clock from the clip's first frame to `ctx.start()`; includes `prepare` when it runs on the recorded target). Write with `python ${CLAUDE_PLUGIN_ROOT}/scripts/project.py --slug <slug> set events --as capture-operator --file <json>`. Missing tool -> handoff `needs-input` with `setup_tools.py --plan` output; never install.
