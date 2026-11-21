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


SCENES = {"s01": short, "s02": typed, "s03": typed_unfocused, "s04": boom, "s05": hang}
