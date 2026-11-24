# Platform: mobile (Android, iOS)

No Appium. One stdlib driver, `${CLAUDE_PLUGIN_ROOT}/scripts/mobile_driver.py`, reads the screen (element tree + screenshot) and acts on it:

| | Android (`capture-android`) | iOS (`capture-ios`) |
|---|---|---|
| Tools on PATH | `adb` (platform-tools); `scrcpy` optional | `xcrun` (Xcode) + `axe` (`brew install cameroncooke/axe/axe`) |
| Read screen | `uiautomator dump` (XML: resource-id, content-desc, text, bounds) | `axe describe-ui` (JSON: AXUniqueId, AXLabel, AXValue, frame) |
| Act | `adb shell input tap/text/swipe/keyevent` | `axe tap/type/swipe/button/key` |
| Targets | emulator **or** phone with USB debugging (no root) | **Simulator only**; real iPhone → `blocked` ("AXe drives the iOS Simulator only") |
| Rect unit | device pixels | points |
| Status | | **not verified on macOS yet**: check every command on the first run and report what differed |

iOS needs macOS; elsewhere `setup_tools.py --check` says `blocked` ("requires macOS + Xcode"): return it, do not improvise. The LLM is used only to **explore** (app-scout, and scene-automator while writing/fixing); the recorded run is always a fixed script. Never put an agent decision inside a scene.

Choose the target once: emulator/Simulator (repeatable, fixed resolution; preferred) or real Android phone (true performance). One device profile for all scenes (e.g. Pixel 1080x2400, one iPhone Simulator model). Device id: `adb devices` serial / Simulator UDID (`xcrun simctl list devices booted`); `--device` defaults to the only/booted one.

## Explore (app-scout, scene-automator)
Toolkit interpreter `PY` = `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --python`.
```
$PY ${CLAUDE_PLUGIN_ROOT}/scripts/mobile_driver.py --platform android --device emulator-5554 screen --png logs/scout-01.png
android elements=14 unit=px screenshot=logs/scout-01.png
[3] tap=540,1210 rect=[40, 1150, 1000, 120] id="com.example.app:id/new_invoice" label="Create invoice" text="New invoice" cls=Button clickable
[5] tap=950,150 rect=[900, 100, 100, 100] cls=ImageButton clickable UNNAMED
```
Then `tap --id new_invoice` (or `--label`, `--text`, `--xy X,Y`), `type TEXT`, `key back|home|enter|tab|delete`, `swipe X1 Y1 X2 Y2 --ms 300`, `launch <package|bundle> [--activity .Main]`, `stop <app>`, `size`. Look at the PNG (Read it) together with the list: the list gives selectors and rects, the picture shows what the viewer will see. `password` = sensitive field; `UNNAMED` = clickable with no id/label/text → no stable selector, note it as a risk in app-map. Exit 0 ok, 1 step (not found / bad input), 2 usage, 3 environment (tool, device); errors are one JSON line on stderr.

## Automation (scene-automator)
Copy `${CLAUDE_PLUGIN_ROOT}/scripts/mobile_driver.py` verbatim to `.demo/<slug>/mobile_driver.py` on every run (like `demo_ctx.py`; never edit the copy). The adapter creates the target as `connect(platform, device=...)` and passes it as `ctx.target`.
```python
from mobile_driver import StepError

def prepare(sid, d):                      # d = ctx.target (AndroidDriver / IOSDriver)
    d.stop("com.example.app"); d.launch("com.example.app", ".MainActivity")   # iOS: bundle id, no activity
    d.find(id="invoices_list", timeout_ms=15000)                          # start state reached

def tap(ctx, el, label):
    ctx.mark("tap", el.bbox, label)       # bbox in driver units; ctx converts with scale
    ctx.target.tap(el)

def s02(ctx):
    d = ctx.target
    ctx.hold_until(700)
    tap(ctx, d.find(id="new_invoice"), "New invoice")
    field = d.find(id="customer_email")
    ctx.sensitive(field.bbox, "customer email")
    tap(ctx, field, "Email field"); d.type("demo@example.com"); ctx.mark("key", None, "typed email")
SCENES = {"s02": s02}
```
- Selectors: Android `id` (resource-id, short form ok) → `label` (content-desc) → `text`; iOS `id` (accessibility identifier) → `label` → `text`. Never coordinates unless app-map says the element has no selector (then `tap((x, y))` and mark a bbox around the point).
- **Find before the beat, act on the beat.** `find()` costs one tree dump (Android `uiautomator dump`: often 0.5-2 s, unmeasured here). Look elements up ahead of the `hold_until` that times the action, so the dump never pushes a tap off its VO beat; one `snapshot()` can serve several `find`s on a static screen (`[e for e in d.snapshot() if ...]`). Measure the dump time in the dry-run and report it in `facts`.
- Typing: Android `input text` is **printable ASCII only** and cannot type a literal `%s` (Android turns it into a space; `StepError` for both): seed values for typed fields must be ASCII, or the app must offer another way (paste, picker). iOS `axe type` follows a US keyboard (unverified for non-ASCII). Never type a sensitive value from a real account into a `key` label.
- Permissions / dialogs: grant before scenes in `prepare` or setup: Android `adb shell pm grant <pkg> <permission>` (or install with `adb install -g`); iOS `xcrun simctl privacy <udid> grant all <bundle>`. An unexpected system dialog is a `step` failure.
- `mobile_driver` raises `StepError` (exit class `step`, exit 10 in the runner) or `EnvError` (`environment`, exit 20): the runner maps `e.error_class` straight to the failure classes of the shared contract.
- Re-runnable: `prepare` stops and relaunches the app (Android `adb shell pm clear <pkg>` only if the seed account survives it).

