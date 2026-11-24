# SVG craft

How to write an SVG that passes `render.mjs --art` and looks the same in the PNG. Checks that enforce it: P2, P5, Q2, Q5, Q7 (`checks.md`).

## Skeleton
```svg
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640">
  <rect width="1280" height="640" fill="#0B1020"/>
  <text x="64" y="220" font-family="'Inter','Segoe UI','Helvetica Neue',Arial,'Liberation Sans','DejaVu Sans',sans-serif"
        font-size="88" font-weight="700" fill="#FFFFFF">Product name</text>
</svg>
```
- `width` and `height` are plain pixel numbers equal to the id's size (no `%`, no units mismatch); `viewBox` equals `0 0 W H`. The top layer is checked against `--size`.
- First element is a full-canvas `rect` in `bg`, so the PNG is opaque. Exception: `art/thumb.svg` draws `bg` only outside the window (use a path with an even-odd hole, `fill-rule="evenodd"`), leaving the window transparent.
- Add `<title>` and `<desc>` with the image's alt text (they are text nodes: they are audited like any other text, P1, and need no `from` entry unless shown).

## Allowed vs rejected by the lint (E13, E18)
| Allowed | Rejected (exit 2) |
|---|---|
| shapes, `path`, `text`, `tspan`, `g`, `defs`, `linearGradient`/`radialGradient`, `pattern`, `clipPath`, `marker`, `use`, filters `feDropShadow` and `feGaussianBlur` (background shapes only) | `<script`, any `on*=` attribute, `<foreignObject>`, `<image>` (logos, screenshots, any raster) |
| `fill="url(#id)"`, `marker-end="url(#id)"`, `<use href="#id">` | `href` / `xlink:href` / `url(` pointing anywhere except `#id` or `data:font/*` (so also `<a href>`, `http(s):`, `file:`, `data:image/*`, `data:image/svg+xml`) |
| `style` and `<style>` with local rules | `@import`, `style="...url(http..)"` |
| `@font-face` with a `data:font/*` source (only for a missing script) | external fonts, web fonts |
- Write attributes literally. Do not entity-encode (`&#x6F;nclick`) or case-vary to dodge the lint: such input is rejected or flagged as P5.
- Never `backdrop-filter` or CSS `blur()` on text or panels: both leak in headless Chrome (`CLAUDE.md`). Fake glass with a blurred duplicate of the background clipped to the panel (`clipPath`). Gradients stay inside the opaque background (no gradient to transparent); no raster texture (grain, noise, paper).
- No logos in v1: the product name is `<text>` in the sans stack. A logo request is declined (E18); an `<image>` or `data:image/*` found by privacy is a blocker for art-designer, never an accepted logo.

## Text
- Use `<text>` with explicit `x`/`y`; one `<tspan>` per wrapped line (no automatic wrapping in SVG). Compute wraps with the 0.60 em budget (`typography.md`).
- `text-anchor="end"` and `direction="rtl"` for RTL scripts; `dominant-baseline` is avoided (differs across renderers): position by `y` baseline.
- No `textLength`/`lengthAdjust` to squeeze text; shorten or step down instead (overflow order, `typography.md`).
- SVG loaded as an image cannot fetch fonts, so rendering uses installed system fonts: PNG and SVG can differ in width (E6). Keep a 10% width slack and check Q7.

## Verify
1. `node .demo/remotion/render.mjs --art --size WxH --layer art/<id>.svg --out art/<id>.png --check-only` prints `{ok:true, mode:"art", w, h, layers}`; exit 2 means fix the SVG.
2. Run without `--check-only`; `w`/`h` in the JSON come from the PNG IHDR and must equal the size.
3. View the PNG (squint test), compare text against the SVG (Q7).
4. For `art/thumb.png` preview: render `art/thumb.svg` alone with `--bg <style bg hex>` (`#0B1020` when `#art.style` is null); never `--bg transparent` (no delivered file uses it).

## Sources
Contract: `remotion/render.mjs --art` (README, `motion-fx` CLI section). An SVG used as an image does not run script or load resources (browser behavior, `unverified` in this environment); the lint is the enforced rule, not that behavior.
