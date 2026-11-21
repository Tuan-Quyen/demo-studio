# Platform: desktop

| App | Automation | Recorder |
|---|---|---|
| Electron | Playwright `_electron` (Node) | `recordVideo` on launch, size = window size |
| Windows native | pywinauto (`uia`) | ffmpeg `gdigrab` region |
| macOS native | Appium Mac2 | ffmpeg `avfoundation` or Mac2 screen recording |

- Fixed window size and position (e.g. 1280x720 at 0,0), one display, notifications off (DND), other apps closed, cursor visible.
- Electron: `electron.launch({args:['main.js'], recordVideo:{dir:'tmp', size:{width:1280,height:720}}})`; close the app to finalize, then move the video to `media/sNN.raw.webm`. Native menus/dialogs are outside the page: avoid them or drive them via `app.evaluate`.
- ffmpeg recorders: start before the scene, stop right after, `-nostdin`, always with a timeout.
- Use seeded data and a demo account. There is no capture-time mask here: demo-qa's OCR verify is the safety net, so keep real data off screen.
- Record the real size and fps with `ffprobe`; do not claim more.
