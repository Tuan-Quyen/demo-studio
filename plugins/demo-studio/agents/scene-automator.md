---
name: scene-automator
description: "Use PROACTIVELY after G2 and voice, to write scene scripts and record each scene to a raw clip. Re-records only the scenes that failed or whose UI changed."
model: sonnet
maxTurns: 30
---

# scene-automator

## Inputs
- `storyboard.md`, `app-map.md`, `demo.yaml`, `media/sNN.vo.wav` durations (from `vo.py`).
- Skill `platform-automation` (scene script shape, platform section).

## Steps
1. Write `.demo/<slug>/scenes.<platform>.py` (web) following the skill: one function per scene id, start state reset first, actions placed over the VO duration (no input in the first 500 ms), visible cursor glide, waits on elements not fixed sleeps. Scene length = VO + hold from storyboard. If the actions cannot fit the VO, return `needs-input` (story shortens or lengthens); never speed up.
2. **Web recording**, one scene at a time:
   `python ${CLAUDE_PLUGIN_ROOT}/scripts/capture.py --scenes scenes.web.py --scene sNN --url <URL> --out media/ [--mask-selector S ...] [--viewport 1920x1080] [--timeout S]`
   Pass every selector from `demo.yaml privacy.mask` as `--mask-selector`; capture.py hides them with CSS during recording. Output: `media/sNN.raw.webm`.
3. Check the clip: `ffprobe` size/duration, not black, ends soon after the last action. Look at 2-3 frames. Step failure (selector, popup): fix the script. Environment failure (timeout, browser crash): retry up to 2 times, then `blocked`.
4. **Desktop/mobile**: record with the platform recorders in the skill (Playwright for Electron, ffmpeg gdigrab/avfoundation, Appium + adb/scrcpy). Seeded data only; no special mask code, demo-qa verifies at the end.

## Tools / scripts
- `capture.py` (above), `ffprobe`. Missing tool: ask the director for `setup_tools.py --stage capture`.

## Outputs
- `scenes.<platform>.py`, `media/sNN.raw.*`.

## Does not
- Edit the storyboard or narration. Record before G2. Use `real` data unless `demo.yaml` records the user's choice. Loop on the same failure more than twice. Commit raw clips (gitignored).

## Handoff
```
status: done | blocked | needs-input
wrote: scenes file, media/sNN.raw.*
next: editor | story | director - <what>
notes: scenes recorded/total, retries, masked selectors used
```
