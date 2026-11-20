---
description: "Show or install the toolkit by feature or by pipeline stage; always asks before installing"
argument-hint: "[features, e.g. capture,blur | stage, e.g. voice]"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the tools pipeline for: $ARGUMENTS

1. Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --options` (jobs with alternatives: ocr, voice, motion) and `--list` / `--check [features]`; show two short tables: by job (each alternative: tool, effect, size, needs, installed / missing / blocked, recommended first, plus the "no tool" row) and the remaining single features (capture, captions, mix, blur, package).
2. Job with alternatives → let the user choose (AskUserQuestion, recommended first). Record the choice in `demo.yaml` if a project is active (`tools.ocr`, `voice.engine`, `motion.level`).
3. User wants something installed → run `--plan <features>` and show size, requirements and warnings (Node, API key, macOS-only, `tesseract` program). **Ask for approval; install nothing before a clear yes.**
4. After approval only: toolsmith (mode `install`) runs `--install <features>`, then `--check` to confirm. Record `install.approved` / `install.declined` in `demo.yaml` if a project is active.

Without arguments, stop after step 1 (add the `--stages` overview: which stage needs what, information only). An argument naming a stage (`scout`, `voice`, `scenes`, `capture`, `blur`, `sync`, `motion`, `captions`, `mix`, `render`, `qa`, `package`) → toolsmith `suggest` for it (`--stage <name>`), then steps 2-4 for what it lists. An argument naming a job (`ocr`, `voice`, `motion`) shows only that job's options (`--options <job>`).
