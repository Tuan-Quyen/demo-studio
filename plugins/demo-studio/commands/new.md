---
description: "Make a new demo video from scratch (brief to final video)"
argument-hint: "<what to demo, audience, platform>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the new-video path for: $ARGUMENTS

Empty request: ask what to demo, then stop. Create the slug and `.demo/<slug>/` from `${CLAUDE_PLUGIN_ROOT}/templates/`, fill STATE.md.

1. demo-strategist -> `brief.md`, `demo.yaml`. **G1**: show them, ask platform, length, voice, formats and data mode (`seeded` by default; `real` only if the user chooses it). toolsmith checks tools for the next stages (asks before installing).
2. app-scout -> `app-map.md`. Then in parallel: privacy-guard -> seeded data, `demo.yaml privacy.*`; storyboarder -> `storyboard.md`.
3. scriptwriter -> `narration.md`; localizer -> `narration.<lang>.md` only if `language` != `voice.language`. **G2**: wait for approval; no recording before it.
4. voice-producer -> `media/sNN.vo.wav`. scene-automator -> `scenes.<platform>.py`. capture-operator -> `media/sNN.raw.*`.
5. sync-editor -> `edit.json`. In parallel: motion-designer -> `motion.json`, caption-writer -> `captions.json`, sound-mixer -> `mix.json`. render-engineer -> `media/final-*.mp4`.
6. demo-qa -> `verify.py`, `qa.md`. FAIL: send each finding to its owner (director's routing table), re-render, QA again (same finding 3 times: ask the user). **G3**: show finals and the PASS verdict, wait for approval. packager -> `thumb.png`, `delivery.md`.

Install tools only after asking. Do not commit or push.
