"""Scene scripts: ai-video-trends-tour (platform web, Playwright sync API).

Action-only. Uses only ctx (target, vo_ms, mark, sensitive, sensitive_end, hold_until).
No recorder, fps, resolution or viewport code here (capture-operator owns that).

Adapter contract (capture-operator), per scene, in a fresh browser context:
    page = context.new_page()
    prepare(sid, page)     # goto + reach the scene's start state, OFF the clip
    ctx.start()            # scene_start, t = 0
    SCENES[sid](ctx)
    ctx.end()              # holds to vo_ms + 400 (already passed by the scene's own hold)

Scene length: each scene holds to min(storyboard duration, vo_ms + 1500).
Sensitive elements (app-map): signed-in email pill (every scene), API key (s03, s04).
They are tracked live: re-marked whenever their on-screen box changes, clipped to the
viewport, and closed with bbox null when they leave the frame. So the marks stay correct
for any viewport capture-operator chooses (API key enters frame in s03 at > 720 px height).
"""
import sys
import time

ENTRY = "http://localhost:5173"
SCROLL_PAD = 76          # CSS scroll-padding-top (sticky header)

PILL = ("[data-testid=signed-in-pill]", "signed-in email pill")
API_KEY = ("[data-testid=api-key]", "API key")

STORYBOARD_MS = {"s01": 7000, "s02": 14000, "s03": 8000, "s04": 11000}


class StepError(Exception):
    """Selector/step failure (error_class step, exit 10)."""


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def scene_end_ms(ctx):
    sid = getattr(ctx, "scene", None)
    sb = STORYBOARD_MS.get(sid, ctx.vo_ms + 400)
    return max(ctx.vo_ms + 400, min(sb, ctx.vo_ms + 1500))


# ---------- sensitive tracking ----------
class Sensitive:
    """Marks sensitive elements; re-marks on every box change while polling."""

    def __init__(self, ctx, items):
        self.ctx, self.items, self.last = ctx, items, {}

    def _boxes(self):
        page = self.ctx.target
        sels = [s for s, _ in self.items]
        return page.evaluate(
            """(sels) => { const W = innerWidth, H = innerHeight;
              return sels.map(s => { const e = document.querySelector(s);
                if (!e) return null; const r = e.getBoundingClientRect();
                const x0 = Math.max(0, r.left), y0 = Math.max(0, r.top);
                const x1 = Math.min(W, r.right), y1 = Math.min(H, r.bottom);
                if (x1 - x0 < 1 || y1 - y0 < 1) return null;
                return [Math.floor(x0), Math.floor(y0), Math.ceil(x1 - x0), Math.ceil(y1 - y0)]; }); }""",
            sels,
        )

    def update(self, force=False):
        for (sel, label), box in zip(self.items, self._boxes()):
            prev = self.last.get(label, "unset")
            if box == prev and not force:
                continue
            if box is None:
                if prev not in ("unset", None) or force:
                    self.ctx.sensitive_end(label)
            else:
                self.ctx.sensitive(box, label)
            self.last[label] = box


# ---------- helpers ----------
def wait_for(ctx, cond, what, timeout_ms=4000, sens=None):
    """Poll a DOM condition (callable -> bool); update sensitive marks meanwhile."""
    t_end = time.monotonic() + timeout_ms / 1000
    while True:
        if sens:
            sens.update()
        if cond():
            if sens:
                sens.update()
            return
        if time.monotonic() > t_end:
            raise StepError(f"timeout waiting for {what}")
        time.sleep(0.03)


def wait_scroll_settled(ctx, sel, what, sens=None, timeout_ms=4000):
    """Wait until page scroll stops and `sel` sits under the sticky header (or page end)."""
    page = ctx.target
    state = {"y": None, "same": 0}

    def settled():
        info = page.evaluate(
            """(s) => { const e = document.querySelector(s);
              return { y: scrollY, top: e ? e.getBoundingClientRect().top : null,
                       max: document.documentElement.scrollHeight - innerHeight }; }""",
            sel,
        )
        if info["top"] is None:
            raise StepError(f"element not found: {sel}")
        state["same"] = state["same"] + 1 if info["y"] == state["y"] else 0
        state["y"] = info["y"]
        at_target = abs(info["top"] - SCROLL_PAD) <= 3 or info["y"] >= info["max"] - 1
        return at_target and state["same"] >= 4

    wait_for(ctx, settled, what, timeout_ms, sens)


