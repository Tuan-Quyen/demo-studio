---
name: run-kits
description: Runbook for the demo-studio team — roster (agent, job, writes, model), the pipeline commands and their gates, the scene-automator/capture-operator boundary, how to write a brief, the handoff format, the .demo/ workspace and project.json keys, /fix routing, toolkit install approval, and resume rules. Load it when running a pipeline, writing a brief, reading a handoff, or when the user asks what the team or a command does.
---

# demo-studio run-kits

Plugin files: `${CLAUDE_PLUGIN_ROOT}/…`. Commands: `/demo-studio:<name>`. Only the director runs pipelines (a subagent cannot spawn agents), so each command starts with "Act as demo-director".

## 1. Roster

| Agent | One job | Writes | Model |
|---|---|---|---|
| `demo-director` | classify request, pick pipeline, delegate, keep resume point | `.demo/STATE.md` | opus |
| `toolsmith` | check/install only the features a job needs, after user approval | `.demo/.venv`, `toolkit.json` | haiku |
| `demo-strategist` | audience, goal, message, length, CTA | `brief.md` | inherit |
| `app-scout` | explore app, set `platform:`, map flows/selectors, flag sensitive elements | `app-map.md` | inherit |
| `storyboarder` | scenes and shots: on-screen action, camera intent, duration | `storyboard.md` | opus |
| `scriptwriter` | per-scene narration within word budget (~150 wpm) | `narration.md` | opus |
| `voice-producer` | TTS per scene, measure duration | `media/sNN.vo.wav`, `#voice` | haiku |
| `scene-automator` | action-only scene scripts, VO pauses, `mark()`, dry-run | `scenes.<platform>.*` | inherit |
| `capture-operator` | recorder wrapper, run script unmodified, collect markers, save raw clips | `media/sNN.raw.*`, `#events` | haiku |
| `privacy-blurrer` | blur regions over time (email, name, amount, token); no fake data, no video | `#blur` | haiku |
| `sync-editor` | align clips with VO: pad, trim, speed | `#timeline` | inherit |
| `motion-designer` | zoom/pan on click, highlights, callouts, title cards, device frames | `#motion` | inherit |
| `caption-writer` | word-timed VTT/SRT captions | `#captions` | haiku |
| `sound-mixer` | music, ducking, −14 LUFS / −1 dBTP target | `#mix` | haiku |
| `render-engineer` | single-pass render 16:9, 9:16, 1:1; measure while rendering | `media/final-*.mp4`, `final.vtt`, `#checks` | haiku |
| `demo-qa` | what machines cannot measure: spelling, broken UI, pacing, leaked PII → PASS/FAIL | `qa.md` | inherit |
| `packager` | thumbnail, chapters, title, description, manifest | `media/thumb.png`, `#delivery` | haiku |

`#key` = `project.json#key`. Only the owner writes its file/key; everyone reads.

## 2. Commands → pipeline → gates

`→` sequential, `∥` parallel. Gates: **G1** brief approved · **G2** storyboard + narration approved (before any recording) · **G3** final render approved after QA.

| Command | For | Pipeline | Gates |
|---|---|---|---|
| `run` | any request; empty = resume | director classifies, then runs one below | per pipeline |
| `new` | video from scratch | toolsmith → strategist → scout → storyboarder → scriptwriter → voice-producer → scene-automator → capture-operator → blurrer → sync-editor → motion-designer → (caption-writer ∥ sound-mixer) → render-engineer → demo-qa → packager | G1, G2, G3 |
| `script` | pre-production only | strategist → scout → storyboarder → scriptwriter | G1, G2 |
| `shoot` | approved script → render | toolsmith → voice-producer → scene-automator → capture-operator → blurrer → sync-editor → motion-designer → (captions ∥ mix) → render-engineer → demo-qa | G3 (needs G2) |
| `rerecord` | UI changed in a scene | scene-automator → capture-operator → blurrer → sync-editor → motion-designer → render-engineer → demo-qa | G3 |
| `revoice` | new text, voice or language | scriptwriter → voice-producer → sync-editor → (captions ∥ mix) → render-engineer → demo-qa | G2 (text), G3 |
| `cut` | new aspect ratio or shorter cut | motion-designer → caption-writer → render-engineer → demo-qa | G3 |
| `fix` | symptom text; empty = read `qa.md` + `#checks` | director diagnoses → owner → dependent keys → render → qa | G3 |
| `tools` | view/install toolkit | `--list`/`--check` → ask → toolsmith | install approval |
| `review` | inspect existing video, no edits | demo-qa | — |
| `status` | where are we | read `STATE.md` only | — |

Loops: render check failure → owner of that key. QA FAIL → owner of the finding, re-render, QA. Same finding 3 rounds → ask the user. VO is produced **before** scenes so pauses fit real durations.

## 3. scene-automator ↔ capture-operator boundary

| Concern | scene-automator | capture-operator |
|---|---|---|
| App actions, selectors, pauses timed to VO | owns | never edits |
| `mark()` for clicks and sensitive bboxes | calls in script | collects into `#events` |
| Recording on/off, fps, resolution, viewport, DND | does not touch | owns (recorder adapter) |
| Run script | dry-run, no recording | real run with recording |
| Step / selector failure | fixes it | stops, returns `blocked` with log + screenshot |
| Environment failure (timeout, device, network) | — | retries max 2, then reports |

Flow: automator → `scenes.<platform>.*` + dry-run PASS → operator → `media/sNN.raw.*` + `#events`. Shared contract (`mark()`, recorder adapters) lives in skill `platform-automation`.

## 4. Writing a brief

Every agent starts cold and sees only the brief.

