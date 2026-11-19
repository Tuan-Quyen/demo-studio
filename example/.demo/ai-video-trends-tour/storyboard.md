# Storyboard: AI Video Trends — quick tour

Target length, formats, platform: from `demo.yaml` (do not copy values here)

Key message (brief): see what's trending in AI video and which genres are worth betting on, all in one place.
Structure: Problem (s01) → Solution (s02, s03) → Outcome + CTA (s04). Scene order follows page order (Hero → Trending → Trends → Genres), so no scene scrolls back up. The hero CTA is not used, because it jumps past the Trending grid.

| Scene | Goal | On-screen action | Camera intent | Measured VO (s) | Duration (s) |
|---|---|---|---|---|---|
| s01 | Hook: too many AI video formats, here is one page that sorts them | Hero → scroll down to Trending grid (8 cards) | wide, slow push-in on H1, then wide on the grid | 6.50 | 7 |
| s02 | Find a trending video by genre and see why it works | Trending → chip "Faceless YouTube" → card v5 → detail modal (prompt, tool, why it trends) | zoom to chip, zoom to card, zoom to modal fields | 11.90 | 14 |
| s03 | See which techniques are rising | Header nav "Trends" → 4 trend cards → chart | wide on trend cards, zoom to chart | 6.91 | 8 |
| s04 | Outcome: know where to focus next + CTA | Header nav "Genres" → ranked list → CTA end card | wide, zoom to rank 1, end card | 8.88 | 11 |

Total: 40 s (demo.yaml `length_s` target 40, tolerance ±10% = 36–44 s). Measured VO total 34.19 s; 5.8 s of action/hold air.

Narration (unchanged, measured in `project.json#voice`): word counts s01 14 · s02 37 · s03 25 · s04 25. Budgets stay at these counts; the measured VO fits every scene, so no cuts are needed. Narration is Vietnamese over an English UI: describe outcomes, never read English labels aloud.

## Scenes

### s01 · Hook — one page for AI video trends (7 s; VO 6.50 s)
- Goal: state the pain (too many AI video formats, hard to know what works) over the starting screen, then show the answer.
- Start state: Hero, fresh load, scrollY 0, filter "All", modal closed.
- Actions:
  1. Hold on the Hero (H1 "What's trending in AI video creation" + sub-copy) ~2 s.
  2. Scroll down to the Trending section (`#trending`); 8 chips and 8 cards come into view; hold ~2 s.
- Expected result: Trending grid fully in frame, count shows "8 videos · All".
- Visible change within 2 s: slow push-in on the H1 from t=0, scroll starts by ~2 s.
- Camera: wide; gentle push-in (≤1.2x) on the H1, ease out before the scroll; wide on the grid.
- Callouts / title cards: none (no logo or title opener; hook is the pain line over the hero).
- Motion hint (basic): push-in + 300 ms cross-fade into s02.
- SENSITIVE visible: signed-in email pill (sticky header).

### s02 · Filter by genre and open a video (14 s; VO 11.90 s)
- Goal: show that you can filter trending AI-made videos by genre and open one to see its prompt example, tool category and why it trends (proof point 1).
- Start state: Trending section at top of the viewport (below sticky header), filter "All", 8 cards, modal closed.
- Actions:
  1. Click genre chip "Faceless YouTube"; non-matching cards fade out; count reads "1 video · Faceless YouTube". (~3 s incl. hold)
  2. Click the remaining card (v5); detail modal fades in. (~2.5 s)
  3. Hold on title/meta, then Prompt example and Tool category (~5 s); scroll inside the modal to "Why it trends" and hold (~3.5 s).
- Expected result: modal open with "Why it trends" fully readable.
- Camera: zoom to chip on click (1.6x), ease out to show the grid shrink; zoom to card v5 on click; modal: zoom to Prompt example + Tool category, then pan/zoom to Why it trends.
- Callouts / title cards: highlight box on the chip and on the card (basic). No callout text.
- Motion hint (basic): zoom to click ×2, highlight ×2, one modal zoom/pan; ≤6 effects.
- SENSITIVE visible: signed-in email pill (also readable dimmed behind the modal backdrop — still blur).

