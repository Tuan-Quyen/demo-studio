# Demo Studio

A [Claude Code](https://claude.com/claude-code) plugin that is an **agent-team configuration**: six agents with clear jobs, a few scripts, and three approval gates that turn a product into a narrated, captioned, privacy-safe demo video (web, desktop, Android, iOS). Design: [docs/LEAN.md](docs/LEAN.md).

## Install

```
/plugin marketplace add <path-to-this-repo or owner/repo>
/plugin install demo-studio@demo-record-teams
/demo-studio:new Show how a new user creates a project in Acme Tasks, for first-time admins, web
```

## Agents

| Agent | Job |
|---|---|
| `demo-director` | Understands the request, asks you at the gates, briefs the others, keeps `STATE.md`, installs tools (asks first) |
| `story` | Brief, `demo.yaml`, storyboard, narration, translations |
| `app-scout` | Explores the app, maps selectors, prepares seeded data, lists sensitive selectors |
| `scene-automator` | Writes scene scripts and records them (`capture.py` for web) |
| `editor` | Voice-over (`vo.py`), `edit.json` (cuts, captions, zooms, cards, music), `render.py` |
| `demo-qa` | Runs `verify.py`, watches the video, writes `qa.md` PASS/FAIL and names who fixes what |

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
