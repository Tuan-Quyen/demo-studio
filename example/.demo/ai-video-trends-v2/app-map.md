target: http://localhost:5173

# App map: AI Video Trends

entry: http://localhost:5173 (static single page, served by the user; no routing, sections reached by in-page anchors/scroll)
login: none. The page always renders a fake signed-in state (`DEMO_DATA.user`); no account, password or setup context needed. All data is fictional sample data (data.js header, footer "Sample data for demo").

Measured at viewport 1280x720 (Chromium headless, device_scale_factor 1). Page height 3414 px, max scrollY 2694. Bboxes below are CSS px. Selectors all `verified` (queried live, counts and boxes checked).

## Flows
| Flow | Steps (screen → action) | Selector / accessibility id | Notes |
|---|---|---|---|
| F1 Hero / key message | Hero (scrollY 0) → read headline + sub-line; optional click "Explore trends" | `[data-testid=section-hero]`, `h1`, `.sub`, `[data-testid=hero-cta]` / role link "Explore trends" | CTA is `href="#trends"`: smooth-scrolls to Trends (scrollY ≈1435). CTA bbox [60,433,156,52] at scrollY 0. verified |
| F2 Filter trending by genre | Trending (scrollY 481 via `#trending`) → click chip "Faceless YouTube" | chips: `[data-testid=chip-<slug>]` (all, short-form-ads, music-video, explainer, faceless-youtube, ugc-avatar, cinematic-shorts, anime) / role button name = label; state `aria-pressed="true"` | Count `#count` changes "8 videos · All" → "1 video · Faceless YouTube" (aria-live). Hidden cards fade 260 ms then `hidden`; wait ≥300 ms before reading card boxes. At scrollY 481 chips at y 189, card-v5 moves from y 583 → 282 after filter. verified |
| F3 Open one video detail | Trending (filtered) → click card → modal → close | cards `[data-testid=card-v1..v8]` (role button, name contains title); modal `[data-testid=modal]` (role dialog, `hidden` attr when closed); close `[data-testid=modal-close]` (role button "Close"), Esc, or backdrop click | Modal fields: `#m-title`, `#m-meta`, `#m-desc`, `#m-prompt` (Prompt example), `#m-tool` (Tool category), `#m-why` (Why it trends). Focus moves to close button on open, back to card on close. `body.lock` stops page scroll while open. Recommended card for F2 pick: card-v5 "10 Habits of Calm Productive People" (faceless-youtube, text-to-video). verified |
| F4 Trends + growth chart | Trends (scrollY ≈1435 via `#trends`, nav "Trends" or hero CTA) → scan trend cards → scroll to chart | `[data-testid=section-trends]`, `#trend-cards`, `[data-testid=trend-t1..t4]`, `[data-testid=genre-chart]` (figcaption "Genre growth, last 90 days (sample)", svg role img) | Trend cards (h 233) and chart (h 565) do not both fit in 720 px: show cards, then scroll ~+330 for the chart. Chart is static SVG (no animation, no hover). Creator dashboard with API key sits directly below the chart (doc y 2462): keep it out of frame or mark sensitive. verified |
| F5 Promising genres ranking | Genres (scrollY 2586 via `#genres` or nav "Genres") → read ranked list | `[data-testid=section-genres]`, `#rank`, `[data-testid=rank-1..5]` (`ol` list items) | Whole list fits (rank bbox y 189, h 498 at scrollY 2586). rank-1 = Faceless YouTube, matches F2/F3 pick. verified |
| Nav (any) | Header → click nav link | `nav a[href='#trending'|'#trends'|'#genres']` / role link "Trending"/"Trends"/"Genres" | Header is sticky: do NOT `scroll_into_view_if_needed()` on nav links (web.md pitfall). verified |

## Screens
- Header (sticky, top 0, h 64, always visible): brand link, nav (Trending/Trends/Genres), signed-in pill with email (SENSITIVE, visible in every frame).
- Hero (doc y 64–557): eyebrow "Weekly snapshot", h1 "What's trending in AI video creation", sub-line (brief key message), CTA "Explore trends".
- Trending now (doc y 557–1511): genre chips (8, single row), live count, grid of 8 video cards (4 per row, 2 rows; each thumb is a deterministic SVG, tool tag, title, creator handle, views, growth %).
- Video detail modal (fixed overlay, card 640x680 centred): thumb, title, meta line, description, Prompt example, Tool category, Why it trends.
- Trends (doc y 1511–2662): 4 trend cards (stat %, title, text), genre growth bar chart (7 bars, labelled "sample"), Creator dashboard panel with API key (out of scope).
- Promising genres (doc y 2662–3321): ranked list 1–5 with "why" text.
- Footer (doc y 3321–3414): copyright, "Sample data for demo" note `[data-testid=sample-note]`.

## Sensitive elements (must be marked and blurred)
| Screen | Element | Selector | Kind (email, name, amount, token, other) |
|---|---|---|---|
| Header (all scenes, incl. under modal backdrop) | Signed-in pill with email | `[data-testid=signed-in-pill]` (bbox [980,15,260,34], fixed on screen while sticky); inner `#user-email` [1065,23,162,17] | email (blur whole pill, `demo.yaml privacy.blur` "signed-in email") |
| Trends | Creator dashboard API key | `[data-testid=api-key]` (`#api-key`, doc y 2551; at scrollY 1435 → viewport y 1116, off-screen) | token (`privacy.blur` "API key"); whole panel `[data-testid=creator-dashboard]` is out of scope per brief |

Both carry `data-sensitive="true"` (query `[data-sensitive=true]` = 2). Not marked: creator handles (`@pixel_harbor`…) are fictional sample data, not private; `privacy.real_data: false`.

## Risks
- Sticky header: pill is in every frame → every scene needs `ctx.sensitive` on it at start; re-mark not needed on scroll (position fixed on screen), but it stays visible (dimmed) under the modal backdrop.
- `html{scroll-behavior:smooth}` + `scroll-padding-top:76px`: anchor/nav scrolls animate; do anchor jumps in `prepare` with `scrollIntoView({behavior:'instant'})` or wait for scroll to settle before reading bboxes.
- Modal content overflows: `.modal-card` scrollHeight 727 > clientHeight 678 (max-height 680, overflow auto) at 720 px. "Why it trends" (`#m-why`, y 700–724) is clipped at the card bottom; scroll the card (e.g. `#m-why` into view inside the card, or wheel over the card) to show it.
- Filter animation 260 ms (`.is-out` fade/scale, then `hidden`): wait ≥300 ms after a chip click before reading card bboxes or clicking a card.
- `prefers-reduced-motion: reduce` disables all transitions/smooth scroll; do not set `reduced_motion` in the recorder.
- API key panel directly under the chart: framing the chart bottom can expose it; keep scrollY ≤ ~1800 when showing the chart or mark `[data-testid=api-key]` sensitive.
- No auth wall, network calls, popups, cookie banners or notifications; no console errors observed. Static data → fully deterministic and re-runnable (reload resets filter state).
- Count text uses "·" (U+00B7); match by regex/partial text, not exact bytes, in assertions.
