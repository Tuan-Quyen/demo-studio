---
description: "Show or install the tools a demo needs (always asks first)"
argument-hint: "[features]"
disable-model-invocation: true
---

Act as demo-director, with toolsmith doing the checks and installs. Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --list` (or `--stage <name>` / `--options ocr|voice`) and show what is installed and missing.

If `$ARGUMENTS` names features: show `--plan <features>` (what, size, needs), ask the user, and only on yes run `--install <features>`. Record approved or declined choices (`tools.ocr`, `voice.engine`) in `demo.yaml`. Never install unasked. Do not commit or push.
