---
description: "Fix a problem in a finished demo video"
argument-hint: "[symptom]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and fix: $ARGUMENTS

1. Empty symptom: read `.demo/<slug>/qa.md` and list its blocking findings.
2. Map each finding to its owner (wording -> story; voice, cut, caption, zoom, render -> editor; bad take or popup -> scene-automator; leaked element -> app-scout adds it to `privacy.mask`, then scene-automator re-records).
3. Brief owners with the finding IDs as the exact scope. Re-render with editor, then demo-qa runs `verify.py` and rewrites `qa.md`.
4. Same finding 3 rounds: ask the user. Show the PASS verdict at G3 before delivery.

Do not commit or push.