## bbox source / scale
`El.rect` / `El.bbox` = `[x, y, w, h]` in driver units, origin = screen top-left (status bar included). Android: device pixels, `scale` = clip width / `d.size()[0]` (1 unless the recorder downsizes, e.g. scrcpy `--max-size`; `wm size` override wins over physical). iOS: points, `scale` = clip width / `d.size()[0]` (~2-3). Assert in the dry-run that one known element's bbox lands on the right pixels of a screenshot (`d.screenshot(path)`).

## Recorder adapter (capture-operator)
| target | command | notes |
|---|---|---|
| Android, preferred | `scrcpy --no-playback --no-audio --max-fps=60 --record=media/s03.raw.mkv` (add `-s <serial>`) | Stop with Ctrl-C/SIGINT so the file is finalized; then `ffmpeg -nostdin -y -i x.mkv -c copy s03.raw.mp4`. Variable frame rate (a frame only when the screen changes): normalize to CFR at render. |
| Android fallback | `adb shell screenrecord --size 1080x2400 --bit-rate 20000000 /sdcard/s03.mp4` then `adb pull` | hard limit **180 s** per run; record per scene, never a whole demo. |
| iOS Simulator | `xcrun simctl io <udid> recordVideo --codec=h264 --force media/s03.raw.mov` | stop with SIGINT and wait for the process to exit before reading the file. |
Order: `d = connect(platform, device)` → `prepare(sid, d)` → start recorder → wait for the file to grow → assert start state → `ctx.start()` → scene → `ctx.end()` → stop recorder → `ffprobe` (w, h, fps, duration). Measure `offset_ms` as the wall-clock gap between recorder spawn and `scene_start` minus recorder startup latency; check the first tap against its frame once. Raw output is `sNN.raw.mp4/.mov/.mkv`; `#events.clips[*].file` is authoritative.
Show touches: Android `adb shell settings put system show_touches 1` (restore after, also on failure); whether `input tap` (injected) taps show the dot is **unverified**: check the first clip, and if not, rely on motion-designer's tap highlight from the `tap` markers. iOS Simulator shows no touches: same fallback. Never bake a highlight into the raw clip if motion-fx adds one.
DND / clean device: Android `adb shell settings put global zen_mode 1` (verify), status-bar demo mode (`adb shell settings put global sysui_demo_allowed 1` then `am broadcast -a com.android.systemui.demo -e command clock -e hhmm 0941`); iOS `xcrun simctl status_bar <udid> override --time 9:41 --batteryState charged --batteryLevel 100`. Hide keyboard suggestions/autofill; use a seed account.

## Pitfalls
- `adb` offline / unauthorized, Simulator not booted, `uiautomator dump` "could not get idle state" 3x, `axe` missing = environment failure (retry <= 2; `adb kill-server && adb start-server` allowed). Element not found = step failure.
- Endless animations (spinners, video) can make `uiautomator dump` fail: wait for an idle screen in the scene, or report the screen as a risk.
- Rotation, font/display-size changes, system dialogs (permissions, "save password", update prompts) in frame: grant/disable in setup.
- Emulator performance: cold boot first, record only when idle; frame drops show as freezedetect hits at render. Dumping the tree during recording adds CPU load: keep lookups out of animated moments.
- Real-device data (notifications, contacts, location) is private: mark `sensitive` for visible names/numbers; status-bar items too.
- Vertical clip (9:16 native): for 16:9 output motion-fx adds a device frame; do not letterbox in the recorder.
