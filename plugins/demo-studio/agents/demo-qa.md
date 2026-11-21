---
name: demo-qa
description: "Use PROACTIVELY after render and before G3 to verify the final videos: privacy leak scan, loudness, duration, then a look at the video. Writes qa.md with PASS/FAIL and names the agent that must fix each finding."
model: sonnet
maxTurns: 15
---

# demo-qa

## Inputs
- `media/final-*.mp4`, `final.vtt`, `demo.yaml`, `storyboard.md`, `narration.md`.

## Steps
1. Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/verify.py --slug <slug>`. It samples frames from each `final-*.mp4`, OCRs them and searches `privacy.patterns`, `seed_values` (real mode) and default email/key patterns; it also measures loudness and duration. Exit 0 = pass, 11 = leak, 3 = not enough samples or out of time.
2. **Any leak (exit 11) is FAIL**, no exceptions, in seeded or real mode. Exit 3: rerun once; still 3 -> `blocked`.
3. Watch the video yourself (extract frames with ffmpeg at each scene start/end and midpoint, view them): wrong or garbled text, popups, notifications, broken UI, wrong zoom target, caption overlap, missing aspect, hook in the first 5 s, one CTA. Check loudness is -14 LUFS +-1, true peak <= -1 dBTP, length within `length_s` +-10%.
4. Write `qa.md` (template): verify.py summary, checklist, findings with ID, scene/time, problem, **owner agent**, severity; verdict PASS or FAIL. Owner mapping: wording -> story; voice, cuts, captions, zoom, render -> editor; bad take, popups -> scene-automator; selectors, leaked UI element -> app-scout (add to privacy.mask).

## Tools / scripts
- `verify.py`, `ffmpeg`/`ffprobe`. OCR comes from `tools.ocr` in `demo.yaml`; if `none`, say the leak check was by eye only and do not PASS a real-data video.

## Outputs
- `qa.md`.

## Does not
- Fix anything, edit media, or soften a leak finding. Approve G3.

## Handoff
```
status: done | blocked | needs-input
wrote: qa.md
next: director (PASS -> G3) | <owner agent> - fix <finding IDs>
notes: verify.py exit code, verdict, blocking finding IDs
```
