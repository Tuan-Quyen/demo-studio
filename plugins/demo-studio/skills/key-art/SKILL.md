---
name: key-art
description: Load when making or checking marketing images (art-designer writing SVG + PNG key art, privacy auditing art, demo-qa verifying art). The single home of the visual rules for title/end cards, thumbnail art, hero, social, pipeline and roster images: composition, typography, color, formats and sizes, SVG craft for `render.mjs --art`, the style catalogue, and the one check list P1-P5 / Q1-Q10.
---

# Key art

Visual rules for static marketing images. Schemas (`project.json#art`, `#privacy`, `title_card.params.image`, `#delivery.thumb_ms`) live in `media-specs`; the render command contract is `render.mjs --art` (README / `motion-fx`). No visual rule lives in an agent file: agents load this skill and follow it.

## Who loads what
| Agent | Loads |
|---|---|
| art-designer | this file + all references, incl. `references/styles.md` (whole file) |
| demo-director (style question) | `references/styles.md`: the `## Picker` section and the keyword tables only |
| privacy (art audit) | `references/checks.md` (P1-P5 only) |
| demo-qa (art mode) | `references/checks.md` (Q1-Q10), `references/formats.md` for sizes, `references/styles.md` hints and core recipes for Q10 |
| packager (thumbnail) | `references/formats.md` (thumbnail rows) + `references/checks.md` (Q2, Q8, P3) |

The style rules (recipes, palettes, stacks, grids, effects, combination and recommendation rules) live only in `references/styles.md`. An agent, command or README names the file and the codes; it never restates a style rule.

## References
| File | Holds | Sources it cites |
|---|---|---|
| `references/composition.md` | hierarchy, one focal point, grid, safe areas, whitespace | Figma design principles; opentextbc graphic design ch.3 |
| `references/typography.md` | font stacks, scale, text limits, overflow order, RTL/CJK | WCAG 2.2 contrast-minimum; opentextbc ch.3 |
| `references/color.md` | tokens, brand colors, contrast formula and ratios, opaque background | WCAG 2.2 contrast-minimum; WebAIM contrast; GitHub social preview docs |
| `references/formats.md` | every image id, size, role, file budget, thumbnail layer model | GitHub social-media-preview docs |
| `references/svg-craft.md` | how to write an SVG that passes the `--art` lint and renders the same in PNG | project contract (`render.mjs --art`) |
| `references/styles.md` | style catalogue: keyword codes A-G, core recipes, combination and recommendation rules, picker copy, sources | external sources cited per row (S1-S29) and project-own S0 |
| `references/checks.md` | the only check list: P1-P5, Q1-Q10, which file gets which check, copy rules, squint test | all of the above |

## Mandatory rules (one line each; details in the references)
1. Every string traces to a source (`texts[].from` = repo file path + line or anchor). Never invent a count, version, claim or name. A missing fact is omitted, not guessed (`checks.md` Q1).
2. No raster in v1: no image, screenshot or logo inside any SVG; vector illustration (shapes, paths, characters) is allowed; the product name is a text wordmark (`svg-craft.md`, P2).
3. Opaque background in every PNG. Only the source layer `art/thumb.svg` may hold a transparent window (`formats.md`, Q2).
4. System font stacks only; text widths budgeted for the widest fallback; no web fonts, no `@import` (`typography.md`).
5. Minimum text size is one rule, stated once in `checks.md` (Q4): 16 px native in video art, 22 px native in README images.
6. Contrast is measured on the pixels behind the text, never assumed from tokens (`color.md`, Q3).
7. Private data is removed, never faked (P1); no text, arrow or shape over a blurred region (P4).
8. One focal element per image; the accent color marks one idea (`composition.md`; squint test in `checks.md`).
9. SVG `width`/`height` equal the delivered PNG size exactly, and `render.mjs --art --check-only` passes before any render (`svg-craft.md`).
10. Check IDs are the contract: findings name an ID (P1-P5, Q1-Q10); nobody restates a check's content elsewhere.

## Workflow (art-designer)
1. Read the source (`brief.md` + `localization.md`, or the standalone source doc). Missing, empty or no product name -> `needs-input` (nothing generated).
2. Pick the ids and sizes for the run (`formats.md`); build the copy deck: each string with its `from`, within the text limits (`typography.md`).
3. Apply `#art.style` when set: resolve its codes into one recipe through `styles.md` (the brief carries the confirmed codes; never ask the user). Key-art rules win over a style on conflict; record the fix in `style.adjusted`. Then lay out on the grid and safe areas (`composition.md`), apply tokens (`color.md`), write the SVG (`svg-craft.md`).
4. Run `--check-only`, then render each PNG; read the IHDR size from the JSON; view each PNG once (squint test, `checks.md`).
5. Self-check Q1-Q7, Q9 and Q10 on your own output before handing off; privacy and demo-qa run the formal pass.

## Declined in v1
Screenshots, logos, photos, raster textures (grain, noise, paper), animation, web fonts; gradients only inside an opaque background: decline with a one-line reason; `needs-input` only when the source cannot be served without one.
