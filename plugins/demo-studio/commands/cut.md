---
description: "Add an aspect-ratio variant or a shorter cut"
argument-hint: "<ratio 9:16|1:1|16:9 and/or target length>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the cut pipeline for: $ARGUMENTS

Empty request → ask for ratio and/or length, then stop. No new recording. A new ratio is a `formats` change: the director records it in `demo.yaml` (user-approved) and runs `config.py diff`.

1. motion-designer updates `#motion` (safe areas, reframing); caption-writer updates `#captions` for the new layout.
2. Shorter cut → agree which scenes to drop with the user first (needs `#timeline` change via sync-editor).
3. render-engineer → new `final-*.mp4` + `#checks`; demo-qa.
4. **G3: show the result, wait for approval.**

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Check tools with `setup_tools.py --check <features>` before a step that needs them; missing -> show `--plan`, ask the user, install only after approval (toolsmith). Never record, render or install without the gate or approval named above. Do not commit or push.
