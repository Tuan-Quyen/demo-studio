"""Scene scripts for ai-video-trends-v2, full tour s01-s10 (platform: web, Playwright sync API).

Action-only (platform-automation contract): exports SCENES and prepare(sid, page).
Ctx lives in demo_ctx.py (verbatim reference core). No recorder, viewport, fps or DND code.
Every wait inside a scene is ctx.hold_until() or a wait for an app state. Logs -> stderr.

Scene lengths = storyboard.md retime table (VO v9 + uncovered action + reading holds):
  s01 7000 · s02 10000 · s03 14000 · s04 8000 · s05 9000 · s06 10500 · s07 7500 · s08 14000 · s09 18000 · s10 10500
Beats are placed on the measured VO sentence times (project.json#voice sentences).

Verified live at 1280x720 (headless Chromium):
  - nav smooth scrolls settle in ~0.4-0.6 s; mouse.wheel lands in ~40 ms (instant).
  - s02: wheel +300 from scrollY 481 -> 781, card-v8 at y 283..565 (row 2 fully in frame).
  - s05: modal Close is position:absolute inside the scrolling .modal-card; after the in-card
    scroll it sits at y -16, so the card is scrolled back up before the visible Close click.
  - brand link "#top" does reach scrollY 0, but s10 uses a page scroll (storyboard action).
  - API key box at scrollY 2586 is y -35..7: it intersects the frame by 7 px under the 92%-opaque
    sticky header, so s08 (end), s09 and s10 (start) mark it; s06/s07 never intersect (guarded).
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo_ctx import Ctx  # noqa: E402,F401  (re-exported for adapters)

APP = "http://localhost:5173"
PILL, API_KEY = "signed-in-pill", "api-key"          # app-map SENSITIVE elements
SCENE_LEN = {"s01": 7000, "s02": 10000, "s03": 14000, "s04": 8000, "s05": 9000,
             "s06": 10500, "s07": 7500, "s08": 14000, "s09": 18000, "s10": 10500}
# cursor rest point per scene start (continuity with the previous scene's end)
REST = {"s01": (640, 380), "s02": (290, 459), "s03": (640, 420), "s04": (110, 208),
        "s05": (640, 450), "s06": (640, 420), "s07": (1080, 300), "s08": (640, 420),
        "s09": (300, 336), "s10": (300, 640)}


class StepError(Exception):
    """Selector/step failure (failure class `step`, exit 10)."""


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- helpers ----------
def _vp(page):
    v = page.viewport_size
    return v["width"], v["height"]


def _box(locator, what):
    b = locator.bounding_box()
    if not b or b["width"] <= 0 or b["height"] <= 0:
        raise StepError(f"no visible box for {what}")
    return [b["x"], b["y"], b["width"], b["height"]]


def _scroll(page):
    return page.evaluate("[scrollX, scrollY]")


def _in_frame(page, b):
    w, h = _vp(page)
    return b[0] >= 0 and b[1] >= 0 and b[0] + b[2] <= w and b[1] + b[3] <= h


def glide_click(ctx, locator, label):
    """web.md glide_click without any scroll_into_view (all targets are in view by design,
    incl. the sticky header nav); fails `step` if the page moves before the click."""
    page = ctx.target
    locator.wait_for(state="visible")
    b = _box(locator, label)
    if not _in_frame(page, b):
        raise StepError(f"click target off-screen: {label} {b}")
    before = _scroll(page)
    cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
    page.mouse.move(cx, cy, steps=25)
    b2 = _box(locator, label)
    if _scroll(page) != before or abs(b2[1] - b[1]) > 1:
        raise StepError(f"page moved before click on {label}")
    ctx.mark("click", b2, label)
    page.mouse.click(cx, cy)


def glide_to(ctx, locator, dx=40, steps=30):
    """Attention pointer: cursor travels to an element, no click."""
    b = _box(locator, "glide target")
    ctx.target.mouse.move(b[0] + dx, b[1] + b[3] / 2, steps=steps)


def mark_pill(ctx):
    ctx.sensitive(_box(ctx.target.get_by_test_id(PILL), PILL), "signed-in email")


_api_last = {}


def api_check(ctx):
    """Mark the API key whenever its box intersects the frame (clipped to the frame);
    re-mark when it moves, sensitive_end when it leaves."""
    page = ctx.target
    w, h = _vp(page)
    b = page.get_by_test_id(API_KEY).bounding_box()
    box = None
    if b:
        x0, y0 = max(0, b["x"]), max(0, b["y"])
        x1, y1 = min(w, b["x"] + b["width"]), min(h, b["y"] + b["height"])
        if x1 - x0 >= 1 and y1 - y0 >= 1:
            box = [x0, y0, x1 - x0, y1 - y0]
    key = tuple(round(v) for v in box) if box else None
    last = _api_last.get(ctx.scene)
    if key != last:
        if box:
            ctx.sensitive(box, "API key")
        elif last is not None:
            ctx.sensitive_end("API key")
        _api_last[ctx.scene] = key
    return box is not None


def follow_scroll(ctx, timeout_ms=3000):
    """Wait until a (smooth) scroll settles, tracking the API key on every sample."""
    page = ctx.target
    y, still = None, 0
    for _ in range(int(timeout_ms / 10)):
        api_check(ctx)
        ny = page.evaluate("scrollY")
        still = still + 1 if ny == y else 0
        y = ny
        if still >= 4:
            return y
        if still:                                        # sample as fast as possible while moving
            page.wait_for_timeout(30)
    raise StepError(f"scroll did not settle (scrollY {y})")


def _settle(page):
    page.wait_for_function(
        """() => new Promise(r => { let y = scrollY, n = 0;
             const f = () => { if (scrollY === y) { if (++n >= 3) return r(true); }
                               else { y = scrollY; n = 0; } requestAnimationFrame(f); };
             requestAnimationFrame(f); })""", timeout=3000)


def _jump(page, anchor, expect_y):
    page.evaluate(f"document.querySelector('{anchor}').scrollIntoView({{behavior:'instant'}})")
    _settle(page)
    y = page.evaluate("scrollY")
    if abs(y - expect_y) > 4:
        raise StepError(f"{anchor} jump landed at scrollY {y}, expected ~{expect_y}")


def _filter(page, slug, expect):
    page.get_by_test_id(f"chip-{slug}").click()
    page.wait_for_function(f"document.querySelector('#count').textContent.includes({expect!r})")
    page.wait_for_timeout(350)                           # 260 ms fade, then hidden


def _count_is(page, text):
    page.wait_for_function(f"document.querySelector('#count').textContent.includes({text!r})")
    page.wait_for_timeout(300)                           # fade finishes before reading boxes


def _nav(ctx, name, expect_y):
    page = ctx.target
    glide_click(ctx, page.get_by_role("link", name=name, exact=True), f'nav "{name}"')
    y = follow_scroll(ctx)
    if abs(y - expect_y) > 4:
        raise StepError(f'nav "{name}" landed at scrollY {y}, expected ~{expect_y}')


# ---------- prepare: start state before ctx.start(); nothing navigates after this ----------
def prepare(sid, page):
    _api_last.pop(sid, None)
    page.goto(APP, wait_until="networkidle")             # fresh load = reset (All, modal closed, top)
    page.get_by_test_id("section-hero").wait_for()
    if sid in ("s01", "s02"):
        pass                                             # hero, scrollY 0
    elif sid in ("s03", "s04"):
        _jump(page, "#trending", 481)                    # All pressed, 8 videos
    elif sid in ("s05", "s06"):
        _jump(page, "#trending", 481)
        _filter(page, "faceless-youtube", "Faceless YouTube")
        if sid == "s05":                                 # popup open on card-v5
            page.get_by_test_id("card-v5").click()
            page.get_by_test_id("modal").wait_for(state="visible")
            page.get_by_test_id("modal-close").wait_for(state="visible")
            page.wait_for_timeout(400)                   # open animation settles
    elif sid == "s07":
        _jump(page, "#trends", 1435)
    elif sid == "s08":
        page.evaluate("scrollTo({top:1765, behavior:'instant'})")   # end of s07 (chart)
        _settle(page)
        if page.evaluate("scrollY") != 1765:
            raise StepError("s08 start: scrollY != 1765")
    elif sid in ("s09", "s10"):
        _jump(page, "#genres", 2586)
    else:
        raise StepError(f"unknown scene {sid}")
    page.mouse.move(*REST[sid])
    _settle(page)


# ---------- scenes (actions only) ----------
def s01(ctx):
    """Hook: title card over the hero (post), cursor drifts near 'Explore trends', no click."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)
    ctx.hold_until(2500)
    cta = _box(page.get_by_test_id("hero-cta"), "hero-cta")
    page.mouse.move(cta[0] + cta[2] + 60, cta[1] + cta[3] / 2, steps=40)
    ctx.hold_until(SCENE_LEN["s01"])


