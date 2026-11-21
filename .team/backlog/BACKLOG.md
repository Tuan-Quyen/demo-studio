# Backlog (non-blocking findings, per redesign §8.0 rule 1)

Source reports: `.team/reports/p0-web/review.md`, `.team/reports/p0-web/security.md`.

| ID | Area | Issue | Known risk | Notes |
|---|---|---|---|---|
| S-19 | capture gate | A strict entry within `NEAR_MS` (37 ms) rescues a bad one; an overlay 2–3 rAF late at a jump passes (probes E, E3) | Short leak (2–3 frames) possible for inputs/boxes in nested scrollers | Partial fix in `s19-s26-partial.patch` (untested; agent stopped mid-edit) |
| S-26 | capture gate | Carry anchor can be a non-strict frame; probe D2 carries 6 readable frames | Short leak (≤ `CARRY_MAX` = 6 frames) | Same patch |
| S-27 | capture gate | Appear/disappear-edge soft frames become carry anchors; soft count too low | Uniform frames only; nothing readable found | Same patch |
| S-29 | capture | Top-layer re-show keyed on element count; carry compares only first 400 rects | Low | — |
| S-24 (rest) | checks | `config.py accept` is a command any agent can call; hard enforcement needs a hook guarding `privacy.accepted` | Agent self-approval | Planned for P1 hooks |
| S-16 | project | `write_checks` writer name is self-declared | Low | Accepted for P0 |
| R-16 (rest) | blur verify | Partial OCR read under 4 matching chars dropped for non-secret regions | Low | Secret regions already fail toward leak |
| — | capture | Untested surfaces: native `<select>` popups, autofill, background-image text, WebGL, cross-document navigation mid-scene, headed mode; fast scroll can freeze Chromium screencast (gate then fails) | Documented in `web.md` | — |
| — | design | Blur strength rule `ceil(h/4)` validated on one font only | False positives | Re-measure on real apps |

Mitigation while open: web capture fails closed on every confirmed repro; `blur.py verify` + `checks.py` still OCR every output once.
