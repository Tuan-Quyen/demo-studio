# Platform: desktop (Electron, Windows, macOS)

Feature `capture-desktop` (pywinauto on Windows, Appium + Mac2 on macOS; Electron needs only Playwright) plus `capture` for ffmpeg. Pick the section for the app:

| app | automation | recorder |
|---|---|---|
| Electron | Playwright `_electron` (**Node only**, no Python API) | Playwright `recordVideo` on the Electron launch |
| Windows native | pywinauto (`uia` backend) | ffmpeg `gdigrab` region |
| macOS native | Appium Mac2 (XCTest) | ffmpeg `avfoundation` or Mac2 `macos: startRecordingScreen` |

Common: fixed window size and position (e.g. 1280x720 at 0,0), one display, DND on, other apps closed, no notifications, wallpaper neutral, real cursor visible, system scaling known (record the DPI/scale factor in `#events`).

## Common Node core (Electron scenes; same contract as SKILL.md)
```js
class Ctx { constructor(scene, target, voMs, scale=1, origin=[0,0], dry=false){Object.assign(this,{scene,target,voMs,scale,origin,dry}); this.t0=Date.now(); this.virt=0;}
  now(){return Math.max(Date.now()-this.t0,this.virt)}
  bb(b){return b&&[Math.round((b.x-this.origin[0])*this.scale),Math.round((b.y-this.origin[1])*this.scale),Math.round(b.width*this.scale),Math.round(b.height*this.scale)]}
  mark(type,b=null,label=''){console.log(JSON.stringify({t:this.now(),scene:this.scene,type,bbox:this.bb(b),label}))}
  sensitive(b,l){this.mark('sensitive',b,l)} sensitiveEnd(l){this.mark('sensitive',null,l)}
  async holdUntil(ms){ if(this.dry){this.virt=Math.max(this.virt,ms);return} const l=ms-this.now(); if(l>0) await new Promise(r=>setTimeout(r,l)) }
  start(){this.t0=Date.now(); this.mark('scene_start')}
  async end(){await this.holdUntil(this.voMs+400); this.mark('scene_end')} }
```

## Electron (Playwright `_electron`)
```js
const { _electron: electron } = require('playwright');
const app = await electron.launch({ args: ['main.js'],
  recordVideo: { dir: 'tmp', size: { width: 1280, height: 720 } } });   // size MUST equal the window size (a larger size pads, see web.md)
await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setBounds({x:0,y:0,width:1280,height:720}));
const page = await app.firstWindow();
const ctx = new Ctx('s02', page, voMs, 1.0); ctx.start();
const el = page.getByRole('button', { name: 'Export' });
const b = await el.boundingBox(); ctx.mark('click', b, 'Export button'); await el.click();
await ctx.end(); await app.close();            // finalize video, then move page.video().path() -> media/s02.raw.webm
```
bbox = `boundingBox()` in window CSS px (origin 0,0; scale = video width / window width). Native menus/dialogs are outside the page (not recorded, not clickable): drive via `app.evaluate` or avoid them. Verify the recorded size with `ffprobe`; if `recordVideo` quality/fps is below spec, use the ffmpeg window-region recorder below with the Electron automation.

## Windows (pywinauto + ffmpeg gdigrab)
```python
import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2)   # coordinates must match real pixels
from pywinauto import Application
app = Application(backend="uia").start(r"C:\Program Files\App\app.exe")
win = app.window(title_re="App.*"); win.wait("visible"); win.move_window(0, 0, 1280, 720)
r = win.rectangle()                                            # screen coords: origin (r.left, r.top)
btn = win.child_window(title="Export", control_type="Button")
rr = btn.rectangle(); ctx.mark("click", [rr.left, rr.top, rr.width(), rr.height()], "Export button")  # Ctx(origin=(r.left,r.top))
btn.click_input()                                              # real mouse input -> visible cursor
```
Recorder adapter: 
```
ffmpeg -y -f gdigrab -framerate 60 -offset_x <left> -offset_y <top> -video_size 1280x720 -i desktop -c:v libx264 -preset ultrafast -crf 16 -pix_fmt yuv420p media/s02.raw.mp4
```
Start the process (`subprocess.Popen`), wait until the output file grows, `ctx.start()`; to stop send `q` on stdin (do not kill: the mp4 needs its moov atom) then `ffprobe`. `gdigrab -i title=<window>` captures one window regardless of position; use region capture when overlays/menus must be included. For a 1440p master use a 2560x1440 display or capture the window at native DPI scale and set `scale` accordingly. Note: raw output here is `sNN.raw.mp4`, not webm (tell the director; `#events.clips[*].file` is authoritative).
DND: Focus Assist/Do Not Disturb has no stable CLI; ask the user to enable it (or verify via screenshot) before recording.

## macOS (Appium Mac2 + ffmpeg avfoundation)
Prereqs the user must grant once (System Settings > Privacy & Security): **Accessibility** to the terminal/Appium host and to WebDriverAgentMac, **Screen Recording** to the process running ffmpeg. Without them automation silently fails or the clip is black/wallpaper only -> `blocked` with the permission name, not a retry.
```python
from appium import webdriver
from appium.options.mac import Mac2Options
o = Mac2Options(); o.bundle_id = "com.example.app"
driver = webdriver.Remote("http://127.0.0.1:4723", options=o)   # server: `appium` with the mac2 driver installed
btn = driver.find_element("accessibility id", "export")
r = btn.rect                                                    # x,y,width,height in screen points
ctx.mark("click", [r["x"], r["y"], r["width"], r["height"]], "Export button"); btn.click()
```
Recorder adapter: `ffmpeg -f avfoundation -capture_cursor 1 -capture_mouse_clicks 1 -framerate 60 -i "<screen idx>:none" -vf crop=<w>:<h>:<x>:<y> ...` (list devices: `ffmpeg -f avfoundation -list_devices true -i ""`; crop to the window region; on Retina the capture is in pixels = points x 2, so `scale` = 2). Alternative: Mac2 `macos: startRecordingScreen` (`deviceId`, `fps` default 15, `captureCursor`, `captureClicks`); it deletes the raw file on stop, so fetch the result from the stop call. Prefer ffmpeg for 60 fps.
DND: turn on a Focus mode manually (no reliable CLI); ask the user.

## Pitfalls
- DPI/Retina mismatch is the #1 cause of wrong bbox: compute `scale` = captured px / automation units and assert it in dry-run against a screenshot.
- Moving the window or another app stealing focus mid-scene: lock position, `win.set_focus()` before each scene; a notification toast in frame = environment failure (retry) and a DND miss (tell the user).
- Taskbar/menu bar, clock, user name, other windows: capture only the window region; mark any username/path in title bars as `sensitive`.
- `type_keys` special characters need escaping (`{ENTER}`, `^c`); never type real secrets, use seed credentials.
