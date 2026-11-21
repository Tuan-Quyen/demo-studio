---
name: demo-storytelling
description: Load when writing or reviewing a demo's brief, storyboard or narration (demo-strategist, storyboarder, scriptwriter, localizer, demo-director). Story structure, hook, CTA, length and word budgets, scene-count rules.
---

# Demo storytelling

## Structure: Problem -> Solution -> Outcome
1. **Problem** (10-20%): one concrete pain of the target user, in their words. Not a feature list.
2. **Solution** (60-70%): the shortest path in the product that removes that pain. Show only the flow that serves the outcome; skip settings, onboarding and anything "also you can".
3. **Outcome** (10-20%): the end state the user cares about (invoice sent, time saved), shown on screen, then the CTA.

## Hook (first 5 seconds)
Open on the result or the pain, never on a logo, "Hi, today I'll show you", or a loading screen. Pick one: (a) the finished outcome on screen + one line, (b) the pain stated in one line over the starting screen. The hook scene must contain motion or a visible change within 2 s.

## One CTA
Exactly one, last, specific and doable ("Start a free trial at example.com"). No second ask, no recap of features after it. It appears in VO and as an end card.

## Length budgets
| format | length | scenes | use |
|---|---|---|---|
| short / social | 60-90 s | 4-6 | one job, one outcome |
| full demo | 2-3 min | 6-10 | one workflow, end to end |
`demo.yaml` `length_s` states the target length in seconds; render check allows +-10% (see media-specs). Over 3 min: split into two videos, do not stretch.

## Narration budget
- **One formula:** `words <= length_s x rate(lang) x 0.85` with rate `en` 2.5, `vi` 3.0, any other language 2.5 words/s (calibrate from the measured VO after the first scene: measured words/s incl. pauses) (the 15% is air for on-screen action and holds; natural ranges in `voice-over`). Per scene use the scene's seconds. `en`: 50 s -> ~106 words, 90 s -> ~191; `vi`: 50 s -> ~127, 90 s -> ~229. By design the VO is ~85% of `length_s`. Scriptwriter and storyboarder use this.
- This is a first estimate. Real duration comes from the measured VO (`vo.py` / ffprobe) (TTS output); languages/voices differ, and some (e.g. Vietnamese) speak faster, so the **measured VO decides**. If the measured VO exceeds the scene budget by >10%, cut words (scriptwriter), do not speed up audio. If total VO is < 75% of `length_s`, the director lowers `length_s` (storyboarder retimes the scenes) rather than leaving silence.

## Scene count rules
- One idea and one on-screen goal per scene. 8-20 s per scene (hook <= 8 s). A scene with more than ~3 user actions gets split.
- Scene ids `s01..sNN` are permanent: reuse them in storyboard, narration, scriptsand media. Insert by renumbering only before G2 approval.
- Every cut changes something the viewer can see (screen, zoom target or state). Never two scenes on the same unchanged screen.

## Storyboard rules (storyboarder)
Per scene: id, goal (one sentence), reading hold in s (after the last action; default 0.4, 1-2 only where asked; scene duration = VO + hold, and VO is within the word budget so the holds fit the 15% air), on-screen actions in order (using app-map names), start/end screen, camera intent (where to zoom/highlight, or "none"), target duration (s), narration ref, sensitive elements visible (from app-map), motion hint. Uses only flows that exist in app-map.md; if a flow is missing, ask app-scout, do not invent UI.

## Narration rules (scriptwriter)
- Write for the ear: present tense, second person ("you"), sentences <= ~14 words (a longer one needs a comma or a split; never over 20; a long comma-less sentence is read too fast), contractions, numerals as people say them.
- Say the outcome of an action, not the click ("Your invoice is on its way"), unless the click is the point. Never read button labels or URLs aloud.
- Narration leads the action by ~0.3-0.5 s: the line starts, then the pointer moves.
- One scene = one block of text with its word count and a target duration; no stage directions inside the spoken text. Keep brand names, numbers and acronyms with a pronunciation hint if the TTS may fail.
- Real private data is never spoken. Use generic words ("a customer"), even if the screen shows a real name.
- Total words must pass the budget above; list `facts:` words and estimated duration in the handoff.
