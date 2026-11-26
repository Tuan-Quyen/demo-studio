# Formats and sizes

Checks that enforce it: Q2, Q8 (`checks.md`). Record shape (`project.json#art`, ids, `missing_png`): `media-specs`.

## Image ids and sizes (px)
| Run | id | Size | Role | Notes |
|---|---|---|---|---|
| video | `title-16x9`, `end-16x9` | 1920x1080 | `title_card`, `end_card` | only ratios listed in `formats` of `demo.yaml` |
| video | `title-9x16`, `end-9x16` | 1080x1920 | same | idem |
| video | `title-1x1`, `end-1x1` | 1080x1080 | same | idem |
| video | `thumb` | 1280x720 | `thumbnail` | layer with a transparent window, see below |
| video | `hero` | 1280x640 | `hero` | text from `brief.md` only |
| video | `social` | 1200x630 | `social` | text from `brief.md` only |
| standalone | `hero` | 1280x640 | `hero` | from the source doc |
| standalone | `pipeline` | 1280x720 | `pipeline` | stage flow with gates |
| standalone | `roster` | 1280x1600 | `roster` | all agents by role; taller than the other ids (user decision, GA r2) |
| standalone | `social` | 1200x630 | `social` | from the source doc |
Files are `art/<id>.svg` + `art/<id>.png`. A ratio missing from `formats` gets no card; adding one produces that ratio's cards only.

## Size rules
- SVG `width` and `height` equal the id's size; the PNG IHDR read back by `render.mjs --art` equals it too (Q2).
- GitHub social preview: 1280x640 recommended, 640x320 minimum, PNG/JPG/GIF, under 1 MB. The `social` id (1200x630) is the open-graph size for other platforms; upload by the user, not by the team. The `hero` (1280x640) is the GitHub-recommended size.
- File budgets: delivered `media/thumb.png` <= 2 MB; `social` and `hero` PNGs <= 1 MB (GitHub's limit); typographic PNGs normally land far below. Over budget -> simplify the SVG (fewer shapes) or shrink the `places` rects of character assets, and re-render; if still over, `needs-input` (Q8). PNG has no quality knob.

## Thumbnail layer model
| File | What | Transparency |
|---|---|---|
| `art/thumb.svg` | overlay layer; text on the left, a transparent window on the right | window transparent (the only transparent area in any art file) |
| `art/thumb.png` | preview of the SVG rendered over the style `bg` (`--bg <hex>`; `#0B1020` when `#art.style` is null) | opaque |
| `media/thumb.png` | delivered file: packager composites a blurred frame (`--layer frame.png --layer art/thumb.svg`, default opaque `--bg`) | opaque, 1280x720, <= 2 MB |
- art-designer never builds `media/thumb.png`; the packager does, from a render-pass frame that applies `#blur`. The frame is always 16:9 whatever `formats` says; frame choice is the packager's rule (system design C7).
- The thumbnail keeps the bottom-right 22% x 16% empty (player duration badge) and puts nothing over the window (P4).

## Sources
- GitHub Docs, Customizing your repository's social media preview: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview (fetched 2026-11-24: PNG, JPG or GIF; under 1 MB; 640x320 minimum; 1280x640 recommended; PNG transparency supported).
- 1200x630 for `social`, the 2 MB thumbnail budget and the other sizes are project decisions (user 2026-11-24; `media-specs`), not claims of that page.
