---
description: "Fix a problem in a finished demo video"
argument-hint: "[symptom]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and fix: $ARGUMENTS

1. Empty symptom: read `.demo/<slug>/qa.md` and list its blocking findings.
2. Map each finding to its owner (see the director's routing table: leak -> privacy-guard; wording -> scriptwriter; voice -> voice-producer; bad take -> scene-automator/capture-operator; cut -> sync-editor; zoom -> motion-designer; captions -> caption-writer; music -> sound-mixer; render -> render-engineer).
3. Brief owners with the finding IDs as the exact scope. Re-render with render-engineer, then demo-qa runs `verify.py` and rewrites `qa.md`.
4. Same finding 3 rounds: ask the user. Show the PASS verdict at G3 before delivery.

Do not commit or push.