```
Slug: <slug> · Pipeline: <name> · Step: <n — name> · Scene(s): <sNN or all>
Goal: <what this step must produce>
Read: <.demo/ files, project.json keys, code/app paths>
Write: <the files / keys it owns for this step>
Constraints: <platform, user decisions so far (motion level, voice, language), finding IDs to fix, gates passed, features approved for install>
User's language: <language>
```

Name files and keys, never "the above". Template: `${CLAUDE_PLUGIN_ROOT}/templates/brief.md` is the demo brief (strategist); the block above is the agent work order.

## 5. Handoff

Every agent ends with:

```
### Handoff · <agent>
status: done | needs-input | blocked
wrote: <paths / project.json#key>
facts: <key numbers: scenes, seconds, words, drift ms, LUFS>
next: <agent or user>
notes: <issues; questions with options + recommended default>
```

Director checks `wrote:` against the agent's allowed outputs; `needs-input` → ask the user (options + default) then re-brief; `blocked` → route by §3 / §7 or tell the user.

## 6. Workspace

```
.demo/STATE.md  .venv/  toolkit.json
.demo/<slug>/
  brief.md  app-map.md  storyboard.md  narration.md  qa.md
  scenes.<platform>.*
  project.json
  media/  sNN.raw.*  sNN.vo.wav  final-16x9.mp4  final-9x16.mp4  final-1x1.mp4  final.vtt  thumb.png
```

Only two kinds of video file: raw clips and finals. Blur, motion, captions and mix are instructions in `project.json`, not intermediate videos. Templates in `${CLAUDE_PLUGIN_ROOT}/templates/`.

**project.json keys → owner:** `events` capture-operator · `voice` voice-producer · `blur` privacy-blurrer · `timeline` sync-editor · `motion` motion-designer · `captions` caption-writer · `mix` sound-mixer · `checks` render-engineer · `delivery` packager.

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/project.py --slug <slug> get <key>
python ${CLAUDE_PLUGIN_ROOT}/scripts/project.py --slug <slug> set <key> --as <agent> --file <json>
```

Locked and owner-checked, so parallel agents do not overwrite each other. Never edit `project.json` by hand.

**Dependency order:** voice → timeline, captions, mix · events → blur, timeline · timeline → motion · {blur, motion, captions, mix} → checks → delivery.

**Render checks (`#checks`, thresholds in skill `media-specs`):** sync drift ≤80 ms/scene → sync-editor · −14±1 LUFS, ≤−1 dBTP → sound-mixer · 0 readable text in blur regions (OCR) → privacy-blurrer · no unintended black/freeze → capture-operator · captions ≤42 chars/line, ≤200 ms off → caption-writer · total length ±10% of brief → storyboarder.

## 7. /fix routing

| Symptom | Owner | Then re-run |
|---|---|---|
| Audio/video out of sync | sync-editor | render → qa |
| Email, name, amount still visible | privacy-blurrer | render → qa |
| Wrong click, UI changed, scene broken | scene-automator | capture → blur → timeline → motion → render → qa |
| Black frame, freeze, bad recording | capture-operator | blur → timeline → motion → render → qa |
| Wrong or awkward narration | scriptwriter → voice-producer | timeline ∥ captions ∥ mix → render → qa |
| Caption wrong or off | caption-writer | render → qa |
| Music too loud, voice too quiet, LUFS off | sound-mixer | render → qa |
| Zoom in wrong place, missing callout | motion-designer | render → qa |

Owner unclear → ask the user, do not guess. One STATE.md line per fix. Same defect after 2 attempts → stop and report. `/rerecord` and `/revoice` are shortcuts when the cause is known.

## 8. Toolkit

`python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py` — `--list` (catalog) · `--check [features]` (installed / missing / blocked) · `--plan <features>` (what, how many MB) · `--install <features>` (only after approval). Installs into `.demo/.venv`, records `.demo/toolkit.json`. It never prompts.

| Feature | Gives |
|---|---|
| `capture` | web recording (Playwright Chromium) + bundled ffmpeg; needed for every platform |
| `capture-desktop` / `capture-android` / `capture-ios` | desktop (pywinauto / Appium Mac2), Android (Appium, scrcpy), iOS (macOS + Xcode only; else `blocked`) |
| `voice-edge` (default) / `voice-kokoro` / `voice-elevenlabs` | free online TTS / offline, heavy (torch) / paid, needs `ELEVENLABS_API_KEY` |
| `captions` | word-level timing (faster-whisper) |
| `mix` | ducking and loudness normalisation |
| `blur` | region blur (OpenCV) |
| `motion-basic` / `motion-cinematic` | ffmpeg zoom/fade (0 MB) / Remotion titles and callouts (Node ≥18, ~400 MB) |
| `qa-ocr` | OCR check for leftover sensitive text; recommended with real data |
| `package` | thumbnails |

Features not yet in `--list` are not installed by the script; report `blocked` rather than improvising.

**Install-approval flow:**
1. An agent runs `--check <feature>`; missing → handoff `needs-input` with the `--plan` output.
2. Director asks the user (options with size and effect, a recommended default; e.g. motion: none / basic / cinematic).
3. Approved → toolsmith `--install`, then `--check`; the agent continues. Declined → fall back (cinematic → basic, word captions → sentence captions) and continue.
4. Save the choice in `brief.md` so it is not asked again. Never install a feature nobody needs.

## 9. Resume

- `.demo/STATE.md` is the director's file: slug, pipeline, current step, gate status, per-step status, fix log, next action.
- `/demo-studio:run` with no argument, or a new session: read STATE.md, check the listed outputs exist (`project.py keys` for keys), continue at the first step not `done`.
- Gates already approved are not asked again; a changed input (storyboard, narration, scene) invalidates the gates and keys downstream of it.
- Conflicting STATE.md and files on disk → trust the files, tell the user, fix STATE.md.
- Never commit or push unless the user asks.
