---
name: motion-fx
description: Load when choosing or designing motion effects or rendering them (demo-director asking the motion level and the render engine, motion-designer writing project.json#motion, render-engineer applying it). Render engines (Remotion default, ffmpeg fallback), levels none/basic/cinematic (the user's choice is `motion.level` in demo.yaml), effect recipes, safe areas, the motion schema.
---

# Motion FX

## Render engine (one per project, every pipeline)
| engine | feature | renders | cost |
|---|---|---|---|
| **Remotion** (default) | `remotion` (Node >= 18; plugin source `remotion/` copied to `.demo/remotion/`, `node_modules` + headless Chrome installed there) | every level: blur, zoom/pan, highlight, ripple, callout, title card, fade (dip and cross), device frame, reframe, burned-in captions, audio, in one pass | ~550 MB once per project, ~1-2x real time |
| ffmpeg (fallback) | `motion-basic` (ffmpeg from `capture`) | levels none and basic only: cuts, zoompan, drawbox, drawtext, fade, crop; moving blur via OpenCV (`blur`) | 0 MB |
Remotion is used unless `remotion` is in `install.declined` or `setup_tools.py --check remotion` is `blocked` (no Node >= 18); then the project falls back to ffmpeg and `cinematic` drops to `basic` (say so in the handoff). The decision is the engine available **before** motion-designer runs, never a retry after a failed Remotion render (that is `blocked`, owner render-engineer).

## Levels (what effects motion-designer writes; same on both engines unless noted)
| level | gives |
|---|---|
| A none | straight cuts between scenes (blur, captions, reframe still applied) |
| B basic | zoom to click, pan, fade, cursor/touch highlight (ring), title card, reframe |
| C cinematic | basic + ripple, callouts with arrows, spring-animated title cards and callouts, cross-fades, device frame (Remotion only) |

### Ask once per project (director, at G1)
1. Engine: if `remotion` is in neither `install.approved` nor `install.declined`, run `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --check remotion`; missing -> show `--plan remotion` (size, Node) and ask: **install Remotion (recommended)** / use the ffmpeg fallback (basic effects only). `blocked` (no Node) -> tell the user, use the fallback. Record the answer in `install.approved`/`install.declined`; toolsmith installs only after "install".
2. Level: read `config.py --slug <slug> get motion.level`; if null ask (AskUserQuestion) "What level of motion effects should the video have?": **A - None** (straight cuts) / **B - Basic** (zoom to clicks, fades, highlights) / **C - Cinematic** (adds ripple, callouts, animated titles; needs Remotion). Recommended default: B for short social clips, C for launch videos. Save `motion.level`.

## Effect recipes (all sources of truth are `#events` markers on the `#timeline`)
- **Zoom to click**: center on the click bbox center (clamp so the crop stays inside the frame), scale 1.5-2.0x (default 1.6), ease in/out cubic. In **500 ms** (frames at the output fps), finishing right at the click: start at `t_click - 500`. Hold until `t_click + 1000`, then ease out; if the next click is outside the zoomed window, ease out first. Skip zoom for targets already larger than ~40% of the frame. Zoom window vs `#blur` regions: clamp the window so blurred regions stay out of the crop only when the scale allows (the clamp is infeasible below ~1.11x); otherwise rely on blur-before-zoom (blur is applied first in the graph, so a zoomed region is already blurred).
- **Cursor/touch highlight**: ring sized from the **click point**, never from the element bbox (diameter ~56 px at 1080p output, scaled with the zoom factor; 3 px stroke, 40-60% fill) at the click point (bbox center), visible 250 ms before to 400 ms after the marker. Web clips already have an injected cursor dot: do not double it; desktop clips have the real cursor; mobile gets a touch circle (iOS and many Android recordings show none).
- **Ripple**: ring expanding 0 -> ~2x bbox over ~400 ms with fading opacity at the click time (level C; B uses highlight only).
- **Callout**: short label (<= 6 words) with an arrow, placed beside the bbox, never over the target or a `sensitive` region; shown 1.5-3 s; fade 150 ms.
- **Title card**: opening/ending cards <= 2.5 s, one line + optional subline; the CTA end card holds >= 3 s. Fade through black is an *intended* black: list it in `#checks.allow.black`. With key art (Remotion only): `params.image` = `art/title-<r>.png` (end card `art/end-<r>.png`, from `#art.items[].png`), one effect per ratio with `params.aspects:["<r>"]`, and the hold goes in `allow.freeze`; the image must exist under `.demo/<slug>/` (`render.mjs` exit 2 otherwise). No art, `png: null` or engine `ffmpeg`: the text card.
- **Device frame (mobile)**: generic bezel (no brand marks) around the 9:16 clip when the output is 16:9; screen scaled to fit, background solid or blurred copy. For 9:16 output of a mobile clip use the clip full-bleed.
- **Reframe (16:9 source -> 9:16 / 1:1)**: crop a window of the target aspect that follows the current focus (last click bbox), smoothed over ~500 ms; alternative: whole frame centered over a blurred copy. Blur regions are mapped through the same transform.
- **Fade**: 300 ms cross-fade between scenes only for image-like screens; for text-heavy screens use a hard cut or a dip through black <= 200 ms (a full dissolve of two text screens reads muddy). 150 ms fade for callouts; no wipes/spins. An end-card fade starts after the last spoken word of the previous scene (`#timeline.scenes[].vo.speech[1]`), never over speech. Remotion never plays footage outside a scene's `in`..`out` during a cross-fade: it holds the first / last selected frame (only those frames are privacy-checked).
- ffmpeg fallback (levels A/B): zoom with `zoompan=z='<expr of on>':x='<expr>':y='<expr>':d=1:s=1920x1080:fps=<output fps>` (per-frame expressions, `on` = output frame number; compose several zooms with `if(between(on,a,b),...)`); highlight with `drawbox=...:enable='between(t,a,b)'`; title with `drawtext` (needs a font file). Preview a 3 s sample first: zoompan can jitter on video.
- Remotion (default): the composition is plugin code, not written per project. Agents never edit `.demo/remotion/` (setup_tools overwrites it on re-sync); a missing effect or a renderer bug goes to the user as a plugin issue. One CLI, run from the project root:
```
node .demo/remotion/render.mjs --project .demo/<slug>/project.json --ratio 16x9|9x16|1x1 --out <file>
     [--audio .demo/<slug>/media/render/mix.wav] [--burn-in] [--layout overlay|band] [--level <motion.level>]
     [--from-ms A --to-ms B]   # preview range (motion-designer)
     [--still MS]              # one PNG frame (blur / effect check)
     [--props-only]            # print the normalized props, no render
node .demo/remotion/render.mjs --art --size WxH --layer <file.svg|png>[@X,Y,W,H] [--layer ...] --out <file>.png
     [--bg #RRGGBB|transparent]   # default #0B1020
     [--check-only]               # size, paths, SVG lint, PNG header; prints JSON, no render
```
  `--art` (raster mode) draws the layers bottom to top into ONE PNG (key art, thumbnail; rules in `key-art`). It needs no `project.json` and is refused with `--project`, `--still` or `--ratio`; `--size` is `WxH` in the allowed range; every layer and `--out` must sit inside the first layer's `.demo/<slug>/` folder; a layer covers the canvas, except a PNG written `FILE.png@X,Y,W,H`, drawn in that rect with its aspect kept (approved character assets, `key-art` P2; rect inside the canvas and no larger than the PNG, else exit 2); `--check-only` loads no Remotion. Exit 2 = bad data (size, path, SVG lint, placement), 1 = render failed.
  It reads `#timeline`, `#events.clips`, `#blur`, `#motion`, `#captions` (cues only with `--burn-in`), maps blur times to the final timeline (`media-specs` Spaces and time), applies blur on the source frame before zoom/reframe, and encodes per `media-specs` Encode (H.264 CRF 18, yuv420p, AAC 192k 48 kHz, fps = lowest clip fps) in one pass. stdout: one JSON line (`renderer`, `remotion` version, `w`, `h`, `fps`, `duration_s`); exit 0 ok, 1 render failed, 2 bad arguments or project data. Effects are drawn from their `params` exactly as in the `#motion` schema; unknown types are ignored, so only write the listed types.

## Safe areas (keep text, callouts, captions inside; fractions of width/height)
| aspect | size | margins |
|---|---|---|
| 16:9 | 1920x1080 | 5% all sides; captions bottom, above 8% |
| 9:16 | 1080x1920 | sides 6%, top 14%, bottom 20% (platform UI covers these) |
| 1:1 | 1080x1080 | 8% all sides |
Platform UI overlap values for 9:16 are conventions, tune per target platform.

## project.json#motion
Schema, spaces and time: `media-specs` (project.json schemas, Spaces and time). Effect `type` and `params` names are the ones in its example; times are ms on the **final timeline** (after sync-editor), coordinates in source-frame px of the scene's clip. Per-effect params: `zoom {center, scale, ease_in_ms, ease_out_ms, source_event}`, `cursor_highlight {bbox}`, `ripple {center}`, `callout {text, anchor, arrow_to}`, `title_card {title, subtitle, bg, image?}`, `fade {mode}`; map a marker to timeline time as in `media-specs` before placing an effect.
