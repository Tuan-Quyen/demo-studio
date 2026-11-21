# QA: <slug>

Video: <media/final-*.mp4 reviewed>

## Machine checks (project.json#checks)
Source: `#checks v<N>` pass=<true|false> (rewrite on every QA run, never keep an older one)

| Check | Threshold | Result | Pass |
|---|---|---|---|
| Sync drift | ≤`targets.max_drift_ms`/scene (80) | <value> | <yes/no> |
| Loudness | `targets.lufs`±1 LUFS (−14), ≤`targets.true_peak` dBTP (−1) | <value> | <yes/no> |
| Blur coverage (`check-blur`) | 0 gaps / invalid / weak | <value> | <yes/no> |
| Black / freeze | none unintended | <value> | <yes/no> |
| Captions | ≤`captions.max_chars`/line (42), ≤`targets.caption_offset_ms` off (200) | <value> | <yes/no> |
| Total length | `length_s` ±10% | <value> | <yes/no> |

## Human-eye checklist
- [ ] Spelling and wording match narration and on-screen text
- [ ] No broken or overlapping UI, no stray popups or notifications
- [ ] No personal or sensitive data visible
- [ ] Pacing: no rushed or dead moments; hook in first 5 s; one CTA
- [ ] Zoom and callouts land on the right element
- [ ] Every requested format present and correctly framed

## Findings
| ID | Time / scene | Problem | Owner agent | Severity (blocking/minor) |
|---|---|---|---|---|
| <Q-1> | <mm:ss or sNN> | <problem> | <agent> | <severity> |

## Verdict: <PASS | FAIL>
<one line reason; on FAIL list blocking finding IDs>
