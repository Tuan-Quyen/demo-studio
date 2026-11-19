# QA: ai-video-trends-tour

Video: media/final-16x9.mp4 (1920x1080, 37.62 s) + media/final.vtt
Method: frames every 0.5 s (75) viewed as contact sheets, dense 5–10 fps grabs around both scene joins and the s04 scroll, full-res crops for blur/softness, RapidOCR on frames every 0.25 s (150), silencedetect (−35 dB) for speech timing. Evidence: `media/preview/qa/` (sheet_NN = frames NN×9 … NN×9+8 at 0.5 s steps).

## Machine checks (project.json#checks, v2 — not re-measured)
| Check | Threshold | Result | Pass |
|---|---|---|---|
| Sync drift | ≤80 ms/scene | max 10 ms | yes |
| Loudness | −14 ±1 LUFS, ≤−1 dBTP | −14.0 LUFS, −1.5 dBTP | yes |
| Blur coverage (OCR) | 0 readable text | 0 hits / 136 frames | yes |
| Black / freeze | none unintended | black 33.57–33.85, 37.40–37.60; freeze 2.73–6.20, 33.93–37.33 (all in allow lists) | yes |
| Captions | ≤42 chars/line, ≤200 ms off | 42 max, start offsets ≤10 ms | yes |
| Total length | 40 s ±10% | 37.62 s (−6.0%) | yes |

Accepted (not findings): 25 fps source in 60 fps output, 720p→1080p upscale, 1.93 Mbps, voice-only mix.

## Human-eye checklist
- [x] Spelling and wording match narration and on-screen text — all 10 VTT cues match narration.md word for word; Vietnamese diacritics correct in captions and end card ("Mở AI Video Trends, / chọn ngay thể loại tiếp theo để thử."). Two line breaks split a compound (Q-8).
- [x] No broken or overlapping UI, no stray popups or notifications — no popups; modal bottom clipped before its internal scroll (Q-5); two scroll-position jumps at scene starts (Q-1, Q-2).
- [x] No personal or sensitive data visible — email pill pixelated in every frame it is in; API key row blurred during the s04 scroll; OCR: see "PII / OCR". The blur in s04 over-covers non-sensitive content (Q-3).
- [x] Pacing: hook in first 5 s (pain line over hero, 0.2–3.2 s); one CTA (spoken + end card). Notes on modal timing, dead air and CTA/card overlap (Q-4, Q-6, Q-7).
- [x] Zoom and callouts land on the right element — chip (7.8 s), card v5 (~9.9 s), modal fields, top chart bar (24.6 s), rank 1 (~31 s). s03 highlight box runs off the right edge of the zoom crop (Q-9).
- [x] Every requested format present and correctly framed — 16:9 only, as in demo.yaml.

## Sample-data framing
No figure is presented as real: narration speaks no numbers; s03 says "theo dữ liệu mẫu" while the chart caption "Genre growth, last 90 days (sample)" is on screen (22.5–27.4 s). Card/modal metrics (views, ▲%) in s01/s02 carry no on-screen "sample" label, but are not referenced by narration — acceptable, no finding.

## Visual softness
Upscale softness is visible but text stays legible at 1080p, including the 1.6x modal zoom (effective ~2.4x of source) — `media/preview/qa/softness.png`. Smallest text (chips, card meta at wide 1.0x, ~10 px source) is soft but readable. Accepted, no finding.

## PII / OCR
RapidOCR on 150 full-res frames (0.25 s grid, 0–37.25 s): no hit for the email (`alex`, `nguyen`, `example.com`, `@` + domain), no `sk-` / `sk_` / API-key string. `@`-hits are only the fictional creator handles from sample data (@pixel_harbor, @loop_lantern, @echo_meadow, @quill_orbit, @still_atlas). Visual check: email pill pixelated in every frame it appears (incl. under the modal backdrop, 10–19.5 s, and the cross-fades); zooms crop it out. API key row blurred during the s04 scroll (28.4–29.0 s, `media/preview/qa/q3-s04-blur-column.png`). Only the "Creator dashboard" heading is readable (23.5–23.75 s, 27.25–27.75 s) — not sensitive, but out of scope per brief (Q-10).

