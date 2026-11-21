"""Scene for the webview fixture: scroll the inner list so the sensitive rows move (~2.5 s, slow (50 css px/s): the simulated recorder stamps frames +-40 ms)."""
SCROLL = """({to, ms}) => new Promise((res) => {
  const el = document.getElementById('list'), from = el.scrollTop, t0 = performance.now();
  const f = (n) => { const k = Math.min(1, (n - t0) / ms); el.scrollTop = from + (to - from) * k; k < 1 ? requestAnimationFrame(f) : res(); };
  requestAnimationFrame(f); })"""


def s01(ctx):
    page = ctx.target
    b = page.locator("#who").bounding_box()
    ctx.sensitive([b["x"], b["y"], b["width"], b["height"]], "header email")
    ctx.hold_until(400)
    page.evaluate(SCROLL, {"to": 90, "ms": 1800})
    ctx.hold_until(2400)


SCENES = {"s01": s01}
