"""Fixture scene script: function sNN(ctx), ctx.page, ctx.mark()."""


def s01(ctx):
    ctx.mark("start")
    ctx.page.wait_for_timeout(800)
    ctx.mark("end")
