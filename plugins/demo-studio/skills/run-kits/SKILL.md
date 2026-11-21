---
name: run-kits
description: Runbook for the demo-studio team — roster (agent, job, writes, model), the pipeline commands and their gates, the scene-automator/capture-operator boundary, how to write a brief, the handoff format, the .demo/ workspace and project.json keys, /fix routing, toolkit install approval, and resume rules. Load it when running a pipeline, writing a brief, reading a handoff, or when the user asks what the team or a command does.
---

# demo-studio run-kits

Plugin files: `${CLAUDE_PLUGIN_ROOT}/…`. Commands: `/demo-studio:<name>`. Only the director runs pipelines (a subagent cannot spawn agents), so each command starts with "Act as demo-director".

## 1. Roster

| Agent | One job | Writes | Model |
|---|---|---|---|
| `demo-director` | classify request, pick pipeline, delegate, keep resume point, record the user's decisions | `.demo/STATE.md`, user decisions in `demo.yaml` | opus |
| `toolsmith` | `suggest` (read-only): what a stage needs, options, plan · `install`: only the approved features | `.demo/.venv`, `toolkit.json` | haiku |
| `demo-strategist` | audience, goal, message, CTA (prose) and the initial video properties | `brief.md`, `demo.yaml` (create) | inherit |
| `app-scout` | explore app, check it matches `platform` in `demo.yaml`, map flows/selectors, flag sensitive elements | `app-map.md` | inherit |
| `storyboarder` | scenes and shots: on-screen action, camera intent, duration | `storyboard.md` | opus |
| `scriptwriter` | per-scene narration in `language` within the `demo-storytelling` word budget | `narration.md` | opus |
| `localizer` | only when `language` ≠ `voice.language`: translate narration, UI-term glossary, lexicon proposals, on-screen strings | `localization.md`, `narration.<voice.language>.md` | inherit |
| `voice-producer` | TTS or own-voice VO per scene (skill `voice-over`: engines, lexicon, pacing), measure duration | `media/sNN.vo.wav`, `#voice` | haiku |
| `scene-automator` | action-only scene scripts, VO pauses, `mark()`, dry-run | `scenes.<platform>.*`, `demo_ctx.py` | inherit |
| `capture-operator` | recorder wrapper, run script unmodified (prepare → start), collect markers, save raw clips, full-frame check | `media/sNN.raw.*`, `#events` | haiku |
| `privacy-blurrer` | plans blur regions not masked at capture with `blur.py` (plan, preview); no fake data, no video, no own OCR | `#blur` | haiku |
| `sync-editor` | align clips with VO: pad, trim, speed | `#timeline` | inherit |
| `motion-designer` | zoom/pan on click, highlights, callouts, title cards, device frames | `#motion` | inherit |
| `caption-writer` | word-timed VTT/SRT captions | `#captions` | haiku |
| `sound-mixer` | music, ducking, loudness targets from `demo.yaml` (default −14 LUFS / −1 dBTP) | `#mix` | haiku |
| `render-engineer` | single-pass render 16:9, 9:16, 1:1 (blur via `blur.py graph`), then `blur.py verify` per aspect + `checks.py` | `media/final-*.mp4`, `final.vtt`, `#checks` (via the scripts) | haiku |
| `demo-qa` | what machines cannot measure: spelling, broken UI, pacing, leaked PII → PASS/FAIL | `qa.md` | inherit |
| `packager` | thumbnail, chapters, title, description, manifest | `media/thumb.png`, `#delivery` | haiku |

`#key` = `project.json#key`. Only the owner writes its file/key; everyone reads. `demo.yaml` is owned by the user (see §6).

## 2. Commands → pipeline → gates

`→` sequential, `∥` parallel. Gates: **G1** brief approved · **G2** storyboard + narration approved (before any recording) · **G3** final render approved after QA.

