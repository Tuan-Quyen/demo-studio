---
name: demo-storytelling
description: Load when writing or reviewing a demo's brief, storyboard or narration (demo-strategist, storyboarder, scriptwriter, demo-director). Story structure, hook, CTA, length and word budgets, scene-count rules.
---

# Demo storytelling

**Scope:** screen-only product demos. No on-camera presenter, talking head, avatar, actor or animated character; narration is voice-over only. Show the problem with product screens, text and title cards.

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
Brief states the target length in seconds; render check allows +-10% (see media-specs). Over 3 min: split into two videos, do not stretch.

## Narration budget
- ~150 words per minute = 2.5 words/s. Budget `words <= seconds x 2.5 x 0.85` (the 15% is air for on-screen action and holds). 60 s -> ~125 words, 90 s -> ~190, 3 min -> ~380.
- This is a first estimate. Real duration comes from `project.json#voice` (TTS output); languages/voices differ. If the measured VO exceeds the scene budget by >10%, cut words (scriptwriter), do not speed up audio.

## Scene count rules
- One idea and one on-screen goal per scene. 8-20 s per scene (hook <= 8 s). A scene with more than ~3 user actions gets split.
- Scene ids `s01..sNN` are permanent: reuse them in storyboard, narration, scripts, media and project.json. Insert by renumbering only before G2 approval.
- Every cut changes something the viewer can see (screen, zoom target or state). Never two scenes on the same unchanged screen.

## Storyboard rules (storyboarder -> storyboard.md)
Per scene: id, goal (one sentence), on-screen actions in order (using app-map names), start/end screen, camera intent (where to zoom/highlight, or "none"), target duration (s), narration ref, sensitive elements visible (from app-map), motion hint. Uses only flows that exist in app-map.md; if a flow is missing, ask app-scout, do not invent UI.

## Narration rules (scriptwriter -> narration.md)
- Write for the ear: present tense, second person ("you"), <= 20 words/sentence, contractions, numerals as people say them.
- Say the outcome of an action, not the click ("Your invoice is on its way"), unless the click is the point. Never read button labels or URLs aloud.
- Narration leads the action by ~0.3-0.5 s: the line starts, then the pointer moves.
- One scene = one block of text with its word count and a target duration; no stage directions inside the spoken text. Keep brand names, numbers and acronyms with a pronunciation hint if the TTS may fail.
- Real private data is never spoken. Use generic words ("a customer"), even if the screen shows a real name (it will be blurred).
- Total words must pass the budget above; list `facts:` words and estimated duration in the handoff.
