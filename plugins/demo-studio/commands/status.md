---
description: "Show where the current demo work stands (reads STATE.md only)"
argument-hint: ""
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the status pipeline for: $ARGUMENTS

Read only `.demo/STATE.md`. Reply in a few lines: active slug(s), pipeline, current step, gate waiting, blockers, next action. If it is missing: "no demo work yet — try `/demo-studio:new`". Do not read other files or run anything.
