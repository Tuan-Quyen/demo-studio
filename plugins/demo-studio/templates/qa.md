# QA: <slug>

Video: <media/final-*.mp4 reviewed>

## Machine checks (project.json#checks)
| Check | Threshold | Result | Pass |
|---|---|---|---|
| Sync drift | ≤80 ms/scene | <value> | <yes/no> |
| Loudness | −14±1 LUFS, ≤−1 dBTP | <value> | <yes/no> |
| Blur coverage (OCR) | 0 readable text | <value> | <yes/no> |
| Black / freeze | none unintended | <value> | <yes/no> |
| Captions | ≤42 chars/line, ≤200 ms off | <value> | <yes/no> |
| Total length | brief ±10% | <value> | <yes/no> |

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
