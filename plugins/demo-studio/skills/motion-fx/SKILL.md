---
name: motion-fx
description: Load when choosing or designing motion effects (demo-director asking the motion level, motion-designer writing project.json#motion, render-engineer applying it). Levels none/basic/cinematic (the user's choice is `motion.level` in demo.yaml), effect recipes, safe areas, the motion schema.
---

# Motion FX

## Levels
| level | stack | gives | cost |
|---|---|---|---|
| A none | ffmpeg cuts | straight cuts between scenes | 0 MB |
| B basic | ffmpeg filters (feature `motion-basic`) | zoom to click, fade, cursor/touch highlight (box/ring), title card (drawtext), reframe | 0 MB, fast |
| C cinematic | Remotion (feature `motion-cinematic`, Node >= 18, project in `.demo/remotion/`) | eased zoom, ripple, callouts, animated title cards and captions, device frame | ~400 MB, slower render |

### Ask before installing (director, once per video)
1. Read `config.py --slug <slug> get motion.level`; if not null, do not ask.
2. Else run `python ${CLAUDE_PLUGIN_ROOT}/scripts/setup_tools.py --check motion-cinematic` and `--plan motion-cinematic`.
3. Ask (AskUserQuestion) "What level of motion effects should the video have?" with options:
   - **A - None**: straight cuts, nothing to install.
   - **B - Basic (ffmpeg)**: zoom to clicks, fades, highlights; +0 MB.
   - **C - Cinematic (Remotion)**: eased zoom, ripple, callouts, title cards; +~400 MB, needs Node >= 18. Recommend for launch videos.
   Put the `--plan` output (what gets installed, size) in the question. Recommended default: B for short social clips, C for launch videos.
4. Director saves the answer to `demo.yaml` (`motion.level`, and `install.approved`/`install.declined`). Install only after the user chose C (toolsmith runs `--install motion-cinematic`). Declined/failed install -> fall back to B and say so in the handoff.

## Effect recipes (all sources of truth are `#events` markers on the `#timeline`)
- **Zoom to click**: center on the click bbox center (clamp so the crop stays inside the frame), scale 1.5-2.0x (default 1.6), ease in/out cubic. In **500 ms** (frames at the output fps), finishing right at the click: start at `t_click - 500`. Hold until `t_click + 1000`, then ease out; if the next click is outside the zoomed window, ease out first. Skip zoom for targets already larger than ~40% of the frame.
- **Cursor/touch highlight**: ring (diameter ~ 1.4x bbox min side, 3 px stroke, 40-60% fill) at the bbox center, visible 250 ms before to 400 ms after the marker. Web clips already have an injected cursor dot: do not double it; desktop clips have the real cursor; mobile gets a touch circle (iOS and many Android recordings show none).
- **Ripple**: ring expanding 0 -> ~2x bbox over ~400 ms with fading opacity at the click time (level C; B uses highlight only).
- **Callout**: short label (<= 6 words) with an arrow, placed beside the bbox, never over the target or a `sensitive` region; shown 1.5-3 s; fade 150 ms.
- **Title card**: opening/ending cards <= 2.5 s, one line + optional subline; the CTA end card holds >= 3 s. Fade through black is an *intended* black: list it in `#checks.allow.black`.
- **Device frame (mobile)**: generic bezel (no brand marks) around the 9:16 clip when the output is 16:9; screen scaled to fit, background solid or blurred copy. For 9:16 output of a mobile clip use the clip full-bleed.
- **Reframe (16:9 source -> 9:16 / 1:1)**: crop a window of the target aspect that follows the current focus (last click bbox), smoothed over ~500 ms; alternative: whole frame centered over a blurred copy. Blur regions are mapped through the same transform.
- **Fade**: 300 ms between scenes (cross-fade) or 150 ms fade for callouts; no wipes/spins.
- ffmpeg basics (level B): zoom with `zoompan=z='<expr of on>':x='<expr>':y='<expr>':d=1:s=1920x1080:fps=<output fps>` (per-frame expressions, `on` = output frame number; compose several zooms with `if(between(on,a,b),...)`); highlight with `drawbox=...:enable='between(t,a,b)'`; title with `drawtext` (needs a font file). Preview a 3 s sample first: zoompan can jitter on video, and more than ~6 effects per scene means switch to level C.
- Remotion basics (level C): composition wraps `<OffthreadVideo src={staticFile(...)}/>`, reads `#motion` and `#events` as input props, drives zoom with `interpolate(frame,[f0,f0+Math.round(fps*0.5)],[1,z],{easing:Easing.inOut(Easing.cubic),extrapolateLeft:'clamp',extrapolateRight:'clamp'})` and pop-ins with `spring({frame,fps})`; render with `npx remotion render <entry> <comp-id> <out> --props=<file>` from `.demo/remotion/`. Blur still happens in the same render (overlay inside the composition) so there is no intermediate video file.

## Safe areas (keep text, callouts, captions inside; fractions of width/height)
| aspect | size | margins |
|---|---|---|
| 16:9 | 1920x1080 | 5% all sides; captions bottom, above 8% |
| 9:16 | 1080x1920 | sides 6%, top 14%, bottom 20% (platform UI covers these) |
| 1:1 | 1080x1080 | 8% all sides |
Platform UI overlap values for 9:16 are conventions, tune per target platform.

## project.json#motion
Schema, spaces and time: `media-specs` (project.json schemas, Spaces and time). Effect `type` and `params` names are the ones in its example; times are ms on the **final timeline** (after sync-editor), coordinates in source-frame px of the scene's clip. Per-effect params: `zoom {center, scale, ease_in_ms, ease_out_ms, source_event}`, `cursor_highlight {bbox}`, `ripple {center}`, `callout {text, anchor, arrow_to}`, `title_card {title, subtitle, bg}`, `fade {mode}`; map a marker to timeline time as in `media-specs` before placing an effect.
