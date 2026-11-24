# Color

Checks that enforce it: Q2, Q3 (`checks.md`).

## Tokens (default palette = `TitleCard` colors in `remotion/src/effects.tsx`)
| Token | Hex | Use |
|---|---|---|
| `bg` | `#0B1020` | opaque full-bleed background |
| `surface` | `#151B2E` | cards, nodes |
| `border` | `#2A3352` | 2 px node/card outline; 1 px image edge |
| `text` | `#FFFFFF` | titles |
| `text-muted` | `#B8C0D9` | sublines, labels |
| `accent` | `#FFC83D` | gates, CTA, one highlight per image |
| `accent-ink` | `#0B1020` | text on `accent` |

## Brand colors
Use them only when `brief.md` or the source doc states them as hex. A stated brand color replaces `accent` (and `bg` if given). A brand color that fails the ratios below is used only as a shape, never under text. No brand color stated -> default palette; never guess a brand color from the product name.

## Ratios (WCAG 2.2 AA; large-text threshold tightened)
| Element | Ratio | Against |
|---|---|---|
| Text under 40 px bold | >= 4.5:1 | the actual pixels behind it |
| Text >= 40 px and weight 700 | >= 3:1 | same |
| Non-text marks that carry meaning (arrows, gate diamonds, node outlines when they are the only boundary) | >= 3:1 | adjacent colors |
WCAG's own large-text line is 18 pt / 14 pt bold (about 24 px / 18.67 px); this project uses the higher bar (40 px bold) because images are downscaled on GitHub and in feeds. Images of text are not exempt from WCAG, and neither is the v1 wordmark (plain text).

## Computing a ratio
Relative luminance L = 0.2126 R + 0.7152 G + 0.0722 B, each channel c in [0,1] linearized: c <= 0.04045 ? c/12.92 : ((c+0.055)/1.055)^2.4. Ratio = (L1 + 0.05) / (L2 + 0.05), lighter L first.
Default pairs (computed with that formula): `text` on `bg` 18.9:1; `text-muted` on `bg` 10.4:1; `text-muted` on `surface` 9.4:1; `accent-ink` on `accent` 12.2:1. `border` on `bg` is 1.5:1, so it is decoration and never the sole carrier of meaning: a node must also differ from `bg` by its `surface` fill. Verify a non-default pair by computing it, not by eye.

## Background and transparency
- Every PNG has an opaque `bg`, so it reads the same in GitHub light and dark mode. No gradients to transparent.
- The only transparent area is the window in the source `art/thumb.svg`. Its preview `art/thumb.png` is rendered over `#0B1020`, and the delivered `media/thumb.png` is built by the packager from the frame layer; both are opaque (Q2).
- GitHub's docs say PNG transparency is supported but advise a solid background when unsure; this project always chooses solid.

## Sources
- W3C, Understanding SC 1.4.3 Contrast (Minimum): https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html (4.5:1 normal, 3:1 large; fetched 2026-11-24).
- WebAIM, Contrast and Color Accessibility: https://webaim.org/articles/contrast/ (AA 4.5:1 / 3:1, AAA 7:1 / 4.5:1; non-text 3:1; large = 18 pt or 14 pt bold; fetched 2026-11-24).
- GitHub Docs, Customizing your repository's social media preview: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview (transparency supported, solid background advised; fetched 2026-11-24).
