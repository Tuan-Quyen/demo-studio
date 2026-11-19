# Storyboard: AI Video Trends in under a minute

Target length, formats, platform: from `demo.yaml` (do not copy values here)

| Scene | Goal | On-screen action | Camera intent | Duration (s) |
|---|---|---|---|---|
| s01 | Hook: one page answers "what's trending in AI video" | Hero headline + sub-line, title card | wide, slow zoom to headline | 7 |
| s02 | Trending videos filter by genre in one tap | Click chip "Faceless YouTube", grid narrows to one card | zoom to chips, then follow to card | 6 |
| s03 | Each video explains its prompt, tool and why it trends | Open card-v5 modal, scroll to "Why it trends", close | zoom to modal fields | 9 |
| s04 | Trend cards and the growth chart show what's rising | Trends cards, scroll to genre growth chart | wide, then zoom to chart | 6 |
| s05 | Ranked genres give a clear pick + CTA | Promising genres list, rank-1 highlight, CTA end card | wide, zoom to rank-1, end card | 10 |

Total: 38 s (demo.yaml `length_s` target 38, tolerance ±10% = 34.2–41.8)

Retimed (step 4b) to measured VO (project.json#voice): s01 5.95 + 1.05 hold/title, s02 5.09 + 0.91 click/fade, s03 7.51 + 1.49 in-modal scroll/close, s04 5.04 + 0.96 scroll settle, s05 8.58 + 1.42 end-card hold = 32.2 s VO + 5.8 s action/hold. Scenes, ids, order and actions unchanged.

Structure: Problem s01 (7 s, 18%) → Solution s02–s04 (21 s, 55%) → Outcome + CTA s05 (10 s, 26%; CTA end card 3 s of it).
Director decisions applied: length lowered 45 → 38 s after measured VO (was: keep 45 s); all three proof points shown briefly; no numbers spoken (sample data on screen only, "sample" label/footer stays legible where shown); CTA uses in-app wording.

## Scenes

### s01 — Hook (7 s)
- Goal: The viewer sees in one line that this page shows what's trending in AI video.
- Start state: Hero, scrollY 0, filter state reset (fresh load).
- On-screen actions: none by the user; cursor rests near the "Explore trends" button (no click).
- Expected result / end screen: Hero with h1 "What's trending in AI video creation" and the key-message sub-line readable.
- Camera intent: wide, slow zoom (~1.2x) toward h1 + sub-line, starting within the first 2 s (visible change for the hook).
- Callouts / title cards: opening title card ≤ 2.5 s over the hero (one line, e.g. the pain: too many AI video formats to track), then fade to the hero.
- Sensitive visible: signed-in pill with email (header).
- Motion hint (basic): title card (drawtext) + fade, gentle zoom.

### s02 — Filter by genre (6 s)
- Goal: One tap narrows the trending grid to a single genre.
- Start state: Trending now section (anchor jump to `#trending` done before the take, scroll settled), chip "All" pressed, count "8 videos · All".
- On-screen actions: click chip "Faceless YouTube"; wait for the fade (~300 ms) as other cards disappear.
- Expected result / end screen: count reads "1 video · Faceless YouTube"; card "10 Habits of Calm Productive People" (card-v5) alone in the grid.
- Camera intent: zoom to the chip row at the click, ease out to follow the grid as it collapses to card-v5.
- Callouts / title cards: optional callout "One tap per genre" beside the chips (≤ 6 words, not over the pill).
- Sensitive visible: signed-in pill with email.
- Motion hint (basic): zoom to click + cursor highlight on the chip.

### s03 — Open one video (9 s)
- Goal: Each trending video opens with its prompt example, tool category and why it trends.
- Start state: Trending, filtered to Faceless YouTube (end state of s02), card-v5 visible.
- On-screen actions (budget: open ~1.5 s, fields ~3 s, in-modal scroll ~2.5 s, hold + close ~2 s): click card-v5; modal opens; scroll inside the modal card so "Why it trends" is fully visible; close the modal (Close button or Esc).
- Expected result / end screen: modal shown with Prompt example, Tool category, Why it trends; closes back to the filtered grid.
- Camera intent: zoom to the modal's Prompt example / Tool category, then to "Why it trends" after the in-card scroll; ease out before the close.
- Callouts / title cards: none (modal fields carry their own labels).
- Sensitive visible: signed-in pill with email (dimmed under the modal backdrop, still blurred).
- Motion hint (basic): zoom to click on the card, cursor highlight; 300 ms fade into s04.

### s04 — Trends + growth chart (6 s)
- Goal: Trend cards and the 90-day genre growth chart show which techniques are rising.
- Start state: Trends section (anchor jump to `#trends`, scrollY ≈ 1435, settled), modal closed.
- On-screen actions: hold on the 4 trend cards; scroll ~+330 px to the genre growth chart.
- Expected result / end screen: chart "Genre growth, last 90 days (sample)" fully in frame with its "sample" caption readable; creator dashboard / API key NOT in frame (stop at scrollY ≤ ~1800).
- Camera intent: wide on trend cards (~2 s), then zoom to the chart's top bars after the scroll settles.
- Callouts / title cards: optional callout "Sample data" near the figcaption if the caption is too small at output size.
- Sensitive visible: signed-in pill with email. API key must stay off-screen; if framing slips, mark `[data-testid=api-key]` sensitive as a safety net.
- Motion hint (basic): zoom after scroll settles; no zoom during the smooth scroll.

### s05 — Promising genres + CTA (10 s)
- Goal: A ranked list gives the viewer a clear genre to bet on; close with the single CTA.
- Start state: Promising genres section (anchor jump to `#genres`, scrollY 2586, settled); whole list rank-1..5 in frame.
- On-screen actions: hold on the ranked list; cursor moves to rank-1 "Faceless YouTube" (same genre as s02/s03, ties the story together).
- Expected result / end screen: rank-1 and its "why" text readable; then CTA end card.
- Camera intent: wide on the list (~2.5 s), zoom to rank-1 (~4.5 s), fade to end card (3 s; the VO CTA line lands on the card).
- Callouts / title cards: CTA end card ≥ 3 s, in-app wording: title "Explore trends" (mirrors the hero button), subline "AI Video Trends · sample data". Final wording belongs to scriptwriter/motion-designer; one CTA only, same in VO and on the card.
- Sensitive visible: signed-in pill with email (none on the end card).
- Motion hint (basic): cursor highlight ring on rank-1, zoom, fade to black end card (intended black, list in checks.allow.black).

## Sensitive elements per scene
| Scene | Visible | Selector (from app-map) |
|---|---|---|
| s01 | signed-in email pill | `[data-testid=signed-in-pill]` |
| s02 | signed-in email pill | `[data-testid=signed-in-pill]` |
| s03 | signed-in email pill (under backdrop) | `[data-testid=signed-in-pill]` |
| s04 | signed-in email pill; API key must stay off-screen | `[data-testid=signed-in-pill]`; guard `[data-testid=api-key]` |
| s05 | signed-in email pill | `[data-testid=signed-in-pill]` |

## Open questions
1. CTA wording: director said "in-app wording"; read as brief option (b) "Explore trends" (the hero button). If option (a) "Open AI Video Trends and pick your next genre" was meant, only the s05 end card text changes. Recommended default: "Explore trends".
2. s02 (6 s) and s04 (6 s) are under the demo-storytelling 8 s scene minimum; that follows from the measured VO and the 38 s target. Each still changes something visible (chip filter; scroll to chart). Options: (a) accept them, (b) merge s04 into s03/s05 (needs renumbering before G2). Recommended default: (a).
3. s04 is tight: the ~330 px smooth scroll must finish in ~1 s so the chart zoom lands before the VO ends. If capture shows it slipping, do the scroll instantly in the scene script rather than adding seconds.

## Approval
G2: pending (test run: gates auto-approved by the director)
