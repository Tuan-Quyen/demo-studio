Verdict: FAIL · Round 1

# p0-web — security

> Owner: **team-security**. PASS = no `open` blocking finding. Findings are cumulative: an ID (`S-01`…) is never reused; status open → fixed → verified (or dropped, with the reason). Never write secret values.
> **Budget:** ≤ 80 lines. Cells ≤ 25 words. **Round detail** ≤ 8 lines, replaced each round; verified/dropped findings collapse to one `Closed:` line of IDs.

## Scope
- In scope: `git diff e52fe88..HEAD -- plugins` (scripts, agents, templates); design §6, §6.5
- Trust boundaries: app DOM → mask log → pixel gate → `#events.masked`; raw clip → blur/verify → `#checks.pass` → QA/G3; argv/config → runs.jsonl, media/, git
- Scanners: `pytest tests/test_privacy_mask.py` ×3 → 22 pass/1 skip each; synthetic `eval_group` probe; 2 scratch capture runs (modal fixture) → silent leak reproduced
- Skipped: gitleaks/osv not installed; desktop/mobile (P0-native)

## Findings
| ID | Severity | Where | Class | Attack scenario | Fix direction | Found | Status |
|---|---|---|---|---|---|---|---|
| S-01 | blocking | `privacy_mask.js:327-330,363,371` | false pass | Hit-testable backdrop (modal, opacity fade) marks items hidden: overlays not drawn, no rects logged. Repro: emails readable whole clip, `ok masked:true rect_checks:0` | Never infer occlusion from elementFromPoint for overlays; draw always; fail gate when rect_checks=0 or hidden items exist | R1 | open |
| S-02 | blocking | `capture.py:222-223` | false pass | Nearest entry shows glyph edges (bad), any entry ≤260 ms away over plain background returns `soft` → frame passes. Synthetic probe confirmed | `bad` within narrow window is decisive unless strict match there; soft/resync count toward fail threshold | R1 | open |
| S-03 | blocking | `capture_recorder.js:177-186`; `capture.py:432-480` | stale state | Re-shoot overwrites `sNN.raw.webm`, then final-assert fail / ffprobe / calibration error: #events keeps old `masked:true` for the unverified file | Record to temp name; rename and write #events only after gate passes; else delete and set masked:false | R1 | open |
| S-04 | blocking | `checks.py:184-214,432`; `blur.py:1100` | stale verdict | `#checks.blur`/`pass` not bound to the final file; re-render or crashed verify keeps an old pass; `--only` reuses old results | Store sha/fingerprint of final video in verdict; checks.py rejects mismatch; verify writes `pass:false` first | R1 | open |
| S-05 | should-fix | `blur.py:963-976,1062,1081` | false pass | Seeded, no regions → zero samples → `pass`. Full-frame tier has no positive control: OCR returning nothing passes | Verdict `incomplete` when total=0; positive control (known rendered text) for full-frame matcher | R1 | open |
| S-06 | should-fix | `capture.py:224-226,189-192` | false pass | Edge grace and lead-in turn `bad` and `state:unmasked` into `empty`; one-frame flashes and pre-scene frames unchecked; timeline `in` < offset_ms not enforced | state:unmasked never graced; grace only for colour, not glyph edges; enforce `in ≥ offset_ms` | R1 | open |
| S-07 | should-fix | `privacy_mask.js:257,455-464`; `capture.py:454,470` | silent gap | Shadow DOM, iframes, canvas, pseudo `content`, broken-img alt: not masked, not listed. `unmaskable[]` lacks bbox/t and never affects status/checks | Detect these surfaces near sensitive data → unmaskable with bbox/t; non-empty unmaskable → masked:false + needs-input | R1 | open |
| S-08 | should-fix | `privacy_mask.js:221-227`; `capture_recorder.js:81` | leak | `type` action shows value prefix until regex matches; gate has no entry so passes | Pre-match action text against regexes in capture.py; mask target from first key or refuse | R1 | open |
| S-09 | should-fix | `privacy_mask.js:339,371`; `capture.py:53` | weak oracle | Overlay rect and logged rect share one source: gate proves overlay painted, not text covered; mask rAF runs first, overlays lag app/scroll rAF one frame | Log post-layout rects (late callback) independent of overlay; prefer Highlight; measured resync 0–32/132 frames unstable | R1 | open |
| S-10 | should-fix | `capture_recorder.js:190-198`; `capture.py:412,427` | retention | Timeout/error leaves `tmp-video/` (unverified raw) and `<sid>.spec.json` (regexes, typed text) in media/ | try/finally cleanup of tmp-video and spec on every exit path | R1 | open |
| S-11 | should-fix | `config.py:139`; `templates/gitignore` | retention | `raw_retention` never enforced; gitignore template never applied, misses spec.json, tmp-video/, runs.jsonl, *.schema1.bak, cache/ | Implement deletion at delivery; init copies/merges gitignore; add missing paths | R1 | open |
| S-12 | should-fix | `blur.py:1244-1247`; `capture.py:395-402` | secrets in logs | `verify --pattern` literals and capture `--url` tokens unredacted; `--rege=` abbreviation bypasses redaction | Redact all --pattern/--regex/--url query; argparse `allow_abbrev=False` | R1 | open |
| S-13 | should-fix | `project.py:394-417` | stale verdict | `migrate` keeps schema-1 `#checks.pass:true` (agent-written) → QA passes without new verify | Migrate resets `checks` (or pass=false, needs re-run) | R1 | open |
| S-14 | suggestion | `blur.py:1022-1037` | key handling | Key written before chmod 600 (umask window); `.secret/` dir default perms | `os.open(O_CREAT|O_EXCL, 0o600)`; mkdir mode 0o700 | R1 | open |
| S-15 | suggestion | `checks.py:363-373`; `capture.py:470` | weak gate | Clips with masked:false / blur style / rect_checks 0 pass `privacy_capture`; blur style fixed 10 px regardless of font | Report and require blur coverage for masked:false clips; scale blur_px | R1 | open |
| S-16 | suggestion | `project.py:368-376` | authz | `writer` is self-declared; any importer can pass "checks.py" or call store_key | Acceptable for P0; enforce via hook (P1 §4.3) | R1 | open |

Closed: none

## Round detail (latest round only)
- Round: R1 · 2026-11-21 · full review of P0-web diff
- Open blocking: 4 (S-01..S-04)
- No shell/filter-graph injection found: all subprocesses list-argv; graph uses numeric values and `tr%d` names; only CLI `--in/--out-label` raw
- blur plan never shrinks coverage except capture-mask regions on `masked:true` clips (amplifies S-01/S-03)
- Hits store region/t/match_len (+16-hex HMAC); no raw PII in #checks
- Repro files: scratchpad `exp/modal2.html` (fake data)
