"""Scene scripts for ai-video-trends-v2 (platform: web, Playwright sync API).

Action-only (platform-automation contract): exports SCENES and prepare(sid, page).
No recorder, viewport, fps or DND code here (capture-operator owns those).
All waiting inside a scene uses ctx.hold_until() or a wait for an app state.
Logs go to stderr only; stdout carries markers from ctx.mark().

Timing: scene length = storyboard duration (VO + hold), within vo_ms+400..vo_ms+1500.
  s01 7000 (vo 5950) · s02 6000 (vo 5090) · s03 9000 (vo 7510) · s04 6000 (vo 5040) · s05 10000 (vo 8580)
"""
import json, sys, time

APP = "http://localhost:5173"
PILL = "signed-in-pill"          # app-map SENSITIVE (email), sticky header: in every frame
API_KEY = "api-key"              # app-map SENSITIVE (token), must stay off-screen in s04
REST = (640, 380)                # neutral cursor rest point used at the start of every scene
SCENE_LEN = {"s01": 7000, "s02": 6000, "s03": 9000, "s04": 6000, "s05": 10000}


class StepError(Exception):
    """Selector/step failure (failure class `step`, exit 10)."""


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- reference core (platform-automation SKILL.md, verbatim) ----------
TAIL_MS = 400                         # keep scene alive after VO ends
class Ctx:
    def __init__(self, scene, target, vo_ms, scale=1.0, origin=(0, 0), dry=False):
        self.scene, self.target, self.vo_ms = scene, target, vo_ms
        self.scale, self.origin, self.dry = scale, origin, dry
        self._t0, self._virt = time.monotonic(), 0
    def now(self):                    # ms since scene start (virtual clock in dry-run)
        return max(int((time.monotonic() - self._t0) * 1000), self._virt)
    def _bbox(self, b):
        if b is None: return None
        ox, oy = self.origin
        return [round((b[0]-ox)*self.scale), round((b[1]-oy)*self.scale),
                round(b[2]*self.scale), round(b[3]*self.scale)]
    def mark(self, type, bbox=None, label=""):
        print(json.dumps({"t": self.now(), "scene": self.scene, "type": type,
                          "bbox": self._bbox(bbox), "label": label}), flush=True)
    def sensitive(self, bbox, label): self.mark("sensitive", bbox, label)
    def sensitive_end(self, label):   self.mark("sensitive", None, label)
    def hold_until(self, ms):         # the ONLY way to wait; never bare sleep()
        if self.dry: self._virt = max(self._virt, ms); return
        left = ms - self.now()
        if left > 0: time.sleep(left / 1000)
    def start(self): self._t0 = time.monotonic(); self.mark("scene_start")
    def end(self):
        self.hold_until(self.vo_ms + TAIL_MS); self.mark("scene_end")


# ---------- helpers ----------
def _box(locator, what):
    b = locator.bounding_box()
    if not b or b["width"] <= 0 or b["height"] <= 0:
        raise StepError(f"no visible box for {what}")
    return [b["x"], b["y"], b["width"], b["height"]]


def _scroll(page):
    return page.evaluate("[scrollX, scrollY]")


def glide_click(ctx, locator, label):
    """web.md glide_click; scrolls only when the target is off-screen, and fails
    (step) if an in-viewport target moved the page before its click."""
    page = ctx.target
    locator.wait_for(state="visible")
    b = locator.bounding_box()
    vh = page.viewport_size["height"]
    if b["y"] < 0 or b["y"] + b["height"] > vh:
        locator.scroll_into_view_if_needed(); b = locator.bounding_box()
    before = _scroll(page)
    cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    page.mouse.move(cx, cy, steps=25)
    b2 = locator.bounding_box()
    if _scroll(page) != before or abs(b2["y"] - b["y"]) > 1:
        raise StepError(f"page moved before click on {label}")
    ctx.mark("click", [b["x"], b["y"], b["width"], b["height"]], label)
    page.mouse.click(cx, cy)


def glide_to(ctx, locator, steps=30):
    """Cursor travel to an element without clicking (attention pointer)."""
    b = _box(locator, "glide target")
    ctx.target.mouse.move(b[0] + 40, b[1] + b[3] / 2, steps=steps)


def mark_pill(ctx):
    ctx.sensitive(_box(ctx.target.get_by_test_id(PILL), PILL), "signed-in email")


def guard_api_key(ctx):
    """Safety net: if the API key ever enters the viewport, mark it sensitive."""
    page = ctx.target
    b = page.get_by_test_id(API_KEY).bounding_box()
    vh = page.viewport_size["height"]
    if b and b["y"] < vh and b["y"] + b["height"] > 0:
        log(f"[{ctx.scene}] WARN api-key in frame at y={b['y']:.0f}; marked sensitive")
        ctx.sensitive([b["x"], b["y"], b["width"], b["height"]], "API key")
        return True
    return False


def _settle_scroll(page, timeout=3000):
    page.wait_for_function(
        """() => new Promise(r => { let y = scrollY, n = 0;
             const f = () => { if (scrollY === y) { if (++n >= 3) return r(true); }
                               else { y = scrollY; n = 0; } requestAnimationFrame(f); };
             requestAnimationFrame(f); })""", timeout=timeout)


def _fresh(page):
    """Fresh load = reset (filter 'All', modal closed, scrollY 0). Static app, re-runnable."""
    page.goto(APP, wait_until="networkidle")
    page.get_by_test_id("section-hero").wait_for()


