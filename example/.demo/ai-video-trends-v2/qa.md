# QA: ai-video-trends-v2

Video: `media/final-16x9.mp4` (1920x1080, 25 fps, 35.04 s), `media/final.vtt` (9 cues). Independent run; v1 not read.
Evidence: `media/preview/qa/` (sheet1.png, sheet2.png = 2 fps contact sheets 0-17.5 s / 17.5-35 s; full/F_NNN.png = full-res 2 fps frames, NNN = t*2+1; k_*.png, xfade.png, scroll.png, join23.png, chart_top*.png).
Accepted per director: 25 fps, 720p source upscaled, voice-only mix.

## Machine checks (project.json#checks, pass=true, not re-measured)
| Check | Threshold | Result | Pass |
|---|---|---|---|
| Sync drift | ≤80 ms/scene | 3 ms max | yes |
| Loudness | −14±1 LUFS, ≤−1 dBTP | −14.0 LUFS / −1.9 dBTP | yes |
| Blur coverage (OCR) | 0 readable text | 5 regions, 0 text | yes |
| Black / freeze | none unintended | only inside allow | yes |
| Captions | ≤42 chars, ≤200 ms | 39 chars, 110 ms max | yes |
| Total length | 38 s ±10% | 35.04 s (−7.8%) | yes |

## Human-eye checklist
- [x] Spelling: title card "Quá nhiều kiểu video AI?", end card "Khám phá xu hướng" / "AI Video Trends · dữ liệu mẫu" diacritics correct (k_2.2.png, F_061.png); all 9 VTT cues match narration.md word for word; line breaks at phrases
- [x] No broken UI, popups or notifications; no other windows
- [x] No sensitive data: OCR of all 70 full-res frames finds no email, API key or token; only fictional creator handles (@still_atlas etc., sample data). Email pill blurred in every wide frame, out of frame in zooms; API key panel never in frame (s04 stops at the chart). Blur box covers only the pill, nav links untouched
- [x] Sample-data framing: chart caption "Genre growth, last 90 days (sample)" readable through the s04 zoom (chart_top.png, chart_top_24.png); end card says "dữ liệu mẫu"; no figures spoken
- [~] Pacing: hook at 0 s, one CTA, VO matches action in every scene; see Q-5, Q-6
- [~] Zoom/highlights land on the right element; rings sized/placed poorly (Q-1, Q-2)
- [x] 16:9 present and framed (only format requested)

## Findings
| ID | Time / scene | Problem | Evidence | Owner agent | Severity | Fix |
|---|---|---|---|---|---|---|
| Q-1 | 00:12.6–00:12.9 / s03 | Click highlight ring is oversized: ~580 px circle drawn from the whole card bbox [60,282,275,282], overflows the card into the count line and empty grid; cursor sits off-centre at the card's lower right | k_12.75.png | motion-designer | minor | Size the ring from the click point (fixed ~60–80 px radius around the cursor / card thumbnail), not the card bbox |
| Q-2 | 00:27.75–00:28.94 / s05 | Rank-1 ring is centred on the row bbox [70,200,580,68], so it sits over "repeatable formats" in the why-text (partly hiding it) while the cursor is on the rank badge; cursor dot also covers the "1" | k_28.3.png | motion-designer | minor | Centre a smaller ring on the cursor/badge (or use a row outline instead of a circle) so the why-text stays clear |
| Q-3 | 00:19.89–00:20.19 / s03→s04 | Cross-fade dissolves two text-heavy screens: "Trending now" and "Trends" headings, the card and the trend cards ghost over each other and two cursors show for ~300 ms; reads muddy, not wrong | xfade.png | motion-designer | minor | Use a hard cut or a short dip-through-black (headers differ, nav is identical, so a cut reads cleaner) |
| Q-4 | 00:20.96 / s04 | Scroll from trend cards to chart is a single-frame jump (instant scroll, ~330 px), no backtrack; looks like a jump cut mid-shot. Storyboard allowed it as a fallback | scroll.png | scene-automator | minor (accept) | Optional: smooth scroll over ~600 ms ending before 21.7 s zoom; otherwise accept |
| Q-5 | 00:28.94–00:29.36 / s05 | End card fades in while VO still says "...kèm lý do"; rank-1 zoom only ~1.4 s (storyboard ~4.5 s), so the "why" text is on screen briefly before the dissolve; fade-in overlays end-card title on the list text (k_29.1.png) | k_28.3.png, k_29.1.png | motion-designer | minor | Start the end-card fade at ~29.4 s (after "kèm lý do", before CTA onset 30.27 s) and start the rank-1 zoom earlier (~26.5 s); end card still ≥ 5 s |
| Q-6 | 00:12.30 / s02→s03 | Cut between two takes of the same screen: cursor jumps from the chip to mid-screen and the grid shifts a few px | join23.png | scene-automator | minor | Start s03 with the cursor parked on the chip (s02 end state); or accept |
| Q-7 | 00:02.5–00:06.9 / s01 | Resting cursor sits on the "Explore trends" button label, covering "Ex" for the whole hero hold | sheet1.png (2.5–6.5 s) | scene-automator | minor | Park the cursor just below/right of the button |

Notes (no action): silences at joins 1.2–1.4 s each (s01→s02 1.19, s02→s03 1.35, s03→s04 1.25, s04→s05 1.41 s) are even and acceptable for this length; s02 holds 3.5 s on the single filtered card while VO finishes (allowed freeze, fine). End-card CTA timing OK: CTA line 30.27–33.80 s fully on the end card, 1.2 s tail. Focus outline on the card after Esc (19.0 s) is real app behaviour, acceptable.

## Verdict: PASS
No blockers; 7 minor findings (motion-designer Q-1, Q-2, Q-3, Q-5; scene-automator Q-4, Q-6, Q-7). Highest-value fixes: Q-1, Q-2, Q-5 (render-only, no re-capture).
