---
description: "Make a new demo video from scratch (brief to final video)"
argument-hint: "<what to demo, audience, platform>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the new-video path for: $ARGUMENTS

Empty request: ask what to demo, then stop. Create the slug and `.demo/<slug>/` from `${CLAUDE_PLUGIN_ROOT}/templates/`, fill STATE.md.

1. story -> `brief.md`, `demo.yaml`. **G1**: show them, ask platform, length, voice, formats and data mode (`seeded` by default; `real` only if the user chooses it).
2. app-scout -> `app-map.md`, seeded data, `privacy.mask` / `patterns`.
3. story -> `storyboard.md`, `narration.md` (+ translation). **G2**: wait for approval; no recording before it.
4. editor -> voice (`vo.py`). scene-automator -> `scenes.*` and `media/sNN.raw.*`.
5. editor -> `edit.json`, `render.py`. demo-qa -> `verify.py`, `qa.md`.
6. FAIL: send each finding to its owner, re-render, QA again (same finding 3 times: ask the user). **G3**: show finals and the PASS verdict, wait for approval.

Install tools only after asking. Do not commit or push.