## Findings
| ID | Time / scene | Problem | Evidence | Owner agent | Fix | Severity |
|---|---|---|---|---|---|---|
| Q-1 | 00:20.4–00:21.2 · s03 | After the s02→s03 cross-fade the s03 clip starts on Trending, then snaps to the page top (hero) and smooth-scrolls back down to Trends — a visible backtrack right after the cut (storyboard: "no scene scrolls back up"). | qa/q1-s03-start-jump.png (5 fps from 19.4 s; tiles 6–8) | scene-automator | Start s03 already at Trending and make the "Trends" nav click scroll from there (no reset to top / no re-navigation); re-capture s03. Cheaper alternative: sync-editor raises s03 `in` past the jump (~+1.0 s) if the VO still fits. | minor |
| Q-2 | 00:27.9–00:28.2 · s04 | Same pattern: s04 opens on the chart (matches s03 end), then snaps up to the Trends heading before scrolling down to Genres. | qa/q2-s04-start-jump-blur.png (10 fps from 27.9 s; tiles 1–4) | scene-automator | Same fix as Q-1 for s04 (start at chart, scroll down only). | minor |
| Q-3 | 00:28.4–00:29.0 · s04 | Privacy blur during the scroll is a fixed tall column (x≈105–400 px out) that pixelates non-sensitive content: chart labels, "Promising genres" heading, rank 1–4 genre names. Reads as a glitch. API key itself stays blurred (no leak). | qa/q3-s04-blur-column.png, q2-…png tiles 7–12 | privacy-blurrer | Track the `api-key` row per frame from the scroll events (moving bbox) instead of one union column; keep blur off the genre list once the dashboard has left frame. | minor |
| Q-4 | 00:10.0–00:12.36 · s02 | Modal opens ~10.0 s; "Mở một video…" starts 12.36 s (VO pause 11.42–12.36), so the viewer sees the modal ~2.3 s before it is introduced. Known item. | qa/q4-s02-modal.png (tile 20 = 10.0 s), silencedetect | sync-editor | Shorten the VO gap between the two s02 sentences (or place the second sentence at the card click event ~9.9 s); voice-producer only if the pause is baked into the VO file. | minor |
| Q-5 | 00:11.0–00:15.0 · s02 | Modal zoom crop cuts the modal at "WHY IT TRENDS" — the label sits on the bottom edge with its text missing for ~4 s until the internal scroll at ~15 s. Looks cut off. | qa/q4-s02-modal.png tiles 22–29 | motion-designer | Shift the modal zoom crop so the bottom edge ends above the "WHY IT TRENDS" label until the scroll, or pan with the scroll. | minor |
| Q-6 | 00:31.93–00:33.9 · s04 | CTA first half "Mở AI Video Trends," is spoken over the genre list (31.93–33.42); the end card fades in at 33.6–33.9 showing words already spoken, and only the second half plays over the card. Known item. | qa/q6-s04-endcard.png (tiles 66–68), silencedetect | sync-editor | Cut the list hold inside the VO pause 30.97–31.93 and start the fade to the end card there, so the card lands with the CTA start; extend card hold to keep ≥3 s (length stays within 36–44 s). motion-designer re-times the title card. | minor |
| Q-7 | 00:17.76–00:20.0 s02→s03; 00:25.87–00:27.70 s03→s04 | Dead air: 2.2 s and 1.8 s without speech on static/zooming-out frames at both joins (plus 2.7–6.2 s static grid in s01, allowed freeze). Pace sags at scene ends. | silencedetect, sheets 04–06 | sync-editor | Trim each join by ~0.8–1.0 s (s02 end hold, s03 zoom-out tail); total stays ≥36 s. | minor |
| Q-8 | 00:12.36 cue 4; 00:22.09 cue 7 | Caption line breaks split compounds: "loại / công cụ" (cue 4) and "thể / loại" (cue 7). | final.vtt | caption-writer | Break at phrase boundaries, e.g. cue 7 "và biểu đồ chín mươi ngày cho biết / thể loại nào tăng nhanh," (≤42 chars). | minor |
| Q-9 | 00:24.6–00:26.7 · s03 | Highlight box on the top growth bar extends past the right edge of the 1.3x zoom crop (right border not visible). | sheet_06 tiles 49–52 | motion-designer | Clamp the highlight bbox to the crop or narrow it to label + bar. | minor |
| Q-10 | 00:23.5–00:23.75, 00:27.25–00:27.75 · s03/s04 | "Creator dashboard" heading readable at the bottom edge before the chart zoom and while zooming out (brief: dashboard out of scope). No key/value visible. | qa/q10-dashboard-heading.png, OCR | motion-designer | Start the s03 chart zoom ~0.4 s earlier and end the zoom-out later (or keep crop bottom ≤ 622 src px through the s03→s04 cross-fade). | minor |

## Verdict: PASS
No blockers. 10 minor findings (Q-1…Q-10); worth fixing before publishing: Q-1/Q-2 (scroll backtracks), Q-3 (visible over-blur), Q-6 (CTA vs end card).
