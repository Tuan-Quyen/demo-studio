---
name: platform-automation
description: Load when writing, dry-running or recording scene scripts (scene-automator, capture-operator) or when app-scout sets `platform:`. Holds the shared mark() contract, VO-pause rule, dry-run rule, failure classes and recorder-adapter duties. Then load ONLY references/<platform>.md for the `platform:` value in app-map.md.
---

# Platform automation (shared contract)

Load exactly one reference, chosen by `platform:` in `.demo/<slug>/app-map.md`:
`web` -> `references/web.md` · `desktop` -> `references/desktop.md` (Windows, macOS, Electron) · `android`/`ios` -> `references/mobile.md`.
Path: `${CLAUDE_PLUGIN_ROOT}/skills/platform-automation/references/<file>`. Never load the other two.

Split of ownership: **scene-automator** = what the app does (actions, selectors, pauses, `mark()`, dry-run). **capture-operator** = how it is filmed (recorder adapter, fps, resolution, viewport, DND, markers -> `#events`, retries). The scene script never starts or stops recording.

## Scene script shape
`.demo/<slug>/scenes.<platform>.<py|js>` exports one function per scene id (`s01`, `s02`, ...). Each receives a `ctx` built by the adapter (live recorder or dry-run) and uses only `ctx`:
`ctx.target` (page / driver / window), `ctx.vo_ms`, `ctx.mark(type, bbox, label)`, `ctx.hold_until(ms)`, `ctx.sensitive(bbox, label)`, `ctx.sensitive_end(label)`.
Print nothing else to stdout (logs go to stderr): the collector parses every stdout line that starts with `{`.

## mark() spec
One JSON object per line on stdout:
```
{"t":<int ms since scene start>,"scene":"s03","type":"click|tap|key|sensitive|scene_start|scene_end","bbox":[x,y,w,h],"label":"..."}
```
- `t`: ms since `scene_start` (which is `t:0`). `scene_start` is emitted by the adapter the moment the recorder is live; `scene_end` after the last action and the VO hold.
- `bbox`: integer pixels in the **recorded frame** (top-left origin), `[x,y,w,h]`. The script passes bbox in app units (CSS px / window px / device units); `ctx` converts with `scale` and `origin` set by the adapter (`(v - origin) * scale`). `null` for `scene_start`, `scene_end` and `key` without a focused element.
- `click`/`tap`: bbox of the target element, marked at the instant of the input. Click point = bbox center.
- `key`: typed text or shortcut; `label` = what was typed, **never** the value of a sensitive field.
- `sensitive`: bbox of an element showing real private data (email, name, amount, token), marked when it becomes visible. Re-mark after every scroll/navigation/resize that moves it. `bbox:null` with the same `label` = region gone (otherwise the region lasts to `scene_end`).
- `label`: short human text ("Create invoice button"), no secrets.

Reference core (copy verbatim to `.demo/<slug>/demo_ctx.py`; JS twin in `references/desktop.md`):
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
- Scene length = `vo_ms + 400` ms; accept up to `vo_ms + 1500`. Pad with `ctx.hold_until(...)`, not fixed sleeps.
- No input in the first 500 ms (narration leads the action); place actions at the beats the storyboard gives, spread over the VO.
- If the real actions cannot fit in `vo_ms`, do not speed up: return `needs-input` to the director (scriptwriter/storyboarder shorten or lengthen) with the measured action time.

## Dry-run rule (scene-automator, before every handoff)
Run every scene through the dry-run adapter: same `ctx`, **no recorder**, virtual clock (pauses are skipped). Actions still really execute, so use the test/seed account and make each scene re-runnable (a reset step at the start). PASS =
1. exit 0 for every scene, 2. each scene emitted `scene_start` ... `scene_end` with non-decreasing `t`, 3. every `sensitive` element from app-map.md is marked in its scenes, 4. every bbox is inside the frame and not empty. Handoff `facts:` = scenes passed / total, markers count. Only then hand to capture-operator.

## Failure classes
Runner exit code + one JSON line on stderr `{"error_class":"step|environment","scene":"s03","detail":"...","screenshot":"logs/s03-fail.png"}`.
| class | examples | exit | owner / action |
|---|---|---|---|
| step | selector not found, wrong element, UI changed, assertion failed, unexpected dialog | 10 | scene-automator fixes. capture-operator returns `blocked` with log + screenshot, never edits the script. |
| environment | timeout while launching, device/emulator offline, Appium/adb dropped, network blip, recorder failed to start, 0-byte clip | 20 | capture-operator retries the scene, **max 2** times, then `blocked`. |
Same step failure at the same selector twice = report to the director, do not loop. Unsure which class: treat as step and attach evidence.

## Recorder adapter (capture-operator owns)
Per platform it must: set fixed size/viewport and fps (record at 1440p, downscale at render; 60 fps target); enable DND / hide notifications where the OS allows (else ask the user); start recording, wait until frames flow, then `ctx.start()`; run the scene script unmodified; stop and finalize the file; save `media/sNN.raw.<ext>` (web: webm); `ffprobe` the clip (w, h, fps, duration); check it is non-empty and not black; collect stdout markers into `project.json#events`:
```json
{"schema":1,"platform":"web",
 "clips":{"s01":{"file":"media/s01.raw.webm","w":2560,"h":1440,"fps":60,"scale":2.0,"offset_ms":120,"duration_ms":9800}},
 "markers":[ {"t":0,"scene":"s01","type":"scene_start","bbox":null,"label":""} ],
 "retries":{"s03":1}}
```
`offset_ms` = delay between the clip's first frame and `scene_start` (0 when the recorder starts the clip itself; measured wall-clock otherwise). Write with `python ${CLAUDE_PLUGIN_ROOT}/scripts/project.py --slug <slug> set events --as capture-operator --file <json>`. Missing tool -> handoff `needs-input` with `setup_tools.py --plan` output; never install.
