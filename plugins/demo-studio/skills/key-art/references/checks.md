# Checks (the only list)

P1-P5 are run by `privacy` (audit only: it reports, never edits `art/`). Q1-Q10 are run by `demo-qa` on the rendered PNG and the SVG. art-designer self-checks Q1-Q7, Q9, Q10. Every finding names its ID, the item id and the file. Nobody restates a check's content in an agent file, a command or the README: they cite the ID.

## Minimum text rule (stated once)
No text smaller than **16 px native** in any video art (title, end, thumbnail, video hero/social) and **22 px native** in README images (hero, pipeline, roster, social). Native = SVG user units at the image's own pixel size. README images display about 830 px wide, so 22 px is roughly 14 px on screen.

## Privacy checks (P)
| ID | Check | Fails when |
|---|---|---|
| P1 | No real personal data in any text, `<title>`, `<desc>` or attribute | an email, phone number, personal name, account/order ID, amount, token/key, local path, internal URL, or URL with a query appears, unless it is the product's own public name/URL from the source doc; also any `SENSITIVE` entry of `app-map.md` and `privacy.blur` terms (video runs) |
| P2 | No raster image or logo in any art SVG; the only raster in an art PNG is an approved character asset (`#art.assets`, placed by `places`) | an `<image>` element or any `data:image/*` exists in an SVG (a blocker, never an accepted logo); a placed PNG is not in `#art.assets`, its sha256 differs, or `assets.approved` is missing; with `assets.sheet`: `art/assets/sheet.png` sha256 differs from `sheet.sha256`, or `art_assets.py split` re-run on it (same roles and `sheet.flags`, into a temp dir) gives a different sha256 for any file; the sheet itself is placed; an asset shows a logo, screenshot, photo, or readable text (P1 applies to it) |
| P3 | Delivered `media/thumb.png`: blurred frame leaks nothing | a `sensitive` box in the frame is not blurred at rendered strength, or a crop edge shows unblurred pixels next to a blur; the frame came from a render pass that applies `#blur` |
| P4 | Nothing over a blurred region | text, arrow or shape overlaps the thumbnail window area or a blurred region |
| P5 | SVG is inert | `<script`, `on*=`, `<foreignObject>`, external `href`/`url(`/`@import` (the `--art` lint rejects these, E13; the audit is defence in depth) |
Method without OCR: read SVG text nodes and attributes from the file; view each PNG. Result goes to `#privacy.art` with the `art_version` audited. A private value is removed, never replaced by fake data.

## QA checks (Q)
| ID | Check | Fails when |
|---|---|---|
| Q1 | Every string traces to its source (copy rules below); no invented or stale fact | a `texts[].from` is missing, does not resolve, or the text is not in/derived from it; a count, version or claim is not true of the repo files now (E4) |
| Q2 | Exact pixel size per `formats.md` and opaque PNG | IHDR size differs from SVG/`#art` size, or any PNG pixel has alpha < 255. Only the source `art/thumb.svg` may hold a transparent window |
| Q3 | Contrast per `color.md`, measured on the actual pixels behind the text | below 4.5:1 for text under 40 px bold, 3:1 for >= 40 px bold text or meaningful marks |
| Q4 | Minimum text rule above | any text smaller than the floor for its image |
| Q5 | No clipped, overflowing or overlapping text; no tofu glyphs | any glyph cut by the canvas or a box, two text blocks overlap, or a missing-glyph box appears |
| Q6 | Text and key marks inside the safe areas (`composition.md`); thumbnail badge keep-out empty | anything outside the margins or in the badge area |
| Q7 | SVG and PNG show the same text and layout (E6); placed assets appear only in the PNG, at their `places` rect | different wording, wrapping, or a shift of more than the 10% width slack; a placed asset off its rect or over text |
| Q8 | File budgets (`formats.md`) | `media/thumb.png` > 2 MB, or `social`/`hero` PNG > 1 MB |
| Q9 | Spelling | any on-art string misspelled in its language (source spelling of names and terms kept as written) |
| Q10 | Style conformance to the resolved recipe (`styles.md`); applies only when `#art.style` is not null, else n/a | an item's background or accent family is not the `core` recipe + D code + `custom` (after the `adjusted` entries); its font stack is not the E code's (or the recipe's); its characters are missing, off the `characters.md` model or smaller than its sizes, or not in the recipe treatment; the F code's grid is not used; the G code's effect is missing; or items of one run disagree on palette or type. An `approximated` entry is not a finding; a key-art rule (Q1-Q9, P1-P5) beats the style |

## Which file gets which check (KART-AC24)
| File | Checks | Not |
|---|---|---|
| `art/thumb.svg` (layer, transparent window) | P1, P2, P4, P5, Q1, Q3-Q7, Q9, Q10 (no bg: stack, accent and effect only) | Q2, Q8 (it is not a PNG) |
| `art/thumb.png` (preview on the style `bg`, `#0B1020` when `style` is null) | same as the SVG plus Q2 (opaque) and Q10 | Q8, P3 |
| `media/thumb.png` (packager, after G3) | Q2, Q8, P3 (text was checked on the layer) | |
| every other art SVG | P1, P2, P4, P5, Q1, Q3-Q7, Q9, Q10 | Q2, Q8, P3 |
| every other art PNG | the same plus Q2, and Q8 where a budget applies | P3 |
"All checks" means all that apply to the file (P3 is thumbnail only; Q8 only where a budget exists). Q10 is n/a for every file when `#art.style` is null or missing. `media/thumb.png` is not checked for Q10 (the packager builds it from a blurred frame). Without PNGs (`png: null`, E1), privacy and demo-qa audit the SVGs and state "PNG not checked" in the report.

## Copy rules (feeds Q1)
- `texts[].from` = a repo-relative file path plus a line or anchor (`README.md:3`, `agents/privacy.md#description`). Allowed files: `brief.md`, `localization.md`, the standalone source doc, or a repo file the source doc describes (`README.md`, `skills/run-kits/SKILL.md`, `agents/*.md`, `commands/*.md`). The path must exist and the anchor must hold the text.
- A shortened string uses words of the source line in source order only. A derived value (a count, a stage name taken from a list) is marked in `from` as `derived: <rule>` such as `derived: count agents/*.md`, and Q1 recomputes it from the files at check time.
- A count of agents equals the number of `agents/*.md` files now; a version equals `plugin.json`. A stale fact in the source (README "v0.1.0", "18 agents") is shown only if the code matches, otherwise omitted; demo-qa FAILs a stale one (E4).
- No source for a string -> omit it or `needs-input`. Never invent. Source holds private data (author email, local path) -> P1 FAIL; art-designer drops it (E14).
- Video `hero`/`social`: text from `brief.md` only.

## Squint test (art-designer self-check and demo-qa fit-to-brief)
View the PNG at about 25% scale (or blur it mentally): the primary element must be identifiable in under one second, the accent marks one idea, and the reading order is title, subline, then supporting items. Fail -> hierarchy problem (`composition.md`).

## Finding identity
A finding is identified by check ID + item id (`P1` + `social`). The same pair failing three rounds in a row goes to the user (run-kits rule); the director compares IDs across rounds.

## Sources
The checks apply: WCAG 2.2 SC 1.4.3 and WebAIM (Q3), GitHub social-media-preview docs (Q2, Q8 for 1280x640 and under 1 MB), Figma design principles and opentextbc ch.3 (squint test, Q5, Q6), see the cited URLs in `color.md`, `formats.md`, `composition.md`. P1-P5/Q1-Q9 numbering is seeded from the design list of the keyart-marketing item and extended with Q9; Q10 comes from the keyart-style item.