def glide_click(ctx, locator, label, sens=None):
    page = ctx.target
    locator.wait_for(state="visible", timeout=4000)
    locator.scroll_into_view_if_needed()
    b = locator.bounding_box()
    if not b or b["width"] < 1 or b["height"] < 1:
        raise StepError(f"no box for {label}")
    cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    page.mouse.move(cx, cy, steps=25)
    b = locator.bounding_box()                        # re-read right before the click
    cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    ctx.mark("click", [b["x"], b["y"], b["width"], b["height"]], label)
    page.mouse.click(cx, cy)
    if sens:
        sens.update()


def smooth_scroll_to(page, sel):
    page.locator(sel).evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'start'})")


def instant_scroll_to(page, sel):
    page.evaluate(
        """(s) => { const d = document.documentElement, e = document.querySelector(s);
          if (!e) throw new Error('not found: ' + s);
          const prev = d.style.scrollBehavior; d.style.scrollBehavior = 'auto';
          window.scrollTo(0, e.getBoundingClientRect().top + scrollY - %d);
          d.style.scrollBehavior = prev; }""" % SCROLL_PAD,
        sel,
    )


def nav(page, href):
    return page.locator(f'nav[aria-label="Primary"] a[href="{href}"]')


def count_text(page):
    return page.locator("#count").inner_text().strip()


# ---------- start states (called by the adapter BEFORE ctx.start(), not filmed) ----------
def _fresh(page):
    page.goto(ENTRY, wait_until="load")
    page.locator("[data-testid=signed-in-pill]").wait_for(state="visible")
    page.locator("#grid .card").first.wait_for(state="visible")


def _settle_instant(page, sel):
    instant_scroll_to(page, sel)
    page.wait_for_function(
        "(s) => Math.abs(document.querySelector(s).getBoundingClientRect().top - %d) <= 3" % SCROLL_PAD,
        arg=sel, timeout=4000,
    )


def prep_s01(page):
    _fresh(page)                                                  # Hero, scrollY 0


def prep_s02(page):
    _fresh(page)
    _settle_instant(page, "[data-testid=section-trending]")       # Trending at top


def prep_s03(page):
    _fresh(page)
    _settle_instant(page, "[data-testid=section-trending]")       # continuity with s02


def prep_s04(page):
    _fresh(page)
    _settle_instant(page, "[data-testid=genre-chart]")            # chart at top (s03 end)


PREPARE = {"s01": prep_s01, "s02": prep_s02, "s03": prep_s03, "s04": prep_s04}


def prepare(sid, page):
    PREPARE[sid](page)


# ---------- scenes ----------
def s01(ctx):
    """Hook: hold on Hero (~2 s), scroll down to the Trending grid, hold."""
    page = ctx.target
    sens = Sensitive(ctx, [PILL])
    sens.update(force=True)
    ctx.hold_until(2000)                                          # push-in on H1 (VO leads)
    smooth_scroll_to(page, "[data-testid=section-trending]")
    wait_scroll_settled(ctx, "[data-testid=section-trending]", "Trending in view", sens)
    if page.locator("#grid .card:not([hidden])").count() != 8 or not count_text(page).startswith("8 videos"):
        raise StepError(f"expected 8 cards / '8 videos · All', got {count_text(page)!r}")
    sens.update()
    ctx.hold_until(scene_end_ms(ctx))                             # hold on the grid


