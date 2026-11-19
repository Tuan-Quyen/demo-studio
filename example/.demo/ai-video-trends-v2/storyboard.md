# Storyboard: AI Video Trends, the full tour

Target length, formats, platform: from `demo.yaml` (do not copy values here)

| Scene | Goal | On-screen action | Camera intent | Duration (s) |
|---|---|---|---|---|
| s01 | Hook: introduce AI Video Trends by name | Product title card, then the hero | title card, then wide with slow zoom to headline | 7 |
| s02 | Header nav reaches the Trending grid; all 8 videos | Click nav "Trending"; grid row 1, scroll to row 2 | wide, follow the scroll | 10 |
| s03 | Genre chips filter the grid; reset to All | Click "Music video", "Anime", then "All" | zoom to chips, ease out to the grid after each click | 14 |
| s04 | Pick Faceless YouTube and open a video | Click "Faceless YouTube", click card-v5, popup opens | zoom to chip, then to the popup's top fields | 8 |
| s05 | The popup explains why it trends; close it | Scroll inside the popup to "Why it trends", click Close | zoom to "Why it trends", ease out for the close | 9 |
| s06 | Header nav reaches Trends; 4 trend cards | Click nav "Trends"; trend cards | wide on the 4 cards, then slow pan across them | 10.5 |
| s07 | The growth chart shows which genres rise | Scroll ~+330 px to the genre growth chart | zoom to the chart after the scroll settles | 7.5 |
| s08 | Header nav reaches Genres; ranks 1–2 | Click nav "Genres"; ranks 1 and 2 | wide on the list, then zoom to ranks 1–2 | 14 |
| s09 | Ranks 3–5 complete the ranking | Cursor moves down ranks 3, 4, 5 | follow cursor down ranks 3–5 | 18 |
| s10 | CTA: Explore trends | Scroll to top, click hero "Explore trends" (page glides to Trends), end card | zoom to the button at the click, fade to end card | 10.5 |

Total: 108.5 s (demo.yaml `length_s` target 105, tolerance ±10% = 94.5–115.5; +3.5 s over target by director decision, extra reading time in s03 and s09)

