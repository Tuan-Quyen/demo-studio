"""Extra scenes for the capture tests (platform-automation contract: actions + mark() only)."""


def short(ctx):
    ctx.target.wait_for_timeout(1200)


def typed(ctx):
    p = ctx.target
    p.locator("#f").click()
    p.keyboard.type("123-45-6789", delay=60)       # SSN-like: must be masked before the first key
    p.wait_for_timeout(300)


def typed_unfocused(ctx):
    ctx.target.keyboard.type("123-45-6789")        # focus is on <body>: cannot be masked -> refused


def boom(ctx):
    raise RuntimeError("selector not found")


def hang(ctx):
    ctx.target.wait_for_selector("#does-not-exist")


def setval(ctx):                                # S-17: programmatic .value (no event, no mutation)
    p = ctx.target
    p.wait_for_timeout(500)
    p.evaluate("document.querySelector('#f').value='jane.doe@example.com'")
    p.wait_for_timeout(1500)


def setclear(ctx):                              # S-17: set, then cleared before the end (final rescan sees nothing)
    setval(ctx)
    ctx.target.evaluate("document.querySelector('#f').value=''")
    ctx.target.wait_for_timeout(300)


def dialog(ctx):                                # S-22: modal dialog (top layer), fading in
    p = ctx.target
    p.wait_for_timeout(400)
    p.evaluate("const d=document.querySelector('#d'); d.showModal(); requestAnimationFrame(()=>requestAnimationFrame(()=>d.classList.add('on')))")
    p.wait_for_timeout(2500)


def split(ctx):                                 # S-08: the secret typed in two calls
    p = ctx.target
    p.locator("#f").click()
    p.keyboard.type("jane.doe@exa", delay=40)
    p.wait_for_timeout(800)
    p.keyboard.type("mple.com", delay=40)
    p.wait_for_timeout(500)


def lpress(ctx):                                # S-08: Locator.press one key at a time
    p = ctx.target
    loc = p.locator("#f")
    for ch in "jane.doe@exa":
        loc.press(ch)
    p.wait_for_timeout(800)


def handle(ctx):                                # S-08: ElementHandle.type
    p = ctx.target
    p.query_selector("#f").type("jane.doe@exa", delay=30)
    p.wait_for_timeout(800)


def kdown(ctx):                                 # S-08: Keyboard.down / insert_text
    p = ctx.target
    p.locator("#f").click()
    for ch in "jane.doe@exa":
        p.keyboard.down(ch)
        p.keyboard.up(ch)
    p.keyboard.insert_text("mple.com")
    p.wait_for_timeout(500)


def canvases(ctx):                              # S-23: unmaskable surfaces inserted at different phases of the 250 ms poll
    p = ctx.target
    p.wait_for_timeout(600)
    for i in range(4):
        p.wait_for_timeout(97)
        p.evaluate("(i) => { const c = document.createElement('canvas'); c.id = 'c' + i; c.style.cssText = 'display:block;width:80px;height:30px'; document.body.appendChild(c); }", i)
        ctx.mark("key", None, "inserted c%d" % i)
    p.wait_for_timeout(600)


def dialog_swap(ctx):                           # S-29: one modal replaced by another in the same tick (count unchanged)
    p = ctx.target
    p.wait_for_timeout(400)
    p.evaluate("document.getElementById('a').showModal()")
    p.wait_for_timeout(700)
    p.evaluate("document.getElementById('a').close(); document.getElementById('b').showModal()")
    p.wait_for_timeout(1200)


SCENES = {"s01": short, "s02": typed, "s03": typed_unfocused, "s04": boom, "s05": hang, "s06": setval, "s07": dialog,
          "s08": split, "s09": lpress, "s10": handle, "s11": setclear, "s12": kdown, "s13": canvases, "s14": dialog_swap}
