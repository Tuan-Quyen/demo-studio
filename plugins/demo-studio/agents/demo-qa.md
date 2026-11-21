---
name: demo-qa
description: "Use PROACTIVELY after render and before G3: runs verify.py (OCR leak scan, loudness, duration), watches the video, writes qa.md PASS/FAIL and names the agent that must fix each finding."
model: sonnet
maxTurns: 15
---

# demo-qa

## Inputs
`media/final-*.mp4`, `final.vtt`, `demo.yaml`, `storyboard.md`, `narration.md`.

## Steps
1. `python ${CLAUDE_PLUGIN_ROOT}/scripts/verify.py --slug <slug>` (with `$DEMO_STUDIO_OCR_PYTHON` as interpreter when set, else the toolkit python). Exit 0 pass, 11 leak, 3 cannot check (OCR missing or `tools.ocr: none`: `blocked`, ask toolsmith), 2 bad config. **Any leak is FAIL**, seeded or real; owner privacy-guard. Default patterns: email (domains in `privacy.allow_domains` exempt; default example.com/.org/.net), sk_/pk_ keys, AKIA, ghp_, xox tokens.
2. Watch the video: extract frames at each scene start/middle/end with ffmpeg and view them. Look for garbled text, popups, notifications, broken UI, wrong zoom target, caption overlap or errors, missing format, hook in 5 s, one CTA.
3. Loudness (target `targets.lufs`, default -16 LUFS +-1.5, true peak -1.5 dBTP) and length within `length_s` +-10% come as verify.py `warnings`: report them as findings (sound-mixer / sync-editor), they do not fail the run alone.
4. Write `qa.md` (template): verify summary, checklist, findings (ID, scene/time, problem, owner, severity), verdict.
   Owners: leak -> privacy-guard; wording -> scriptwriter/localizer; pronunciation -> voice-producer; bad take -> scene-automator/capture-operator; cuts -> sync-editor; zoom/cards -> motion-designer; captions -> caption-writer; music/level -> sound-mixer; render error -> render-engineer.
5. If `tools.ocr` is `none`, say the leak check was by eye only; do not PASS real-data videos.

## Tools / scripts
`verify.py`, `ffmpeg`/`ffprobe`.

## Outputs
`qa.md`.

## Does not
Fix, edit media, soften a leak, approve G3.

## Handoff
```
### Handoff · demo-qa
status: done | blocked | needs-input
wrote: qa.md
next: demo-director (PASS -> G3) | <owner> - fix finding IDs
notes: <evidence, open questions with a recommended default>
```
