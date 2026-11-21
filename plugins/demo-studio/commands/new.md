---
description: "Make a new demo video from scratch (brief to final render)"
argument-hint: "<what to demo, audience, platform>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the new pipeline for: $ARGUMENTS

Empty request → ask what to demo, then stop. Create slug and `.demo/<slug>/` from `${CLAUDE_PLUGIN_ROOT}/templates/`, set STATE.md. At the start of every step block run `config.py validate` + `diff` (see the director file); run `config.py apply` after G1 (baseline) and after G3 (a missing snapshot = first run).

1. **Brief** — demo-strategist → `brief.md` (audience, goal, message, CTA) and `demo.yaml` (length, platform, formats, voice language). Director asks the motion level, the render engine (Remotion / ffmpeg fallback, `motion-fx`) and the voice engine and records them in `demo.yaml`. **G1: show the brief and the `demo.yaml` values (optionally `setup_tools.py --stages` as information on what will be needed; install nothing), wait for approval.**
2. **Map** (stage `scout`) — app-scout → `app-map.md` (must contain `target:` and the sensitive-elements list; platform comes from `demo.yaml`).
3. **Storyboard** — storyboarder → `storyboard.md`; scriptwriter → `narration.md` (in `language`); localizer → `localization.md` + `narration.<voice.language>.md` only when `language` differs from `voice.language` (it proposes lexicon entries; the director asks the user and records them). **G2: show storyboard, narration (both languages if localized) and the glossary, wait for approval. No recording before G2.**
4. **Voice first** (stage `voice`) — voice-producer (reads `narration.<voice.language>.md` when it exists) → `media/sNN.vo.wav`, `project.json#voice` (durations).
5. **Scenes** (stage `scenes`) — scene-automator → `scenes.<platform>.*` + dry-run PASS (uses `#voice` for pauses).
6. **Capture** (stage `capture`) — capture-operator → `media/sNN.raw.*`, `#events`. Step failure → back to scene-automator; env failure → retry max 2.
7. **Post** (stages `blur`, `sync`, then `motion`, `captions`, `mix`) — privacy-blurrer (`#blur`) ∥ sync-editor (`#timeline`); then motion-designer (`#motion`) ∥ caption-writer (`#captions`) ∥ sound-mixer (`#mix`) (they read `#timeline`).
8. **Render** (stage `render`) — render-engineer: single pass, writes `#checks`. A failed check goes back to the owner of that key.
9. **QA** (stage `qa`) — demo-qa → `qa.md` PASS/FAIL. FAIL → owner of the finding, re-render, QA again (same finding 3 rounds → ask the user).
10. **G3: show finals + QA verdict, wait for approval.** Then packager (stage `package`) → `media/thumb.png`, `#delivery`.

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Tools just in time: right before a step, if `setup_tools.py --stage <name>` is not ready, the director briefs toolsmith `suggest` for that stage, asks the user, then toolsmith `install` (director file, **Tools, just in time**); install nothing for later stages. Never record, render or install without the gate or approval named above. Do not commit or push.
