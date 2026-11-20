---
description: "Show or install the toolkit by feature; always asks before installing"
argument-hint: "[features, e.g. capture,blur]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the tools pipeline for: $ARGUMENTS

1. Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --options` (jobs with alternatives: ocr, voice, motion) and `--list` / `--check [features]`; show two short tables: by job (each alternative: tool, effect, size, needs, installed / missing / blocked, recommended first, plus the "no tool" row) and the remaining single features (capture, captions, mix, blur, package).
2. Job with alternatives → let the user choose (AskUserQuestion, recommended first). Record the choice in `demo.yaml` if a project is active (`tools.ocr`, `voice.engine`, `motion.level`).
3. User wants something installed → run `--plan <features>` and show size, requirements and warnings (Node, API key, macOS-only, `tesseract` program). **Ask for approval; install nothing before a clear yes.**
4. After approval only: toolsmith runs `--install <features>`, then `--check` to confirm. Record `install.approved` / `install.declined` in `demo.yaml` if a project is active.

Without arguments, stop after step 1. An argument naming a job (`ocr`, `voice`, `motion`) shows only that job's options (`--options <job>`).
