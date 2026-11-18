---
description: "Inspect an existing video without changing it"
argument-hint: "<path to video or slug>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the review pipeline for: $ARGUMENTS

Read-only. Empty → use the latest `.demo/<slug>/media/final-*.mp4`.

1. demo-qa reviews the video against `brief.md` (if any) and `project.json#checks`; uses `qa-ocr` when installed (ask first if not).
2. Write `.demo/<slug>/qa.md` (checklist + PASS/FAIL, findings with timestamps). No re-render, no edits.
3. Show findings; suggest `/demo-studio:fix` for any FAIL.

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Check tools with `setup_tools.py --check <features>` before a step that needs them; missing -> show `--plan`, ask the user, install only after approval (toolsmith). Never record, render or install without the gate or approval named above. Do not commit or push.
