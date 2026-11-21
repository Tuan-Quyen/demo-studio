---
description: "Inspect an existing video without changing it"
argument-hint: "<path to video or slug>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the review pipeline for: $ARGUMENTS

Read-only. Empty → use the latest `.demo/<slug>/media/final-*.mp4`.

1. demo-qa reviews the video against `brief.md` (if any) and `project.json#checks`; reads blur/text results from `#checks` (no OCR of its own; if `#checks` is missing or has no `blur` verdict for an output, say so and suggest `/demo-studio:fix`, which re-runs render-engineer's `blur.py verify` + `checks.py`) and checks frames by eye.
2. Write `.demo/<slug>/qa.md` (checklist + PASS/FAIL, findings with timestamps). No re-render, no edits.
3. Show findings; suggest `/demo-studio:fix` for any FAIL.

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Tools just in time: right before a step, if `setup_tools.py --stage <name>` is not ready, the director briefs toolsmith `suggest` for that stage, asks the user, then toolsmith `install` (director file, **Tools, just in time**); install nothing for later stages. Never record, render or install without the gate or approval named above. Do not commit or push.