| Command | For | Pipeline | Gates |
|---|---|---|---|
| `run` | any request; empty = resume | director classifies, then runs one below | per pipeline |
| `new` | video from scratch | strategist → scout → storyboarder → scriptwriter → (localizer) → voice-producer → scene-automator → capture-operator → (blurrer ∥ sync-editor) → (motion-designer ∥ caption-writer ∥ sound-mixer) → render-engineer → demo-qa → packager | G1, G2, G3 |
| `script` | pre-production only | strategist → scout → storyboarder → scriptwriter → (localizer) | G1, G2 |
| `shoot` | approved script → render | voice-producer → scene-automator → capture-operator → (blurrer ∥ sync-editor) → (motion-designer ∥ caption-writer ∥ sound-mixer) → render-engineer → demo-qa | G3 (needs G2) |
| `rerecord` | UI changed in a scene | scene-automator → capture-operator → (blurrer ∥ sync-editor) → motion-designer → render-engineer → demo-qa | G3 |
| `revoice` | new text, voice or language | scriptwriter → (localizer) → voice-producer → sync-editor → (motion-designer ∥ caption-writer ∥ sound-mixer) → render-engineer → demo-qa | G2 (text), G3 |
| `cut` | new aspect ratio or shorter cut | (sync-editor if scenes are dropped) → (motion-designer ∥ caption-writer) → render-engineer → demo-qa | G3 |
| `fix` | symptom text; empty = read `qa.md` + `#checks` | director diagnoses → owner → dependent keys → render → qa | G3 |
| `tools` | view/install toolkit | `--list`/`--options`/`--stages` → toolsmith `suggest` → ask → toolsmith `install` | install approval |
| `review` | inspect existing video, no edits | demo-qa | — |
| `status` | where are we | read `STATE.md` only | — |

Order is the dependency order of §6: caption-writer and sound-mixer need `#timeline`, so they never run before sync-editor. (localizer) runs only when `language` is set and differs from `voice.language`. Loops: render check failure → owner of that key. QA FAIL → owner of the finding, re-render, QA. Same finding 3 rounds → ask the user. VO is produced **before** scenes so pauses fit real durations.

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
.demo/STATE.md  .venv/  toolkit.json
.demo/<slug>/
  brief.md  demo.yaml  app-map.md  storyboard.md  narration.md  qa.md
  scenes.<platform>.*
  project.json  .demo.applied.json
  media/  sNN.raw.*  sNN.vo.wav  final-16x9.mp4  final-9x16.mp4  final-1x1.mp4  final.vtt  thumb.png
```

Only two kinds of video file: raw clips and finals. Blur, motion, captions and mix are instructions in `project.json`, not intermediate videos. Templates in `${CLAUDE_PLUGIN_ROOT}/templates/`.

**Files → owner:** `brief.md` demo-strategist (prose; user approves at G1) · `demo.yaml` **the user** (demo-strategist creates it at G1; demo-director records the user's decisions in it: motion level, voice, tool choices, install choices; every other agent reads only) · `.demo.applied.json` snapshot written by `config.py apply` (director: after G1 as baseline, after every G3) · `app-map.md` app-scout · `storyboard.md` storyboarder · `narration.md` scriptwriter (in `language`) · `localization.md`, `narration.<voice.language>.md` localizer (only when `language` ≠ `voice.language`; voice-producer reads the latter when it exists) · `qa.md` demo-qa.

**`demo.yaml`** controls the video's properties: `platform`, `length_s`, `formats`, `voice {engine, name, language, lexicon}`, `motion {level}`, `music {style, duck_db}`, `captions {burn_in, layout, max_chars}`, `targets {lufs, true_peak, max_drift_ms, caption_offset_ms}`, `privacy {blur, real_data}`, `install {approved, declined}`. Template with allowed values and defaults: `${CLAUDE_PLUGIN_ROOT}/templates/demo.yaml`. A value lives only there; agents read it, never copy it.

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/config.py --slug <slug> init | validate | get <dotted.path> | diff [--json] | apply | apply-lexicon (--text T | --file F | stdin) [--json]
```
`get` prints JSON with defaults applied (e.g. `get targets.max_drift_ms` → `80`). `apply-lexicon` returns the TTS input with `voice.lexicon` substituted plus the `applied` list (voice-producer only; a lexicon change re-runs voice, no G2). `diff` compares with `.demo.applied.json` (the config of the last approved state; missing = first run, nothing to diff) and prints the changed fields, the `project.json` keys to re-run (own step + `project.py deps`) and any earlier agent/gate to reopen. Exit 2 on a bad file, with the line.

