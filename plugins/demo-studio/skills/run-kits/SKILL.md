---
name: run-kits
description: Runbook for the demo-studio team — roster (agent, job, writes, model), the pipeline commands and their gates, the scene-automator/capture-operator boundary, how to write a brief, the handoff format, the .demo/ workspace and project.json keys, /fix routing, toolkit install approval, and resume rules. Load it when running a pipeline, writing a brief, reading a handoff, or when the user asks what the team or a command does.
---

# demo-studio run-kits

Plugin files: `${CLAUDE_PLUGIN_ROOT}/…`. Commands: `/demo-studio:<name>`. Only the director runs pipelines (a subagent cannot spawn agents), so each command starts with "Act as demo-director".

## 1. Roster

| Agent | One job | Writes | Model |
|---|---|---|---|
| `demo-director` | classify request, pick pipeline, delegate, keep resume point, record the user's decisions; after gate GA only, place approved art in the repo | `.demo/STATE.md`, user decisions in `demo.yaml`, repo files after GA | opus |
| `toolsmith` | `suggest` (read-only): what a stage needs, options, plan · `install`: only the approved features | `.demo/.venv`, `toolkit.json` | haiku |
| `demo-strategist` | audience, goal, message, CTA (prose) and the initial video properties | `brief.md`, `demo.yaml` (create) | inherit |
| `app-scout` | explore app, check it matches `platform` in `demo.yaml`, map flows/selectors, flag sensitive elements | `app-map.md` | inherit |
| `storyboarder` | scenes and shots: on-screen action, camera intent, duration | `storyboard.md` | opus |
| `scriptwriter` | per-scene narration in `language` within the `demo-storytelling` word budget | `narration.md` | opus |
| `localizer` | only when `language` ≠ `voice.language`: translate narration, UI-term glossary, lexicon proposals, on-screen strings | `localization.md`, `narration.<voice.language>.md` | inherit |
| `art-designer` | marketing images from `brief.md` + `localization.md` (video) or a source doc (standalone): static SVG + PNG (skill `key-art`); proposes the repo placement | `art/<id>.svg` + `.png`, `art/assets/*.png` (approved character images, or a character sheet + its crops), `art/prompts.md` (sheet prompt), `art/readme-snippet.md` (standalone), `#art` | inherit |
| `voice-producer` | TTS or own-voice VO per scene (skill `voice-over`: engines, lexicon, pacing), measure duration | `media/sNN.vo.wav`, `#voice` | haiku |
| `scene-automator` | action-only scene scripts, VO pauses, `mark()`, dry-run | `scenes.<platform>.*`, `demo_ctx.py`, `mobile_driver.py` (copy, android/ios) | inherit |
| `capture-operator` | recorder wrapper, run script unmodified (prepare → start), collect markers, save raw clips, full-frame check | `media/sNN.raw.*`, `#events` | haiku |
| `privacy` | recordings: blur regions over time (email, name, amount, token); art: audit only, never blurs or edits it; no fake data, no video | `#blur`, `#privacy` | haiku |
| `sync-editor` | align clips with VO: pad, trim, speed | `#timeline` | inherit |
| `motion-designer` | zoom/pan on click, highlights, callouts, title cards, device frames | `#motion` | inherit |
| `caption-writer` | word-timed VTT/SRT captions | `#captions` | haiku |
| `sound-mixer` | music, ducking, loudness targets from `demo.yaml` (default −14 LUFS / −1 dBTP) | `#mix` | haiku |
| `render-engineer` | single-pass render 16:9, 9:16, 1:1; measure while rendering | `media/final-*.mp4`, `final.vtt`, `#checks` | haiku |
| `demo-qa` | what machines cannot measure: spelling, broken UI, pacing, leaked PII → PASS/FAIL; art mode checks the art set | `qa.md` (video, G3), `qa-art.md` (art) | inherit |
| `packager` | thumbnail, chapters, title, description, manifest | `media/thumb.png`, `#delivery` | haiku |

19 agents. `#key` = `project.json#key`. Only the owner writes its file/key; everyone reads. `demo.yaml` is owned by the user (see §6).

## 2. Commands → pipeline → gates

`→` sequential, `∥` parallel. Gates: **G1** brief approved · **G2** storyboard + narration (+ art in `new`/`script`) approved (before any recording) · **G3** final render approved after QA · **GA** art set approved (standalone `art` only).

