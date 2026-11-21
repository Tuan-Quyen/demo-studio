Verdict: FAIL · Round 3 (R-18 blocker open: `doctor --clean` deletes `.tmp-*` dirs outside the project; R-15..R-17 verified)

# p0-web — code review

> Owner: **team-code-reviewer**. PASS = no `open` blocking finding. Findings are cumulative: an ID (`R-01`…) is never reused; status open → fixed → verified (or dropped, with the reason). **Round detail** holds the latest round only.
> **Budget:** ≤ 80 lines. Cells ≤ 25 words. **Round detail** ≤ 8 lines, replaced each round; verified/dropped findings collapse to one `Closed:` line of IDs.
> Severity here: blocker = blocking, major = should-fix (fix before P0 exit), minor = suggestion.

## Findings
| ID | Severity | Where | What is wrong | Fix direction | Found | Status |
|---|---|---|---|---|---|---|
| R-01 | blocker | `scripts/checks.py:432-434`, `scripts/blur.py:1100` | `checks.pass` goes stale: blur.py verify merges a leak/inconclusive into `#checks.blur.<A>` but leaves `pass:true`; `--only` merges old `results`. | verify must also set `pass:false`/drop `results.blur`; checks.py recompute `pass` from live `blur.<A>`, not old `results`. | R1 | verified |
| R-02 | blocker | `scripts/blur.py:1096-1100`, `checks.py:184-205` | Blur verdict not bound to the output file: re-render after verify still aggregates `pass`. Fingerprint (design 4.5) not used. | Store `file:{size,mtime_ns,ino}` of the verified mp4 in `#checks.blur.<A>`; checks.py rejects mismatch as incomplete. | R1 | verified |
| R-03 | major | `scripts/checks.py:459` | `--only blur` (or any subset) gives `status:incomplete, pass:false` but exit 0; consumers trusting exit code see success. Verified by run. | `code = 3` when `not total_pass` and no other class. Add test. | R1 | verified |
| R-04 | major | `scripts/capture.py:454`, `privacy_mask.js:455-465`, `agents/privacy-blurrer.md:18` | `unmaskable[]` entries are `{surface,attr,tag,selector}`: no bbox/t, unlike design 4.5. blur.py never reads them; blurrer cannot make regions. Clip stays `masked:true`. | Emit bbox+t+reason (canvas/iframe/img/title). Make `plan` fail-closed (exit 2 needs-input) when a clip has unmaskable[] with no covering region. | R1 | verified |
| R-05 | major | `scripts/blur.py:932-945,1056-1061` | verify maps ROIs with a centred default transform; nothing writes `#blur.transforms`. Motion zoom/pan or other reframe → ROI on wrong pixels, verify passes blind. | Require `transforms.<aspect>` from render-engineer/motion (or exit 2); sanity-check ROI with a blur-vs-raw variance probe. | R1 | verified |
| R-06 | major | `scripts/setup_tools.py:86-96`, `capture_recorder.js:98` | `capture` feature installs Python playwright only; recorder needs `node` and the Node `playwright` module (`node:False`). Also bare `ffmpeg` on PATH vs bundled imageio. | Add node check + `npm` playwright to feature or make `capture.py` tool check verify `require('playwright')` (exit 4). | R1 | verified |
| R-07 | minor | `scripts/capture.py:453`, `agents/capture-operator.md:32` | `mask_style: blur` always yields `masked:false`, yet capture-operator must `block` unless `masked` true. | Doc: for blur style require `frames_unmasked==0` and assertion ok instead. | R1 | verified |
| R-08 | minor | `scripts/config.py:276-282` | Regexes validated with Python `re`, applied by JS `RegExp` (mask) and Python (verify). Dialect mismatch → mask asserts fail (exit 11) or verify misses. | Validate under both (node one-liner) or document a shared subset. | R1 | verified |
| R-09 | minor | `scripts/capture.py:410-432` | `<scene>.spec.json` (regexes in clear) left in `media/` on wall/stall/leak paths; dry-run prints spec. | `try/finally` remove; redact regexes in dry-run output. | R1 | verified |
| R-10 | minor | `scripts/blur.py:1198`, `skills/run-kits/SKILL.md:184`, `agents/render-engineer.md:12` | `tools.ocr` never reaches `--ocr`; `none` yields exit 4 and no verdict, docs say `inconclusive`. | Agents pass `--ocr`; doc the real result (exit 4 → checks incomplete). | R1 | verified |
| R-11 | minor | `scripts/blur.py:1056-1063` | `seeded`: no full-frame pass, so `seed_values` never searched; no regions → `pass` with `sampled 0` (test 431 enshrines it). | Mark `total:0` as `not_applicable`; scan seed_values full-frame sparsely. | R1 | verified |
| R-12 | minor | `scripts/blur.py:207` | Drop test reads only `spans[0]` scene; merged multi-scene region may drop other-scene spans. Source `capture-mask` is emitted by no agent (dead, safe). | Require every span scene masked, or delete the rule. | R1 | verified |
| R-13 | minor | `scripts/project.py:340-365` | `inputs` fingerprints written but never consumed (no staleness); hash cache written outside the lock. | Wire into `demo.py`/checks (P1) or note; lock cache write. | R1 | verified |
| R-14 | minor | `scripts/capture.py:68`, `tests/` | capture.py has no unit test; cross-check thresholds only via real Chromium test. `positive_controls` OCR calls not budget-checked. | Add dry-run/spec tests; check clock per OCR call. | R1 | verified |
| R-18 | blocker | `scripts/project.py:572-581,658-672` | `stale_tmp_dirs` scans every `#events` clip folder, so `doctor --clean` rmtrees any `.tmp-*` dir there, even outside `.demo/<slug>/` (run: `ext/.tmp-keepme` deleted, no `--include-outside`). Retention guards this. | Match `^\.tmp-<sid>-\d+$` only; outside dirs listed, removed only with `--include-outside`. Test. | R3 | open |
| R-19 | minor | `tests/test_capture.py:177-183`, `capture.py:67,381-382,267-268,531` | Named constants untested: `CARRY_MAX` test is vacuous (cap 100 gives the same 6 carried); `EDGE_MS`, `NEAR_MS`, 60 ms throttle, `UNM_PAD_MS` wiring in `gate()` have no test. | Add a probe that fails if each constant changes; assert gate output carries the pad. | R3 | open |
| R-20 | minor | `capture.py:271-277,289-294`, `checks.py:459-465`, `web.md` | `_boundary` has unnamed `35`; docstring says a bad neighbour still fails, code only checks entries within `NEAR_MS`. `EDGE_MS` 100 not in docs; `privacy.accepted` `*:` wildcard and 10-char minimum undocumented. | Name `35`; fix docstring; document 100 ms, `*`, minimum length. | R3 | open |