def s02(ctx):
    """Chip 'Faceless YouTube' -> card v5 -> modal; scroll modal to 'Why it trends'."""
    page = ctx.target
    sens = Sensitive(ctx, [PILL])
    sens.update(force=True)
    ctx.hold_until(700)
    chip = page.get_by_test_id("chip-faceless-youtube")
    glide_click(ctx, chip, "Faceless YouTube genre chip", sens)
    wait_for(ctx, lambda: chip.get_attribute("aria-pressed") == "true"
             and count_text(page) == "1 video · Faceless YouTube"
             and page.locator("#grid .card:not([hidden])").count() == 1,
             "filter Faceless YouTube applied", sens=sens)
    ctx.hold_until(3000)                                          # grid shrink beat
    card = page.get_by_test_id("card-v5")
    glide_click(ctx, card, "Video card v5", sens)
    modal = page.get_by_test_id("modal")
    wait_for(ctx, lambda: modal.is_visible() and modal.evaluate(
        "m => !m.hidden && parseFloat(getComputedStyle(m).opacity) > 0.99"), "detail modal open", sens=sens)
    for f in ("#m-title", "#m-meta", "#m-prompt", "#m-tool", "#m-why"):
        if not page.locator(f).inner_text().strip():
            raise StepError(f"modal field empty: {f}")
    sens.update(force=True)                                       # pill readable under backdrop
    ctx.hold_until(8500)                                          # title/meta -> prompt + tool
    mc = page.locator(".modal-card")
    mc.evaluate("c => c.scrollTo({top: c.scrollHeight, behavior: 'smooth'})")
    st = {"v": None, "n": 0}

    def modal_scrolled():
        v = mc.evaluate("c => [c.scrollTop, c.scrollHeight - c.clientHeight]")
        st["n"] = st["n"] + 1 if v == st["v"] else 0
        st["v"] = v
        return v[0] >= v[1] - 1 and st["n"] >= 3

    wait_for(ctx, modal_scrolled, "modal scrolled to Why it trends", sens=sens)
    wb = page.locator("#m-why").bounding_box()
    vh = page.viewport_size["height"] if page.viewport_size else 720
    if not wb or wb["y"] + wb["height"] > vh + 1:
        raise StepError("'Why it trends' not fully in view after modal scroll")
    sens.update()
    ctx.hold_until(scene_end_ms(ctx))                             # hold on Why it trends


def s03(ctx):
    """Header nav 'Trends' -> 4 trend cards (hold) -> chart to top (hold)."""
    page = ctx.target
    sens = Sensitive(ctx, [PILL, API_KEY])
    sens.update(force=True)                                       # API key: null if off-frame
    ctx.hold_until(600)
    glide_click(ctx, nav(page, "#trends"), "Header nav Trends", sens)
    wait_scroll_settled(ctx, "[data-testid=section-trends]", "Trends section in view", sens)
    if page.locator("[data-testid^=trend-t]").count() != 4:
        raise StepError("expected 4 trend cards")
    ctx.hold_until(3500)                                          # trend cards beat
    smooth_scroll_to(page, "[data-testid=genre-chart]")
    wait_scroll_settled(ctx, "[data-testid=genre-chart]", "chart at top", sens)
    if "(sample)" not in page.get_by_test_id("genre-chart").inner_text():
        raise StepError("chart caption '(sample)' missing")
    sens.update()
    ctx.hold_until(scene_end_ms(ctx))                             # hold on chart


def s04(ctx):
    """Header nav 'Genres' -> ranked list, dwell on rank 1. End card is added in render."""
    page = ctx.target
    sens = Sensitive(ctx, [PILL, API_KEY])
    sens.update(force=True)
    ctx.hold_until(600)
    glide_click(ctx, nav(page, "#genres"), "Header nav Genres", sens)
    wait_scroll_settled(ctx, "[data-testid=section-genres]", "Genres section in view", sens)
    if page.locator("[data-testid^=rank-]").count() != 5:
        raise StepError("expected 5 ranked genres")
    if not page.get_by_test_id("rank-1").is_visible():
        raise StepError("rank-1 not visible")
    sens.update()
    ctx.hold_until(scene_end_ms(ctx))                             # list + rank 1 dwell


SCENES = {"s01": s01, "s02": s02, "s03": s03, "s04": s04}