| Command | For | Pipeline | Gates |
|---|---|---|---|
| `run` | any request; empty = resume | director classifies, then runs one below | per pipeline |
| `new` | video from scratch | strategist → scout → storyboarder → scriptwriter → (localizer) → **[art]** → voice-producer → scene-automator → capture-operator → (privacy ∥ sync-editor) → (motion-designer ∥ caption-writer ∥ sound-mixer) → render-engineer → demo-qa → packager | G1, G2, G3 |
| `script` | pre-production only | strategist → scout → storyboarder → scriptwriter → (localizer) → **[art]** | G1, G2 |
| `art` | marketing images from a source doc (e.g. README.md), no video | **[art]**, then the director places the files in the repo | GA |
| `shoot` | approved script → render | voice-producer → scene-automator → capture-operator → (privacy ∥ sync-editor) → (motion-designer ∥ caption-writer ∥ sound-mixer) → render-engineer → demo-qa | G3 (needs G2) |
| `rerecord` | UI changed in a scene | scene-automator → capture-operator → (privacy ∥ sync-editor) → motion-designer → render-engineer → demo-qa | G3 |
| `revoice` | new text, voice or language | scriptwriter → (localizer) → ([art] when `localization.md` or the language changed, via `config.py diff`; style asked only if `#art.style` is missing) → voice-producer → sync-editor → (motion-designer ∥ caption-writer ∥ sound-mixer) → render-engineer → demo-qa | G2 (text), G3 |
| `cut` | new aspect ratio or shorter cut | (sync-editor if scenes are dropped) → (motion-designer ∥ caption-writer) → render-engineer → demo-qa | G3 |
| `fix` | symptom text; empty = read `qa.md` + `#checks` | director diagnoses → owner → dependent keys → render → qa | G3 |
| `tools` | view/install toolkit | `--list`/`--options`/`--stages` → toolsmith `suggest` → ask → toolsmith `install` | install approval |
| `review` | inspect existing video, no edits | demo-qa | — |
| `status` | where are we | read `STATE.md` only | — |

