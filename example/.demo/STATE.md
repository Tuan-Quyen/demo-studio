# Demo studio state

- Slug: ai-video-trends-v2 (base; v1 deleted by user request)
- Pipeline: fix — full app coverage (user: demo skips too much; add full grid + chips, trend cards, all 5 ranks, nav + CTA; length < 10 min)
- Current step: done — delivered (G3 approved by user 2026-11-19; minors M-1..M-4 accepted)
- Gates: G1 (auto) · G2 · G3 approved by user
- Tools approved: capture, voice-edge, captions, mix, blur, motion-basic, qa-ocr, package (installed, --check ok)

## Steps
| # | Agent | Output | Status | Note |
|---|---|---|---|---|
| 1 | toolsmith | toolkit | done | reused from v1 |
| 2 | demo-strategist | brief.md, demo.yaml | done | 45 s, ~99 words; G1 auto; director: motion basic, HoaiMy, privacy.blur, apply@G1 |
| 3 | app-scout | app-map.md | done | 5 flows, 2 sensitive, all verified |
| 4 | storyboarder | storyboard.md | done | retimed 38 s (7/6/9/6/10); G2 re-approved auto; s02/s04 6 s accepted |
| 5 | scriptwriter | narration.md | done | 93/97 words vi |
| 6 | voice-producer | media/sNN.vo.wav, #voice | done | 32.2 s; lexicon: AI round-trips raw, none proposed; s04 3.77 w/s accepted |
| 7 | scene-automator | scenes.web.* | done | dry-run PASS 3x; start states unchanged; Ctx inside scenes.web.py |
| 8 | capture-operator | media/sNN.raw.*, #events | done | 1280x720 full-frame (director spot-checked), no jump-to-top; s03/s04 tails → option A |
| 9 | privacy-blurrer ∥ sync-editor | #blur, #timeline | done | blur 5 regions OCR 0/78; timeline 35.04 s (accepted), joins ≤1.4 s |
| 10 | motion-designer ∥ caption-writer ∥ sound-mixer | #motion, #captions, #mix | done | 13 effects; 9 cues on onsets; -14.0 LUFS |
| 11 | render-engineer | finals, #checks | done | #checks v4 pass=true (after allow fix) |
| 12 | demo-qa | qa.md | done | PASS, 7 minor (Q-1..Q-7) |
| 13 | packager | thumb.png, #delivery | done | 5 vi chapters |

## Fix log
- 2026-11-19 freeze s02 8.32–11.84 deliberate → motion-designer allow → fixed, checks PASS
- 2026-11-19 VO 32.2 s vs 45 (−28.6%) → director length_s 45→38 (diff: storyboarder, timeline↓, no voice) → storyboarder retime

- 2026-11-19 full coverage: blur v2 (17 regions, OCR partial, API-key transit checked visually) → render → #checks v9 freeze 74280–74480 (deliberate hold) → motion v8 allow → #checks v10 pass; QA PASS, minors M-1..M-4 open
- 2026-11-19 G3 approved by user → config apply → packager: thumb (12 s grid), 10 en chapters, #delivery v2

## Next action
Next: user asked to fix M-1, M-2 and make title/intro introduce the product → s01 narration + title card → voice s01 → timeline (M-1) → motion ∥ captions ∥ mix → render → qa → G3.
