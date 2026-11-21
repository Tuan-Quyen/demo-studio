---
description: "Fix a problem in the finished video from a symptom (empty = read QA + checks)"
argument-hint: "[symptom, e.g. scene 3 out of sync]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the fix pipeline for: $ARGUMENTS

1. **Diagnose** — with a symptom: map it to the owning agent using the /fix routing table in `${CLAUDE_PLUGIN_ROOT}/skills/run-kits/SKILL.md`. Empty: read `.demo/<slug>/qa.md` and `project.json#checks`, list the failures. The user edited `demo.yaml` → run `config.py --slug <slug> validate` then `diff` and re-run what it lists. Owner unclear → ask the user, do not guess.
2. **Re-run** only the owner's key and the keys that depend on it (voice → timeline, captions, mix; events → blur, timeline; timeline → motion, captions, mix; {blur, motion, captions, mix} → checks → delivery), then render-engineer → demo-qa.
3. Log one line per fix in STATE.md. Same defect again after 2 attempts → stop and report to the user.
4. **G3: show the result, wait for approval.**

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Tools just in time: right before a step, if `setup_tools.py --stage <name>` is not ready, the director briefs toolsmith `suggest` for that stage, asks the user, then toolsmith `install` (director file, **Tools, just in time**); install nothing for later stages. Never record, render or install without the gate or approval named above. Do not commit or push.