Closed: R-01..R-17 (R-15..R-17 verified R3: gitignore, template and `raw_artifacts` cover `.tmp-*`, mask/sync/probe sidecars, `--out-dir` clips; `similar_text` matcher; playwright `>=1.63,<1.64` plus `setup_tools` check)

## Round detail (latest round only)
- Round: R3 · 2026-11-21 · diff: edd1f68..HEAD (plugins, README) · 26 files
- Evidence: `pytest -q tests` with OCR venv = 350 passed, 1 skipped (369 s); repro of R-18 in a scratch dir; `probe.py` set `CARRY_MAX=100` on the cap test: unchanged result
- Contracts consistent: capture `mask.thresholds{max_soft,max_resync,accepted_unmaskable}`, `frames_soft`, `unmaskable[].accepted` are read by `checks.weakened`; `undecided` needs `privacy.accepted` `<scene>: <reason>`. Failures `finding` (demo-director / capture-operator) give exit `finding`, not 0. demo-qa, README, run-kits, capture-operator, web.md match; 6, 37, 300, 60, 250 ms documented.
- Good: `finish_run` backs up and rolls back on any failure; `similar_text` stays in memory, generic matcher only without a pattern; retention classifies by realpath; TypeGuard fail-closed on every typing path.
- Fix order: R-18 (blocker), then R-19, R-20. No security-review blocker beyond R-18 (deletes user data outside the project).
