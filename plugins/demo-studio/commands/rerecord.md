---
description: "Re-shoot scenes after a UI change, then re-render"
argument-hint: "<scene ids and what changed>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the rerecord pipeline for: $ARGUMENTS

Empty request → ask which scenes changed, then stop.

1. scene-automator fixes the scenes' selectors/steps; dry-run PASS.
2. capture-operator re-shoots only those scenes (`sNN.raw.*`, `#events`).
3. Re-run dependents: privacy-blurrer ∥ sync-editor → motion-designer → render-engineer → demo-qa.
4. **G3: show the result, wait for approval.**

Voice, captions and mix are untouched unless a scene duration changed (then sync-editor flags it; ask the user).

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Tools just in time: right before a step, if `setup_tools.py --stage <name>` is not ready, the director briefs toolsmith `suggest` for that stage, asks the user, then toolsmith `install` (director file, **Tools, just in time**); install nothing for later stages. Never record, render or install without the gate or approval named above. Do not commit or push.
