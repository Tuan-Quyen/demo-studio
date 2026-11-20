# Platform: mobile (Android, iOS)

Features `capture-android` (Appium + UiAutomator2, adb, scrcpy) and `capture-ios` (Appium + XCUITest). **iOS needs macOS + Xcode**; on Windows/Linux return `blocked` ("ios capture requires macOS with Xcode"), do not improvise. Start the Appium server (`appium`, default `http://127.0.0.1:4723`) before scenes.

Choose the target first: **emulator/simulator** (repeatable, no signing, easy fixed resolution; preferred) vs **real device** (true touches/performance; needs USB debugging on Android, and on iOS a provisioned WebDriverAgent: `appium:xcodeOrgId`, `appium:xcodeSigningId`, `appium:updatedWDABundleId`). Pick a device profile once and keep it for all scenes (e.g. 1080x2400 Android, iPhone simulator of one model).

## Automation (scene-automator)
Android:
```python
from appium import webdriver
from appium.options.android import UiAutomator2Options
o = UiAutomator2Options(); o.udid = "emulator-5554"; o.app_package = "com.example.app"; o.app_activity = ".MainActivity"
driver = webdriver.Remote("http://127.0.0.1:4723", options=o)      # automationName UiAutomator2
```
iOS (simulator): capabilities `platformName=iOS`, `appium:automationName=XCUITest`, `appium:deviceName`, `appium:platformVersion`, `appium:app` or `appium:bundleId`.
Tap with marker:
```python
def tap(ctx, el, label):
    r = el.rect                                    # {x,y,width,height}
    ctx.mark("tap", [r["x"], r["y"], r["width"], r["height"]], label)
    el.click()
ctx.hold_until(500); tap(ctx, driver.find_element("accessibility id", "new_invoice"), "New invoice")
```
Prefer `accessibility id` (stable on both OSes), then resource-id / predicate. Typing: `el.send_keys(...)` then `ctx.mark("key", None, "typed ...")`. Add small `hold_until` gaps so taps are readable; avoid long swipes with no VO.

## bbox source / scale
`element.rect`: Android in device pixels; **iOS in points**. `scale` = clip width / `driver.get_window_size()["width"]` (iOS ~2-3, Android 1 unless the recorder downsizes, e.g. scrcpy `--max-size`). Assert in dry-run that a known element's bbox lands on the right pixels in a screenshot. Status bar / notch offsets are included in `rect` (origin = screen top-left).

## Recorder adapter (capture-operator)
| target | command | notes |
|---|---|---|
| Android, preferred | `scrcpy --no-playback --no-audio --max-fps=60 --record=media/s03.raw.mkv` (add `-s <udid>`) | `--record` / `--time-limit` documented by scrcpy. Stop with Ctrl-C/SIGINT so the file is finalized; then `ffmpeg -nostdin -y -i x.mkv -c copy s03.raw.mp4`. Variable frame rate: a frame is only produced when the screen changes, so normalize to CFR at render. |
| Android fallback | `adb shell screenrecord --size 1080x2400 --bit-rate 20000000 /sdcard/s03.mp4` then `adb pull` | hard limit **180 s** per run (default and max); scenes are shorter, never record a whole demo in one go. |
| iOS simulator | `xcrun simctl io booted recordVideo --codec=h264 --force media/s03.raw.mov` | stop with SIGINT and wait for the process to exit before reading the file. |
| iOS real device | QuickTime/`ffmpeg -nostdin -f avfoundation` capture of the USB-attached device, or Appium `startRecordingScreen` | not verified here; test on the first run. |
Order: start recorder -> wait for the file to grow -> `ctx.start()` -> scene -> `ctx.end()` -> stop recorder -> `ffprobe` (w, h, fps, duration). Measure `offset_ms` as the wall-clock gap between recorder spawn and `scene_start` minus recorder startup latency; check the first tap against its frame once. Raw output is `sNN.raw.mp4/.mov/.mkv`, not webm; `#events.clips[*].file` is authoritative.
Show touches: Android `adb shell settings put system show_touches 1` (turn off after; also restore on failure). scrcpy `--show-touches` only shows physical touches, so verify on the first run whether Appium-injected taps appear; if not, rely on motion-designer's tap highlight from the `tap` markers. iOS shows no touches by default: same fallback. Never bake a highlight into the raw clip if motion-fx will add one.
DND / clean device: Android `adb shell settings put global zen_mode 1` (verify on the device), airplane mode off but notifications silenced, fixed clock/battery if the app allows (demo mode: `adb shell cmd statusbar` / simulator `xcrun simctl status_bar booted override --time 9:41 --batteryState charged --batteryLevel 100`). Hide the keyboard suggestions/autofill; use a seed account.

## Pitfalls
- Appium session timeout / adb offline / simulator not booted = environment failure (retry <= 2, `adb kill-server && adb start-server` is allowed); element not found = step failure.
- Rotation, font/display-size changes, system dialogs (permissions, "save password", update prompts) in frame: pre-grant permissions in capabilities (`appium:autoGrantPermissions` on Android) or in setup.
- Emulator performance: cold boot first, record only when idle; frame drops show as freezedetect hits at render.
- Real-device data (notifications, contacts, location) is private: mark `sensitive` for visible names/numbers; status-bar items too.
- Vertical clip (9:16 native): for 16:9 output motion-fx adds a device frame; do not letterbox in the recorder.
