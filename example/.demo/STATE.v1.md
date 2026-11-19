# Demo studio state

- Slug: ai-video-trends-tour
- Pipeline: new
- Current step: done — pipeline new finished
- Gates: G1 approved (auto) · G2 approved (auto) · G3 approved (auto; QA PASS, Q-1..Q-10 logged as known)
- Tools approved: capture, voice-edge, captions, mix, blur, motion-basic, qa-ocr, package (user approved full ~625 MB)

## Steps
| # | Agent | Output | Status (todo/doing/done/blocked) | Note |
|---|---|---|---|---|
| 1 | toolsmith | .demo/.venv, toolkit.json | done | 8 features installed, --check ok |
| 2 | demo-strategist | brief.md, demo.yaml | done | G1 auto; director set motion basic, voice vi-VN-HoaiMyNeural, privacy.blur, install.approved |
| 3 | app-scout | app-map.md | done | 5 flows, 2 sensitive, viewport ≥1280x800 |
| 4 | storyboarder | storyboard.md | done | 4 scenes, 50 s, 104 words |
| 5 | scriptwriter | narration.md | done | 102 words vi |
| 6 | voice-producer | media/sNN.vo.wav, #voice | done | 34.2 s total; kept (narration unchanged) |
| 7 | scene-automator | scenes.web.* | done | dry-run PASS 2/2 @1280x720; adds prepare() contract |
| 8 | capture-operator | media/sNN.raw.*, #events | done | re-captured 1280x720 full-frame, 25 fps, #events v2 bbox_space |
| 9 | privacy-blurrer ∥ sync-editor | #blur, #timeline | done | blur v2 13 regions OCR-verified; timeline v2 37.62 s |
| 10 | motion-designer ∥ caption-writer ∥ sound-mixer | #motion, #captions, #mix | done | 14 effects; 11 cues; -14.1 LUFS |
| 12 | render-engineer | finals, #checks | done | re-render pass=true (captions v2) |
| 13 | demo-qa | qa.md | done | PASS, 10 minor (Q-1..Q-10) |
| 14 | packager | thumb.png, #delivery | done | vi title/chapters |

## Fix log
- 2026-11-19 captions cue 2 offset 220 ms → caption-writer → fixed (v2), re-render PASS
- 2026-11-19 grey padding in raw clips (Playwright recordVideo size>viewport) → capture-operator → fixed (720p honest); motion aborted
- 2026-11-19 VO 34.2 s vs 50 s cut → director set length_s 40 → storyboarder retime (voice kept: text unchanged, overriding diff)

## Next action
Done. Optional: /fix round for Q-1,Q-2,Q-3,Q-6 (see qa.md).
