---
description: "Pre-production only: brief, storyboard and narration"
argument-hint: "<what to demo>"
disable-model-invocation: true
---

Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run the script pipeline for: $ARGUMENTS

Empty request → ask what to demo, then stop.

1. demo-strategist → `brief.md` + `demo.yaml`. **G1: wait for approval.**
2. app-scout → `app-map.md` (with `target:` and sensitive elements).
3. storyboarder → `storyboard.md`; scriptwriter → `narration.md` (word budget per `demo-storytelling` vs scene durations); localizer → `localization.md` + `narration.<voice.language>.md` when `language` differs from `voice.language`.
4. **Art** (stage `art`, after the localizer) — the art sub-pipeline, run to the end: **style question first** (director step 0, asked here and never at G1; skipped when the request names valid codes or keywords, or `#art.style` is set); art-designer → `#art` → privacy (audit only, `#privacy.art`) → demo-qa art mode → `qa-art.md`. FAIL → the finding's owner fixes, then privacy and demo-qa again (same finding 3 rounds → ask the user).
5. **G2 (one question, only after art PASS): show the art previews (PNG, else SVG) + the `qa-art.md` verdict + storyboard + narration (both languages if localized), wait for approval; options approve and record / edit script / edit storyboard / edit art (a different style re-asks step 0 and redoes all art; the 3-round cap restarts).** Stop. Next step is `/demo-studio:shoot`.

No recording, voice or render here.

Rules: slug, STATE.md, briefs and handoffs follow the director file and the `run-kits` skill. Tools just in time: right before a step, if `setup_tools.py --stage <name>` is not ready, the director briefs toolsmith `suggest` for that stage, asks the user, then toolsmith `install` (director file, **Tools, just in time**); install nothing for later stages. Never record, render or install without the gate or approval named above. Do not commit or push.
