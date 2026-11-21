Verdict: PASS · Round 2 (no open blocker; R-15 major to fix before P0 exit)

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

| R-15 | major | `scripts/project.py:262,569-575`, `templates/gitignore`, `capture.py:762,797-804` | Retention and gitignore still name `<scene>.spec.json` (no longer written). Not covered: `.tmp-sNN-<pid>/` (raw unmasked video survives SIGKILL/OOM; `media/*.raw.*` does not match inside a subdir), `*.mask.jsonl`, `*.sync.json`, `*.probe.jsonl`, `--out-dir` outside media. | Add `*/media/.tmp-*/`, `*/media/*.mask.jsonl`, `*.sync.json`, `*.probe.jsonl` to GITIGNORE_LINES, template, `raw_artifacts`; test. | R2 | open |
| R-16 | minor | `blur.py:740-753,261-263`, `tests/test_blur.py:726` | Generic matcher counts any 4+ char OCR output as a hit, so fuzz read from lr=8 on 32 px text is a false positive; the test dodges it with text_h=64. | See Round detail: match against positive-control text. | R2 | open |
| R-17 | minor | `scripts/requirements/capture.txt`, `setup_tools.py:86-92` | `playwright>=1.40` unpinned; only 1.63.0 was run. `install chromium` follows the package, so fresh installs are consistent; a preinstalled Chromium is not. | Raise floor to the tested minor (`>=1.63`) or add an upper bound; note in `effort`. | R2 | open |

Closed: R-01..R-14 (verified R2; R-11 now fails closed as `incomplete: no-samples`, stricter than asked)

## Round detail (latest round only)
- Round: R2 · 2026-11-21 · diff: c62ff0d..HEAD (plugins, README) · 35 files · fixes 97e6345, 4f5a342, 2272177
- Evidence: `pytest -q tests` with OCR venv = 327 passed, 1 skipped (220 s)
- Contracts consistent: unmaskable t_* clip ms, bbox clip px; blur subtracts offset_ms (`blur.py:174`), plan, graph, verify and checks share `uncovered_unmaskable`. `safe_from_ms` clip ms = timeline `in` clip ms (`project.py:411`, `blur.py:392`); capture gates `safe_from <= offset_ms`. `rects_checked`, `style`, `frames_unmasked` read by checks match capture's names; `mask.status` in {failed, needs-input, blur-only, unmasked, verified}, consumed by none (informational).
- Docs match CLIs (capture run|gate, set-transform, retention/stale, `--accept-unmaskable` only on a quoted user decision, `--ocr` optional). `capture_recorder.js`/Node removed; setup_tools says no Node.
- Blur strength recommendation: keep the strength rule as a floor; fix the matcher. With a positive-control string (OCR of the raw crop), count a hit only if the blurred text shares a run (>=4 chars or >=50% similarity) with it; keep generic only when no control exists. Optionally raise boxblur to ceil(h/3) and default secrets to opaque.
- Good: spec no longer on disk, temp dir removed in `finally`, regex dialect check, fail-closed `no-samples`.
- Needs security review: R-15 (raw video on crash path not ignored).