def s02(ctx):
    """Nav 'Trending' (real click), row 1; wheel +300 so row 2 (card-v8) is fully in frame."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)
    ctx.hold_until(550)
    _nav(ctx, "Trending", 481)
    if "8 videos" not in page.locator("#count").inner_text():
        raise StepError("s02: count is not 8 videos")
    ctx.hold_until(5600)                                 # row 1 + count, under both VO lines
    page.mouse.wheel(0, 300)
    y = follow_scroll(ctx)
    v8 = _box(page.get_by_test_id("card-v8"), "card-v8")
    if y != 781 or not _in_frame(page, v8) or v8[1] < 64:
        raise StepError(f"s02: row 2 not fully in frame (scrollY {y}, card-v8 {v8})")
    ctx.hold_until(SCENE_LEN["s02"])


def s03(ctx):
    """Chips Music video -> Anime -> All, hold on each result."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)
    ctx.hold_until(1000)
    glide_click(ctx, page.get_by_test_id("chip-music-video"), "Music video chip")
    _count_is(page, "1 video")
    page.get_by_test_id("card-v3").wait_for(state="visible")
    ctx.hold_until(5000)
    glide_click(ctx, page.get_by_test_id("chip-anime"), "Anime chip")
    _count_is(page, "1 video")
    page.get_by_test_id("card-v8").wait_for(state="visible")
    ctx.hold_until(9000)
    glide_click(ctx, page.get_by_test_id("chip-all"), "All chip")
    _count_is(page, "8 videos")
    if _scroll(page) != [0, 481]:
        raise StepError("s03: page scrolled")
    ctx.hold_until(SCENE_LEN["s03"])


