---
description: "Any demo-video request; the director picks the path (empty = resume)"
argument-hint: "[request]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and handle: $ARGUMENTS

- Empty: read `.demo/STATE.md`, say where the work stands, resume at the recorded step.
- New video: follow `/demo-studio:new`.
- Otherwise classify and run only what is needed:
  - wording, voice or language: story -> editor -> demo-qa
  - UI changed or bad take: app-scout (if needed) -> scene-automator (those scenes) -> editor -> demo-qa
  - cut, extra aspect, captions, zoom: editor -> demo-qa
  - problem in a finished video: `/demo-studio:fix`; inspect only: `/demo-studio:review`
- State the chosen path in one line. Unclear: ask one question with options and a recommended default.

Gates G1/G2/G3 apply whenever the path includes them. Install tools only after asking. Do not commit or push.