def _jump(page, anchor, expect_y):
    page.evaluate(f"document.querySelector('{anchor}').scrollIntoView({{behavior:'instant'}})")
    _settle_scroll(page)
    y = page.evaluate("scrollY")
    if abs(y - expect_y) > 4:
        raise StepError(f"{anchor} jump landed at scrollY {y}, expected ~{expect_y}")


# ---------- prepare: start state before ctx.start(); nothing navigates after this ----------
def prepare(sid, page):
    _fresh(page)
    if sid == "s01":
        pass                                              # hero, scrollY 0
    elif sid == "s02":
        _jump(page, "#trending", 481)
        if page.get_by_test_id("chip-all").get_attribute("aria-pressed") != "true":
            raise StepError("s02 start: chip All not pressed")
    elif sid == "s03":                                    # end state of s02
        _jump(page, "#trending", 481)
        page.get_by_test_id("chip-faceless-youtube").click()
        page.wait_for_function("document.querySelector('#count').textContent.includes('Faceless YouTube')")
        page.wait_for_timeout(350)                        # 260 ms fade, then hidden
        page.get_by_test_id("card-v5").wait_for(state="visible")
    elif sid == "s04":
        _jump(page, "#trends", 1435)
    elif sid == "s05":
        _jump(page, "#genres", 2586)
    else:
        raise StepError(f"unknown scene {sid}")
    page.mouse.move(*REST)                                # cursor visible at a neutral spot
    _settle_scroll(page)


# ---------- scenes (actions only) ----------
def s01(ctx):
    """Hook: hero headline + sub-line; cursor drifts near 'Explore trends', no click."""
    page = ctx.target
    mark_pill(ctx)
    ctx.hold_until(2500)                                  # title card + zoom start over still hero
    glide_to(ctx, page.get_by_test_id("hero-cta"), steps=40)
    ctx.hold_until(SCENE_LEN["s01"])


def s02(ctx):
    """One tap filters the grid to Faceless YouTube."""
    page = ctx.target
    mark_pill(ctx)
    ctx.hold_until(1200)                                  # VO introduces the chips
    glide_click(ctx, page.get_by_test_id("chip-faceless-youtube"), "Faceless YouTube chip")
    page.wait_for_function("document.querySelector('#count').textContent.includes('1 video')")
    page.wait_for_timeout(300)                            # fade finishes (app state wait)
    page.get_by_test_id("card-v5").wait_for(state="visible")
    if page.get_by_test_id("chip-faceless-youtube").get_attribute("aria-pressed") != "true":
        raise StepError("chip not pressed after click")
    ctx.hold_until(SCENE_LEN["s02"])


def s03(ctx):
    """Open card-v5, scroll the modal to 'Why it trends', close with Esc."""
    page = ctx.target
    mark_pill(ctx)                                        # stays visible (dimmed) under the backdrop
    ctx.hold_until(700)
    glide_click(ctx, page.get_by_test_id("card-v5"), "card: 10 Habits of Calm Productive People")
    modal = page.get_by_test_id("modal")
    modal.wait_for(state="visible")
    page.locator("#m-prompt").wait_for(state="visible")
    ctx.hold_until(4000)                                  # Prompt example + Tool category on screen
    card = _box(page.locator(".modal-card"), "modal card")
    page.mouse.move(card[0] + card[2] / 2, card[1] + card[3] * 0.6, steps=15)
    page.mouse.wheel(0, 160)                              # in-card scroll to 'Why it trends'
    page.wait_for_function("(()=>{const c=document.querySelector('.modal-card');"
                           "return c.scrollTop + c.clientHeight >= c.scrollHeight - 1})()")
    why = _box(page.locator("#m-why"), "#m-why")
    if why[1] + why[3] > 720:
        raise StepError("#m-why still clipped after in-card scroll")
    if _scroll(page) != [0, 481]:
        raise StepError("page scrolled behind the modal")
    ctx.hold_until(7400)                                  # read 'Why it trends'
    ctx.mark("key", None, "Esc closes the modal")
    page.keyboard.press("Escape")
    page.wait_for_function("document.querySelector('[data-testid=modal]').hidden")
    ctx.hold_until(SCENE_LEN["s03"])


def s04(ctx):
    """Trend cards, then instant scroll ~+330 px to the genre growth chart (API key off-screen)."""
    page = ctx.target
    mark_pill(ctx)
    guard_api_key(ctx)
    page.get_by_test_id("trend-t1").wait_for(state="visible")
    ctx.hold_until(2000)                                  # wide on the 4 trend cards
    page.mouse.wheel(0, 330)                              # headless wheel lands in ~70 ms (instant)
    _settle_scroll(page)
    y = page.evaluate("scrollY")
    if not (1700 <= y <= 1800):
        raise StepError(f"s04 scroll landed at {y}, want 1700..1800")
    chart = _box(page.get_by_test_id("genre-chart"), "genre-chart")
    if chart[1] < 64 or chart[1] + chart[3] > 720:
        raise StepError(f"genre chart not fully in frame: {chart}")
    guard_api_key(ctx)
    ctx.hold_until(SCENE_LEN["s04"])


def s05(ctx):
    """Ranked genres; cursor rests on rank-1 Faceless YouTube. End card is added in post."""
    page = ctx.target
    mark_pill(ctx)
    page.get_by_test_id("rank-5").wait_for(state="visible")
    ctx.hold_until(2500)                                  # wide on the list
    glide_to(ctx, page.get_by_test_id("rank-1"), steps=35)
    ctx.hold_until(SCENE_LEN["s05"])


SCENES = {"s01": s01, "s02": s02, "s03": s03, "s04": s04, "s05": s05}
