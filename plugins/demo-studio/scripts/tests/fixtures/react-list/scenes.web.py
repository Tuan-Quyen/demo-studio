"""Scene script for the react-list fixture (platform-automation contract): actions + mark() only, no recorder code.
~5 s: window scroll down and back, inner list scroll, late toast (2 s after load), SSN-like text set into #note."""

SMOOTH = """({to, ms}) => new Promise((res) => {
  const from = window.scrollY, t0 = performance.now();
  const f = (n) => { const k = Math.min(1, (n - t0) / ms), e = (1 - Math.cos(Math.PI * k)) / 2; window.scrollTo(0, from + (to - from) * e); k < 1 ? requestAnimationFrame(f) : res(); };
  requestAnimationFrame(f); })"""
SMOOTH_EL = """({selector, to, ms}) => new Promise((res) => {
  const el = document.querySelector(selector), from = el.scrollTop, t0 = performance.now();
  const f = (n) => { const k = Math.min(1, (n - t0) / ms); el.scrollTop = from + (to - from) * k; k < 1 ? requestAnimationFrame(f) : res(); };
  requestAnimationFrame(f); })"""
SET_NOTE = """() => { const i = document.getElementById('note'); i.value = 'ssn 123-45-6789';
  i.dispatchEvent(new Event('input', {bubbles: true})); }"""


def s01(ctx):
    page = ctx.target
    b = page.locator("#hdr-email").bounding_box()
    ctx.sensitive([b["x"], b["y"], b["width"], b["height"]], "header email")
    page.wait_for_timeout(500)
    page.evaluate(SMOOTH, {"to": 500, "ms": 1600})
    page.evaluate(SMOOTH_EL, {"selector": "#inner", "to": 300, "ms": 800})
    page.wait_for_timeout(1500)
    page.evaluate(SET_NOTE)
    page.wait_for_timeout(300)


SCENES = {"s01": s01}
SCENES["s02"] = lambda ctx: (ctx.target.evaluate(SMOOTH, {"to": 300, "ms": 500}), ctx.target.wait_for_timeout(500))
