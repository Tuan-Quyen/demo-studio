#!/usr/bin/env node
/*
 * capture_recorder.js - Node Playwright recorder driven by capture.py (never run `playwright install`).
 *
 *   node capture_recorder.js <spec.json>
 *
 * spec: { url, viewport:{width,height}, out_dir, name, mask:{enabled, selectors, regexes, mask_style,
 *         force_overlay, force_style_element}, actions:[...], probes:[css], preflight:true, sync:true,
 *         timeouts:{load_ms, assert_ms, step_ms, total_ms}, headless:true }
 * actions (each bounded by timeouts.step_ms): {op:"wait",ms} {op:"scroll",to,ms} {op:"scroll_el",selector,to,ms}
 *   {op:"click",selector} {op:"type",selector,text,delay} {op:"wait_for",selector} {op:"eval",js}
 *   {op:"mark",type,label,selector} {op:"goto",url}
 * stdout: ONE JSON line (result). stderr: JSON heartbeat every 2 s. Exit: 0 ok | 11 mask assertion failed
 * (leak, nothing kept) | 3 over budget | 2 bad spec | 70 environment/unexpected error.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const hb = (step) => process.stderr.write(JSON.stringify({ hb: Date.now(), step }) + '\n');
let current = 'init';
const timer = setInterval(() => hb(current), 2000);
timer.unref();

function withTimeout(p, ms, what) {
  let t;
  const to = new Promise((_, rej) => { t = setTimeout(() => rej(Object.assign(new Error('timeout: ' + what), { code: 'TIMEOUT' })), ms); });
  return Promise.race([p, to]).finally(() => clearTimeout(t));
}

const PROBE_JS = (sels) => `(() => {
  const S = ${JSON.stringify(sels)}; const out = (window.__dsProbe = []);
  const f = (ts) => { requestAnimationFrame(f); const t = performance.timeOrigin + ts;
    for (const s of S) { const e = document.querySelector(s); if (!e) continue; const b = e.getBoundingClientRect();
      if (b.width > 0) out.push({t, selector: s, rect: [b.left, b.top, b.width, b.height]}); } };
  requestAnimationFrame(f); })();`;

async function newContext(browser, spec, record) {
  const kw = { viewport: spec.viewport };
  if (record) kw.recordVideo = { dir: path.join(spec.out_dir, 'tmp-video'), size: spec.viewport };
  const ctx = await browser.newContext(kw);
  const sink = [];
  await ctx.exposeFunction('__dsMaskSink', (batch) => { for (const e of batch) sink.push(e); });
  if (spec.mask && spec.mask.enabled) {
    const cfg = Object.assign({}, spec.mask); delete cfg.enabled;
    const js = fs.readFileSync(path.join(__dirname, 'privacy_mask.js'), 'utf8');
    await ctx.addInitScript({ content: 'window.__DS_MASK_CONFIG = ' + JSON.stringify(cfg) + ';\n' + js });
  }
  if (spec.probes && spec.probes.length) await ctx.addInitScript({ content: PROBE_JS(spec.probes) });
  return { ctx, sink };
}

const maskOn = (spec) => !!(spec.mask && spec.mask.enabled);

async function waitReady(page, spec) {
  await withTimeout(page.waitForFunction('window.__dsMaskReady === true', null, { timeout: spec.timeouts.assert_ms }),
    spec.timeouts.assert_ms + 500, 'mask ready');
}
async function assertMask(page, spec) {
  await waitReady(page, spec);
  return withTimeout(page.evaluate('window.__dsMask.assertMasked()'), spec.timeouts.assert_ms, 'assertMasked');
}

async function runAction(page, a, spec, markers, t0) {
  const stepMs = spec.timeouts.step_ms;
  switch (a.op) {
    case 'wait': return page.waitForTimeout(Math.min(a.ms, stepMs));
    case 'scroll':
      return page.evaluate(({ to, ms }) => new Promise((res) => {
        const from = window.scrollY, t0 = performance.now();
        const f = (n) => { const k = Math.min(1, (n - t0) / ms); window.scrollTo(0, from + (to - from) * k); k < 1 ? requestAnimationFrame(f) : res(); };
        requestAnimationFrame(f);
      }), { to: a.to, ms: a.ms || 500 });
    case 'scroll_el':
      return page.evaluate(({ selector, to, ms }) => new Promise((res) => {
        const el = document.querySelector(selector); const from = el.scrollTop, t0 = performance.now();
        const f = (n) => { const k = Math.min(1, (n - t0) / ms); el.scrollTop = from + (to - from) * k; k < 1 ? requestAnimationFrame(f) : res(); };
        requestAnimationFrame(f);
      }), { selector: a.selector, to: a.to, ms: a.ms || 500 });
    case 'click': return page.click(a.selector, { timeout: stepMs });
    case 'type': return page.type(a.selector, a.text, { delay: a.delay || 60, timeout: stepMs });
    case 'wait_for': return page.waitForSelector(a.selector, { timeout: stepMs });
    case 'eval': return page.evaluate(a.js);
    case 'goto': return page.goto(a.url, { timeout: spec.timeouts.load_ms, waitUntil: 'domcontentloaded' });
    case 'mark': {
      let bbox = null;
      if (a.selector) { const b = await page.locator(a.selector).first().boundingBox({ timeout: stepMs }); if (b) bbox = [b.x, b.y, b.width, b.height]; }
      markers.push({ t: Date.now() - t0, type: a.type || 'mark', bbox, label: a.label || '' });
      return null;
    }
    default: throw Object.assign(new Error('unknown op ' + a.op), { code: 'SPEC' });
  }
}

async function main() {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  spec.viewport = spec.viewport || { width: 1280, height: 720 };
  spec.timeouts = Object.assign({ load_ms: 15000, assert_ms: 5000, step_ms: 15000, total_ms: 90000 }, spec.timeouts || {});
  spec.name = spec.name || 'clip';
  if (!spec.url || !spec.out_dir) throw Object.assign(new Error('url and out_dir required'), { code: 'SPEC' });
  fs.mkdirSync(spec.out_dir, { recursive: true });
  const { chromium } = require('playwright');

  const result = { ok: false, status: 'error', mask_enabled: maskOn(spec), viewport: spec.viewport };
  let browser;
  const deadline = setTimeout(async () => {
    result.status = 'incomplete'; result.error = 'total budget exceeded (' + spec.timeouts.total_ms + ' ms)';
    process.stdout.write(JSON.stringify(result) + '\n');
    try { await browser.close(); } catch (e) { /* ignore */ }
    process.exit(3);
  }, spec.timeouts.total_ms);

  try {
    current = 'launch';
    browser = await withTimeout(chromium.launch({ headless: spec.headless !== false }), 30000, 'launch');

    // 1) preflight: assert in a NON-recording context; a failure here means nothing is ever recorded
    if (maskOn(spec) && spec.preflight !== false) {
      current = 'preflight';
      const { ctx } = await newContext(browser, spec, false);
      const page = await ctx.newPage();
      await withTimeout(page.goto(spec.url, { timeout: spec.timeouts.load_ms, waitUntil: 'domcontentloaded' }), spec.timeouts.load_ms + 1000, 'preflight goto');
      result.preflight = await assertMask(page, spec);
      await ctx.close();
      if (!result.preflight.ok) {
        result.status = 'leak'; result.reason = 'preflight assertion failed: nothing recorded';
        process.stdout.write(JSON.stringify(result) + '\n'); clearTimeout(deadline); await browser.close(); process.exit(11);
      }
    }

    // 2) record
    current = 'record';
    const { ctx, sink } = await newContext(browser, spec, true);
    const tPage = Date.now();
    const page = await ctx.newPage();
    result.t_page_epoch = tPage;
    if (spec.sync !== false) {
      // calibration flashes on about:blank (5 on/off pulses, phases vary vs the 25 fps grid): capture.py aligns
      // rAF epoch times to video time from the pulse edges (video frames quantize the true instant)
      result.t_flashes = [];
      for (let k = 0; k < 5; k++) {
        result.t_flashes.push(await page.evaluate(() => new Promise((res) => requestAnimationFrame((ts) => {
          document.documentElement.style.background = '#ff00ff'; res(performance.timeOrigin + ts);
        }))));
        await page.waitForTimeout(110);
        await page.evaluate(() => { document.documentElement.style.background = '#ffffff'; });
        await page.waitForTimeout(95);
      }
      result.t_flash_epoch = result.t_flashes[0];
      await page.waitForTimeout(100);
    }
    await withTimeout(page.goto(spec.url, { timeout: spec.timeouts.load_ms, waitUntil: 'domcontentloaded' }), spec.timeouts.load_ms + 1000, 'goto');
    if (maskOn(spec)) {
      result.inline = await assertMask(page, spec);
      if (!result.inline.ok) {
        result.status = 'leak'; result.reason = 'assertion failed before scene start: clip discarded';
        await ctx.close(); fs.rmSync(path.join(spec.out_dir, 'tmp-video'), { recursive: true, force: true });
        process.stdout.write(JSON.stringify(result) + '\n'); clearTimeout(deadline); await browser.close(); process.exit(11);
      }
    }
    const t0 = Date.now(); result.scene_start_epoch = t0;
    const markers = [];
    let i = 0;
    for (const a of spec.actions || []) {
      current = 'action ' + (i++) + ' ' + a.op;
      await withTimeout(runAction(page, a, spec, markers, t0), spec.timeouts.step_ms + 1000, current);
    }
    current = 'finalize';
    if (maskOn(spec)) { result.final = await withTimeout(page.evaluate('window.__dsMask.assertMasked()'), spec.timeouts.assert_ms, 'final assert'); }
    const perf = maskOn(spec) ? await page.evaluate('window.__dsMask.stats()') : null;
    const rest = maskOn(spec) ? await page.evaluate('window.__dsMask.drain()') : [];
    for (const e of rest) sink.push(e);
    const probe = (spec.probes && spec.probes.length) ? await page.evaluate('window.__dsProbe || []') : [];
    result.scene_end_epoch = Date.now();   // nothing after this but the close
    const vpath = await page.video().path();
    await ctx.close();                     // finalizes the video
    const out = path.join(spec.out_dir, spec.name + '.raw.webm');
    fs.copyFileSync(vpath, out);
    fs.rmSync(path.join(spec.out_dir, 'tmp-video'), { recursive: true, force: true });
    const logPath = path.join(spec.out_dir, spec.name + '.mask.jsonl');
    fs.writeFileSync(logPath, sink.map((e) => JSON.stringify(e)).join('\n') + (sink.length ? '\n' : ''));
    if (probe.length) fs.writeFileSync(path.join(spec.out_dir, spec.name + '.probe.jsonl'), probe.map((e) => JSON.stringify(e)).join('\n') + '\n');
    Object.assign(result, { video: out, mask_log: logPath, mask_log_entries: sink.length, markers, perf,
      probe_log: probe.length ? path.join(spec.out_dir, spec.name + '.probe.jsonl') : null });
    result.ok = true; result.status = 'ok';
    if (maskOn(spec) && result.final && !result.final.ok) { result.status = 'leak'; result.ok = false; result.reason = 'final assertion failed'; }
    process.stdout.write(JSON.stringify(result) + '\n');
    clearTimeout(deadline); await browser.close();
    process.exit(result.ok ? 0 : 11);
  } catch (e) {
    clearTimeout(deadline);
    result.error = String(e && e.message || e);
    const timedOut = e.code === 'TIMEOUT' || e.name === 'TimeoutError';
    result.status = timedOut ? 'incomplete' : 'error';
    result.at = current;
    process.stdout.write(JSON.stringify(result) + '\n');
    try { await browser.close(); } catch (e2) { /* ignore */ }
    process.exit(timedOut ? 3 : e.code === 'SPEC' ? 2 : 70);
  }
}
main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, status: 'error', error: String(e) }) + '\n'); process.exit(70); });
