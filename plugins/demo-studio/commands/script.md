---
description: "Pre-production only: brief, storyboard and narration"
argument-hint: "<what to demo>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the script pipeline for: $ARGUMENTS

Empty request → ask what to demo, then stop.

1. demo-strategist → `brief.md` + `demo.yaml`. **G1: wait for approval.**
2. app-scout → `app-map.md` (with `target:` and sensitive elements).
3. storyboarder → `storyboard.md`; scriptwriter → `narration.md` (word budget per `demo-storytelling` vs scene durations); localizer → `localization.md` + `narration.<voice.language>.md` when `language` differs from `voice.language`.
4. **G2: show storyboard + narration, wait for approval.** Stop. Next step is `/demo-studio:shoot`.

No recording, voice or render here.

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Tools just in time: right before a step, if `setup_tools.py --stage <name>` is not ready, the director briefs toolsmith `suggest` for that stage, asks the user, then toolsmith `install` (director file, **Tools, just in time**); install nothing for later stages. Never record, render or install without the gate or approval named above. Do not commit or push.
