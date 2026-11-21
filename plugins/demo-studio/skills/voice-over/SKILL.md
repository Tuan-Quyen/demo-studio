---
name: voice-over
description: Load when choosing a voice engine, producing voice-over with vo.py, fixing pronunciation or pacing, or using the user's own recording (voice-producer, scriptwriter, localizer, demo-director).
---

# Voice-over

Settings are in `demo.yaml` `voice`: `engine`, `name`, `rate`, `language`, `lexicon`. The user decides; the director records.

## Engines
| Engine | Cost | Notes |
|---|---|---|
| `edge` (default) | free, internet | good; Vietnamese `vi-VN-NamMinhNeural` (calm male), `vi-VN-HoaiMyNeural` (warm female) |
| `kokoro` | free, offline, heavy | fewer languages |
| `elevenlabs` | paid, `ELEVENLABS_API_KEY` in env only | most natural; cloning needs the speaker's written consent |
| `recorded` | the user's voice | one 48 kHz WAV per scene at `vo-src/sNN.wav`, ~0.3 s silence each end |

`setup_tools.py --options voice` shows status. Never put keys in files or chat. One voice per video. `rate`: edge `en` voices -5..-10%, `vi` +0%; if too fast cut words, not speed.

## Producing (voice-producer)
- One sentence per TTS call, then join with the helpers (never hand-roll trimming):
  - `vo.py trim IN OUT --lead-ms 200 --trail-ms 150`
  - `vo.py join OUT IN1 IN2 ... --gap-ms 300 --edge-ms 50` (a `[pause]` = 400 ms gap)
  - `vo.py check FILE --pause-ms 400` (one per `[pause]`; exit 1 = fail)
- Output `media/sNN.vo.wav`, 48 kHz; measure duration with `ffprobe`. Peaks <= -3 dBFS.
- Report each scene's duration so scene-automator paces actions to it.

## Pronunciation
`voice.lexicon` maps written term -> spoken spelling (whole word, case-sensitive, TTS input only; captions keep the written text). Before TTS scan for acronyms, brands, numbers, money, dates, domains in the voice language. Unknown terms: ask the director with proposed spellings and a default; never invent silently. Vietnamese examples: `AI` -> `ây ai`, `YouTube` -> `du túp`. Test tricky terms on one scene first.

## Pacing
Natural words/s: `en` 2.4-2.6, `vi` 2.8-3.0. A scene over 1.3x natural is rushed: scriptwriter cuts or splits words. A scene over its budget by >10%: scriptwriter cuts words. `rate` is global; change in 5% steps.
