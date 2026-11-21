---
name: media-specs
description: Load when writing edit.json, motion.json, captions.json or mix.json, or judging a final video (sync-editor, motion-designer, caption-writer, sound-mixer, render-engineer, demo-qa). Encode, loudness, caption rules, motion basics, file names.
---

# Media specs

Defaults come from `demo.yaml`; the numbers below are the usual values.

## Encode
- Output sizes: 16:9 1920x1080, 9:16 1080x1920, 1:1 1080x1080. fps = source fps (web recordings are 25 fps; never fake higher).
- H.264 High, yuv420p, AAC 48 kHz 192k, `+faststart`, CRF 18. `render.py` does this in one ffmpeg run per aspect; do not hand-write ffmpeg for the final.
- Every ffmpeg call you run yourself: `-nostdin` and a timeout.

## Loudness
Integrated -14 LUFS +-1, true peak <= -1 dBTP (render.py runs 2-pass `loudnorm`). VO peaks <= -3 dBFS before mixing. Music about -20 dB under the voice, fade in 0.5 s, out 1.5 s.

## Captions
`media/final.vtt` (burn in only if `captions.burn_in`). <= 42 chars per line, <= 2 lines, <= 17 chars/s, 1-6 s per cue, break at phrases. Text = written narration (not the lexicon spelling). Start within 200 ms of the spoken first word.

## Motion (keep it light)
- Cuts: trim dead start/end with `in_ms`/`out_ms`; every cut shows something new.
- Zoom: only on the element being discussed, scale 1.3-1.6, 1-2 s, at most 2 per scene, `center` in output pixels.
- Title card <= 3 s, end card = the CTA, 3 s. No transitions, no stock effects.
- `speed` 1.0; up to 1.5 only on waiting time, never on the voice.

## Files (`.demo/<slug>/media/`)
`sNN.raw.webm`, `sNN.vo.wav`, `final-16x9.mp4`, `final-9x16.mp4`, `final-1x1.mp4`, `final.vtt`. `<slug>` = lowercase kebab-case, scenes `sNN`.