def s04(ctx):
    """Chip Faceless YouTube, then open card-v5 (popup with Prompt example + Tool category)."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)                       # pill stays (dimmed) under the backdrop
    ctx.hold_until(600)
    glide_click(ctx, page.get_by_test_id("chip-faceless-youtube"), "Faceless YouTube chip")
    _count_is(page, "Faceless YouTube")
    page.get_by_test_id("card-v5").wait_for(state="visible")
    ctx.hold_until(2600)
    glide_click(ctx, page.get_by_test_id("card-v5"), "card: 10 Habits of Calm Productive People")
    page.get_by_test_id("modal").wait_for(state="visible")
    for sel in ("#m-prompt", "#m-tool"):
        b = _box(page.locator(sel), sel)
        if not _in_frame(page, b):
            raise StepError(f"s04: {sel} not in frame {b}")
    ctx.hold_until(SCENE_LEN["s04"])


def s05(ctx):
    """In-card scroll to 'Why it trends'; scroll back so Close is on screen; click Close."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)
    card = _box(page.locator(".modal-card"), "modal card")
    ctx.hold_until(500)
    page.mouse.move(card[0] + card[2] / 2, card[1] + card[3] * 0.62, steps=15)
    page.mouse.wheel(0, 160)
    page.wait_for_function("(()=>{const c=document.querySelector('.modal-card');"
                           "return c.scrollTop + c.clientHeight >= c.scrollHeight - 1})()")
    if not _in_frame(page, _box(page.locator("#m-why"), "#m-why")):
        raise StepError("s05: #m-why still clipped")
    ctx.hold_until(4800)                                 # read 'Why it trends' (VO line 1 ends 3.43 s)
    page.mouse.wheel(0, -160)                            # Close is absolute in the card: bring it back
    page.wait_for_function("document.querySelector('.modal-card').scrollTop === 0")
    glide_click(ctx, page.get_by_test_id("modal-close"), "Close button")
    page.wait_for_function("document.querySelector('[data-testid=modal]').hidden")
    page.get_by_test_id("card-v5").wait_for(state="visible")
    if _scroll(page) != [0, 481]:
        raise StepError("s05: page scrolled behind the modal")
    ctx.hold_until(SCENE_LEN["s05"])


