# Platform: mobile

Appium + UiAutomator2 (Android, `adb`, scrcpy) or XCUITest (iOS; needs macOS + Xcode, otherwise return `blocked`). Start the Appium server (`appium`, http://127.0.0.1:4723) first.

- Prefer an emulator/simulator with one fixed device profile for all scenes (e.g. 1080x2400). Real device only if the user asks (USB debugging; iOS needs a provisioned WebDriverAgent).
- Locate by accessibility id / resource-id first, XPath last. Taps: `driver.tap` / W3C actions with visible touch (enable "show taps" on Android).
- Recorders: Android `adb shell screenrecord` (max 180 s; chunk longer scenes) or `scrcpy --record`; iOS `xcrun simctl io booted recordVideo` or Appium `start_recording_screen`.
- DND on, notifications cleared, demo account and seeded data only. No capture-time mask: demo-qa's OCR verify is the safety net.
- Save as `media/sNN.raw.mp4`; check size/fps/duration with `ffprobe`.
