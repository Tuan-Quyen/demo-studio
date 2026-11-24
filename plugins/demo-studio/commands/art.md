---
description: "Make marketing images (SVG + PNG) from a source doc, privacy-audited and QA-checked, then place them in the repo"
argument-hint: "<source doc, e.g. README.md>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the art pipeline for: $ARGUMENTS

Empty request, or a source doc that is missing or empty → ask for the doc path, then stop; generate nothing. No video is made here: no `brief.md`, `demo.yaml`, `.demo.applied.json`, storyboard, voice or recording, and the director never calls `config.py`.

Slug `<source-stem>-art` (README.md → `readme-art`). Create `.demo/<slug>/` and `project.py --slug <slug> init`; the workspace holds only `art/`, `project.json` and `qa-art.md`. Keep the state and the install answers in `.demo/STATE.md`.

0. **Style** (director, once per run, before the stage check) — the director's Art sub-pipeline step 0 (style question; skipped when the request names valid codes or keywords, or `#art.style` is already set). The answer goes into STATE.md before art-designer is briefed.
1. **Tools** (stage `art`) — `setup_tools.py --stage art --json --choose render=<remotion|ffmpeg>`. Not ready → toolsmith `suggest`, ask the user (install Remotion for PNG / SVG-only), then toolsmith `install`. Declined → SVG-only art (`png: null`), stated at GA, with an install offer.
2. **Art** — art-designer reads the source doc and the repo files it describes → `art/hero`, `pipeline`, `roster`, `social` as `.svg` + `.png`, `art/readme-snippet.md`, `#art`. Every text traces to a repo file (`texts[].from`); never invented.
3. **Audit** — privacy (check only, never blurs or edits art) → `#privacy.art`.
4. **QA** — demo-qa in art mode → `qa-art.md` PASS/FAIL. FAIL → the finding's owner (`art-designer`, or `privacy` for an audit gap) fixes, then privacy and demo-qa again; same finding 3 rounds → ask the user.
5. **GA: show the previews (PNG, else SVG), the `qa-art.md` verdict and the target files; wait for the answer.** Options: approve and place / edit art / keep in `.demo/` only. A request for a different style goes back to step 0 (list shown again, current choice marked): art-designer redoes all items, then audit and QA, back to GA; the 3-round cap restarts. Nothing is copied to the repo or README.md before "approve and place".
6. **Place** (director, only after "approve and place") — for each `#art.repo.files` entry: target exists → ask overwrite or rename; copy to `docs/images/`; insert `art/readme-snippet.md` into the source doc; Glob every relative link of the snippet (all resolve); report the changed repo files. Do not commit or push.

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Tools just in time: right before a step, if `setup_tools.py --stage <name>` is not ready, the director briefs toolsmith `suggest` for that stage, asks the user, then toolsmith `install` (director file, **Tools, just in time**); install nothing for later stages. Never render, install or copy files into the repo without the gate or approval named above. Do not commit or push.
