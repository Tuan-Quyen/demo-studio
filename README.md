# Demo Studio

A [Claude Code](https://claude.com/claude-code) plugin: a team of 18 agents that plans, records, edits and packages narrated, captioned, privacy-safe demo videos for **web, desktop, Android and iOS** apps.

You describe what to demo. The team writes the brief, storyboard and narration, records the app, blurs sensitive data, syncs the voice-over, adds motion and captions, mixes audio, renders 16:9 / 9:16 / 1:1 and checks the result. You approve at three gates.

This repo is a plugin marketplace (`demo-record-teams`) that ships one plugin: `plugins/demo-studio/` (v0.1.0).

## Install

```
/plugin marketplace add <path-to-this-repo or owner/repo>
/plugin install demo-studio@demo-record-teams
```

## Requirements

| Need | When |
|---|---|
| Python 3.10+ | always (toolkit and `project.py` are stdlib-only scripts) |
| ffmpeg | comes with the `capture` toolkit feature (bundled via imageio-ffmpeg); no system install needed |
| Node.js >= 18 | only for Remotion (`motion-cinematic`), Android/iOS Appium, and macOS desktop capture |
| macOS + Xcode | only for iOS (`capture-ios`); on other systems it reports `blocked` |
| `adb` on PATH | only for Android |
| `ELEVENLABS_API_KEY` | only for the paid `voice-elevenlabs` option |

## Quick start

```
/demo-studio:new Show how a new user creates a project in Acme Tasks, for first-time admins, web
```

The director picks the steps and pauses at three gates:

| Gate | You approve | Before |
|---|---|---|
| **G1** | the brief (audience, goal, message, CTA) and `demo.yaml` (length, platform, formats, voice, motion level) | anything is planned |
| **G2** | storyboard + narration | any recording |
| **G3** | the final renders and the QA verdict | packaging |

Pipeline order after recording: capture → (privacy-blurrer ∥ sync-editor) → (motion-designer ∥ caption-writer ∥ sound-mixer) → render → QA. Captions and mix need the timeline, so they never run before sync-editor. Web recordings are 25 fps at the viewport size (a Playwright limit); the render upscales and keeps the source fps.

Already have a script? `/demo-studio:shoot`. Lost your place? `/demo-studio:run` with no argument resumes from `.demo/STATE.md`.

## Commands

All are `/demo-studio:<name>`.

| Command | Purpose |
|---|---|
| `run [request]` | Any demo-video request; the director picks the pipeline. Empty = resume. |
| `new <what, audience, platform>` | Make a video from scratch, brief to final render (G1, G2, G3). |
| `script <what to demo>` | Pre-production only: brief, storyboard, narration (G1, G2). |
| `shoot [slug]` | From an approved script to the rendered, QA-checked video (needs G2, ends at G3). |
| `rerecord <scenes and what changed>` | Re-shoot scenes after a UI change, then re-render. |
| `revoice <what to change>` | Change narration text, voice or language, then re-render. |
| `cut <ratio and/or length>` | Add an aspect-ratio variant (9:16, 1:1, 16:9) or a shorter cut. |
| `fix [symptom]` | Fix a problem in the finished video; empty = read QA report and render checks. |
| `review <video path or slug>` | Inspect an existing video without changing it. |
| `tools [features]` | Show or install the toolkit by feature; always asks first. |
| `status` | Show where the work stands (reads `STATE.md` only). |

## Agents

Only `demo-director` runs pipelines; the others each do one job and write only their own files.

| Agent | One job | Model |
|---|---|---|
| `demo-director` | Classify the request, pick the pipeline, delegate, gate you, keep the resume point | opus |
| `toolsmith` | Install only the toolkit features you approved | haiku |
| `demo-strategist` | Audience, goal, message, CTA; creates `demo.yaml` | inherit |
| `app-scout` | Explore the app, check platform, map flows and selectors, flag sensitive elements | inherit |
| `storyboarder` | Scenes and shots: on-screen action, camera intent, duration | opus |
| `scriptwriter` | Narration per scene within a word budget (`demo-storytelling` formula), in the source `language` | opus |
| `localizer` | When `language` differs from `voice.language`: translated narration, UI-term glossary, lexicon proposals, on-screen strings | inherit |
| `voice-producer` | Text-to-speech per scene; measure durations | haiku |
| `scene-automator` | Action-only scene scripts with voice-over pauses; dry-run | inherit |
| `capture-operator` | Run the scripts unmodified under the recorder; save raw clips | haiku |
| `privacy-blurrer` | Decide blur regions over time (no fake data) | haiku |
| `sync-editor` | Align clips with voice-over: pad, trim, speed | inherit |
| `motion-designer` | Zoom/pan on clicks, highlights, callouts, title cards, device frames | inherit |
| `caption-writer` | Word-timed captions | haiku |
| `sound-mixer` | Music, ducking, loudness (default -14 LUFS, -1 dBTP; set in `demo.yaml`) | haiku |
| `render-engineer` | One-pass render to 16:9, 9:16, 1:1; measure the result | haiku |
| `demo-qa` | What machines cannot measure: spelling, broken UI, pacing, leaked personal data; PASS/FAIL | inherit |
| `packager` | Thumbnail, chapters, title, description, delivery manifest | haiku |

Voice-over is produced **before** scene scripts, so scene pauses fit the real audio durations.

## Skills

Loaded by agents as needed; you do not call them.

| Skill | Holds |
|---|---|
| `run-kits` | Roster, pipelines and gates, briefs, handoffs, workspace, `/fix` routing, toolkit approval, resume rules |
| `voice-over` | Voice engines and choice, pronunciation lexicon, natural speech rates, `[pause]`, recording your own voice |
| `demo-storytelling` | Story structure, hook, CTA, length and word budgets, scene-count rules |
| `platform-automation` | `mark()` contract, VO-pause and dry-run rules, per-platform references (web, desktop, mobile) |
| `motion-fx` | Motion levels none / basic / cinematic, effect recipes, safe areas, schema |
| `media-specs` | Encode specs, loudness, caption rules, render-check thresholds, key schemas |

## Workspace

Everything lives in `.demo/` in your project:

```
.demo/
  STATE.md  toolkit.json  .venv/
  <slug>/
    brief.md  demo.yaml  app-map.md  storyboard.md  narration.md  qa.md
    scenes.<platform>.*
    project.json  .demo.applied.json
    media/  sNN.raw.*  sNN.vo.wav  final-16x9.mp4  final-9x16.mp4
            final-1x1.mp4  final.vtt  thumb.png
```

Only two kinds of video file exist: raw clips and finals. Blur, motion, captions and mix are instructions in `project.json`, not intermediate videos.

### `demo.yaml`: the video's properties (you own it)

`brief.md` holds only prose (audience, goal, message, CTA, out of scope). Everything you can tune lives in `.demo/<slug>/demo.yaml`: `platform`, `length_s`, `formats`, `voice` (engine, name, language, lexicon), `motion.level`, `music` (style, duck_db), `captions` (burn_in, max_chars), `targets` (lufs, true_peak, max_drift_ms, caption_offset_ms), `privacy` (blur, real_data), `tools` (ocr), `install`. The strategist creates it at G1 from `templates/demo.yaml` (every field commented with allowed values and its default); the director records your decisions in it; all other agents only read it.

Edit it any time. On `/demo-studio:run` (or `/demo-studio:fix`) the director validates it and diffs it against the last snapshot (taken after G1 and after every G3; no snapshot = first run), then re-runs only what your change affects (e.g. `voice.*` re-runs voice and everything after it; `music.*` re-runs the mix; `platform` re-records everything).

```
python scripts/config.py --slug <slug> init | validate | get <dotted.path> | diff [--json] | apply | apply-lexicon (--text T | --file F | stdin) [--json]
```
Stdlib only; a built-in strict parser accepts plain maps, lists and scalars (anything else is an error with the line number). Tests: `python -m unittest discover -s scripts/tests`.

### `project.json` key ownership

One owner per key; writes go through `scripts/project.py`, which locks the file and rejects the wrong writer (exit 4). Never edit it by hand.

| Key | Owner | Key | Owner |
|---|---|---|---|
| `events` | capture-operator | `captions` | caption-writer |
| `voice` | voice-producer | `mix` | sound-mixer |
| `blur` | privacy-blurrer | `checks` | render-engineer |
| `timeline` | sync-editor | `delivery` | packager |
| `motion` | motion-designer | | |

```
python scripts/project.py --slug <slug> keys
python scripts/project.py deps voice     # what to re-run if voice changes
```

Dependency order: voice → timeline, captions, mix · events → blur, timeline · timeline → motion, captions, mix · {blur, motion, captions, mix} → checks → delivery. A `length_s` change re-runs storyboarder (G2) → timeline → motion, captions, mix → checks → delivery; voice only if the narration changes. Pronunciation fixes live in `demo.yaml` `voice.lexicon` (written term → spoken spelling, applied to TTS input only; captions keep the written text); a lexicon change re-runs voice.

```
python scripts/project.py owner blur     # privacy-blurrer
```

## Toolkit

Nothing is installed up front. When a step needs a feature, the agent runs a check; if it is missing, **you are asked first** with the size and effect (and a recommended default). Declined features fall back (cinematic to basic motion, word captions to sentence captions). Installs go into `.demo/.venv` and are recorded in `.demo/toolkit.json`. Your choice is saved in `demo.yaml` (`install.approved` / `install.declined`), so you are not asked twice.

Where several tools can do the same job you choose, and the recommended one is listed first: `scripts/setup_tools.py --options [ocr|voice|motion]` shows the alternatives with size, requirements and status. The choice is stored in `demo.yaml` (`tools.ocr`, `voice.engine`, `motion.level`); `none` skips the job (OCR: blur and text are checked by eye only).

```
python scripts/setup_tools.py --list | --options [job] | --check [features] | --plan <features> | --install <features>
```

| Feature | What it gives | Size |
|---|---|---|
| `capture` | Web recording (Playwright Chromium) + bundled ffmpeg | ~250 MB |
| `capture-desktop` | Desktop window: pywinauto (Windows) / Appium Mac2 (macOS) | ~15 MB |
| `capture-android` | Android via Appium UiAutomator2, scrcpy or adb | ~280 MB |
| `capture-ios` | iOS Simulator/device via Appium XCUITest (macOS only) | ~300 MB |
| `voice-edge` | Microsoft Edge neural voices; online, free | ~5 MB |
| `voice-kokoro` | Kokoro TTS; fully offline, pulls PyTorch | ~2 GB |
| `voice-elevenlabs` | ElevenLabs voices; paid API | ~5 MB |
| `captions` | Word timing (faster-whisper), SRT/ASS | ~150 MB |
| `mix` | Music ducking, loudness normalisation | ~30 MB |
| `blur` | Blur emails, tokens, faces in frames | ~60 MB |
| `motion-basic` | Zoom/pan, overlays, fades via ffmpeg | ~0 MB |
| `motion-cinematic` | Titles, transitions, animated captions via Remotion | ~400 MB |
| `qa-ocr` | OCR the finished video to verify text and redactions: RapidOCR + onnxruntime, Python 3.10-3.13 (default) | ~120 MB |
| `qa-ocr-tesseract` | Same job with Tesseract: lighter, less accurate; needs the `tesseract` program on PATH | ~60 MB |
| `package` | Thumbnails, posters, covers | ~10 MB |

## Fixing a finished video

`/demo-studio:fix "scene 3 out of sync"` (or no argument, to read `qa.md` and render checks). The director diagnoses, routes to the one owner, re-runs only the dependent steps, re-renders and re-checks.

| Symptom | Owner |
|---|---|
| Audio/video out of sync | sync-editor |
| Email, name or amount still visible | privacy-blurrer |
| Wrong click, UI changed, scene broken | scene-automator |
| Black frame, freeze, bad recording | capture-operator |
| Wrong translation, UI term, on-screen text language | localizer, then voice-producer |
| Awkward narration | scriptwriter, (localizer), then voice-producer |
| Caption wrong or off | caption-writer |
| Music too loud, voice too quiet | sound-mixer |
| Zoom in the wrong place, missing callout | motion-designer |
| You edited `demo.yaml` | director runs `config.py diff`, then the owners it lists |

Owner unclear: it asks you. Same defect after two attempts: it stops and reports. If you already know the cause, `/rerecord` and `/revoice` are shortcuts.

## Privacy

- Real data in the app is **blurred, not replaced**: `privacy-blurrer` never fakes or swaps content.
- `app-scout` flags sensitive elements up front; scene scripts report their boxes with `mark()`.
- The render check requires zero readable text inside blur regions (OCR); an OCR tool (`tools.ocr`) is recommended whenever the app shows real data.
- `demo-qa` also looks for leaked personal data by eye before you reach G3.

## License

MIT. See [LICENSE](LICENSE).