Retimed (/fix, VO v8 = narration.md en, Andrew -10%, project.json#voice): scene = VO + on-screen action not covered by speech + reading hold(s). Scenes, order, actions and sensitive notes unchanged.
| Scene | VO (s) | Uncovered action (s) | Reading hold(s) (s) | Scene (s) | Timing inside the scene (approx., for scene-automator pauses) |
|---|---|---|---|---|---|
| s01 | 5.88 | 0 (title card runs under VO) | ~1.1 on the hero | 7 | title card 0–2.5; VO 0–5.9; hold 5.9–7 |
| s02 | 7.92 | ~0.6 (nav smooth scroll ~1 s, VO starts during it) | ~0.8 row 1 + ~0.7 row 2 | 10 | nav click ~0.3, settle ~1.3; row-1 line + hold; scroll to row 2 ~0.6 s; row-2 line + hold to 10 |
| s03 | 9.80 | ~0.9 (3 × ~0.3 s fade) | ~1.1 Music video + ~1.1 Anime + ~1.1 after All | 14 | click Music video ~0.5; click Anime ~5; click All ~9.5; each click lands after its VO line, fade 0.3, then hold |
| s04 | 5.02 | ~1.0 (chip fade 0.3 + popup open ~0.7) | ~0.8 filtered grid + ~1.2 popup fields | 8 | chip click ~0.5; card click ~3; popup settled ~3.7; hold on fields to 8 |
| s05 | 5.46 | ~1.0 (in-modal scroll ~1 s, close ~0.5, partly under VO) | ~1.8 "Why it trends" + ~0.7 grid after close | 9 | in-modal scroll 0.3–1.3; "Why it trends" hold to ~6.5; Close click ~7; grid hold to 9 |
| s06 | 9.27 | ~0.2 (nav scroll ~1 s, VO starts during it) | ~1.0 on the 4 cards | 10.5 | nav click ~0.3, settle ~1.3; cursor t1→t4 under VO; hold 9.5–10.5 |
| s07 | 4.90 | ~1.0 (scroll ~+330 px and settle) | ~1.6 on the chart | 7.5 | scroll 0.3–1.3; zoom after settle; VO; hold 5.9–7.5 |
| s08 | 11.98 | ~0.8 (nav scroll from ~1765 to ~2586, ~1.3 s, VO starts during it) | ~0.6 rank 1 + ~0.6 rank 2 | 14 | nav click ~0.3, settle ~1.6; wide ~2 s under the VO opener; zoom ranks 1–2; short hold after each rank line |
| s09 | 13.89 | 0 (cursor moves only, under VO) | ~1.1 each for ranks 3, 4, 5 + ~0.8 full list | 18 | rank-3 line 0–4.6, hold to 5.7; rank-4 line 5.7–10.3, hold to 11.4; rank-5 line 11.4–16, hold to 17.1 (cursor moves just before each line); ease out to full list 17.1–18 |
| s10 | ~6.5 (incl. ~1 s [pause]) | ~1.5 (scroll up ~1.5 s; click + glide ~1.5 s, partly under VO) | ~1.0 on the hero before the click + ~1.5 end-card hold after the CTA | 10.5 | scroll up 0–1.5; hero line; hold; button click ~4.5; glide to Trends ~4.5–6; [pause]; end card 6.5–10.5 (4 s), CTA sentence starts at card in |
Sum: VO ~80.6 s + uncovered action ~7.0 s + reading holds ~20.8 s ≈ 108.5 s.
Note: director chose the slower option (user found the previous cut too fast): s03 12.5 → 14 and s09 16 → 18, with the extra time in the chip-result and rank holds. Holds in s02 and s08 stay under 1 s (multi-step screens; the content stays on screen while the next line plays).

Structure: Hook s01 (7 s, 6%) → Solution s02–s09 (91 s, 84%, the tour in brief order: nav → trending + chips → popup → trends → chart → genres) → Outcome + CTA s10 (10.5 s, 10%; end card 4 s, ≥ 3 s).
Director decisions applied: G1 re-approved (auto); length 120 → 105 s after measured VO v8, cut planned at 108.5 s for more reading time; header nav used for all three sections (s02 Trending, s06 Trends, s08 Genres); hero "Explore trends" button used as the visible CTA action in s10, matching the end card; all 5 ranks read with their reasons (s08 + s09); no spoken figures (sample data shown on screen only, "sample" chart caption and "Sample data for demo" footer stay legible where in frame); every screen has a silent reading hold after its VO line (sizes in the retime table).
On-screen text: title card and end card text come from narration.md "On-screen strings (en)" (title card "AI Video Trends" + its subline; end card "Explore trends" / "AI Video Trends · sample data"); this file does not restate other strings. narration.md's chapter titles are keyed to the old s01–s05 and must be re-keyed to s01–s10 by the scriptwriter.

Narration: measured VO v8 (table above) decides; the earlier word budget no longer applies.

## Scenes

### s01 — Hook: AI Video Trends (7 s)
- Goal: The viewer learns the product's name and what it shows.
- Start state: Hero, scrollY 0, fresh load (filter state reset).
- On-screen actions: none by the user; cursor rests near the "Explore trends" button (no click).
- Expected result / end screen: hero h1 and key-message sub-line readable.
- Camera intent: product title card ≤ 2.5 s, fade to the hero, slow zoom (~1.2x) toward h1 + sub-line (visible change within 2 s).
- Callouts / title cards: title card "AI Video Trends" + subline (narration.md On-screen strings). First spoken line names "AI Video Trends".
- Reading hold: ~1.1 s on the hero after the VO line.
- Sensitive visible: signed-in email pill.
- Motion hint (basic): title card (drawtext) + fade, gentle zoom.

### s02 — Header nav to Trending, all 8 videos (10 s)
- Goal: The header nav takes the viewer to the Trending grid, where all 8 sample videos are visible.
- Start state: Hero (end of s01), scrollY 0.
- On-screen actions: click header nav "Trending" (page smooth-scrolls to Trending, scrollY ≈ 481; chips, count "8 videos · All" and grid row 1 in frame); hold; scroll down ~+300 px so grid row 2 (cards v5–v8) is fully in frame; hold.
- Expected result / end screen: all 8 cards have been seen, row 2 fully in frame.
- Camera intent: wide; cursor highlight on the nav link; follow the scroll (no zoom during smooth scroll).
- Callouts / title cards: none.
- Reading hold: ~0.8 s on row 1 + count, ~0.7 s on row 2 (each row is on screen ~4 s in total).
- Sensitive visible: signed-in email pill.
- Motion hint (basic): cursor highlight on "Trending"; 300 ms fade into s03.

### s03 — Filter by genre, reset to All (14 s)
- Goal: One tap per chip narrows the grid to a genre; "All" brings every video back.
- Start state: Trending, scrollY ≈ 481 (instant jump to `#trending` in prepare), chip "All" pressed, 8 videos.
- On-screen actions: click chip "Music video" → one card ("Synthwave Sunrise (Full Music Video)", card-v3); click chip "Anime" → one card ("Moonlit Blade: Episode 0", card-v8); click chip "All" → all 8 cards return. Wait ≥ 300 ms after each click for the fade.
- Expected result / end screen: count back to "8 videos · All", full grid row 1 in frame.
- Camera intent: zoom to the chip row at each click, ease out to the grid as it changes.
- Callouts / title cards: none.
- Reading hold: ~1.1 s after each filter result (Music video, Anime) and after the reset to All.
- Sensitive visible: signed-in email pill.
- Motion hint (basic): zoom to click + cursor highlight per chip (3 zooms; within the ~6-effects limit).

### s04 — Faceless YouTube, open a video (8 s)
- Goal: Pick a genre and open one video's detail popup.
- Start state: Trending, All selected (end of s03).
- On-screen actions: click chip "Faceless YouTube" → card-v5 "10 Habits of Calm Productive People" alone; click card-v5 → detail popup opens (thumb, title, meta, description, Prompt example, Tool category).
- Expected result / end screen: popup open, Prompt example and Tool category readable.
- Camera intent: zoom to the chip at the click, ease out; zoom to the popup's Prompt example / Tool category after it opens.
- Callouts / title cards: none (popup fields carry their own labels).
- Reading hold: ~0.8 s on the filtered grid, ~1.2 s on the popup fields.
- Sensitive visible: signed-in email pill (dimmed under the popup backdrop, still blurred).
- Motion hint (basic): zoom to click ×2, cursor highlight.

### s05 — Why it trends, close the popup (9 s)
- Goal: The popup explains why the video trends; closing it returns to the grid.
- Start state: popup open on card-v5 (end of s04), "Why it trends" clipped at the card bottom.
- On-screen actions: scroll inside the popup card until "Why it trends" is fully visible; hold; click "Close" (shown on screen) → back to the Faceless YouTube grid with card-v5.
- Expected result / end screen: popup closed, filtered grid with card-v5.
- Camera intent: zoom to "Why it trends" after the in-card scroll; ease out before the close so the Close button and the return to the grid are visible.
- Callouts / title cards: none.
- Reading hold: ~1.8 s on "Why it trends", ~0.7 s on the grid after the close.
- Sensitive visible: signed-in email pill (under the backdrop, then normal).
- Motion hint (basic): zoom, cursor highlight on Close.

### s06 — Header nav to Trends, 4 trend cards (10.5 s)
- Goal: The header nav takes the viewer to Trends, where 4 trend cards show rising techniques.
- Start state: Trending, Faceless YouTube filtered (end of s05).
- On-screen actions: click header nav "Trends" (smooth-scrolls to scrollY ≈ 1435); hold on the 4 trend cards; cursor moves across cards t1 → t4.
- Expected result / end screen: the 4 trend cards readable.
- Camera intent: wide on the 4 cards; slow pan/zoom (~1.2x) following the cursor across them; no zoom during the smooth scroll.
- Callouts / title cards: none.
- Reading hold: ~1 s on the cards after the VO line.
- Sensitive visible: signed-in email pill. API key is below the frame (viewport y ≈ 1116 at scrollY 1435): mark `[data-testid=api-key]` sensitive as a safety net.
- Motion hint (basic): cursor highlight on "Trends", gentle zoom.

### s07 — Genre growth chart (7.5 s)
- Goal: The growth chart shows which genres are rising (sample data).
- Start state: Trends, scrollY ≈ 1435 (end of s06).
- On-screen actions: scroll ~+330 px to the genre growth chart; hold.
- Expected result / end screen: chart "Genre growth, last 90 days (sample)" fully in frame with "(sample)" readable; creator dashboard / API key NOT in frame (stay at scrollY ≤ ~1800: API key at doc y 2551 → viewport y ≥ 751, just below the 720 frame).
- Camera intent: wide, then zoom to the chart's bars once the scroll settles; keep the zoom window inside the chart (never toward the frame bottom).
- Callouts / title cards: none.
- Reading hold: ~1.6 s on the chart.
- Sensitive visible: signed-in email pill; guard `[data-testid=api-key]` (off-frame by ~30 px; mark sensitive).
- Motion hint (basic): zoom after the scroll settles.

### s08 — Header nav to Genres, ranks 1–2 (14 s)
- Goal: The header nav takes the viewer to the genre ranking; ranks 1–2 and their reasons.
- Start state: Trends chart, scrollY ≈ 1765 (end of s07).
- On-screen actions: click header nav "Genres" (smooth-scrolls to scrollY ≈ 2586); whole ranked list rank-1..5 in frame; cursor rests on rank-1 "Faceless YouTube", then rank-2 "Short-form ads".
- Expected result / end screen: ranks 1–2 and their "why" text readable.
- Camera intent: wide on the full list (~2 s), then zoom (~1.5x) to ranks 1–2.
- Callouts / title cards: none.
- Reading hold: ~0.6 s after each rank's VO line (the whole list stays on screen).
- Sensitive visible: signed-in email pill; API key passes through the frame during the nav smooth scroll (doc y 2551 lies between scrollY 1765 and 2586): `[data-testid=api-key]` must be blurred in transit frames.
- Motion hint (basic): cursor highlight on "Genres", zoom after the scroll settles.

### s09 — Ranks 3–5 (18 s)
- Goal: Ranks 3–5 and their reasons complete the ranking.
- Start state: Genres, scrollY ≈ 2586, zoomed on ranks 1–2 (end of s08).
- On-screen actions: cursor moves down to rank-3 "UGC avatar", rank-4 "Cinematic shorts", rank-5 "Anime" (no clicks).
- Expected result / end screen: rank-5 and its reason readable; full list shown again at the end.
- Camera intent: follow the cursor down ranks 3–5 (zoom window pans down), ease out to the full list at the end.
- Callouts / title cards: none.
- Reading hold: ~1.1 s after each rank's VO line (ranks 3, 4, 5); ~0.8 s on the full list at the end.
- Sensitive visible: signed-in email pill.
- Motion hint (basic): zoom pan (reframe following cursor), cursor highlight per rank.

### s10 — CTA: Explore trends (10.5 s)
- Goal: The viewer has a genre to try; one CTA, shown as the real "Explore trends" button and the end card.
- Start state: Genres, scrollY ≈ 2586 (end of s09).
- On-screen actions: scroll to the top of the page (hero); click the hero "Explore trends" button → page glides to Trends (trend cards).
- Expected result / end screen: Trends section, then the CTA end card.
- Camera intent: wide during the scroll up; zoom to the button at the click (button bbox [60,433,156,52] at scrollY 0); ease out as the page glides; fade to the end card.
- Callouts / title cards: CTA end card ≥ 3 s (4 s planned, 6.5–10.5 s): "Explore trends" / "AI Video Trends · sample data" (narration.md On-screen strings). The CTA sentence is spoken over the end card. One CTA only.
- Reading hold: ~1 s on the hero before the click.
- Sensitive visible: signed-in email pill; API key passes through the frame during the scroll up (from scrollY 2586 past doc y 2551): `[data-testid=api-key]` must be blurred in transit frames. None on the end card.
- Motion hint (basic): zoom to click + cursor highlight on the button, fade to black end card (intended black, list in checks.allow.black).

## Sensitive elements per scene
| Scene | Visible | Selector (from app-map) |
|---|---|---|
| s01 | signed-in email pill | `[data-testid=signed-in-pill]` |
| s02 | signed-in email pill | `[data-testid=signed-in-pill]` |
| s03 | signed-in email pill | `[data-testid=signed-in-pill]` |
| s04 | signed-in email pill (under popup backdrop) | `[data-testid=signed-in-pill]` |
| s05 | signed-in email pill (under backdrop, then normal) | `[data-testid=signed-in-pill]` |
| s06 | signed-in email pill; API key below frame (safety net) | `[data-testid=signed-in-pill]`; `[data-testid=api-key]` |
| s07 | signed-in email pill; API key ~30 px below frame (safety net) | `[data-testid=signed-in-pill]`; `[data-testid=api-key]` |
| s08 | signed-in email pill; API key in transit during the nav scroll | `[data-testid=signed-in-pill]`; `[data-testid=api-key]` |
| s09 | signed-in email pill | `[data-testid=signed-in-pill]` |
| s10 | signed-in email pill; API key in transit during the scroll up | `[data-testid=signed-in-pill]`; `[data-testid=api-key]` |

## Open questions
Resolved by the director: API key in transit (s08, s10) → privacy-blurrer tracks `[data-testid=api-key]` through the scroll frames; s02 row-2 scroll offset (stop when `[data-testid=card-v8]` is fully in frame) and s10 scroll-to-top → scene-automator verifies live; short holds → slower option (s03 14 s, s09 18 s). None open.

## Approval
G2: pending (G2 reopened after /fix; test run, auto-approved by the director)
