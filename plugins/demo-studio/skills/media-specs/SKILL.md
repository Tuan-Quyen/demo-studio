---
name: media-specs
description: Load when encoding, mixing, captioning, blurring or verifying a demo render (voice-producer, privacy-blurrer, caption-writer, sound-mixer, render-engineer, demo-qa). Encode specs, loudness, caption rules, file naming, the default render-check thresholds (the user's values live in demo.yaml) and measuring commands, plus the #blur #mix #captions #checks schemas.
---

# Media specs

Tunable values (loudness, true peak, drift, caption width and offset, burn-in, formats, music, duck level) come from the project's `demo.yaml`: read with `python ${CLAUDE_PLUGIN_ROOT}/scripts/config.py --slug <slug> get <path>`. The numbers below are the **defaults** (the same ones the `demo.yaml` template ships); never hard-code them in an agent. Fixed values (codec, resolution, sample rate, tolerance of the length check) stay here.

## Encode
- Record at the largest native size the platform gives; the render scales to the output size (`scale=1920:1080:flags=lanczos`). Web: Playwright `recordVideo` size MUST equal the viewport (a larger size pads, it does not scale), so a web clip is the viewport size (default 1280x720) and render upscales; pick a larger viewport only if the app layout allows. Never claim 1440p for a clip `ffprobe` does not show as 1440p.
- Outputs: 16:9 1920x1080, 9:16 1080x1920, 1:1 1080x1080. One encode, from raw clips + project.json (blur, motion, captions, mix applied in the same pass).
- **fps = source fps.** Playwright `recordVideo` is capped at 25 fps, so a web raw is 25 fps and the output is 25 fps; never fake 60 by frame duplication. 60 fps output only when every raw clip is a real 60 fps recording (desktop/mobile recorders); clips with different fps: output at the lowest, resample only down. Record the real value in `#checks.outputs`.
- H.264 High, yuv420p, AAC 48 kHz 192 kbps, `+faststart`. **CRF governs quality; there is no bitrate target** (low-motion screen content is fine far below 10 Mbps); `-maxrate` is only a safety cap:
```
ffmpeg -y <inputs/filtergraph> -c:v libx264 -preset slow -crf 18 -maxrate 20M -bufsize 40M -profile:v high -pix_fmt yuv420p -r <source fps> -c:a aac -b:a 192k -ar 48000 -movflags +faststart media/final-16x9.mp4
```
- Blur first in the graph (before scale/reframe) so bbox stay in source-frame pixels.

## Loudness
Target **`targets.lufs` integrated (default -14), true peak <= `targets.true_peak` dBTP (default -1)**, accept the target +-1 LUFS. Normalize the mix with two-pass `loudnorm=I=<targets.lufs>:TP=<true_peak - 0.5>:LRA=11` (default `I=-14:TP=-1.5`; the 0.5 dB leaves margin; `-ar 48000` explicitly since loudnorm upsamples). Ducking: `[music][vo]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400`, music `music.duck_db` (default -20) dB under VO when not ducked, fade-in 500 ms / fade-out 1500 ms. VO peaks <= -3 dBFS before mixing.

## Captions
VTT (`media/final.vtt`) and SRT (`media/final.srt`); per language add `.<lang>` (`final.vi.vtt`). <= **`captions.max_chars` characters per line (default 42), <= 2 lines**, 1-6 s per cue, <= 17 chars/s reading speed (soft). Break at phrases, never mid-word; text = narration text (spelling and punctuation as written). Every cue start within **`targets.caption_offset_ms` (default 200)** of the measured onset of its first word (see the captions check). Cue text aligns to the written narration in `voice.language` (`narration.<voice.language>.md` if it exists, else `narration.md`), never to the spoken (lexicon) spelling. No speaker labels or sound tags unless asked. Burn-in only when `captions.burn_in` is true (default false; read from demo.yaml, not stored in `#captions`). `captions.layout`: `overlay` = text over the picture at the cue `pos`; `band` = picture scaled to fit the width and aligned top, captions in the remaining bottom band (`#blur`/`#motion` coordinates go through the same scale).

## File naming
`<slug>` = lowercase ascii kebab-case. Scenes `sNN` (two digits). In `.demo/<slug>/media/`: `sNN.raw.webm` (non-web platforms may be `.mp4/.mov/.mkv`; `#events.clips` is authoritative), `sNN.vo.wav`, `final-16x9.mp4`, `final-9x16.mp4`, `final-1x1.mp4`, `final.vtt`, `final.srt`, `thumb.png` (1280x720 PNG). Language variant: `final-16x9.<lang>.mp4`. No other intermediate videos are kept.

## Delivery limits
Thumbnail `media/thumb.png` 1280x720 PNG (16:9, <= 2 MB). Title <= 100 characters, description <= 5000 characters. First chapter at 00:00.

## Render checks
Thresholds are the defaults; the project's `demo.yaml` overrides them (key in the threshold column). `#checks.results.*.threshold_*` records the value actually used.
| id | what | threshold (demo.yaml key, default) | how measured | owner on fail |
|---|---|---|---|---|
| vo | each `sNN.vo.wav` clean: lead <= 200, trail <= 150, gaps <= 500 ms except declared pauses; `#voice` fields present | `vo.py check <file> [--pause-ms N...]` exit 0 (run before mixing) | voice-producer |
| sync | rendered scene length vs timeline | drift <= `targets.max_drift_ms` (80) per scene | render-engineer knows each scene's cut points; `ffprobe` the final and compare scene durations/VO onsets with `#timeline` | sync-editor |
| loudness | integrated LUFS, true peak | `targets.lufs` (-14) +-1 LUFS, <= `targets.true_peak` (-1) dBTP | `ffmpeg -nostats -i F -af ebur128=peak=true -f null -` (read summary `I:` and `True peak`) | sound-mixer |
| blur | readable text in blur regions | 0 | for each `#blur` region OCR ROI crops (not full frames) every 0.5 s plus first/last and every frame in a tracked transit, mapped to output coordinates and final time per Spaces and time (feature `qa-ocr`); match the sensitive value's pattern, not a bare `@`; positive control on an unblurred crop | privacy-blurrer |
| black | black frames not intended | none (>0.2 s) outside `allow.black` | `-vf blackdetect=d=0.2:pix_th=0.10 -an -f null -` | capture-operator |
| freeze | frozen video not intended | none (>=3 s) outside `allow.freeze` | `-vf freezedetect=n=-60dB:d=3 -an -f null -` | capture-operator |
| captions | chars/line, lines, onset offset | <= `captions.max_chars` (42), <= 2 lines; **for EVERY cue** `|t_start - onset of its first word| <= targets.caption_offset_ms` (200) | parse `final.vtt`; measure each word onset in the final audio: 10 ms RMS window, onset = first window above -40 dBFS after a silence, merging silences < 150 ms; match cues to words by order in `narration.md`. Report the max over all cues and the count over the limit; one cue over = fail | caption-writer |
| length | total duration vs `length_s` | +-10% (fixed) | `ffprobe -v error -show_entries format=duration -of csv=p=0 F` | storyboarder |
Intentional black (fade through black, title cards) and deliberate holds (screen static while VO explains) are listed in `#checks.allow` (from `#motion.allow` and the storyboard) and are not failures. Black/freeze are measured on the final render and tied to the nearest scene for blame. `allow` spans must be per hold; if they cover > 30% of the duration the check is blind there: render-engineer puts the covered % in `detail`, and demo-qa samples frames inside allowed spans. Change a project's values in its `demo.yaml`; change the defaults here and in `templates/demo.yaml` together.

Measuring snippets:
```
# loudness
ffmpeg -nostats -i media/final-16x9.mp4 -vn -af ebur128=peak=true -f null - 2>&1 | tail -n 14
# black + freeze in one pass
ffmpeg -i media/final-16x9.mp4 -vf "blackdetect=d=0.2:pix_th=0.10,freezedetect=n=-60dB:d=3" -an -f null - 2>&1 | grep -E "black_start|freeze_start"
# blur-region frame for OCR (mapped output px; repeat per sample time T)
ffmpeg -y -ss T -i media/final-16x9.mp4 -frames:v 1 -vf crop=W:H:X:Y blur_check.png
```
Blur filter (static region; privacy-blurrer verifies one preview frame per region):
```
[0:v]split[a][b];[b]crop=W:H:X:Y,boxblur=lr=min(25\,H/4):lp=3[bl];[a][bl]overlay=X:Y:enable='between(t,T0,T1)'
# stronger, text-proof alternative: pixelate
[b]crop=W:H:X:Y,scale=iw/16:ih/16,scale=iw*16:ih*16:flags=neighbor[bl]
```
Moving regions (scroll) use per-frame `keyframes` and the OpenCV path (feature `blur`). If OCR still reads text, switch to pixelate or enlarge the padding.

## Voice lexicon
Pronunciation rules, `apply-lexicon` and starter entries: skill `voice-over`.

## Spaces and time (one rule per key)
| key | space | time | mapping to the final render |
|---|---|---|---|
| `#events` bbox | recorded frame px of the scene clip (`bbox_space`) | marker `t` = ms since `scene_start` | clip time = `t + clips[sid].offset_ms` |
| `#blur` | `space:"source"`: frame px of the scene clip | `time:"scene"`: ms since `scene_start` | final = `#timeline.scenes[sid].start + (t + offset_ms - in) / speed` |
| `#motion` | `space:"source"`: frame px of the scene clip | `time:"timeline"`: ms on the final timeline | none needed for time; the render maps coordinates through the same crop/scale/reframe as the clip |
| `#captions`, `#mix`, `#checks.allow` | n/a | ms on the final timeline | none |
`offset_ms` = clip time of `scene_start`; `#timeline` `in`/`out`/`start`/`end` are ms (`in`/`out` on the clip, `start`/`end` on the final timeline), `speed` a factor (1.0 = unchanged). Because `#blur` is scene-relative it does not depend on `#timeline` and runs in parallel with sync-editor.

## project.json schemas
Single source for every shape below; agents reference this section and never restate it. `schema` is always `1`.

**#events** (capture-operator; written per `platform-automation`): `{schema, platform, clips:{sid:{file,w,h,fps,scale,offset_ms,duration_ms}}, bbox_space:{unit:"px",frame:[w,h],scale,origin:[x,y]}, markers:[{t,scene,type,bbox,label}], retries}`; `t` is ms since `scene_start`.
**#voice** (voice-producer): `{engine, voice, language, scenes:[{id, file, duration_s, words, lead_ms, trail_ms, sentences:[{words,start_ms,end_ms}], words_per_s, pauses_ms:[400], lexicon_applied:[{term,spoken}]}]}` (`lead_ms`, `trail_ms`, `sentences` (scene-relative ms), `words_per_s`, `pauses_ms` (declared `[pause]` gaps, `[]` if none) are **mandatory**, measured after `vo.py join` + `trim`; a scene without them fails the `vo` check).
**#timeline** (sync-editor): `{scenes:[{id, clip, in, out, speed, pad_end, vo:{file, start, end, speech:[onset, offset]}, start, end, drift_ms}], total_s}`; ms as in the table above. `vo.start/end` = the trimmed VO file on the final timeline, `vo.speech` = first and last spoken ms (from `lead_ms`/`trail_ms`); end cards and fades key off `speech[1]`. The sync check compares each rendered scene with `scenes[].start/end`.

**#blur** (privacy-blurrer):
```json
{"schema":1,"space":"source","time":"scene","regions":[{"id":"b1","scene":"s03","t_start":4100,"t_end":9200,"bbox":[820,300,420,60],"pad":12,"margin_ms":150,"mode":"boxblur","strength":25,"source":"events:sensitive:customer email","keyframes":null,"preview":"logs/b1.png"}]}
```
Every `sensitive` marker in `#events` must be covered; `pad` px on all sides; `margin_ms` before/after. `mode`: `boxblur|pixelate`.

**#motion** (motion-designer; recipes in `motion-fx`):
```json
{"schema":1,"engine":"ffmpeg","level":"basic","space":"source","time":"timeline","allow":{"black":[[0,300]],"freeze":[]},
 "effects":[
  {"scene":"s02","type":"zoom","t_start":4200,"t_end":5700,"params":{"center":[1240,610],"scale":1.6,"ease_in_ms":500,"ease_out_ms":400,"source_event":"s02@4700"}},
  {"scene":"s02","type":"cursor_highlight","t_start":4450,"t_end":5100,"params":{"bbox":[1180,580,120,60]}},
  {"scene":"s02","type":"ripple","t_start":4700,"t_end":5100,"params":{"center":[1240,610]}},
  {"scene":"s02","type":"callout","t_start":6000,"t_end":8500,"params":{"text":"Pick a template","anchor":[900,300],"arrow_to":[1240,610]}},
  {"scene":null,"type":"title_card","t_start":0,"t_end":2500,"params":{"title":"Invoice in 60 seconds","subtitle":"","bg":"#0B1020"}},
  {"scene":"s02","type":"fade","t_start":12000,"t_end":12300,"params":{"mode":"cross"}}]}
```
`engine`: `ffmpeg|opencv|remotion|null` is a hint, not a contract (render-engineer records what it actually used in `#checks.outputs.<ratio>.renderer`); `level`: `none|basic|cinematic` (copied from `motion.level`; `none` -> `engine:null`, `effects:[]`). `type` in `zoom, pan, cursor_highlight, ripple, callout, title_card, fade, device_frame, reframe`. `allow` lists intentional black/freeze spans (ms, final timeline) for the checks. Optional `params.aspects` (e.g. `["9x16"]`) limits an effect to some outputs. Every effect derives from an `#events` marker or a storyboard camera note; none over a `#blur` region; effects the level cannot do are not written.

**#mix** (sound-mixer):
```json
{"schema":1,"voice":{"gain_db":0},"music":{"file":"assets/music.mp3","license":"...","gain_db":-20,"fade_in_ms":500,"fade_out_ms":1500},"ducking":{"threshold":0.05,"ratio":8,"attack_ms":20,"release_ms":400},"chain":"<complete audio filter_complex incl. make-up gain and limiter>","target":{"lufs":-14,"tp_db":-1.5},"preview":{"lufs":-14.2,"tp_db":-1.8}}
```
`music` may be `null` (voice only). `target.lufs` / `tp_db` from `demo.yaml` (`tp_db` = `targets.true_peak` - 0.5); `music.gain_db` from `music.duck_db`. `chain` is the single source of the final audio: render-engineer runs it as-is; `preview` is that chain measured.

**#captions** (caption-writer; `lang`, `max_chars` from `voice.language`, `captions.max_chars`; `pos` = `bottom|top`; burn-in vs sidecar is read by render-engineer from demo.yaml `captions.burn_in`, never mirrored here; times ms on the final timeline):
```json
{"schema":1,"lang":"en","max_chars":42,"max_lines":2,"cues":[{"i":1,"scene":"s01","t_start":300,"t_end":2900,"pos":"bottom","lines":["Create an invoice","in three clicks."]}]}
```

**#checks** (render-engineer, after render; every result carries its `owner`):
```json
{"schema":1,"outputs":{"16x9":{"file":"media/final-16x9.mp4","w":1920,"h":1080,"fps":25,"duration_s":84.2,"video_kbps":2400,"renderer":"ffmpeg"}},
 "allow":{"black":[[0,300]],"freeze":[]},
 "results":{"sync":{"pass":true,"measured_ms_max":42,"threshold_ms":80,"owner":"sync-editor","detail":""},
            "vo":{"pass":true,"scenes_checked":4,"failures":[],"owner":"voice-producer","detail":""},
            "loudness":{"pass":true,"lufs":-14.1,"tp_db":-1.6,"owner":"sound-mixer","detail":""},
            "blur":{"pass":true,"regions_checked":3,"text_found":0,"owner":"privacy-blurrer","detail":""},
            "black":{"pass":true,"hits":[],"owner":"capture-operator","detail":""},
            "freeze":{"pass":true,"hits":[],"owner":"capture-operator","detail":""},
            "captions":{"pass":true,"max_chars":38,"cues":24,"cues_over_offset":0,"max_offset_ms":120,"owner":"caption-writer","detail":""},
            "length":{"pass":true,"target_s":90,"actual_s":84.2,"delta_pct":-6.4,"owner":"storyboarder","detail":""}},
 "pass":true}
```
`pass` = all results pass. `allow` = `#motion.allow` plus deliberate holds from the storyboard. A failing result names the owner; the director routes the fix and reruns only dependent keys.
