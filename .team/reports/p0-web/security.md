Verdict: FAIL · Round 2

# p0-web — security

> Owner: **team-security**. PASS = no `open` blocking finding. Findings are cumulative: an ID (`S-01`…) is never reused; status open → fixed → verified (or dropped, with the reason). Never write secret values.
> **Budget:** ≤ 80 lines. Cells ≤ 25 words. **Round detail** ≤ 8 lines, replaced each round; verified/dropped findings collapse to one `Closed:` line of IDs.

## Scope
- In scope: R2 delta `git diff d5b3c49..HEAD -- plugins` (97e6345, 4f5a342, 2272177): capture.py gate, web_adapter.py, privacy_mask.js, privacy_oracle.js, checks.py, blur.py
- Trust boundaries: app DOM / scene script → mask + oracle log → pixel gate → `#events.masked`, `safe_from_ms`; CLI flags (`--accept-unmaskable`, `--max-*`) → gate; argv → runs.jsonl
- Scanners: pytest privacy_mask+capture ×3 → R1 7 fail (gate failed closed, 1 unmasked oracle frame), R2/R3 58 pass/1 skip; synthetic `_pass` probes; 8 scratch captures
- Skipped: gitleaks/osv not installed; desktop/mobile (P0-native)

## Findings
| ID | Severity | Where | Class | Attack scenario | Fix direction | Found | Status |
|---|---|---|---|---|---|---|---|
| S-08 | should-fix | `web_adapter.py:175-183` | leak | Guard misses Locator/Page.press, ElementHandle.type/fill, Keyboard.down, split calls: typed email prefix readable, gate `ok masked:true rect_checks:0` (repro s04/s05) | Wrap all typing paths; forceMask every typed field while regexes exist; refuse when only buffer matches | R1 | open |
| S-16 | suggestion | `project.py:368-376` | authz | `writer` is self-declared; any importer can pass "checks.py" or call store_key | Acceptable for P0; enforce via hook (P1 §4.3) | R1 | open |
| S-17 | blocking | `privacy_mask.js:315-318`; `privacy_oracle.js:81` | false pass | Input `.value` set as property (Vue v-model, app prefill, `page.evaluate`) fires no event/mutation: mask and oracle blind. Repro s07: full email readable 1.5 s, `ok masked:true` | Re-test input values every frame (or hook value setter) in both scripts; fail when final rescan finds unlogged hits | R2 | open |
| S-18 | should-fix | `capture.py:337-341,286-300` | false pass | Carry compares to previous (maybe carried) frame, ≤16/px per step: slow fade accumulates. Probe: 32 frames readable text carried, unmasked 0 | Compare to last strictly verified frame; cap carry length; never carry glyph-edge `bad`; gap failures need full-frame repeat | R2 | open |
| S-19 | should-fix | `capture.py:258-262` | false pass | Any strict entry within ±90 ms beats a `bad` one: overlay lagging 1–2 frames (nested scroller, compositor scroll) passes. Probe C: unmasked 0 | Bad at nearest entry decisive unless nearest is strict; other strict matches count as resync | R2 | open |
| S-20 | should-fix | `capture.py:326-331,390-392` | false pass | Soft frames with no strict ever, through last frame: `leadin_end_ms` None, safe_from not pushed → masked:true with zero strict evidence (probe B) | Lead-in reaching clip end, or no strict frame while rects exist → gate fail `no_strict_evidence` | R2 | open |
| S-21 | should-fix | `privacy_mask.js:368-372`; `privacy_oracle.js:111-116` | weak oracle | Sensitive owner with `pointer-events:none`: hit-test returns opaque ancestor → rect "proven occluded", skipped (907 skips, repro s06). Mixed with checked rects: silently unverified | Ignore hits on owner's ancestors (`e.contains(owner)`); use elementsFromPoint and require occluder above owner | R2 | open |
| S-22 | should-fix | `privacy_mask.js:151-168` | silent gap | Top layer (`<dialog>.showModal`, popover) paints above overlay host: regex inputs, typed fields, boxes unmasked in modals. Repro s02 fails closed (59 frames) | Put host in top layer (popover, re-shown after each modal) or report top-layer sensitive items unmaskable | R2 | open |
| S-23 | should-fix | `privacy_mask.js:526`; `blur.py:174-178` | silent gap | Unmaskable detection every 250 ms; `t_start` lags appearance, blur span starts there: first ≤250 ms of canvas/iframe/shadow content unblurred | Pad unmaskable spans by detect interval + 1 frame, or detect on mutation | R2 | open |
| S-24 | suggestion | `capture.py:796-801`; `checks.py:438-457` | authz | Agent self-passes `--max-soft/--max-resync/--accept-unmaskable`, `gate --slug` rewrites #events; thresholds not recorded, checks ignores frames_soft | Record thresholds + acceptance in clip mask{}; checks treats soft>0 as needs-blur. Accepted unmaskable still blurred (mitigated) | R2 | open |
| S-25 | suggestion | `templates/gitignore`; `capture.py:658-668,318` | retention | gitignore misses `media/.tmp-*/` (SIGKILL leftovers); write_events failure after rename leaves new file under old record; `frames_unverified` counts all pre-entry frames | Add pattern; write #events before rename or roll back; count ticks in cross_check ready_t | R2 | open |

Closed: S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-09, S-10, S-11, S-12, S-13, S-14, S-15 (verified R2; residuals tracked as S-18..S-25)

## Round detail (latest round only)
- Round: R2 · 2026-11-21 · delta since R1 + R1 repro re-run
- Open blocking: 1 (S-17)
- R1 repros fail closed: modal backdrop (test passes), soft-vs-bad, failed re-shoot → masked:false, stale verdict (fingerprint+inputs), seeded no-region → incomplete, temp cleanup, runs.jsonl redaction (abbrev, `=`)
- Pre-paint rule: safe_from ≥ leadin_end, gate requires offset_ms ≥ safe_from; checks/blur reject `in` < safe_from; all clip ms. Only hole: S-20
- Oracle shares selector/regex config and event blindness with mask (S-17, S-21); it did catch R1 test frame 136 that the mask entry passed
- Tests ×3: unmasked 0/soft 0/resynced 0 in R2/R3 (carried 1, 5; lead-in 30); R1 leaked 1 frame, caught → flaky
- Repro files: scratchpad `r2/` (fake data: value.html, dialog.html, pe.html, scenes.py, probe.py)
