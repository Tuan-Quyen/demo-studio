---
description: "Make a new demo video from scratch (brief to final render)"
argument-hint: "<what to demo, audience, platform>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the new pipeline for: $ARGUMENTS

Empty request → ask what to demo, then stop. Create slug and `.demo/<slug>/` from `${CLAUDE_PLUGIN_ROOT}/templates/`, set STATE.md.

1. **Tools** — toolsmith `--check` for the features the platform and options need (capture*, voice-*, blur, mix, captions, motion-*, qa-ocr, package); ask before any install.
2. **Brief** — demo-strategist → `brief.md` (audience, goal, message, length, CTA, motion level, voice). **G1: show the brief, wait for approval.**
3. **Map** — app-scout → `app-map.md` (must contain `platform:` and the sensitive-elements list).
4. **Storyboard** — storyboarder → `storyboard.md`; scriptwriter → `narration.md`. **G2: show both, wait for approval. No recording before G2.**
5. **Voice first** — voice-producer → `media/sNN.vo.wav`, `project.json#voice` (durations).
6. **Scenes** — scene-automator → `scenes.<platform>.*` + dry-run PASS (uses `#voice` for pauses).
7. **Capture** — capture-operator → `media/sNN.raw.*`, `#events`. Step failure → back to scene-automator; env failure → retry max 2.
8. **Post** — privacy-blurrer (`#blur`) → sync-editor (`#timeline`) → motion-designer (`#motion`); caption-writer (`#captions`) ∥ sound-mixer (`#mix`).
9. **Render** — render-engineer: single pass, writes `#checks`. A failed check goes back to the owner of that key.
10. **QA** — demo-qa → `qa.md` PASS/FAIL. FAIL → owner of the finding, re-render, QA again (same finding 3 rounds → ask the user).
11. **G3: show finals + QA verdict, wait for approval.** Then packager → `media/thumb.png`, `#delivery`.

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Check tools with `setup_tools.py --check <features>` before a step that needs them; missing -> show `--plan`, ask the user, install only after approval (toolsmith). Never record, render or install without the gate or approval named above. Do not commit or push.
