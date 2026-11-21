# Review v0.4 lean (single combined round)

Verdict: FAIL (1 blocker, small fix). Everything else PASS.
Evidence: pytest 43 passed (OCR venv); ast.parse feature_version=3.10 ok for all 6 scripts; no match/except*/tomllib; setup_tools uses `from __future__ import annotations`; CI matrix 3.10 + 3.12. Manual capture run: `#secret` input value and a node inserted 300 ms after load (`.late`) are both blacked out; unmasked run shows both.

## Blockers
B1 scripts/setup_tools.py:~228-250 (CAPABILITIES["motion"], feature "motion-cinematic" = Remotion/Node 400 MB), STAGES "motion" (choices motion) and "render" (optional motion-cinematic, "Remotion render"); toolsmith runs `--options motion`, which names setting `motion.level`.
- Remotion was removed in 0.4 (LEAN "Bỏ"), render.py cannot use it. Toolsmith can propose a 400 MB install that nothing consumes.
- common.py:122 `top` has no `motion` key, so a recorded `motion.level` makes load_config raise: render.py and verify.py exit 2 on every run. motion-designer.md ("Motion level `none` in demo.yaml: zooms []") also points at this nonexistent key.
- Fix: delete motion-cinematic, the `motion` capability and the render optional; stage motion = needs ["capture"] (no choices); drop the "motion" mention from the setup_tools docstring/`--options` help; remove the "Motion level" sentence in agents/motion-designer.md (cards null / zooms [] decided from storyboard). Adjust test_setup_tools if it asserts motion.
- Same family, not blocking: example/.demo/ai-video-trends-v2/demo.yaml has `install`/`motion` keys, so load_config rejects it (see backlog 5).

## Checked, no finding
1. CLI consistency: capture.py flags/exit (0/2/3), render.py (--slug --aspect --root --timeout --burn-in; 0/2/3), verify.py (0/11/3/2), vo.py trim/join/check (check exit 1) and setup_tools modes all match agent/command/skill text. Each agent writes only its LEAN.md file; director pipeline = new.md = LEAN flow; routing table owners match demo-qa/fix.md owners.
2. capture.py: init-script CSS covers text, input value (`-webkit-text-fill-color`), svg fill, caret; re-added by MutationObserver and on DOMContentLoaded; works in all frames. verify.py: one ffmpeg decode per file, OCR built once, deadline checked per frame + killpg timer + 15 s hard guard, only `pattern_id`/t_ms printed, seeded mode never loads seed_values, leak beats incomplete in exit code, missing OCR fails closed (3). render.py: sibling merge (motion/captions/mix) correct, input indices (clips, vo, music) correct, loudnorm 2-pass once. common._run: start_new_session + killpg(SIGKILL) + rc 124, `-nostdin` for ffmpeg (test_run_timeout_kills_group passes).
3. Stages for blur/web_adapter/project.json/hooks are gone (only Remotion left, B1). `.demo/.venv` matches Ctx default and toolsmith.md.

## Backlog (none blocks delivery)
1. verify.py:scan: a killed/short decode returns finished=True; only the 90% sample check catches it. Make `done` false when the kill timer fired.
2. verify.py DEFAULTS email regex flags any non-example.com address, including invented ones (`ana@acme.io`): false FAIL. privacy-guard.md says use `@example.com`; add one line to demo-qa and the template saying seeded emails must use example.com
3. templates/demo.yaml + parse_yaml: block-list item `- [data-secret]` parses as a list, not a selector; tell agents to quote selectors (`- "[data-secret]"`) or use inline `["[data-secret]"]`. Same for patterns containing ` #`.
4. Preview runs: motion-designer/sync-editor are told to run `render.py --aspect 16x9`, which writes media/final-16x9.mp4 (render-engineer's file; verify then scans a stale preview). Use a scratch --root or delete after; or drop the "optional preview" lines.
5. example/: the app (index.html, app.js, data.js, README) is fine and used as target. `example/.demo/ai-video-trends-v2/` is old-schema (project.json, `.demo.applied.json`, demo_ctx.py, blur owner); load_config rejects its demo.yaml. Not mentioned in README/LEAN so not misleading, but add one line to example/README.md: ".demo/ is a legacy 0.3 project, kept as reference; re-run from its storyboard" (or delete it).
6. media-specs/sound-mixer say render.py applies ducking and music fades; render.py does plain amix (no ducking/fades) and CRF 20 (spec says 18). Reword to match.
7. privacy-guard.md handoff `next: scriptwriter / capture-operator`: scriptwriter is not a leak-fix target; use `capture-operator (leak fix)` / `storyboarder`.
8. Mask limits worth one line in privacy-guard/platform-automation: shadow DOM, canvas, img/avatars and video are not hidden by CSS; OCR (layer 2) is the only catch there. test_capture_masks_selector does not cover input value or late nodes (verified by hand); add to the fixture when convenient.
9. Agents run bare `python` for capture.py/render.py/verify.py; only demo-qa mentions the venv interpreter. Add "use `setup_tools.py --python`" to capture-operator/render-engineer.
10. OCR input is RGB ndarray fed to RapidOCR (expects BGR); harmless for text, mention only.
