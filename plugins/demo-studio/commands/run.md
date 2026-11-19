---
description: "Any demo-video request: the director picks the pipeline (empty = resume)"
argument-hint: "[request]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the right pipeline for: $ARGUMENTS

Empty `$ARGUMENTS` → read `.demo/STATE.md`, run `config.py --slug <slug> validate` then `diff` (changed `demo.yaml` fields invalidate the keys and gates `diff` lists), show where the work stands, resume at the recorded step (or the earliest invalidated one). Otherwise classify the request:

- new video from scratch → `new` · only brief/storyboard/narration → `script` · approved script to render → `shoot`
- UI changed in a scene → `rerecord` · wording, voice or language → `revoice` · extra aspect ratio or shorter cut → `cut`
- edited `demo.yaml` or something wrong in a finished video → `fix` (director runs `config.py diff`) · inspect an existing video → `review` · tools → `tools` · progress → `status`

State the chosen pipeline in one line, then follow that command's steps (see `${CLAUDE_PLUGIN_ROOT}/skills/run-kits/SKILL.md` §2). Unclear → ask one question with options and a recommended default. Gates: per chosen pipeline.

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Check tools with `setup_tools.py --check <features>` before a step that needs them; missing -> show `--plan`, ask the user, install only after approval (toolsmith). Never record, render or install without the gate or approval named above. Do not commit or push.
