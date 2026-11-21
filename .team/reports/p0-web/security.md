Verdict: PASS · Round 3

# p0-web — security

> Owner: **team-security**. PASS = no `open` blocking finding. Findings are cumulative: an ID (`S-01`…) is never reused; status open → fixed → verified (or dropped, with the reason). Never write secret values.
> **Budget:** ≤ 80 lines. Cells ≤ 25 words. **Round detail** ≤ 8 lines, replaced each round; verified/dropped findings collapse to one `Closed:` line of IDs.

## Scope
- In scope: R3 delta `git diff c2d2bc0..0cf9471 -- plugins`: capture.py gate (carry, NEAR_MS, edges, no_strict_evidence, rollback), privacy_mask.js, privacy_oracle.js, web_adapter.py TypeGuard, checks.py (S-24), project.py retention/doctor, blur.py (R-16), gitignore
- Trust boundaries: app DOM / scene script → mask + oracle log → pixel gate → `#events.masked`; agent-editable demo.yaml `privacy.accepted` + CLI thresholds → checks; `#events.clips[*].file` paths → retention/doctor deletes
- Scanners: pytest privacy_mask+capture ×3 → 74p/1s, 74p/1s, 79p/1s (tests added mid-run; another agent's pytest ran in parallel); 20 live scratch captures; synthetic `_pass` probes A–F, D2
- Skipped: gitleaks/osv not installed; real autofill (headless has none); desktop/mobile (P0-native)

## Findings
| ID | Severity | Where | Class | Attack scenario | Fix direction | Found | Status |
|---|---|---|---|---|---|---|---|
| S-16 | suggestion | `project.py:368-376` | authz | `writer` is self-declared; any importer can pass "checks.py" or call store_key | Acceptable for P0; enforce via hook (P1 §4.3) | R1 | open |
| S-19 | should-fix | `capture.py:308-311` | false pass | Strict entry ≤37 ms beats bad one: overlay 2-3 rAF late (nested scroller) shows text, judged strict. Probe E/E3: unmasked 0 | Any glyph-edge (bad) inner entry fails the frame; strict only rescues uniform/soft neighbours | R2 | open |
| S-24 | should-fix | `checks.py:457-463`; `config.py:141` | authz | Any agent can Edit demo.yaml `privacy.accepted: ["*: accepted by user"]`; wildcard, free-text, unbound to clip/thresholds silences all weakened clips | Drop `*`; bind entry to scene+thresholds+clip hash; write only via director command after AskUserQuestion, or hook-guard the key | R2 | open |
| S-26 | should-fix | `capture.py:458-466` | false pass | Anchor = any ok frame (empty, skipped, or itself a lag leak), not strictly verified. Probe D2: 6 glyph frames with logged rects carried, unmasked 0 | Anchor only on frames where every rect group is strict; empty-only frames never anchor a bad frame | R3 | open |
| S-27 | suggestion | `capture.py:321-323` | weak counter | Edge/boundary soft→empty frames become carry anchors; probe F: 17 non-pill frames → soft 2, carried 12 (under-reports, uniform so unreadable) | Count edge-exempt frames separately; never anchor on them | R3 | open |
| S-28 | should-fix | `project.py:573-574` | retention | `.tmp-<sid>-<pid>` matched only for sids already in #events: SIGKILLed first take of a new scene leaves raw video unflagged by doctor/checks/retention | Match `^\.tmp-[\w-]+-\d+$` (or a marker file capture writes) inside the slug folder | R3 | open |
| S-29 | suggestion | `capture.py:458`; `privacy_mask.js:186-193` | gap | Carry compares only first 400 rects; top-layer re-show keyed on element count (swap kept same count, masked here by timing) | Compare all rects (or whole frame above 400); key top-layer signature on element identities | R3 | open |

Closed: S-01..S-15, S-17, S-18, S-20, S-21, S-22, S-23, S-25 (S-08, S-17..S-23, S-25 verified R3; residuals S-26..S-29)

## Round detail (latest round only)
- Round: R3 · 2026-11-21 · delta c2d2bc0..0cf9471 + R2 repro re-run (scratchpad `r3/`, fake data)
- Open blocking: 0 (S-17 verified)
- Live repros all masked with strict evidence or fail closed: s01 strict 48/rect 990/oracle 491; s02 70; s03 68; s04 35; s05 40; s06 40 (S-21); s07 38; dark-pixel scan per frame: no transient glyph spikes
- New bypasses: setAttribute/defaultValue/form.reset/contenteditable/textarea innerHTML/.value/setRangeText/iframe-realm setter, shadow .value + fill, dialog swap → masked (strict 45-50); `<select>` option → fail closed `regex_hits_not_logged`; iframe → unmaskable, fail closed
- Probes: A unmasked 30, B strict_frames 0 → `no_strict_evidence` (capture.py:663), C unmasked 1 — all fail closed; E/E3/D2 pass leaks (S-19, S-26)
- R-15 ok: gitignore covers media/.tmp-*/ + sidecars; retention and doctor keep outside paths unless --include-outside (R-18); finish_run rolls back on #events failure
- S-24: thresholds recorded in clip mask{}, checks flags soft/raised/accepted; accepted unmaskable still need blur coverage (checks.py:228); remaining gap is self-approval
- R-16 blur verify similarity filter (≥4-char run / 50%) can drop a partially readable OCR read; generic matcher only, acceptable