def s06(ctx):
    """Nav 'Trends' (real click); cursor across trend cards t1 -> t4."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)
    ctx.hold_until(550)
    _nav(ctx, "Trends", 1435)
    for i, at in zip(range(1, 5), (4300, 5600, 6900, 8200)):   # VO line 3 lists the techniques
        ctx.hold_until(at)
        glide_to(ctx, page.get_by_test_id(f"trend-t{i}"), dx=137, steps=30)
    api_check(ctx)
    ctx.hold_until(SCENE_LEN["s06"])


def s07(ctx):
    """Wheel +330 to the genre growth chart; API key stays below the frame."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)
    ctx.hold_until(600)
    page.mouse.wheel(0, 330)
    y = follow_scroll(ctx)
    chart = _box(page.get_by_test_id("genre-chart"), "genre-chart")
    if y != 1765 or chart[1] < 64 or not _in_frame(page, chart):
        raise StepError(f"s07: chart not fully in frame (scrollY {y}, chart {chart})")
    ctx.hold_until(SCENE_LEN["s07"])


def s08(ctx):
    """Nav 'Genres' (real click; API key passes through the frame); cursor on rank-1, rank-2."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)
    ctx.hold_until(550)
    _nav(ctx, "Genres", 2586)
    page.get_by_test_id("rank-5").wait_for(state="visible")
    ctx.hold_until(1500)                                 # rank-1 line starts 1.58 s
    glide_to(ctx, page.get_by_test_id("rank-1"))
    ctx.hold_until(6800)                                 # rank-2 line starts 6.93 s
    glide_to(ctx, page.get_by_test_id("rank-2"))
    ctx.hold_until(SCENE_LEN["s08"])


def s09(ctx):
    """Cursor down ranks 3, 4, 5 on the VO lines; no clicks."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)                       # API key 7 px under the header strip
    for i, at in ((3, 500), (4, 4900), (5, 9400)):
        ctx.hold_until(at)
        glide_to(ctx, page.get_by_test_id(f"rank-{i}"))
    ctx.hold_until(SCENE_LEN["s09"])


def s10(ctx):
    """Page scroll up to the hero (wheel steps, API key in transit), click 'Explore trends'."""
    page = ctx.target
    mark_pill(ctx); api_check(ctx)
    t = 500
    for _ in range(12):                                  # ~1.4 s of visible scrolling, 2586 -> 0
        ctx.hold_until(t)
        prev = page.evaluate("scrollY")
        page.mouse.wheel(0, -230)
        page.wait_for_function(f"scrollY !== {prev}", timeout=2000)
        api_check(ctx)
        t += 120
    y = follow_scroll(ctx)
    if y != 0:
        raise StepError(f"s10: did not reach the hero (scrollY {y})")
    ctx.hold_until(4500)                                 # hero hold, then the CTA click
    glide_click(ctx, page.get_by_test_id("hero-cta"), "Explore trends button")
    y = follow_scroll(ctx)                               # glides to Trends; API key in transit
    if abs(y - 1435) > 4:
        raise StepError(f"s10: CTA landed at scrollY {y}, expected ~1435")
    ctx.hold_until(SCENE_LEN["s10"])


SCENES = {"s01": s01, "s02": s02, "s03": s03, "s04": s04, "s05": s05,
          "s06": s06, "s07": s07, "s08": s08, "s09": s09, "s10": s10}
