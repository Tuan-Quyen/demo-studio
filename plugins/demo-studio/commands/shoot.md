---
description: "From an approved script to the rendered, QA-checked video"
argument-hint: "[slug]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the shoot pipeline for: $ARGUMENTS

Needs G2 approved (`storyboard.md` + `narration.md`). Missing or unapproved → say so and point to `/demo-studio:script`; stop.

1. toolsmith `--check` the required features; ask before any install.
2. voice-producer → `.vo.wav` + `#voice`; scene-automator → scenes + dry-run PASS; capture-operator → raw clips + `#events`.
3. privacy-blurrer → `#blur` ∥ sync-editor → `#timeline`; then motion-designer → `#motion` ∥ caption-writer → `#captions` ∥ sound-mixer → `#mix`.
4. render-engineer → finals + `#checks` (failures go to the key owner); demo-qa → `qa.md`.
5. **G3: show finals + verdict, wait for approval.** Then packager.

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Check tools with `setup_tools.py --check <features>` before a step that needs them; missing -> show `--plan`, ask the user, install only after approval (toolsmith). Never record, render or install without the gate or approval named above. Do not commit or push.