**project.json keys → owner:** `events` capture-operator · `voice` voice-producer · `blur` privacy-blurrer · `timeline` sync-editor · `motion` motion-designer · `captions` caption-writer · `mix` sound-mixer · `checks` render-engineer (written only by `checks.py` / `blur.py verify`; `project.py set checks` is refused) · `delivery` packager. **Retention and git hygiene:** `project.py init` writes `.demo/.gitignore` (preview, `.secret/`, raw clips, `media/.tmp-*/`, mask/sync/probe sidecars, `tmp-video/`, `runs.jsonl`, `*.schema1.bak`, `cache/`); once `#delivery` is written the director (or packager) runs `project.py --slug <slug> retention --apply`, which deletes raw clips (files resolving outside `.demo/<slug>/`, e.g. `--out-dir` clips, are listed as `outside_project` and kept unless `--include-outside`), `.tmp-*` dirs, mask/sync/probe sidecars and `tmp-video` when `privacy.raw_retention` is `delete-after-delivery` (the default; `keep` deletes nothing; it refuses with exit 3 before delivery). Raw clips are gone afterwards, so a later `blur.py verify` has no positive control (`inconclusive`): re-record or choose `keep` if re-verification must stay possible. `project.py doctor [--clean]` lists / removes stale `.tmp-<sid>-<pid>` capture dirs inside `.demo/<slug>/` only (outside ones are listed as `outside_project`, removed only with `--include-outside`) (raw unmasked video after a killed capture; exit 10). `demo.yaml` `privacy.accepted` is the only way past a weaker capture gate (`frames_soft`, raised `mask.thresholds`, accepted unmaskable): written ONLY by the director through `config.py --slug <slug> accept --scene <sNN> --reason "<the user's answer, quoted, with date>" --decided-by user`, after AskUserQuestion; it records scene, reason (>= 10 characters), thresholds and the clip fingerprint, and `checks.py` honours it only while those match the current `#events` clip (re-shoot or changed thresholds voids it). No wildcard; hand-written or legacy string entries are ignored and reported as a finding for demo-director. Hard enforcement (a hook guarding the key) is P1. `project.py stale <key>` lists upstream keys changed since `<key>` was written (exit 10).

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

**Dependency order:** voice → timeline, captions, mix · events → blur, timeline · timeline → motion, captions, mix · {blur, motion, captions, mix} → checks → delivery. A `length_s` change re-runs storyboarder (G2) → timeline → motion, captions, mix → checks → delivery; voice only if narration changes.

**Render checks (`#checks`; thresholds from `demo.yaml` `targets`/`captions`, defaults in skill `media-specs`):** sync drift ≤`targets.max_drift_ms` (80) per scene → sync-editor · `targets.lufs` (−14) ±1 LUFS, ≤`targets.true_peak` (−1) dBTP → sound-mixer · blur verdict `pass` for every rendered aspect (`blur.py verify`; leak / inconclusive → privacy-blurrer, missing → render-engineer) → privacy-blurrer · no unintended black/freeze → capture-operator · captions ≤`captions.max_chars` (42) chars/line, ≤`targets.caption_offset_ms` (200) off → caption-writer · total length ±10% of `length_s` → storyboarder.

## 7. /fix routing

| Symptom | Owner | Then re-run |
|---|---|---|
| Audio/video out of sync | sync-editor | render → qa |
| Email, name, amount still visible | privacy-blurrer (region missing/wrong) or capture-operator (clip `masked` false / `frames_unmasked` > 0) | blur: render → qa; capture: as below |
| Wrong click, UI changed, scene broken | scene-automator | capture → (blur ∥ timeline) → motion → render → qa |
| Black frame, freeze, bad recording | capture-operator | (blur ∥ timeline) → motion → render → qa |
| Wrong translation, UI term, on-screen text language | localizer → voice-producer | timeline → (motion ∥ captions ∥ mix) → render → qa |
| Wrong or awkward narration | scriptwriter → (localizer) → voice-producer | timeline → (motion ∥ captions ∥ mix) → render → qa |
| Caption wrong or off | caption-writer | render → qa |
| Music too loud, voice too quiet, LUFS off | sound-mixer | render → qa |
| Zoom in wrong place, missing callout | motion-designer | render → qa |
| Changed `demo.yaml` (user edited it) | director runs `config.py validate` + `diff` | from the earliest owner `diff` lists, then downstream keys → render → qa |

Owner unclear → ask the user, do not guess. One STATE.md line per fix. Same defect after 2 attempts → stop and report. `/rerecord` and `/revoice` are shortcuts when the cause is known.

## 8. Toolkit

`python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py` — `--list` (catalog) · `--check [features]` (installed / missing / blocked) · `--plan <features>` (what, how many MB) · `--install <features>` (only after approval) · `--options [capability]` (alternatives per job, see below) · `--stage [name]` / `--stages` (read-only: what a pipeline stage needs, alternatives, suggested `--plan`; `--platform`, `--choose cap=value`, `--with feature`, `--json`) · `--python` (prints the toolkit interpreter path; never hard-code `.demo/.venv/...`). Installs into `.demo/.venv`, records `.demo/toolkit.json`. It never prompts.

