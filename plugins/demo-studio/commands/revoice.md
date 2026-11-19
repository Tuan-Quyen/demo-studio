---
description: "Change narration text, voice or language, then re-render"
argument-hint: "<what to change>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the revoice pipeline for: $ARGUMENTS

Empty request → ask what to change, then stop.

1. Text change → scriptwriter edits `narration.md`. **G2: show the diff, wait for approval.** Voice/language change only → skip. The director records a new voice or language in `demo.yaml` (`voice.*`) and runs `config.py diff`; a language change reopens narration (G2).
2. voice-producer regenerates `.vo.wav` + `#voice`. If scene durations move, tell the user: scenes may need new pauses (scene-automator + re-record).
3. sync-editor → `#timeline`; then motion-designer ∥ caption-writer ∥ sound-mixer; render-engineer → `#checks`; demo-qa.
4. **G3: show the result, wait for approval.**

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Check tools with `setup_tools.py --check <features>` before a step that needs them; missing -> show `--plan`, ask the user, install only after approval (toolsmith). Never record, render or install without the gate or approval named above. Do not commit or push.
