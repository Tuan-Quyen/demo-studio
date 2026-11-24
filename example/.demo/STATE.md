# Demo studio state

- Slug: ai-video-trends-v2 (v1 deleted by user request)
- Pipeline: fix — full app coverage, English
- Current step: none — delivered 2026-11-19
- Gates: G1 approved (auto) · G2 approved (auto) · G3 approved (user, 2026-11-19)
- Tools approved: capture, voice-edge, captions, mix, blur, motion-basic, qa-ocr, package

## Steps
| # | Agent | Output | Status | Note |
|---|---|---|---|---|
| 1 | demo-strategist | brief.md, demo.yaml | done | full tour, length_s 105, en, en-US-AndrewNeural -10% |
| 2 | storyboarder | storyboard.md | done | 10 scenes, 108.5 s, 1–2 s reading holds |
| 3 | scriptwriter | narration.md | done | 194 words en, product-intro title card |
| 4 | voice-producer | media/sNN.vo.wav, #voice v9 | done | 80.5 s, vo.py check pass |
| 5 | scene-automator | scenes.web.*, demo_ctx.py | done | dry-run PASS |
| 6 | capture-operator | media/sNN.raw.*, #events v2 | done | 1280x720 full-frame |
| 7 | privacy ∥ sync-editor | #blur v2, #timeline v6 | done | 17 regions; 100.04 s |
| 8 | motion-designer ∥ caption-writer ∥ sound-mixer | #motion v8, #captions v7, #mix v6 | done | 32 effects; 23 cues; -14.7 LUFS |
| 9 | render-engineer | final-16x9.mp4, final.vtt, #checks v10 | done | pass=true |
| 10 | demo-qa | qa.md | done | PASS, minors M-1..M-4 accepted at G3 |
| 11 | packager | thumb.png, #delivery v2 | done | 10 en chapters |

## Fix log
- 2026-11-19 English conversion, product intro, reading holds → narration/voice/timeline → done
- 2026-11-19 demo skipped content → full-coverage storyboard, re-capture 10 scenes → done
- 2026-11-19 blur write landed in .demo/.demo (project.py cwd bug) → rewritten v2, plugin fixed → done
- 2026-11-19 freeze 74280–74480 deliberate → motion v8 allow → #checks v10 pass

## Next action
None. Open, optional: M-1 blur flicker 89.9–90.7 s, M-2 4.2 s silent scroll-back 88–92 s, M-3 hero zoom clips headline, M-4 cues 12/14 fast (run `/demo-studio:fix` to address).
