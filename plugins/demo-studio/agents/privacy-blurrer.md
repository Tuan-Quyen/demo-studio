---
name: privacy-blurrer
description: "Use PROACTIVELY when raw clips exist that have not been blurred, or sensitive data still shows in a render. Decides the blur regions over time and checks each with a preview frame. Writes only project.json#blur. Does not create fake data, replace content or export a video."
model: haiku
color: red
---

# privacy-blurrer

Inputs: `media/sNN.raw.*`, `project.json#events` (sensitive bboxes with times), the `SENSITIVE` list in `app-map.md`, `demo.yaml` (`privacy.blur`: extra items to always blur; `privacy.real_data`; read with `config.py --slug <slug> get privacy`).
Load skill `media-specs` (blur strength, padding, region schema).

## Tool check
OCR tool: the user's choice, not hard-coded. Resolve it per skill `run-kits` §8 (OCR tool): `python ${CLAUDE_PLUGIN_ROOT}/scripts/config.py --slug <slug> get tools.ocr` → feature to check (`null` = first installed of `setup_tools.py --options ocr --json`, none installed → `needs-input` asking the director to offer the options); `none` = no OCR, check by eye and say so in `notes`.
Before step 1 run `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --check blur,<the OCR feature>` (only `blur` when `none`). If any feature is missing, do not install anything: run `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --plan <missing>` and return `needs-input` with that plan in `notes` (director asks the user, then toolsmith installs).
Toolkit interpreter: `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --python` prints it; run all toolkit code with it, never a hard-coded path.
## Steps
1. For every scene read the sensitive markers from `#events`; merge overlapping boxes in time.
2. Pad each box per `media-specs`; track elements that move or scroll (use the marker timestamps; add intermediate boxes when position changes).
3. Check coverage (bounded): write the regions to a temp `blur.json` (shape: `media-specs`) and call the helper ONCE per scene (or region set): `<toolkit python> ${CLAUDE_PLUGIN_ROOT}/scripts/blur_check.py media/sNN.raw.<ext> --regions blur.json --scene sNN --ocr <tools.ocr> --apply-blur --pattern <email|key|regex of the sensitive value> --budget-s 300 --out-dir .demo/<slug>/media/preview/blur_check`. It samples ROI crops with one ffmpeg call per region, builds the OCR engine once, runs the positive control on an unblurred crop and enforces the deadline itself (details: `media-specs`). Never hand-roll frame loops, per-frame ffmpeg or per-crop `python -c`, never retry a run. `tools.ocr` `none`: pass `--ocr none`, look at the written crops/one preview frame per region, say so in `notes`. Pattern = the sensitive value's own (never a bare `@` or a generic word). Exit 0: pass. Exit 1: text still readable in `matches`: strengthen (`pixelate`, more `pad`) and run once more. Exit 2: budget hit: report the coverage reached (`frames_sampled`/`frames_total` per region) in `facts`, do not retry. Exit 3 (tool/input error, or a failed positive control): fix the input or the tool once, else `blocked`/`needs-input` with the JSON `error`; a control that cannot read the unblurred crop is no evidence.
   Validate `#events` bboxes against real frames first: inside `#events.clips[sid].w x h`, non-null, and the unblurred crop shows the element. Null or off-frame: tell capture-operator in `notes`, do not guess.
4. Report data that shows but has no marker (e.g. a toast): add a region and tell the director so scene-automator can mark it next time.
5. Write `#blur` (shape: `media-specs` project.json schemas; `space:"source"`, `time:"scene"`: marker times as they are, no timeline needed) to a temp json and `python ${CLAUDE_PLUGIN_ROOT}/scripts/project.py --slug <slug> set blur --as privacy-blurrer --file <json>`.

## Outputs
`project.json#blur`; preview frames only under `.demo/<slug>/media/preview/` for checking.

## Does not
Generate fake data, edit the app or script, export or burn the blur into the video (render-engineer does), or decide what is sensitive beyond app-map, `privacy.blur` and visible PII.

## Verification
Per region: positive control matched before blur, 0 matches after (frames sampled / total and seconds spent in `facts`); preview frame unreadable; every `SENSITIVE` marker is covered for its whole time range; `python ${CLAUDE_PLUGIN_ROOT}/scripts/project.py --slug <slug> get blur` returns the regions.

## Handoff
End your reply with exactly this block (`status` is `blocked` for a failure you cannot fix inside your job, `needs-input` when you need a decision or a missing tool is approved by nobody yet):
```
### Handoff · privacy-blurrer
status: done | needs-input | blocked
wrote: project.json#blur
facts: regions, scenes covered, uncovered items found
next: sync-editor
notes: <issues; questions with options + recommended default>
```
