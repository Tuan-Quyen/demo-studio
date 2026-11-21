# Platform: web

Playwright for Python + chromium (`setup_tools.py --stage capture`). capture-operator runs `capture.py`; the scene function `sNN(ctx)` uses `ctx.page` and `ctx.mark()`.

- Viewport 1920x1080 by default (`--viewport WxH`); web recordings are 25 fps at the viewport size.
- Prefer locators `get_by_role`, `get_by_test_id`, `get_by_label`; CSS last.
- Seeded account: log in at the start of each scene or reuse a saved storage state from the app-scout notes.
- Cookie banners, chat widgets, update popups: dismiss in the scene's setup before the first action.
- iframes: `page.frame_locator(...)`; masks apply to the main page and same-origin frames.
- Slow pages: `wait_for` an element, then act; set `--timeout` for long scenes.
