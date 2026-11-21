# Demo Studio

A [Claude Code](https://claude.com/claude-code) plugin that is an **agent-team configuration**: eighteen specialist agents with clear jobs, a few scripts, and three approval gates that turn a product into a narrated, captioned, privacy-safe demo video (web, desktop, Android, iOS). Design: [docs/LEAN.md](docs/LEAN.md).

## Install

```
/plugin marketplace add <path-to-this-repo or owner/repo>
/plugin install demo-studio@demo-record-teams
/demo-studio:new Show how a new user creates a project in Acme Tasks, for first-time admins, web
```

## Agents (18, each owns one file)

| Agent | Job | Writes |
|---|---|---|
| `demo-director` | Understands the request, picks the path, asks you at 3 gates, routes fixes | `STATE.md` |
| `toolsmith` | Proposes and installs tools via `setup_tools.py` (asks first) | none |
| `demo-strategist` | Brief and video properties | `brief.md`, `demo.yaml` |
| `app-scout` | Explores the app, selectors, sensitive elements | `app-map.md` |
| `privacy-guard` | Seeded data / demo account, `privacy.mask`/`patterns`/`seed_values`; owns leak fixes | `demo.yaml#privacy` |
| `storyboarder` | Scenes, shots, durations | `storyboard.md` |
| `scriptwriter` | Narration within word budgets | `narration.md` |
| `localizer` | Translation when voice language differs | `narration.<lang>.md` |
| `voice-producer` | TTS with `vo.py`, durations | `media/sNN.vo.wav` |
| `scene-automator` | Scene scripts `sNN(ctx)` | `scenes.<platform>.py` |
| `capture-operator` | Records with `capture.py` or platform recorders | `media/sNN.raw.*`, `sNN.marks.json` |
| `sync-editor` | Cuts and timing against the voice | `edit.json` |
| `motion-designer` | Zooms, title and end cards | `motion.json` |
| `caption-writer` | Timed captions | `captions.json` |
| `sound-mixer` | Music and level | `mix.json` |
| `render-engineer` | Runs `render.py` (merges the JSON files) | `media/final-*.mp4`, `final.vtt` |
| `demo-qa` | Runs `verify.py`, watches the video, PASS/FAIL and owner | `qa.md` |
| `packager` | Thumbnail, chapters, description | `media/thumb.png`, `delivery.md` |

Five scripts do the mechanical work: `setup_tools.py`, `vo.py`, `capture.py`, `render.py`, `verify.py`.

## Commands

| Command | Purpose |
|---|---|
| `/demo-studio:new <what>` | Video from scratch, brief to final |
| `/demo-studio:run [request]` | Any other request (re-voice, re-record, cut, new aspect); empty = resume |
| `/demo-studio:fix [symptom]` | Fix a problem found in a finished video |
| `/demo-studio:review <video or slug>` | Inspect a video without changing it |
| `/demo-studio:tools [features]` | Show or install tools; always asks first |

## Gates

| Gate | You approve | Before |
|---|---|---|
| G1 | brief + `demo.yaml` (incl. data mode: seeded or real) | planning |
| G2 | storyboard + narration | any recording |
| G3 | final videos + QA verdict | delivery |

## Privacy

1. **Seeded data by default**: a demo account or invented data. `real` data only if you choose it at G1.
2. **CSS mask while recording** (web): selectors from `demo.yaml privacy.mask` are hidden.
3. **OCR verify on every final video** (`verify.py`): any leak = FAIL, nothing is delivered.

Desktop and mobile record with the platform's tools on seeded data; the final OCR verify still runs.

## Requirements

Python 3.10+; ffmpeg, Playwright + chromium and OCR are installed on request by `setup_tools.py`. Node.js only for Electron/Appium; macOS + Xcode for iOS; `adb` for Android; `ELEVENLABS_API_KEY` only for the paid voice.
