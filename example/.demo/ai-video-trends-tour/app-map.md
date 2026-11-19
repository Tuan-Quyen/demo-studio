target: http://localhost:5173
# App map: AI Video Trends

entry: http://localhost:5173 (static single page: index.html + data.js + app.js; served externally, already running)
login: none. The page always renders "signed in" from fictional `DEMO_DATA.user` in data.js; no auth, no account needed. Start state for every scene = fresh `page.goto(entry)` (filter resets to "All", modal closed, scrollY 0).

Inspected live with Playwright 1.65.2 (Chromium, viewport 1280x720), no console errors. All selectors below `verified` (queried live, count = 1, visible when expected).

## Flows
| Flow | Steps (screen → action) | Selector / accessibility id | Notes |
|---|---|---|---|
| Hero CTA | Hero → click "Explore trends" → page smooth-scrolls to Trends | `[data-testid=hero-cta]` (fallback `#cta`, role link "Explore trends") | Anchor `href="#trends"`; CSS `scroll-behavior:smooth`, `scroll-padding-top:76px`. Wait ~1000 ms or until `[data-testid=section-trends]` top ≈ 76 px. Lands at scrollY 1435; skips the Trending grid. |
| Genre chip filter | Trending → click chip → non-matching cards fade out | `[data-testid=chip-<slug>]`; slugs: `all, short-form-ads, music-video, explainer, faceless-youtube, ugc-avatar, cinematic-shorts, anime` (container `#chips`, role group "Filter by genre") | Done when chip `aria-pressed="true"` and `#count` text updates (e.g. "1 video · Faceless YouTube"; "8 videos · All"). Cards fade 260 ms, then `hidden` (0 ms if prefers-reduced-motion). Visible cards: `#grid .card:not([hidden])`. Multi-card genre: `ugc-avatar` (v6, v7). |
| Card detail modal | Trending → click card → modal with prompt example, tool category, why it trends → Esc / close / backdrop click | Card `[data-testid=card-v1..v8]`; modal `[data-testid=modal]` (role dialog); close `[data-testid=modal-close]`; fields `#m-title`, `#m-meta`, `#m-desc`, `#m-prompt`, `#m-tool`, `#m-why` | Open = `modal` loses `hidden`; focus moves to close button. Fade-in 200 ms. Close restores focus to card. At 720 px height the card scrolls 49 px: "Why it trends" text is cut at the bottom (see Risks). Suggested card for faceless filter: `card-v5`. |
| Trends + chart | Trends → view 4 trend cards → scroll to chart | Section `[data-testid=section-trends]`; cards `[data-testid=trend-t1..t4]` (container `#trend-cards`); chart `[data-testid=genre-chart]`, svg `#chart` (role img "Bar chart of genre growth", 7 `rect` bars) | Static, rendered on load, no animation. Chart caption says "(sample)". Creator dashboard with API key sits directly below the chart (see Sensitive). |
| Promising genres | Genres → view ranked list | Section `[data-testid=section-genres]`; items `[data-testid=rank-1..5]` (container `#rank`) | Static. Reach via `#genres` nav link or scroll. Scrolling from chart to genres passes over the API key panel. |

## Screens
- Header (sticky, z-index 20, on every screen): brand, nav links Trending/Trends/Genres, signed-in pill `[data-testid=signed-in-pill]` at ~x 980, y 15, 260x34 (1280 viewport).
- Hero `[data-testid=section-hero]`: eyebrow, H1 "What's trending in AI video creation", sub-copy (key message), CTA `[data-testid=hero-cta]`.
- Trending `[data-testid=section-trending]` (`#trending`): 8 genre chips, live count `#count` (aria-live), grid `#grid` of 8 card buttons (thumbnail, tool tag, title, creator handle, views, growth %).
- Detail modal `[data-testid=modal]`: thumbnail, title, meta line (creator · genre · views · growth), description, Prompt example, Tool category, Why it trends.
- Trends `[data-testid=section-trends]` (`#trends`): 4 trend cards with stat, genre growth bar chart, creator dashboard panel `[data-testid=creator-dashboard]` (out of scope per brief).
- Promising genres `[data-testid=section-genres]` (`#genres`): ordered list of 5 genres with rank number and reason.
- Footer `[data-testid=section-footer]`: "Sample data for demo" note `[data-testid=sample-note]`.

## Sensitive elements (must be marked and blurred)
| Screen | Element | Selector | Kind (email, name, amount, token, other) |
|---|---|---|---|
| Header (every screen, sticky) | Signed-in email pill ("Signed in as …") | `[data-testid=signed-in-pill]` (email text in `#user-email`) | email |
| Trends → Creator dashboard | API key | `[data-testid=api-key]` (`#api-key`; whole panel `[data-testid=creator-dashboard]`) | token |

Both carry `data-sensitive="true"`; both values are fictional (data.js) but per `privacy.blur` they are blurred, not replaced. Generic query for all: `[data-sensitive="true"]`.
Not marked sensitive: creator handles on cards/modal (`@pixel_harbor`, …) are fictional brand-style handles, not personal data. Downstream may treat them as `name` if QA prefers.

## Risks
- Pill is in frame in every scene (sticky header, also dimmed but readable under the modal backdrop): must be `sensitive`-marked at every `scene_start` and after every scroll/resize. Alternative: crop/frame the header out (motion-designer) — blurring is the default.
- API key exposure: with the chart scrolled to the top (block:start) the dashboard heading is at y 661 and the key at ~y 750 (just off a 720 px viewport); any taller viewport, `scrollIntoView` with `block:nearest/center`, or scrolling chart → genres brings the key into frame. Scenes passing through must mark `[data-testid=api-key]`; simplest is to jump to genres with `#genres` / `scrollIntoView({block:'start'})` on `section-genres` (dashboard then above the fold at y −124) and still mark it during the scroll.
- Smooth scrolling (CSS) makes scroll timing non-instant: wait on element position, not fixed sleeps; or use `scrollIntoView` and wait ~900 ms.
- Modal height at 1280x720: card is 680 px tall with 49 px internal scroll; "Why it trends" clipped. Use a viewport ≥ 1280x800 or scroll `.modal-card` before the Why beat.
- Filter animation 260 ms; respect it before the next action (wait for `#count` text). `prefers-reduced-motion` disables it.
- Hero CTA jumps past the Trending grid straight to Trends; storyboard must scroll back up (or use nav `a[href="#trending"]`) if the chip/modal scene follows the CTA.
- No popups, notifications, auth walls, network calls or rate limits. All figures are sample data (footer note, chart caption).
