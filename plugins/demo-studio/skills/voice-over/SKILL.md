---
name: voice-over
description: Load when choosing a voice engine or voice, setting `voice` in demo.yaml, generating or measuring voice-over, fixing pronunciation (lexicon) or pacing, or when the user records their own voice (voice-producer, demo-director, scriptwriter). Engines, voice choice, lexicon, natural speech rates, `[pause]`, own-voice recording, VO output and sync consequences.
---

# Voice-over

Settings live in `demo.yaml` (`config.py --slug <slug> get voice`): `engine`, `name`, `language`, `rate`, `pitch`, `lexicon`. Never copy values elsewhere. Owner of the audio: voice-producer. Decisions are the user's; the director asks and records them.

## 1. Engines
| Engine | Cost / key | Quality | Vietnamese | Toolkit feature | Settings |
|---|---|---|---|---|---|
| `edge` (default) | free, needs internet | good, neutral | `vi-VN-HoaiMyNeural` (warm female), `vi-VN-NamMinhNeural` (calm male) | `voice-edge` | `name`, `rate`, `pitch` |
| `kokoro` | free, offline, heavy (PyTorch) | good, fewer languages | check the voice list for `language`; else use `edge` | `voice-kokoro` | `name`, `rate` |
| `elevenlabs` | paid, key `ELEVENLABS_API_KEY` | most natural, emotional | multilingual model | `voice-elevenlabs` | `name` (voice id), `rate` |
| `recorded` | the user's own voice | the user's | any | none (ffmpeg via `capture`) | section 5 |

`rate` ("+0%", -30..+30%) is global; `pitch` ("+0Hz", -50..+50) is `edge` only. Cloning a voice only with the owner's written consent. OpenAI and Google TTS are not supported yet (no toolkit feature): do not offer them. API keys live only in environment variables, never in files, `demo.yaml`, briefs or chat; never print them.

## 2. Choosing
- Default by brief: no-budget Vietnamese demo -> `edge` (HoaiMy, or NamMinh for a calm technical tone); premium or emotional launch -> `elevenlabs`; founder/personal story -> `recorded`.
- One voice per video. Match gender and tone to the brief's audience and tone.
- Ask the user (options, recommended default), then the director records the answer in `demo.yaml`; a paid engine also needs the install-approval flow in `run-kits`.

## 3. Pronunciation lexicon
`voice.lexicon` maps a written term to its spoken spelling. It changes the **TTS input only**: whole word, case-sensitive, longest match first, done by `config.py --slug <slug> apply-lexicon (--text|--file|stdin) [--json]` (returns the text and an `applied` list; never substitute by hand). `narration.md` and captions keep the written text; caption-writer aligns to it.
- Before TTS scan the narration for terms likely mispronounced in `voice.language`: English words and brands in a non-English narration, acronyms, numbers, money, dates, domains, abbreviations. A term not in the lexicon -> `needs-input` with proposed entries (term -> spelling) and a default; the director asks the user (auto mode may approve) and records them. Never invent spellings silently.
- Examples (`vi`): `AI` -> `ây ai`, `YouTube` -> `du túp`, `UI` -> `diu ai`, `URL` -> `diu a eo`, `1.250.000 ₫` -> `một triệu hai trăm năm mươi nghìn đồng`, `example.com` -> `example chấm com`. Suggestions only, never auto-applied.
- Test tricky terms on one scene first. After TTS transcribe the scene (faster-whisper, feature `captions`): this round-trip only catches gross errors, because whisper writes "AI" (or the written form) for any pronunciation of an acronym or loanword. So for each lexicon-candidate term voice-producer also cuts a <= 3 s preview to `media/preview/lex-<term>.wav` and lists it in the handoff; the director asks the user to listen (auto mode: accept and log the term as unverified in STATE.md).
- Still wrong after the lexicon -> `needs-input` proposing a rephrase to scriptwriter. Never edit `narration.md`.

## 4. Pacing
| language | natural words/s |
|---|---|
| `en` | 2.4-2.6 |
| `vi` | 2.8-3.0 (measured: `edge` HoaiMy ~2.9-3.0 incl. pauses) |

Budget: `demo-storytelling` (rate en 2.5, vi 3.0, else 2.5; calibrate from `#voice` after the first scene). A scene whose **measured** words/s > 1.3x natural is rushed: flag it. Cut words (scriptwriter) rather than speed up. `voice.rate` is global: change it in steps of +-5% and re-measure. `[pause]` in `narration.md` inserts ~400 ms of silence between TTS chunks; captions ignore it. The measured VO decides lengths (rules in `demo-storytelling`).

## 5. Recording your own voice (`engine: recorded`)
Quiet room, close mic, pop filter, same distance and energy for every take. One 48 kHz WAV per scene at `.demo/<slug>/vo-src/sNN.wav`, about 0.3 s of silence at both ends. voice-producer cleans each file (`ffmpeg -af highpass=f=80,afftdn=nf=-25`), then normalises loudness to the `media-specs` targets, writes `media/sNN.vo.wav` and measures it like TTS. No lexicon (the speaker reads the written text); missing or unusable takes -> `needs-input` listing scene ids.

## 6. Output and measurement
`media/sNN.vo.wav` in the format of `media-specs`; `project.json#voice` shape in `media-specs` (project.json schemas, incl. `scenes[].lexicon_applied`). Durations come from `ffprobe`, not from the engine. Trim each file to leading <= 200 ms and trailing <= 150 ms silence (long tails force silent joins), record `lead_ms`/`trail_ms` in `#voice`, check clipping (peaks <= -3 dBFS).

## 7. Sync consequences
VO length drives scene length (`platform-automation` VO-pause rule). A narration, voice or lexicon change -> `config.py diff` -> voice -> timeline -> motion, captions, mix -> render (dependency order: `run-kits` §6; a lexicon change needs no G2). Do not re-record video because the VO changed unless a scene length moves beyond the storyboard's holds.

Adapted from the voiceover skill of DemoBuilder (https://github.com/quocthai179/DemoBuilder, MIT, (c) 2026 quocthai179).
