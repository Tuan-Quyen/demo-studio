---
name: media-specs
description: Load when encoding, mixing, captioning, blurring or verifying a demo render (voice-producer, privacy-blurrer, caption-writer, sound-mixer, render-engineer, demo-qa). Encode specs, loudness, caption rules, file naming, the render-check thresholds (single source of truth) and measuring commands, plus the #blur #mix #captions #checks schemas.
---

# Media specs

## Encode
- Record 1440p (2560x1440 where the platform allows), downscale at render with `scale=1920:1080:flags=lanczos`.
- Outputs: 16:9 1920x1080, 9:16 1080x1920, 1:1 1080x1080. One encode, from raw clips + project.json (blur, motion, captions, mix applied in the same pass).
- H.264 High, yuv420p, 60 fps (`fps=60`; if the raw fps is lower note it in `#checks.outputs`), ~15-20 Mbps, AAC 48 kHz 192 kbps, `+faststart`:
```
ffmpeg -y <inputs/filtergraph> -c:v libx264 -preset slow -crf 18 -maxrate 20M -bufsize 40M -profile:v high -pix_fmt yuv420p -r 60 -c:a aac -b:a 192k -ar 48000 -movflags +faststart media/final-16x9.mp4
```
- Blur first in the graph (before scale/reframe) so bbox stay in recorded-frame pixels.

## Loudness
Target **-14 LUFS integrated, true peak <= -1 dBTP** (accept -14 +-1). Normalize the mix with two-pass `loudnorm=I=-14:TP=-1.5:LRA=11` (TP -1.5 leaves margin; `-ar 48000` explicitly since loudnorm upsamples). Ducking: `[music][vo]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400`, music ~ -20 dB under VO when not ducked, fade-in 500 ms / fade-out 1500 ms. VO peaks <= -3 dBFS before mixing.

## Captions
VTT (`media/final.vtt`) and SRT (`media/final.srt`); per language add `.<lang>` (`final.vi.vtt`). <= **42 characters per line, <= 2 lines**, 1-6 s per cue, <= 17 chars/s reading speed (soft). Break at phrases, never mid-word; text = narration text (spelling and punctuation as written). Cue start/end within **200 ms** of the VO timing. No speaker labels or sound tags unless asked. Burn-in only on request (`#captions.burn_in`).

## File naming
`<slug>` = lowercase ascii kebab-case. Scenes `sNN` (two digits). In `.demo/<slug>/media/`: `sNN.raw.webm` (non-web platforms may be `.mp4/.mov/.mkv`; `#events.clips` is authoritative), `sNN.vo.wav`, `final-16x9.mp4`, `final-9x16.mp4`, `final-1x1.mp4`, `final.vtt`, `final.srt`, `thumb.png`. Language variant: `final-16x9.<lang>.mp4`. No other intermediate videos are kept.

## Render checks (single source of truth)
| id | what | threshold | how measured | owner on fail |
|---|---|---|---|---|
| sync | rendered scene length vs timeline | drift <= 80 ms per scene | render-engineer knows each scene's cut points; `ffprobe` the final and compare scene durations/VO onsets with `#timeline` | sync-editor |
| loudness | integrated LUFS, true peak | -14 +-1 LUFS, <= -1 dBTP | `ffmpeg -nostats -i F -af ebur128=peak=true -f null -` (read summary `I:` and `True peak`) | sound-mixer |
| blur | readable text in blur regions | 0 | for each `#blur` region sample frames every 0.5 s plus first/last (output coordinates), OCR (feature `qa-ocr`) | privacy-blurrer |
| black | black frames not intended | none (>0.2 s) outside `allow.black` | `-vf blackdetect=d=0.2:pix_th=0.10 -an -f null -` | capture-operator |
| freeze | frozen video not intended | none (>=3 s) outside `allow.freeze` | `-vf freezedetect=n=-60dB:d=3 -an -f null -` | capture-operator |
| captions | chars/line, lines, timing | <= 42, <= 2, <= 200 ms | parse `final.vtt`, compare cue times with `#voice`/`#captions` word timing | caption-writer |
| length | total duration vs brief | +-10% | `ffprobe -v error -show_entries format=duration -of csv=p=0 F` | storyboarder |
Intentional black (fade through black, title cards) and deliberate holds (screen static while VO explains) are listed in `#checks.allow` (derived from `#motion` and the storyboard) and are not failures. Black/freeze are measured on the final render and tied to the nearest scene for blame. These values are starting points: change them only here.