**[art] = art sub-pipeline** (one unit, run to the end before the next step starts): **step 0 style question (director only; shown with the visual picker page `.demo/artifact_design/key_design_picker.html`, rebuilt by `style_picker.py` before each ask; once per run, right before the stage check, never at G1; in `revoice` only when art re-runs and `#art.style` is missing; the answer is in STATE.md before art-designer is briefed; rules in the director file and `key-art/references/styles.md`; the same exchange records the user's approval of their own character images, `Assets:`, when offered; or, when the user picks a character sheet: art-designer `Mode: sheet-prompt` writes `art/prompts.md` → the user runs it in their own image tool → the director asks approval of the sheet and its role order → `Assets: sheet ...`, cut by `art_assets.py split`)** → art-designer → privacy (audit, `#privacy.art`) → demo-qa (art mode, `qa-art.md`) → FAIL: the finding's owner (`art-designer`, or `privacy` for an audit gap) fixes, then privacy and demo-qa run again; same finding 3 rounds → ask the user. PASS → the gate. In `new`/`script` the gate is **G2**: one question shows the art previews (PNG, or SVG when the PNG is missing, each labelled `<file> · <w>x<h>`) + the `qa-art.md` verdict + storyboard + narration (both languages when localized) + glossary; options: approve and record / edit script / edit storyboard / edit art; G2 never opens before art PASS, there is no separate GA, and nothing after G2 starts earlier. In `art` (standalone) the gate is **GA**: options approve and place / edit art / keep in `.demo/` only. Standalone workspace: slug `<source-stem>-art`, `.demo/<slug>/{art/, project.json, qa-art.md}` only (no `brief.md`, `demo.yaml`, `.demo.applied.json`; the director never calls `config.py`; the render-engine and install answers are kept in STATE.md). A missing or empty source doc → `needs-input`, nothing generated. Stage `art` (§8) is checked right before art-designer; declined remotion → SVG-only art (`png: null`, `missing_png`), the handoff is `needs-input` and the gate offers the install.

**Placement (director, only after GA "approve and place"):** for each `from`/`to` in `#art.repo.files` (`from` inside `.demo/<slug>/art/`; `to` relative, no `..`, no drive or leading `/`, inside the repo root, not under `.git/`, `.demo/` or `.claude/`; otherwise skipped and reported), if the target exists ask overwrite or rename; copy; insert `art/readme-snippet.md` into the source doc; Glob every relative link in the snippet (all must resolve); report the changed repo files; never commit. Before GA nothing is copied, and a re-run that changes art leaves the repo files untouched until GA again. A `brief.md` edit reopens G1 and re-runs the art sub-pipeline before G2.

Order is the dependency order of §6: caption-writer and sound-mixer need `#timeline`, so they never run before sync-editor. (localizer) runs only when `language` is set and differs from `voice.language`. Loops: render check failure → owner of that key. QA FAIL → owner of the finding, re-render, QA. Same finding 3 rounds → ask the user (art: `qa-art.md` / `#privacy` findings, as above). VO is produced **before** scenes so pauses fit real durations.

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
Python: python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --python   (prints the toolkit interpreter; use it for all toolkit code)
Constraints: <values the step needs from `demo.yaml` (name the fields, e.g. platform, voice.language), finding IDs to fix, gates passed, features approved for install>
User's language: <language>
```

Name files and keys, never "the above". Do not paste property values into the brief: the agent reads them itself with `config.py get`. Template: `${CLAUDE_PLUGIN_ROOT}/templates/brief.md` is the demo brief (prose only, strategist); `templates/demo.yaml` holds the video properties; the block above is the agent work order.

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

**Handoff truth:** after every `project.py set`, quote the printed line (`<key> version N (<path>)`) in `facts`; never claim a write without it. Director checks `wrote:` against the agent's allowed outputs and the quoted version against `project.py --slug <slug> get <key> --version` (mismatch, or a path outside `.demo/<slug>/` = re-brief). **Evidence rule:** a `wrote:` claim about media (raw clips, finals) must come with evidence in `facts` (ffprobe w x h @ fps + duration, and a checked frame); the director spot-checks one frame of the raw clips and of the final before moving on, and sends back a claim without evidence; `needs-input` → ask the user (options + default) then re-brief; `blocked` → route by §3 / §7 or tell the user.

## 6. Workspace

```
.demo/STATE.md  .venv/  toolkit.json  artifact_design/key_design_picker.html (director, style picker)
.demo/<slug>/
  brief.md  demo.yaml  app-map.md  storyboard.md  narration.md  qa.md  qa-art.md
  art/  <id>.svg  <id>.png  readme-snippet.md (standalone)
  scenes.<platform>.*
  project.json  .demo.applied.json
  media/  sNN.raw.*  sNN.vo.wav  final-16x9.mp4  final-9x16.mp4  final-1x1.mp4  final.vtt  thumb.png
```

Only two kinds of video file: raw clips and finals. Blur, motion, captions and mix are instructions in `project.json`, not intermediate videos. Templates in `${CLAUDE_PLUGIN_ROOT}/templates/`.

**Files → owner:** `brief.md` demo-strategist (prose; user approves at G1) · `demo.yaml` **the user** (demo-strategist creates it at G1; demo-director records the user's decisions in it: motion level, voice, tool choices, install choices; every other agent reads only) · `.demo.applied.json` snapshot written by `config.py apply` (director: after G1 as baseline, after every G3) · `app-map.md` app-scout · `storyboard.md` storyboarder · `narration.md` scriptwriter (in `language`) · `localization.md`, `narration.<voice.language>.md` localizer (only when `language` ≠ `voice.language`; voice-producer reads the latter when it exists) · `qa.md` demo-qa (video, G3) · `qa-art.md` demo-qa (art mode) · `art/` art-designer only (nobody else writes there; the director copies from it into the repo after GA).

**`demo.yaml`** controls the video's properties: `platform`, `length_s`, `formats`, `voice {engine, name, language, lexicon}`, `motion {level}`, `music {style, duck_db}`, `captions {burn_in, layout, max_chars}`, `targets {lufs, true_peak, max_drift_ms, caption_offset_ms}`, `privacy {blur, real_data}`, `install {approved, declined}`. Template with allowed values and defaults: `${CLAUDE_PLUGIN_ROOT}/templates/demo.yaml`. A value lives only there; agents read it, never copy it.

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/config.py --slug <slug> init | validate | get <dotted.path> | diff [--json] | apply | apply-lexicon (--text T | --file F | stdin) [--json]
```
`get` prints JSON with defaults applied (e.g. `get targets.max_drift_ms` → `80`). `apply-lexicon` returns the TTS input with `voice.lexicon` substituted plus the `applied` list (voice-producer only; a lexicon change re-runs voice, no G2). `diff` compares with `.demo.applied.json` (the config of the last approved state; missing = first run, nothing to diff) and prints the changed fields, the `project.json` keys to re-run (own step + `project.py deps`) and any earlier agent/gate to reopen. Exit 2 on a bad file, with the line.

**project.json keys → owner:** `art` art-designer · `events` capture-operator · `voice` voice-producer · `blur` privacy · `privacy` privacy (art audit results, separate from `blur`) · `timeline` sync-editor · `motion` motion-designer · `captions` caption-writer · `mix` sound-mixer · `checks` render-engineer · `delivery` packager.

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/project.py --slug <slug> get <key>
python ${CLAUDE_PLUGIN_ROOT}/scripts/project.py --slug <slug> set <key> --as <agent> --file <json>
```

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/vo.py trim IN OUT [--lead-ms 200 --trail-ms 150]
python ${CLAUDE_PLUGIN_ROOT}/scripts/vo.py join OUT IN... [--gap-ms 300 --edge-ms 50]
python ${CLAUDE_PLUGIN_ROOT}/scripts/vo.py check IN [--lead-max 200 --trail-max 150 --gap-max 500 --pause-ms N...]   # exit 1 on fail
```
`vo.py` (voice-producer builds scenes with it; render-engineer and sound-mixer check with it) prints JSON; never hand-roll audio trimming.

Locked and owner-checked, so parallel agents do not overwrite each other. Never edit `project.json` by hand. A key's value has no version field (`schema` is the format version, not the data version): read the version with `get <key> --version` (0 = never set) or `keys`. `--slug` finds the nearest `.demo/<slug>` above cwd and refuses to run from inside `.demo/` without one.

**Dependency order:** art → privacy, motion, delivery · voice → timeline, captions, mix · events → blur, timeline · timeline → motion, captions, mix · {blur, motion, captions, mix} → checks → delivery. A `length_s` change re-runs storyboarder (G2) → timeline → motion, captions, mix → checks → delivery; voice only if narration changes.

**Render checks (`#checks`; thresholds from `demo.yaml` `targets`/`captions`, defaults in skill `media-specs`):** sync drift ≤`targets.max_drift_ms` (80) per scene → sync-editor · `targets.lufs` (−14) ±1 LUFS, ≤`targets.true_peak` (−1) dBTP → sound-mixer · every `sensitive` marker covered by `#blur` (`project.py check-blur`, geometric, no OCR) → privacy · no unintended black/freeze → capture-operator · captions ≤`captions.max_chars` (42) chars/line, ≤`targets.caption_offset_ms` (200) off → caption-writer · total length ±10% of `length_s` → storyboarder.

## 7. /fix routing

| Symptom | Owner | Then re-run |
|---|---|---|
| Audio/video out of sync | sync-editor | render → qa |
| Email, name, amount still visible (video) | privacy | render → qa |
| Wrong click, UI changed, scene broken | scene-automator | capture → (blur ∥ timeline) → motion → render → qa |
| Black frame, freeze, bad recording | capture-operator | (blur ∥ timeline) → motion → render → qa |
| Wrong translation, UI term, on-screen text language | localizer → voice-producer | timeline → (motion ∥ captions ∥ mix) → render → qa |
| Wrong or awkward narration | scriptwriter → (localizer) → voice-producer | timeline → (motion ∥ captions ∥ mix) → render → qa |
| Caption wrong or off | caption-writer | render → qa |
| Music too loud, voice too quiet, LUFS off | sound-mixer | render → qa |
| Zoom in wrong place, missing callout | motion-designer | render → qa |
| Wrong key art, title/end/thumbnail art | art-designer | privacy → demo-qa (art) → art approval → motion → render → qa → G3 → packager |
| Wrong look or style of key art (user wants a different style) | director: style question again (re-pick, list shown with current choice marked; not a finding, 3-round cap restarts), then art-designer redoes all items | privacy → demo-qa (art) → art approval → motion → render → qa → G3 → packager |
| Private data visible in key art | art-designer (the `#privacy.art` finding) | privacy → demo-qa (art) → art approval → motion → render → qa → G3 → packager |
| Changed `demo.yaml` (user edited it) | director runs `config.py validate` + `diff` | from the earliest owner `diff` lists, then downstream keys → render → qa |

**Art approval** (the key-art rows, after the video passed G2): the director shows the new art previews and the `qa-art.md` verdict in one question (approve / edit art / keep previous art); it is not G2, and G3 still follows the render.

Owner unclear → ask the user, do not guess. One STATE.md line per fix. Same defect after 2 attempts → stop and report. `/rerecord` and `/revoice` are shortcuts when the cause is known.

## 8. Toolkit

`python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py` — `--list` (catalog) · `--check [features]` (installed / missing / blocked) · `--plan <features>` (what, how many MB) · `--install <features>` (only after approval) · `--options [capability]` (alternatives per job, see below) · `--stage [name]` / `--stages` (read-only: what a pipeline stage needs, alternatives, suggested `--plan`; `--platform`, `--choose cap=value`, `--with feature`, `--json`) · `--python` (prints the toolkit interpreter path; never hard-code `.demo/.venv/...`). Installs into `.demo/` (`.venv`, `remotion/`, `appium/` for macOS desktop only), records `.demo/toolkit.json`. It never prompts.

| Feature | Gives |
|---|---|
| `capture` | web recording (Playwright Chromium) + bundled ffmpeg; needed for every platform |
| `capture-desktop` / `capture-android` / `capture-ios` | desktop (pywinauto / Appium Mac2), Android (`adb` + `scripts/mobile_driver.py`, scrcpy; nothing downloaded), iOS (Simulator via AXe + simctl; macOS + Xcode only, else `blocked`) |
| `voice-edge` (default) / `voice-kokoro` / `voice-elevenlabs` | free online TTS / offline, heavy (torch) / paid, needs `ELEVENLABS_API_KEY` |
| `captions` | word-level timing (faster-whisper) |
| `mix` | ducking and loudness normalisation |
| `blur` | moving-region blur for the ffmpeg fallback renderer (OpenCV) |
| `remotion` (default) / `motion-basic` | render engine for every pipeline: Remotion, all motion levels (Node ≥18, ~550 MB, `.demo/remotion/`) / ffmpeg fallback, motion none + basic only (0 MB) |
| `package` | thumbnails |

Features not yet in `--list` are not installed by the script; report `blocked` rather than improvising.

**Choosing the tool (capabilities).** Where several features do the same job, the user picks; no agent hard-codes one. `setup_tools.py --options [voice|render] [--json]` lists the alternatives (tool, effect, size, needs, installed / missing / blocked, recommended first) and the `demo.yaml` field that records the choice:

| Capability | demo.yaml | Values (features) |
|---|---|---|
| `voice` | `voice.engine` | `edge` (`voice-edge`) · `kokoro` · `elevenlabs` · `recorded` (no feature) |
| `render` | `install.approved` / `install.declined` (`remotion`) | `remotion` (recommended) · `ffmpeg` (`motion-basic`, motion none/basic only) |

Blur coverage needs no tool choice: `project.py check-blur` (stdlib, geometric) is the only check, no OCR. A new alternative = a `CATALOG` entry with `capability` and its `CAPABILITIES` value.

Stage `art` (needs the render choice, `remotion` for PNG) sits after `scout` in `--stages` but runs after (localizer) in the pipelines; its agent is art-designer.

**Just-in-time flow (nothing is installed at the start of a pipeline).** The stage map lives in `setup_tools.py` (`--stages`); the pipelines name each step's stage. The render engine is the one choice made at G1 (motion-designer plans for it, `motion-fx`); Remotion itself is still installed just in time, before the motion stage.
1. Right before a step the director runs `--stage <name> --platform <p> --json` (with `--choose render=<remotion|ffmpeg>` for `motion` / `render`). `ready` → run the step.
2. Not ready → toolsmith `suggest` for that stage only (reads `voice.engine`, `motion.level`, `platform`, `voice.lexicon`, `install.approved`, `install.declined` from `demo.yaml`; returns `needs-input` with options table, recommended default and `--plan`, or `done`).
3. Director asks the user (install recommended / alternative / skip with fallback / cancel). Approved → toolsmith `install` (`--plan` check, `--install`, `--check`), then the step runs. Declined → fall back (Remotion → ffmpeg with cinematic → basic, word captions → sentence captions) and continue.
4. Director records the decision in `demo.yaml` (`install.approved` / `install.declined`, plus the choice itself: `motion.level`, `voice.engine`) so it is not asked again. Agents keep their own `--check` as a safety net: a missing feature → `needs-input` with the `--plan`, handled by steps 2-4. Never install a feature nobody needs yet.

## 9. Resume

- `.demo/STATE.md` is the director's file: slug, pipeline, current step, gate status, per-step status, fix log, next action.
- `/demo-studio:run` with no argument, or a new session: read STATE.md, run `config.py validate` then `diff` (invalid → show the errors and stop; changed fields → invalidate the listed keys/gates and restart at the earliest owner `diff` names), check the listed outputs exist (`project.py keys` for keys), continue at the first step not `done`.
- Gates already approved are not asked again; a changed input (`demo.yaml` field, storyboard, narration, scene) invalidates the gates and keys downstream of it. The director runs `config.py validate` + `diff` at the start of every pipeline, `config.py apply` after G1 (baseline) and after every G3.
- Conflicting STATE.md and files on disk → trust the files, tell the user, fix STATE.md.
- Never commit or push unless the user asks.
