# QA: <slug>

Video: <media/final-*.mp4 reviewed>

## verify.py
Exit code: <0 pass | 11 leak | 3 incomplete> · Leaks: <none | list> · Loudness: <LUFS / dBTP> · Length: <s vs length_s>

## Checklist
- [ ] No personal or sensitive data visible (OCR and by eye)
- [ ] Text and narration spelling correct; captions in sync, <= 42 chars/line
- [ ] No popups, notifications or broken UI
- [ ] Hook in first 5 s, one CTA, zoom lands on the right element
- [ ] Every requested format present and framed correctly

## Findings
| ID | Time / scene | Problem | Owner agent | Severity (blocking/minor) |
|---|---|---|---|---|
| <Q-1> | <mm:ss or sNN> | <problem> | <agent> | <severity> |

## Verdict: <PASS | FAIL>
<one line reason; on FAIL list blocking finding IDs. Any leak = FAIL>
