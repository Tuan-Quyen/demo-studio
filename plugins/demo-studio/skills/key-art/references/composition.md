# Composition

Applies to every image id in `formats.md`. Checks that enforce it: Q5, Q6 (`checks.md`).

## Principles used (named as in Figma's graphic design principles and opentextbc ch.3)
| Principle | Rule here |
|---|---|
| Hierarchy / emphasis | One primary element per image (product name, CTA, or diagram heading). Size ratio primary : secondary >= 2:1. It must survive the squint test. |
| Contrast | Primary vs background by size and weight first, color second. Weight 700 titles, 600 labels, 400 sublines. |
| Alignment | One left edge per text column (or one center axis on title/end cards). No third alignment axis. |
| Proximity | Group a title with its subline (gap <= 0.5 x subline size); separate groups by >= 2 x that gap. |
| Repetition | Same node shape, outline, radius and arrow style across one diagram; same card style across a roster. |
| White space | At least the safe-area margin around everything; leave empty space rather than shrink text below the minimum (Q4). |
| Balance | Text block left, visual right (hero, thumbnail); mirrored for RTL languages. |

## One accent rule
`accent` marks exactly one idea per image: a CTA pill, the gates, or one highlight. If two unrelated things are accent-colored, neither is emphasized.

## Grid and safe areas
| Image | Margins and grid |
|---|---|
| Video title / end card 16:9 (1920x1080) | 5% all sides; title block centered vertically in the safe area |
| 9:16 (1080x1920) | sides 6%, top 14%, bottom 20% (platform UI covers these) |
| 1:1 (1080x1080) | 8% all sides |
| End card | CTA line as an `accent` pill below the title |
| Thumbnail art 1280x720 | 5% margins; left ~55% text on opaque `bg`; right ~45% is the transparent window (12 px radius, 1 px `border` stroke drawn in the SVG); bottom-right 22% x 16% stays empty (player duration badge) |
| Hero 1280x640 | 64 px sides, 56 px top/bottom; 12 columns, gutter 24; text cols 1-7, visual cols 8-12 |
| Social 1200x630 | 60 px margins; all text inside the central 1000x480 (platform crops); one column, left-aligned |
| Pipeline 1280x720 | 64 px sides; heading band 0-120 px; content 136-680 px |
| Roster 1280x1600 | 64 px sides; heading band 0-120 px; content 136-1536 px (bottom margin = side margin 64 px); up to 14 roles: 2 columns of 466 px at x 64-530 and 750-1216, row pitch 160; 15 or more roles: 3 columns of 368 px at x 64-432, 456-824 and 848-1216, row pitch 202 (7 rows hold 21; user decision 2026-11-25, 19-agent roster) |
Video margins mirror the `motion-fx` Safe areas table; if they ever differ, `motion-fx` wins for video cards.

## Diagram rules (pipeline, roster)
- Nodes: radius 10, 2 px `border`, fill `surface`; arrows 2 px `text-muted`; gates are `accent` diamonds with `accent-ink` text.
- Parallel stages stack inside one dashed 2 px `border` box with a label; order reads left to right, rows wrap at the right edge.
- A node label never exceeds its box at the widest-fallback budget (`typography.md`). If it would, step the size down or wrap to two lines; never abbreviate with a word not in the source.

## Thumbnail window
Nothing (text, arrow, shape) overlaps the window area, so nothing can sit over a blurred region (P4). The packager's frame layer covers the full canvas (`object-fit: cover`), so the window shows the matching crop of the frame, not a scaled frame; keep the window's aspect close to the right-hand crop of a 16:9 frame (designer confirm, qa N15).

## Sources
- Figma, "13 Graphic Design Principles + How To Apply Them": https://www.figma.com/resource-library/graphic-design-principles/ (fetched 2026-11-24; alignment, contrast, balance, hierarchy, white space, repetition, proximity, emphasis defined there).
- BCcampus / BCIT, Graphic Design and Print Production Fundamentals, ch.3 "Design Elements, Design Principles, and Compositional Organization" (3.3 compositional principles, 3.4 organizational principles incl. grids): https://opentextbc.ca/graphicdesign/chapter/3-3-organizational-principles/ . Direct fetch returned HTTP 403 at build time; chapter and section titles come from a search result and the section text was not read. Rules resting on it (grid, proximity) also appear in the Figma page.
- Numeric margins, gaps and ratios are this project's design decisions, not source claims.