### s03 · Rising techniques and genre growth (8 s; VO 6.91 s)
- Goal: show the trend cards and the 90-day genre growth chart (proof point 2). Figures are sample data; chart caption says "(sample)".
- Start state: Trending section in view (continuity with s02's page position), modal closed, filter "All".
- Actions:
  1. Click header nav "Trends"; page smooth-scrolls to the Trends section; 4 trend cards in view (~3.5 s incl. hold).
  2. Scroll so the chart sits at the top of the viewport (block: start) and hold on the chart (~4.5 s). Do not scroll further.
- Expected result: chart in frame with its "(sample)" caption; creator dashboard / API key below the fold.
- Camera: wide on the 4 trend cards; zoom to the chart (top bars + caption), keep the crop above the dashboard.
- Callouts / title cards: none; optional highlight box on the top growth bar.
- Motion hint (basic): one zoom on the chart.
- SENSITIVE visible: signed-in email pill; API key / creator dashboard is just off-frame at 720 px viewport height and in frame at any taller viewport → mark `api-key` sensitive for the whole scene regardless.

### s04 · Where to focus next + CTA (11 s; VO 8.88 s)
- Goal: show the ranked "Promising genres" list with a reason for each (proof point 3), land the outcome, then the CTA.
- Start state: Trends section with the chart at the top of the viewport (continuity with s03).
- Actions:
  1. Click header nav "Genres"; page jumps straight to Promising genres (block: start), passing over the creator dashboard during the smooth scroll (~2 s).
  2. Hold on the 5 ranked genres; dwell on rank 1 and its reason (~5 s).
  3. CTA end card (4 s, ≥3 s): "Open AI Video Trends and pick your next genre to try." in the narration language. The spoken CTA line plays over the end card; the card holds ~1 s after the VO ends.
- Expected result: ranked list in frame, then the end card.
- Camera: wide on the list, zoom to rank 1 (1.5x), ease out, fade to end card.
- Callouts / title cards: highlight box on rank 1; end card (drawtext, one line + optional subline), holds ≥3 s; fade through black is intended (list in `#checks.allow.black`).
- Motion hint (basic): one zoom, one highlight, fade, title card.
- SENSITIVE visible: signed-in email pill; API key / creator dashboard during the scroll from chart to genres (mark for the scroll; dashboard ends above the fold at y ≈ −124).

## Sensitive elements by scene
| Scene | Elements (app-map) |
|---|---|
| s01 | signed-in email pill `[data-testid=signed-in-pill]` |
| s02 | signed-in email pill (incl. under modal backdrop) |
| s03 | signed-in email pill; API key `[data-testid=api-key]` (mark all scene; in frame if viewport > 720 px tall) |
| s04 | signed-in email pill; API key `[data-testid=api-key]` during the scroll to Genres |

## Open questions
1. Recording viewport (capture-operator) vs modal and API key. At 1280x720 the API key stays off-frame in s03 but the modal clips "Why it trends" (s02 then needs the internal modal scroll, already planned). At ≥1280x800 the modal fits but the API key enters frame under the chart in s03 and must be blurred. Options: (a) 1280x720, internal modal scroll in s02, API key marked anyway [recommended default]; (b) 1280x800+, no modal scroll, API key blurred in s03; (c) 1920x1080, same as (b) with more of the page visible.
2. Header nav links "Trends" / "Genres" (s03, s04): app-map lists the nav links on the Header screen and names the `#genres` nav link, but gives a verified selector only for the hero CTA. Fallback if no stable nav selector: `scrollIntoView({block:'start'})` on `section-trends` / `section-genres` (same on-screen result, pointer moves to the nav link for realism). Not a missing flow; scene-automator decides.
3. Per-scene start states: app-map's default start is a fresh load at scrollY 0. s02–s04 start mid-page (Trending / Trending / Trends). Scene-automator should reach those positions before recording starts (instant scroll, no smooth scroll in the clip).
4. Tight scenes after the retime: s01 has 0.5 s of air over its VO and s03 has 1.1 s. If sync-editor finds an action cannot fit, add the time from s02/s04 holds (total may rise to 44 s) rather than cutting a beat.

## Approval
G2: pending (retimed for length_s 40; re-approval needed)
