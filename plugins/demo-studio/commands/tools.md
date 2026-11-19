---
description: "Show or install the toolkit by feature; always asks before installing"
argument-hint: "[features, e.g. capture,blur]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the tools pipeline for: $ARGUMENTS

1. Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --list` and `--check [features]`; show a short table (feature, effect, installed / missing / blocked).
2. User wants something installed → run `--plan <features>` and show size, requirements and warnings (Node, API key, macOS-only). **Ask for approval; install nothing before a clear yes.**
3. After approval only: toolsmith runs `--install <features>`, then `--check` to confirm. Record the user's choice in `demo.yaml` (`install.approved` / `install.declined`) if a project is active.

Without arguments, stop after step 1.
