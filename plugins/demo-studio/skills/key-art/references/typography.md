# Typography

Checks that enforce it: Q3, Q4, Q5, Q9 (`checks.md`).

## Font stacks (same as `FONT` in `remotion/src/effects.tsx`)
- Sans: `'Inter','Segoe UI','Helvetica Neue',Arial,'Liberation Sans','DejaVu Sans',sans-serif`
- Mono: `ui-monospace,'Cascadia Mono',Consolas,'DejaVu Sans Mono','Liberation Mono',monospace`
- Serif (style code E4, `styles.md`): `Georgia,'Times New Roman','Liberation Serif','DejaVu Serif',serif`; budget 0.65 em per character (Georgia Bold measured 0.534 em, so 0.55 would leave about 3% headroom). A box W px wide holds at most W / (0.65 x size) characters.
- Inter is not assumed installed. The PNG is what ships, so budget text width for the widest fallback: sans 0.60 em per character, mono 0.62 em. A box W px wide holds at most W / (0.60 x size) sans characters.
- No web fonts, no `@import`, no external `url(` (the lint rejects them). Only a `data:font/*` base64 `@font-face` is allowed, and only for a script the stack lacks (tofu, Q5).
- Weights: 700 titles, 600 labels, 400 sublines. Line height 1.1 titles, 1.3 body.

## Scale (px, native)
| Image | Title | Subline | Label / CTA | Smallest used | Q4 floor |
|---|---|---|---|---|---|
| Video title/end 1920x1080, 1080x1080, 1080x1920 | 92 | 40 | 48 (CTA) | 32 | 16 |
| Video thumbnail 1280x720 | 96 | 44 | - | 40 | 16 |
| Video hero 1280x640 / social 1200x630 | 88 / 80 | 32 / 34 | 24 / 26 | 22 / 24 | 16 |
| README hero 1280x640 / social 1200x630 | 88 / 80 | 32 / 34 | 24 / 26 | 22 / 24 | 22 |
| README pipeline 1280x720 / roster 1280x1600 | 40 (heading) | 24 | 22 | 22 | 22 |
"Smallest used" is the design target; the Q4 floor is the pass/fail line. Why 22 px for README: GitHub shows README images about 830 px wide (x0.65), so 22 px lands near 14 px on screen.

## Text limits (source words only)
| Field | Max |
|---|---|
| Title / product name | 32 chars, 2 lines |
| Subline / tagline | 90 chars (hero), 70 (cards, social), 2 lines |
| Thumbnail title | 5 words, 28 chars |
| CTA | 30 chars, 1 line |
| Node / card label | 16 chars at 22 px in a 217 px card (0.60 em = 13.2 px per char, 211 px); anything longer wraps or steps down |

## Overflow order
1. Wrap to the allowed line count.
2. Step down one size on the scale, never below the Q4 floor.
3. Shorten by dropping words of the source sentence (never add words).
4. Still too long -> `needs-input` with the long string.
Checked on the PNG; nothing is clipped (Q5).

## Scripts
- RTL (ar, he, fa, ur): `direction="rtl"`, `text-anchor="end"`, mirror the grid (text right, visual left), arrows point right to left.
- CJK, Thai, Devanagari: title line height 1.3; halve the character budget for CJK; tofu glyphs -> embed a base64 font subset or `needs-input`; never ship tofu.
- Spelling: every on-art string spelled correctly in its own language; source spelling of names and terms kept as written (Q9).

## Size and contrast
WCAG 2.2 treats text as "large" at 18 pt (about 24 px) or 14 pt bold (about 18.67 px) and requires 3:1 for it, 4.5:1 otherwise; images of text are not exempt, logotype text is. The ratios applied here are in `color.md`.

## Sources
- W3C, Understanding SC 1.4.3 Contrast (Minimum), WCAG 2.2: https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html (fetched 2026-11-24: large text = 18 pt or 14 pt bold; images of text not exempt).
- BCcampus / BCIT, Graphic Design and Print Production Fundamentals, ch.3 (hierarchy through size and weight): https://opentextbc.ca/graphicdesign/chapter/3-3-organizational-principles/ (not read; HTTP 403, see `composition.md`).
- Character-width budgets, the scale and the limits are project decisions; 0.60 / 0.62 em are conservative estimates for the fallback fonts, `unverified` by measurement. The 0.65 em serif budget rests on one measurement of Georgia (System.Drawing, 2026-11-24); DejaVu Serif and Liberation Serif were not measured (`unverified`). The 22 px README floor assumes GitHub's ~830 px display width (`unverified`, observed convention).
