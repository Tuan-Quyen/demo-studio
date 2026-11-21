// Helper for test_privacy_mask.py: load a page with and without privacy_mask.js and report DOM differences.
// usage: node dom_check.js <url> <config.json>   -> one JSON line
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

async function snapshot(browser, url, cfg) {
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 700 } });
  if (cfg) {
    const js = fs.readFileSync(path.join(__dirname, '..', 'privacy_mask.js'), 'utf8');
    await ctx.addInitScript({ content: 'window.__DS_MASK_CONFIG = ' + JSON.stringify(cfg) + ';\n' + js });
  }
  const page = await ctx.newPage();
  const mut = [];
  await page.goto(url, { waitUntil: 'load' });
  if (cfg) {
    await page.waitForFunction('window.__dsMaskReady === true', null, { timeout: 5000 });
    // typing into an input must not add attributes either
    await page.fill('#note', 'ssn 123-45-6789').catch(() => {});
    await page.waitForTimeout(300);
  }
  const snap = await page.evaluate(() => {
    const kids = Array.from(document.documentElement.children).map((e) => e.tagName.toLowerCase());
    const attrs = (el) => Array.from(el.attributes).map((a) => a.name + '=' + a.value).sort().join('|');
    const all = Array.from(document.querySelectorAll('body, body *, head, head *')).map((e) => e.tagName + ':' + attrs(e));
    return { kids, root_attrs: attrs(document.documentElement), body_html: document.body.innerHTML, head_html: document.head.innerHTML,
             all, highlights: window.CSS && CSS.highlights ? (CSS.highlights.get('ds-mask') ? CSS.highlights.get('ds-mask').size : 0) : -1,
             adopted: document.adoptedStyleSheets.length };
  });
  await ctx.close();
  return snap;
}

(async () => {
  const [url, cfgPath] = process.argv.slice(2);
  const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  const browser = await chromium.launch();
  try {
    const base = await snapshot(browser, url, null);
    const masked = await snapshot(browser, url, cfg);
    process.stdout.write(JSON.stringify({
      base_children: base.kids, masked_children: masked.kids,
      root_attrs_same: base.root_attrs === masked.root_attrs,
      body_html_same: base.body_html === masked.body_html,
      head_html_same: base.head_html === masked.head_html,
      attrs_same: JSON.stringify(base.all) === JSON.stringify(masked.all),
      highlight_ranges: masked.highlights, adopted: masked.adopted,
    }) + '\n');
  } finally { await browser.close(); }
})().catch((e) => { process.stdout.write(JSON.stringify({ error: String(e) }) + '\n'); process.exit(70); });
