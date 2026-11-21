// Scene script for the electron-app fixture (platform-automation contract): actions + ctx.mark() only.
const SMOOTH_EL = ({ sel, to, ms }) => new Promise((res) => {
  const el = document.querySelector(sel), from = el.scrollTop, t0 = performance.now();
  const f = (n) => { const k = Math.min(1, (n - t0) / ms); el.scrollTop = from + (to - from) * k; k < 1 ? requestAnimationFrame(f) : res(); };
  requestAnimationFrame(f);
});

module.exports = {
  scenes: {
    s01: async (ctx) => {
      const page = ctx.target;
      ctx.sensitive(await page.locator('#hdr-email').boundingBox(), 'header email');
      await ctx.holdUntil(400);
      await page.evaluate(SMOOTH_EL, { sel: '#list', to: 700, ms: 4200 });   // passes the email row and the API key
      await page.locator('#toast').waitFor({ state: 'visible' });             // late toast with an email
      await page.evaluate(SMOOTH_EL, { sel: '#list', to: 350, ms: 1800 });
      ctx.mark('click', await page.locator('#hdr').boundingBox(), 'header');
      await ctx.holdUntil(6800);
    },
  },
};
