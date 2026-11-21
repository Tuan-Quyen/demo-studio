---
description: "Inspect an existing demo video without changing it"
argument-hint: "<video path or slug>"
disable-model-invocation: true
---

Act as demo-qa: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-qa.md` and review: $ARGUMENTS

Empty: ask for a slug or video path. Run `verify.py`, watch the frames, write `qa.md` with findings and their owner agents. Change no media, scripts or `demo.yaml`. A leak is FAIL. End with the verdict and the next command (`/demo-studio:fix`).