| Feature | Gives |
|---|---|
| `capture` | web recording (Playwright Chromium) + bundled ffmpeg; needed for every platform |
| `capture-desktop` / `capture-android` / `capture-ios` | desktop (pywinauto / Appium Mac2), Android (Appium, scrcpy), iOS (macOS + Xcode only; else `blocked`) |
| `voice-edge` (default) / `voice-kokoro` / `voice-elevenlabs` | free online TTS / offline, heavy (torch) / paid, needs `ELEVENLABS_API_KEY` |
| `captions` | word-level timing (faster-whisper) |
| `mix` | ducking and loudness normalisation |
| `blur` | region blur (OpenCV) |
| `motion-basic` / `motion-cinematic` | ffmpeg zoom/fade (0 MB) / Remotion titles and callouts (Node ≥18, ~400 MB) |
| `qa-ocr` (default) / `qa-ocr-tesseract` | OCR check for leftover sensitive text, recommended with real data: RapidOCR + onnxruntime (~120 MB, Python 3.10-3.13) / Tesseract (~60 MB, needs the `tesseract` program on PATH) |
| `package` | thumbnails |

Features not yet in `--list` are not installed by the script; report `blocked` rather than improvising.

**Choosing the tool (capabilities).** Where several features do the same job, the user picks; no agent hard-codes one. `setup_tools.py --options [ocr|voice|motion] [--json]` lists the alternatives (tool, effect, size, needs, installed / missing / blocked, recommended first) and the `demo.yaml` field that records the choice:

| Capability | demo.yaml | Values (features) |
|---|---|---|
| `ocr` | `tools.ocr` | `qa-ocr` (recommended) · `qa-ocr-tesseract` · `none` |
| `voice` | `voice.engine` | `edge` (`voice-edge`) · `kokoro` · `elevenlabs` · `recorded` (no feature) |
| `motion` | `motion.level` | `basic` (`motion-basic`) · `cinematic` · `none` |

Resolving **OCR tool** (render-engineer for `blur.py verify`, privacy-blurrer for `blur.py preview`; demo-qa and `/review` read `#checks` and run no OCR): `config.py get tools.ocr` → that feature is the one to `--check`. `null` = not chosen: use the first installed option of `--options ocr --json`; none installed → handoff `needs-input` and the director asks (options table, recommended first). `none` = no OCR: the agent checks frames by eye and says so in `notes` (`blur.py verify`/`preview` return `inconclusive`, exit 10, writing the verdict; not exit 4: `checks.py` then fails the blur row as `inconclusive`). The engine runs inside `blur.py`: `--ocr rapidocr|tesseract|none|python:<module>:<factory>`, default taken from `tools.ocr` (`qa-ocr` -> rapidocr, `qa-ocr-tesseract` -> tesseract, `null` -> rapidocr); agents may pass it explicitly. Agents never write OCR code. A new alternative = a `CATALOG` entry with `capability`, its `CAPABILITIES` value and the matching enum in `config.py`.

**Just-in-time flow (nothing is installed at the start of a pipeline).** The stage map lives in `setup_tools.py` (`--stages`); the pipelines name each step's stage.
1. Right before a step the director runs `--stage <name> --platform <p> --json`. `ready` → run the step.
2. Not ready → toolsmith `suggest` for that stage only (reads `tools.ocr`, `voice.engine`, `motion.level`, `platform`, `voice.lexicon`, `install.declined` from `demo.yaml`; returns `needs-input` with options table, recommended default and `--plan`, or `done`).
3. Director asks the user (install recommended / alternative / skip with fallback / cancel). Approved → toolsmith `install` (`--plan` check, `--install`, `--check`), then the step runs. Declined → fall back (cinematic → basic, word captions → sentence captions) and continue.
4. Director records the decision in `demo.yaml` (`install.approved` / `install.declined`, plus the choice itself: `tools.ocr`, `motion.level`, `voice.engine`) so it is not asked again. Agents keep their own `--check` as a safety net: a missing feature → `needs-input` with the `--plan`, handled by steps 2-4. Never install a feature nobody needs yet.

## 9. Resume

- `.demo/STATE.md` is the director's file: slug, pipeline, current step, gate status, per-step status, fix log, next action.
- `/demo-studio:run` with no argument, or a new session: read STATE.md, run `config.py validate` then `diff` (invalid → show the errors and stop; changed fields → invalidate the listed keys/gates and restart at the earliest owner `diff` names), check the listed outputs exist (`project.py keys` for keys), continue at the first step not `done`.
- Gates already approved are not asked again; a changed input (`demo.yaml` field, storyboard, narration, scene) invalidates the gates and keys downstream of it. The director runs `config.py validate` + `diff` at the start of every pipeline, `config.py apply` after G1 (baseline) and after every G3.
- Conflicting STATE.md and files on disk → trust the files, tell the user, fix STATE.md.
- Never commit or push unless the user asks.