Measuring snippets:
```
# loudness
ffmpeg -nostats -i media/final-16x9.mp4 -vn -af ebur128=peak=true -f null - 2>&1 | tail -n 14
# black + freeze in one pass
ffmpeg -i media/final-16x9.mp4 -vf "blackdetect=d=0.2:pix_th=0.10,freezedetect=n=-60dB:d=3" -an -f null - 2>&1 | grep -E "black_start|freeze_start"
# blur-region frame for OCR (output px; repeat per sample time T)
ffmpeg -y -ss T -i media/final-16x9.mp4 -frames:v 1 -vf crop=W:H:X:Y blur_check.png
```
Blur filter (static region; privacy-blurrer verifies one preview frame per region):
```
[0:v]split[a][b];[b]crop=W:H:X:Y,boxblur=lr=min(25\,H/4):lp=3[bl];[a][bl]overlay=X:Y:enable='between(t,T0,T1)'
# stronger, text-proof alternative: pixelate
[b]crop=W:H:X:Y,scale=iw/16:ih/16,scale=iw*16:ih*16:flags=neighbor[bl]
```
Moving regions (scroll) use per-frame `keyframes` and the OpenCV path (feature `blur`). If OCR still reads text, switch to pixelate or enlarge the padding.

## project.json schemas
Owned elsewhere, read here: **#voice** (voice-producer) `{engine, voice, language, scenes:[{id, file, duration_s, words}]}`; **#timeline** (sync-editor) `{scenes:[{id, clip, in, out, speed, pad_end, vo, start, end, drift_ms}], total_s}`. The sync check compares each rendered scene with `#timeline.scenes[].start/end`.

**#blur** (privacy-blurrer; coordinates in recorded-frame pixels of the scene clip, times ms on the final timeline):
```json
{"schema":1,"regions":[{"id":"b1","scene":"s03","t_start":4100,"t_end":9200,"bbox":[820,300,420,60],"pad":12,"margin_ms":150,"mode":"boxblur","strength":25,"source":"events:sensitive:customer email","keyframes":null,"preview":"logs/b1.png"}]}
```
Every `sensitive` marker in `#events` must be covered; `pad` px added on all sides; `margin_ms` before/after. `mode`: `boxblur|pixelate`.

**#mix** (sound-mixer):
```json
{"schema":1,"voice":{"gain_db":0},"music":{"file":"assets/music.mp3","license":"...","gain_db":-20,"fade_in_ms":500,"fade_out_ms":1500},"ducking":{"threshold":0.05,"ratio":8,"attack_ms":20,"release_ms":400},"target":{"lufs":-14,"tp_db":-1.5},"preview":{"lufs":-14.2,"tp_db":-1.8}}
```
`music` may be `null` (voice only).

**#captions** (caption-writer):
```json
{"schema":1,"lang":"en","burn_in":false,"max_chars":42,"max_lines":2,"cues":[{"i":1,"t_start":300,"t_end":2900,"lines":["Create an invoice","in three clicks."]}]}
```
Times ms on the final timeline.

**#checks** (render-engineer, written after render):
```json
{"schema":1,"outputs":{"16x9":{"file":"media/final-16x9.mp4","w":1920,"h":1080,"fps":60,"duration_s":84.2,"video_kbps":16800}},
 "allow":{"black":[[0,300]],"freeze":[]},
 "results":{"sync":{"pass":true,"measured_ms_max":42,"threshold_ms":80,"owner":"sync-editor","detail":""},
            "loudness":{"pass":true,"lufs":-14.1,"tp_db":-1.6,"owner":"sound-mixer","detail":""},
            "blur":{"pass":true,"regions_checked":3,"text_found":0,"owner":"privacy-blurrer","detail":""},
            "black":{"pass":true,"hits":[],"owner":"capture-operator","detail":""},
            "freeze":{"pass":true,"hits":[],"owner":"capture-operator","detail":""},
            "captions":{"pass":true,"max_chars":38,"max_offset_ms":120,"owner":"caption-writer","detail":""},
            "length":{"pass":true,"target_s":90,"actual_s":84.2,"delta_pct":-6.4,"owner":"storyboarder","detail":""}},
 "pass":true}
```
`pass` = all results pass. A failing result names the owner; the director routes the fix and reruns only dependent keys.
