---
description: "From an approved script to the rendered, QA-checked video"
argument-hint: "[slug]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the shoot pipeline for: $ARGUMENTS

Needs G2 approved (`storyboard.md` + `narration.md`). Missing or unapproved → say so and point to `/demo-studio:script`; stop.

1. voice-producer (stage `voice`) → `.vo.wav` + `#voice`; scene-automator (`scenes`) → scenes + dry-run PASS; capture-operator (`capture`) → raw clips + `#events`.
2. privacy-blurrer (`blur`) → `#blur` ∥ sync-editor (`sync`) → `#timeline`; then motion-designer (`motion`) → `#motion` ∥ caption-writer (`captions`) → `#captions` ∥ sound-mixer (`mix`) → `#mix`.
3. render-engineer (`render`) → finals + `#checks` (failures go to the key owner); demo-qa (`qa`) → `qa.md`.
4. **G3: show finals + verdict, wait for approval.** Then packager (`package`).

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Tools just in time: right before a step, if `setup_tools.py --stage <name>` is not ready, the director briefs toolsmith `suggest` for that stage, asks the user, then toolsmith `install` (director file, **Tools, just in time**); install nothing for later stages. Never record, render or install without the gate or approval named above. Do not commit or push.
