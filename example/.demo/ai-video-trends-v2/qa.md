# QA: ai-video-trends-v2 (full 10-scene tour, #checks v9)

Video: `media/final-16x9.mp4` (1920x1080, 25 fps, 100.04 s). The picture is 1600x900 at the top; the caption band runs from y 900 to 1080. Captions: `media/final.vtt` (23 cues, en, burned into the band).

Evidence in `media/preview/qa/`:
- sheet1–sheet4.png: 1 fps contact sheets for 0–24 s, 25–49 s, 50–74 s and 75–99 s.
- s08_scroll.png and s10_scroll.png: 25 fps strips of the key-sensitive scrolls.
- f90.png and keys.png: the API key card.
- nav_8.5.png: the header nav.
- k_93.5.png: the s10 zoom.
- a.wav: the final audio.

Sampling was lean: no per-frame OCR. Whisper ran once on the full audio.

Accepted by the director:
- the 200 ms freeze at 74.28–74.48 s;
- the s06 wide shot;
- allow.freeze for the reading holds;
- loudness −14.7 LUFS / −4.4 dBTP;
- 25 fps, 720p source upscaled, voice-only mix.

## Machine checks (`project.json#checks` v9: **pass=false**)
| Check | Result | Pass |
|---|---|---|
| VO / sync | vo.py exit 0; drift ≤10 ms | yes |
| Loudness | −14.7 LUFS / −4.4 dBTP | yes |
| Blur (OCR) | 108 samples, 0 readable | yes |
| Black | only in the title and end card dips | yes |
| **Freeze** | **74.28–74.48 s is outside allow.freeze (which starts at 74480)** | **no** |
| Captions | 23 cues in the band, ≤42 chars, ≤2 lines; soft: cue 12 17.8 cps, cue 14 18.8 cps | yes |
| Length | 100.04 s vs 105 ±10% | yes |

Per the demo-qa rule, `#checks.pass=false` means FAIL. The director has accepted this freeze as intended, but the accepted span is not in `allow`, so the gate still fails. Fix (bookkeeping only, no re-render): add [74280, 74480] to `#motion.allow.freeze` (motion-designer), then render-engineer re-runs the checks (v10). The human review below found no blockers, so the verdict becomes PASS once #checks passes.

## User requests
| Request | Result | Evidence |
|---|---|---|
| Entirely English | Yes. Whisper detects en at p 1.0, and the transcript follows narration.md. final.vtt contains no non-ASCII characters. Cards and captions are English | a.wav, final.vtt, sheets |
| Title card introduces the product | Yes. 0–2.5 s: "AI Video Trends" with the subline "Trending AI videos, rising techniques, genres to bet on". The first spoken line is "Meet AI Video Trends: …" | sheet1 0–2 s |
| 1–2 s reading holds | Yes. Measured silences (−50 dB, ≥0.8 s): 1.59 / 1.71 / 2.25 / 1.94 / 1.68 / 1.69 / 1.82 / 2.02 s, then 4.17 s at s09→s10 (M-2) and the 0.89 s declared pause | silencedetect |
| Captions in the band below the picture | Yes. All sampled cues are in the band, with no overlap on the UI | sheets |
| 8-video grid | Yes, 8–16 s; both rows shown | sheet1 8–15 s |
| 2–3 genre chips | Yes: Music video (18–21 s), Anime (22–24 s), Faceless YouTube (29–30 s) | sheet1, sheet2 |
| Reset to All | Yes, 25–28 s; all 8 cards return | sheet2 25–28 s |
| Detail popup open / close | Yes: opens at 31 s; prompt, tool and "Why it trends" are readable from 32 to 39 s; closes at 40–41 s | sheet2 31–41 s |
| 4 trend cards | Yes, 44–53 s, all four readable | sheet2 44–49 s, sheet3 50–53 s |
| Chart | Yes, 54–60 s, all 7 bars, "(sample)" caption shown | sheet3 54–60 s |
| All 5 genre ranks with reasons | Yes. Ranks 1–2 at 62–73 s and ranks 3–5 at 74–88 s, each reason line readable, with the ring on the rank badge as each is spoken | sheet3 62–73 s, sheet4 75–88 s |
| Header nav Trending / Trends / Genres | Yes. The cursor clicks Trending (about 8 s, readable: nav_8.5.png), Trends (about 43 s) and Genres (about 61 s) | nav_8.5.png, sheet2 43 s, sheet3 61 s |
| "Explore trends" CTA | Yes. In s10 the cursor clicks the hero "Explore trends" button (about 94 s). The end card "Explore trends" is up from 95.6 s, and the CTA line plays from 95.19 to 98.97 s on the card, which then holds about 4.4 s | sheet4 94–99 s |
| Email and API key never readable | Yes, in every sample. The email pill is blurred in all wide frames. The API key value is blurred where the Creator dashboard card scrolls through (61.1–61.5 s and 89.9–90.7 s): f90.png shows the label "Your API key for the sample generator:" over a blurred key field. See M-1 for blur misplacement | f90.png, s08_scroll.png, s10_scroll.png |

## Findings
| ID | Time / scene | Problem | Evidence | Owner agent | Severity | Fix |
|---|---|---|---|---|---|---|
| G-1 | 74.28–74.48 s s09 | `#checks.freeze` fails: the accepted 200 ms hold is missing from allow.freeze | #checks v9 | motion-designer, then render-engineer (checks only) | **gate** | Add [74280, 74480] to `#motion.allow.freeze` and re-run the checks; no re-render |
| M-1 | 89.9–90.7 s s10 | The tracked API-key blur (b12–b14) jumps between frames onto harmless content: the rank-1 title "Faceless YouTube" and the chart labels "Music video" / "Explainer". It shows as flickering blobs. The key itself stays blurred | s10_scroll.png | privacy-blurrer | minor | Re-track b12–b14 to the key field only. Trimming the scroll (M-2) also removes this |
| M-2 | 88.05–92.22 s s09→s10 | 4.2 s without VO: the s09 hold (1.6 s), then a 2.6 s scroll back up through the whole page (genres → chart → trends → hero). It reads as a rewind | sheet4 88–91 s; silencedetect | sync-editor | minor | Raise s10 `in` so s10 opens on the hero (or cut straight to it); the gap drops to the 1–2 s hold the user asked for |
| M-3 | 93.0–94.3 s s10 | The zoom on the hero clips the headline at the right edge ("What's trending in AI vid…") | k_93.5.png | motion-designer | minor | Move the zoom centre left or lower the scale (about 1.3) so the full h1 fits |
| M-4 | 44.51 s (cue 12), 53.73 s (cue 14) | Soft caption speed over 17 cps (17.8 and 18.8). Cue 14 "Scroll a little further," flashes for 1.28 s | final.vtt | caption-writer | minor | Merge cue 14 into cue 15, and extend cue 12 into the gap before cue 13; otherwise accept |

The cursor issues from earlier renders are gone in this capture: the s01 cursor rests beside the button, not on it.

## Verdict: FAIL (gate only)
The only failure is G-1: `#checks.pass=false` because the accepted 200 ms freeze is not listed in allow.freeze. The human review found no blockers; the four minors (M-1 to M-4) are optional. Once G-1 is fixed and #checks re-runs as pass=true, this is a PASS and no new QA pass is needed unless the render changes.

## Gate update (director, 2026-11-19)
G-1 fixed: #motion v8 allow.freeze += [74280, 74480]; #checks v10 pass=true, no re-render. Final verdict: **PASS** (minors M-1..M-4 accepted by the user at G3).
