#!/usr/bin/env node
/* electron_adapter.js - fixed recorder adapter for Electron apps (redesign 6.7.2 Electron T1/T1', P0-native).
 *
 * Same contract as web_adapter.py (capture.py spawns it via run_bounded, jsonl heartbeat on stderr):
 *
 *   node electron_adapter.js <spec.json>
 *
 * spec = web_adapter spec (scene, viewport, tmp_dir, mask{enabled,selectors,regexes,mask_style,...}, probes, vo_ms,
 *        scene_script, timeouts{load_ms,assert_ms,step_ms,total_ms}, preflight) plus
 *   electron: { executable_path, app_path, args[], flags[], cwd, env{}, mode: "auto"|"hook"|"init"|"none", no_sandbox }
 *   ffmpeg: path of ffmpeg (pre-roll trim)
 * The scene script is JS (not Python): `module.exports = { prepare(sid, page), scenes: { s01: async ctx => {...} } }`,
 * actions + ctx.mark() only; ctx.target = Playwright Page of the app window, ctx.app = ElectronApplication.
 *
 * Mask injection (the FULL privacy_mask.js + privacy_oracle.js in the page's main world, as on the web):
 *   T1  (mode hook): `electron -r assets/mask-kits/electron/mask_hook.js <app>`: main-process hook registers a session
 *       preload that runs the payload before the page's own scripts. Works for dev/unpackaged apps.
 *   T1' (mode init): the hook is not accepted (window.__dsMask missing after launch): context.addInitScript(payload) +
 *       page.reload(). The recording also starts about:blank -> calibration pulses -> app URL, and the pre-roll before
 *       the first pulse is cut from the video, so frames from before the mask existed never reach the clip.
 *   mode none: no injection at all (negative control: the preflight assertion must fail with exit 11).
 * Fuse probe (before any launch): RunAsNode or EnableNodeCliInspectArguments disabled -> exit 4, "electron fuses locked".
 *
 * Writes, into spec.tmp_dir: <sid>.raw.webm, <sid>.mask.jsonl, <sid>.sync.json (same format as web), optional
 * <sid>.probe.jsonl; prints ONE JSON line. It decides nothing about the clip: capture.py's gate re-verifies everything.
 * The page's log is pulled by polling (window.__dsOut, filled by the payload's __dsMaskSink), not by exposeFunction.
 *
 * Exit: 0 ok | 2 bad spec / refused typed text / invalid regex | 3 over budget | 4 missing tool or fuses locked |
 * 10 scene step failed | 11 mask assertion failed (nothing kept) | 70 environment/unexpected.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');

const HERE = __dirname;
const KIT = path.join(HERE, '..', 'assets', 'mask-kits', 'electron');
const TAIL_MS = 400;
const LOCKED_REASON = 'electron fuses locked → use native path T3/T4';
// @electron/fuses wire format: SENTINEL, version byte, count byte, then one byte per fuse ('0' off, '1' on, 'r' removed)
const FUSE_SENTINEL = Buffer.from('dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX');
const FUSE_NAMES = ['RunAsNode', 'EnableCookieEncryption', 'EnableNodeOptionsEnvironmentVariable', 'EnableNodeCliInspectArguments',
  'EnableEmbeddedAsarIntegrityValidation', 'OnlyLoadAppFromAsar', 'LoadBrowserProcessSpecificV8Snapshot', 'GrantFileProtocolExtraPrivileges'];

class Refused extends Error {}
class StepError extends Error {}
class ToolError extends Error { constructor(msg, extra) { super(msg); this.extra = extra || {}; } }
class Leak extends Error {}

let current = 'init';
function hb(step) {
  if (step) current = step;
  process.stderr.write(JSON.stringify({ hb: Date.now(), step: current }) + '\n');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ fuse probe
function readFuses(file) {
  /* Streams the binary looking for the sentinel (the Electron binary is ~200 MB, never held in memory whole).
   * Returns {name: "on"|"off"|"removed"} or null when the binary carries no fuse wire (unfused dev build). */
  const fd = fs.openSync(file, 'r');
  try {
    const size = fs.fstatSync(fd).size, chunk = 8 * 1024 * 1024, keep = FUSE_SENTINEL.length + 64;
    const buf = Buffer.alloc(chunk + keep);
    let pos = 0, carry = 0;
    while (pos < size) {
      const n = fs.readSync(fd, buf, carry, chunk, pos);
      if (n <= 0) break;
      const view = buf.subarray(0, carry + n), at = view.indexOf(FUSE_SENTINEL);
      if (at >= 0 && at + FUSE_SENTINEL.length + 2 <= view.length) {
        const off = at + FUSE_SENTINEL.length, count = view[off + 1], out = {};
        for (let i = 0; i < count && off + 2 + i < view.length; i++) {
          const b = view[off + 2 + i];
          out[FUSE_NAMES[i] || 'fuse' + i] = b === 0x31 ? 'on' : b === 0x30 ? 'off' : b === 0x72 ? 'removed' : 'unknown';
        }
        return out;
      }
      pos += n;
      carry = Math.min(keep, carry + n);
      view.copy(buf, 0, view.length - carry, view.length);
    }
    return null;
  } finally { fs.closeSync(fd); }
}

function probeFuses(exe) {
  const files = [exe];
  if (process.platform === 'darwin') files.push(path.join(exe, '..', '..', 'Frameworks', 'Electron Framework.framework', 'Electron Framework'));
  for (const f of files) {
    try { const r = readFuses(f); if (r) return r; } catch (e) { /* unreadable: treated as unknown */ }
  }
  return null;
}

function fusesLocked(f) {
  if (!f) return false;
  const bad = (k) => f[k] === 'off' || f[k] === 'removed';
  return bad('RunAsNode') || bad('EnableNodeCliInspectArguments');
}

// ------------------------------------------------------------------ playwright (Node)
function loadPlaywright() {
  const roots = [process.env.DS_NODE_MODULES, undefined];
  try { roots.push(cp.execFileSync('npm', ['root', '-g'], { encoding: 'utf8', timeout: 10000 }).trim()); } catch (e) { /* no npm */ }
  for (const name of ['playwright', 'playwright-core']) {
    for (const r of roots) {
      try { return require(require.resolve(name, r ? { paths: [r] } : undefined)); } catch (e) { /* next */ }
    }
  }
  throw new ToolError('missing tools: playwright (node) (npm i playwright; set DS_NODE_MODULES to its node_modules)', { missing: ['playwright-node'] });
}

// ------------------------------------------------------------------ ctx (same API as demo_ctx / web_adapter.Ctx)
class Ctx {
  constructor(scene, page, app, voMs, markers) {
    Object.assign(this, { scene, target: page, app, voMs, scale: 1.0, origin: [0, 0], dry: false });
    this.t0 = Date.now();
    this.markers = markers;
  }
  now() { return Date.now() - this.t0; }
  bb(b) {
    if (!b) return null;
    const [x, y, w, h] = Array.isArray(b) ? b : [b.x, b.y, b.width, b.height];
    return [Math.round((x - this.origin[0]) * this.scale), Math.round((y - this.origin[1]) * this.scale), Math.round(w * this.scale), Math.round(h * this.scale)];
  }
  mark(type, b = null, label = '') { this.markers.push({ t: this.now(), scene: this.scene, type, bbox: this.bb(b), label }); }
  sensitive(b, label) { this.mark('sensitive', b, label); }
  sensitiveEnd(label) { this.mark('sensitive', null, label); }
  async holdUntil(ms) { const left = ms - this.now(); if (left > 0) await this.target.waitForTimeout(left); }   // the ONLY way to wait
  start() { this.t0 = Date.now(); this.mark('scene_start'); }
  async end() { await this.holdUntil(this.voMs + TAIL_MS); this.mark('scene_end'); }
}

// ------------------------------------------------------------------ typed-text guard (S-08), same rules as web_adapter
class TypeGuard {
  constructor(getPage) { this.getPage = getPage; this.buf = ''; this.active = false; this.orig = []; }
  async hit(t) { return !!(await this.getPage().evaluate((x) => !!(window.__dsMask && window.__dsMask.testText(x)), t)); }
  async before(text, locator, handle) {
    if (!this.active || typeof text !== 'string' || !text) return;
    const buf = (this.buf + text).slice(-400), page = this.getPage();
    const fm = (el) => window.__dsMask.forceMask(el);
    let r;
    if (handle) r = await handle.evaluate(fm);
    else if (locator) r = await locator.first().evaluate(fm);
    else r = await page.evaluate(() => window.__dsMask.forceMask(document.activeElement));
    if (!r) {
      if ((await this.hit(text)) || (await this.hit(buf))) {
        throw new Refused('typed text matches a privacy regex but the target cannot be masked before the first key (not an input/textarea/contenteditable): not typed');
      }
    } else if (r === 2) {   // newly masked: wait until the overlay has painted
      await page.evaluate(() => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(res)))));
    }
    this.buf = buf;
  }
  async install(page) {
    const guard = this;
    const h = await page.$('html');
    const protos = { loc: Object.getPrototypeOf(page.locator('html')), handle: h && Object.getPrototypeOf(h), page: Object.getPrototypeOf(page),
      frame: Object.getPrototypeOf(page.mainFrame()), kb: Object.getPrototypeOf(page.keyboard) };
    if (h) await h.dispose();
    const wrap = (proto, name, kind, reset) => {
      const orig = proto && proto[name];
      if (typeof orig !== 'function') return;
      proto[name] = async function (...a) {
        const single = (t) => typeof t === 'string' && t.length === 1;
        if (kind === 'kb') {
          const t = a[0];
          if (typeof t === 'string' && (t.length === 1 || name === 'type' || name === 'insertText')) await guard.before(t);
        } else if (kind === 'loc' || kind === 'handle') {
          const t = a[0];
          if (name !== 'press' || single(t)) await guard.before(t, kind === 'loc' ? this : null, kind === 'handle' ? this : null);
        } else {   // Page / Frame: (selector, text)
          const t = a[1];
          if (name !== 'press' || single(t)) await guard.before(t, this.locator(a[0]));
        }
        if (reset) guard.buf = '';
        return orig.apply(this, a);
      };
      guard.orig.push([proto, name, orig]);
    };
    for (const n of ['type', 'pressSequentially', 'press']) { wrap(protos.loc, n, 'loc'); wrap(protos.handle, n, 'handle'); }
    wrap(protos.loc, 'fill', 'loc', true);
    wrap(protos.handle, 'fill', 'handle', true);
    for (const pr of [protos.page, protos.frame]) { for (const n of ['type', 'press']) wrap(pr, n, 'pf'); wrap(pr, 'fill', 'pf', true); }
    for (const n of ['type', 'insertText', 'press', 'down']) wrap(protos.kb, n, 'kb');
  }
  uninstall() { for (const [p, n, o] of this.orig.reverse()) p[n] = o; this.orig = []; }
}

// ------------------------------------------------------------------ ffmpeg: cut the pre-roll before the first pulse
function ffmpegExe(spec) {
  const c = spec.ffmpeg || 'ffmpeg';
  const r = cp.spawnSync(c, ['-version'], { encoding: 'utf8' });
  if (r.error || r.status !== 0) throw new ToolError('missing tools: ffmpeg', { missing: ['ffmpeg'] });
  return c;
}

function findFirstFlash(ffmpeg, video, w, h) {
  /* centre pixel of every frame (3 bytes) + showinfo pts_time (stderr): first magenta frame -> its time in seconds */
  const r = cp.spawnSync(ffmpeg, ['-nostdin', '-v', 'info', '-i', video, '-vf', 'scale=' + w + ':' + h + ',crop=1:1:' + (w >> 1) + ':' + (h >> 1) + ',showinfo',
    '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], { maxBuffer: 256 * 1024 * 1024 });
  if (r.status !== 0) throw new Error('ffmpeg flash scan failed');
  const times = [...r.stderr.toString().matchAll(/pts_time:\s*([0-9.]+)/g)].map((m) => parseFloat(m[1]));
  const px = r.stdout;
  for (let i = 0; i < Math.min(times.length, px.length / 3); i++) {
    if (px[3 * i] > 200 && px[3 * i + 1] < 60 && px[3 * i + 2] > 200) return times[i];
  }
  return null;
}

function trimPreRoll(ffmpeg, src, dst, flashT, w, h) {
  const cut = Math.max(0, flashT - 0.2);
  if (cut <= 0) { fs.copyFileSync(src, dst); return 0; }
  const r = cp.spawnSync(ffmpeg, ['-nostdin', '-v', 'error', '-y', '-ss', cut.toFixed(3), '-i', src, '-vf', 'scale=' + w + ':' + h, '-c:v', 'libvpx', '-b:v', '8M', '-crf', '6', '-an', dst]);
  if (r.status !== 0) throw new Error('ffmpeg trim failed: ' + String(r.stderr).slice(0, 200));
  return cut;
}

// ------------------------------------------------------------------ main
async function run(spec) {
  const tmo = Object.assign({ load_ms: 15000, assert_ms: 5000, step_ms: 15000, total_ms: 90000 }, spec.timeouts || {});
  const sid = spec.scene, vp = spec.viewport, mask = spec.mask || {}, maskOn = !!mask.enabled, tmp = spec.tmp_dir;
  const el = spec.electron || {};
  fs.mkdirSync(tmp, { recursive: true });
  const result = { ok: false, status: 'error', mask_enabled: maskOn, platform: 'electron' };
  if (!el.app_path) throw new Refused('spec.electron.app_path required');

  // 0) fuses first: a locked app can never be driven, so nothing else is attempted
  let exe = el.executable_path;
  const pwHolder = {};
  const getPw = () => (pwHolder.pw || (pwHolder.pw = loadPlaywright()));
  if (!exe) {
    try { exe = getPw()._electron && require(require.resolve('electron', { paths: [el.app_path, process.env.DS_NODE_MODULES].filter(Boolean) })); } catch (e) { /* below */ }
    if (typeof exe !== 'string') throw new ToolError('missing tools: electron (set spec.electron.executable_path)', { missing: ['electron'] });
  }
  const fuses = probeFuses(exe);
  result.fuses = fuses;
  if (fusesLocked(fuses)) {
    result.status = 'missing-tool';
    result.reason = LOCKED_REASON;
    return [4, result];
  }
  const pw = getPw();
  const ffmpeg = ffmpegExe(spec);

  // 1) payload: config + privacy_mask.js + privacy_oracle.js + the in-page log sink (private file, removed with tmp_dir)
  const maskJs = fs.readFileSync(path.join(HERE, 'privacy_mask.js'), 'utf8');
  const oracleJs = fs.readFileSync(path.join(HERE, 'privacy_oracle.js'), 'utf8');
  const cfg = {}; for (const k of Object.keys(mask)) if (k !== 'enabled') cfg[k] = mask[k];
  const ocfg = { selectors: mask.selectors || [], regexes: mask.regexes || [], probes: spec.probes || [] };
  let payload = "Object.defineProperty(window,'__dsOut',{value:[],enumerable:false});" +
    "window.__dsMaskSink=function(b){for(var i=0;i<b.length;i++)window.__dsOut.push(b[i]);};\n";
  if (maskOn) payload += 'window.__DS_MASK_CONFIG = ' + JSON.stringify(cfg) + ';\n' + maskJs + '\n';
  if (mask.oracle !== false && (ocfg.selectors.length || ocfg.regexes.length || ocfg.probes.length || maskOn)) {
    payload += 'window.__DS_ORACLE_CONFIG = ' + JSON.stringify(ocfg) + ';\n' + oracleJs + '\n';
  }
  const payloadPath = path.join(tmp, 'ds_mask_payload.js');
  fs.writeFileSync(payloadPath, payload, { mode: 0o600 });

  let mod = {}, fn = null;
  if (spec.scene_script) {
    mod = require(path.resolve(spec.scene_script));
    fn = mod.scenes && mod.scenes[sid];
    if (typeof fn !== 'function') throw new Refused('scene script has no scenes[' + JSON.stringify(sid) + ']');
  }

  const sink = [], probes = [];
  const takeBatch = (b) => { for (const e of b || []) (e.kind === 'probe' ? probes : sink).push(e); };
  const requested = el.mode || 'auto';
  const isRoot = typeof process.getuid === 'function' && process.getuid() === 0;

  async function launch(record, mode) {
    const args = [];
    if (el.no_sandbox === undefined ? isRoot : el.no_sandbox) args.push('--no-sandbox');
    args.push(...(el.flags || []));
    if (mode === 'hook') args.push('-r', path.join(KIT, 'mask_hook.js'));
    args.push(el.app_path, ...(el.args || []));
    const opts = { executablePath: exe, args, cwd: el.cwd, timeout: tmo.load_ms,
      env: Object.assign({}, process.env, el.env || {}, mode === 'hook' ? { DS_MASK_PAYLOAD: payloadPath } : {}) };
    if (record) opts.recordVideo = { dir: path.join(tmp, 'pw'), size: vp };
    let app;
    try {
      app = await pw._electron.launch(opts);
    } catch (e) {
      const m = String(e && e.message || e).split('\n')[0];
      if (/ECONNREFUSED|Process failed to launch|Timeout|Target closed|exited/i.test(m)) {
        e.hint = 'launch failed (' + m + '); if the app is packaged, its fuses may block the inspector → ' + LOCKED_REASON;
      }
      throw e;
    }
    const page = await app.firstWindow();
    await page.waitForLoadState('domcontentloaded');
    if (mode === 'init') await app.context().addInitScript(payload);
    return { app, page, mode };
  }
  const hasMask = (page) => page.evaluate(() => !!window.__dsMask).catch(() => false);
  async function assertMask(page) {
    await page.waitForFunction('window.__dsMaskReady === true', null, { timeout: tmo.assert_ms });
    return page.evaluate(() => window.__dsMask.assertMasked());
  }
  const summarize = (a) => !a ? null : { ok: a.ok, mode: a.mode, checked: a.checked, failures: a.failures, regex_hits: a.regex_hits, regex_labels: a.regex_labels, unmaskable: a.unmaskable };
  const present = (...as) => as.some((a) => a && ((a.regex_hits || 0) > 0 || (a.checked || []).some((c) => (c.rendered || 0) > 0)));
  async function closeQuiet(app) { try { await app.close(); } catch (e) { /* gone */ } }
  async function resize(app, page) {
    const [w, h] = await page.evaluate(() => [innerWidth, innerHeight]);
    if (w === vp.width && h === vp.height) return false;
    await app.evaluate(({ BrowserWindow }, [cw, ch]) => { const win = BrowserWindow.getAllWindows()[0]; win.setContentSize(cw, ch); win.setPosition(0, 0); }, [vp.width, vp.height]);
    await sleep(300);
    return true;
  }

  // 2) preflight in a NON-recording launch: decides T1 vs T1', and a failure means nothing is ever recorded
  let mode = requested === 'auto' ? 'hook' : requested;
  if (!maskOn) mode = 'none';
  const guard = new TypeGuard(() => page);
  let page = null, app = null;
  try {
    if (spec.preflight !== false || requested === 'auto') {
      hb('preflight');
      let L = await launch(false, mode);
      app = L.app; page = L.page;
      if (maskOn && mode === 'hook' && requested === 'auto' && !(await hasMask(page))) {
        await closeQuiet(app);
        hb('fallback-init');
        mode = 'init';
        L = await launch(false, mode); app = L.app; page = L.page;
        await page.reload({ waitUntil: 'domcontentloaded' });
      } else if (maskOn && mode === 'init') {
        await page.reload({ waitUntil: 'domcontentloaded' });
      }
      result.mode = mode;
      if (maskOn) {
        if (!(await hasMask(page))) {
          result.status = 'leak'; result.reason = 'preflight assertion failed: mask not installed (mode ' + mode + '): nothing recorded';
          await closeQuiet(app); app = null;
          return [11, result];
        }
        if (mod.prepare) { hb('prepare'); await mod.prepare(sid, page); }
        result.preflight = summarize(await assertMask(page));
        const badRe = (result.preflight.failures || []).filter((f) => f.reason === 'invalid_regex');
        await closeQuiet(app); app = null;
        sink.length = 0; probes.length = 0;
        if (badRe.length) throw new Refused('invalid regex (JS semantics): ' + badRe.map((f) => f.selector).join(', '));
        if (!result.preflight.ok) { result.status = 'leak'; result.reason = 'preflight assertion failed: nothing recorded'; return [11, result]; }
      } else { await closeQuiet(app); app = null; }
    }
    result.mode = mode;

    // 3) record
    hb('record');
    const L = await launch(true, mode);
    app = L.app; page = L.page;
    const startUrl = page.url();
    result.window_resized = await resize(app, page);
    result.t_page_epoch = Date.now();
    await page.goto('about:blank');
    const flashes = [];
    for (let i = 0; i < 5; i++) {   // calibration pulses on about:blank (phases vary vs the 25 fps grid)
      flashes.push(await page.evaluate(() => new Promise((res) => requestAnimationFrame((ts) => { document.documentElement.style.background = '#ff00ff'; res(performance.timeOrigin + ts); }))));
      await page.waitForTimeout(110);
      await page.evaluate(() => { document.documentElement.style.background = '#ffffff'; });
      await page.waitForTimeout(95);
    }
    await page.waitForTimeout(100);
    hb('goto');
    await page.goto(startUrl, { waitUntil: 'domcontentloaded' });
    let puller = null, pulling = false;
    const pull = async () => {
      if (pulling || !page) return;
      pulling = true;
      try { takeBatch(await page.evaluate(() => (window.__dsOut ? window.__dsOut.splice(0, window.__dsOut.length) : []))); } catch (e) { /* navigating */ } finally { pulling = false; }
    };
    puller = setInterval(pull, 120);
    try {
      if (maskOn) await page.waitForFunction('window.__dsMaskReady === true', null, { timeout: tmo.assert_ms });
      if (mod.prepare) { hb('prepare'); await mod.prepare(sid, page); }
      if (maskOn) {
        result.inline = summarize(await assertMask(page));
        if (!result.inline.ok) { result.status = 'leak'; result.reason = 'assertion failed before scene start: clip discarded'; await closeQuiet(app); app = null; return [11, result]; }
      }
      const before = await page.evaluate(() => [scrollX, scrollY]);
      const markers = [];
      const sctx = new Ctx(sid, page, app, parseInt(spec.vo_ms || 0, 10), markers);
      guard.active = maskOn && (mask.regexes || []).length > 0;
      if (guard.active) await guard.install(page);
      const after = await page.evaluate(() => [scrollX, scrollY]);
      if (after[0] !== before[0] || after[1] !== before[1]) throw new StepError('start state moved between prepare and start');
      hb('scene');
      sctx.start();
      const sceneStart = Date.now();
      try { if (fn) await fn(sctx); } finally { guard.uninstall(); }
      await sctx.end();
      const sceneEnd = Date.now();
      hb('finalize');
      let fin = null, perf = null;
      if (maskOn) {
        fin = await assertMask(page);
        perf = await page.evaluate(() => window.__dsMask.stats());
      }
      clearInterval(puller); puller = null;
      while (pulling) await sleep(20);
      takeBatch(await page.evaluate(() => {
        if (window.__dsMask) window.__dsMask.flush();
        if (window.__dsOracle) window.__dsOracle.flush();
        const o = window.__dsOut ? window.__dsOut.splice(0, window.__dsOut.length) : [];
        return o.concat(window.__dsMask ? window.__dsMask.drain() : [], window.__dsOracle ? window.__dsOracle.drain() : []);
      }));
      const vid = page.video();
      await app.close(); app = null;                  // finalizes the video: nothing after this
      const vpath = await vid.path();
      const rawPath = path.join(tmp, 'raw-full.webm');
      fs.copyFileSync(vpath, rawPath);
      fs.rmSync(path.join(tmp, 'pw'), { recursive: true, force: true });
      const out = path.join(tmp, sid + '.raw.webm');
      const flashT = findFirstFlash(ffmpeg, rawPath, vp.width, vp.height);
      if (flashT === null) throw new Error('calibration flash not found in the recording');
      const cut = trimPreRoll(ffmpeg, rawPath, out, flashT, vp.width, vp.height);
      fs.rmSync(rawPath, { force: true });
      result.preroll_trimmed_ms = Math.round(cut * 1000);
      const tPage = flashes[0] - (flashT - cut) * 1000.0;     // epoch of video time 0 (first flash minus its time in the cut clip)
      const logp = path.join(tmp, sid + '.mask.jsonl');
      fs.writeFileSync(logp, sink.sort((a, b) => (a.t || 0) - (b.t || 0)).map((e) => JSON.stringify(e) + '\n').join(''));
      if (probes.length) {
        fs.writeFileSync(path.join(tmp, sid + '.probe.jsonl'), probes.sort((a, b) => a.t - b.t).map((e) => JSON.stringify({ t: e.t, selector: e.selector, rect: e.rect }) + '\n').join(''));
      }
      const sync = { schema: 1, scene: sid, viewport: vp, t_page_epoch: tPage, t_flashes: flashes, scene_start_epoch: sceneStart, scene_end_epoch: sceneEnd,
        mask_enabled: maskOn, mask_mode: fin && fin.mode, sensitive_present: present(result.preflight, result.inline, fin), markers, perf,
        preflight: result.preflight || null, inline: result.inline || null, final: summarize(fin),
        platform: 'electron', electron: { mode, fuses, window_resized: result.window_resized, preroll_trimmed_ms: result.preroll_trimmed_ms } };
      const sp = path.join(tmp, sid + '.sync.json');
      fs.writeFileSync(sp, JSON.stringify(sync));
      Object.assign(result, { ok: true, status: 'ok', video: out, mask_log: logp, sync: sp, mask_log_entries: sink.length,
        probe_log: probes.length ? path.join(tmp, sid + '.probe.jsonl') : null });
      if (maskOn && fin && !fin.ok) { Object.assign(result, { ok: false, status: 'leak', reason: 'final assertion failed' }); return [11, result]; }
      return [0, result];
    } finally { if (puller) clearInterval(puller); }
  } finally {
    guard.uninstall();
    if (app) await closeQuiet(app);
  }
}

function classify(e, result) {
  const name = e && e.name, msg = String(e && e.message || e).split('\n')[0];
  if (e instanceof Refused) return [2, { ok: false, status: 'input', error: msg, at: current }];
  if (e instanceof ToolError) return [4, Object.assign({ ok: false, status: 'missing-tool', error: msg }, e.extra)];
  if (e instanceof StepError) return [10, { ok: false, status: 'step', error: msg, error_class: 'step', at: current }];
  if (name === 'TimeoutError') {
    if (current === 'scene' || current === 'prepare') return [10, { ok: false, status: 'step', error: 'timeout: ' + msg, error_class: 'step', at: current }];
    return [3, { ok: false, status: 'incomplete', error: 'timeout: ' + msg, at: current }];
  }
  const step = current === 'scene' || current === 'prepare';
  const out = { ok: false, status: step ? 'step' : 'error', error: (e && e.hint) || msg, at: current, error_class: step ? 'step' : 'environment' };
  if (!step) process.stderr.write(String(e && e.stack || e) + '\n');
  return [step ? 10 : 70, out];
}

async function main(argv) {
  let spec;
  try {
    spec = JSON.parse(fs.readFileSync(argv[0], 'utf8'));
    spec.viewport = spec.viewport || { width: 1280, height: 720 };
    if (!spec.tmp_dir || !spec.scene || !(spec.electron && spec.electron.app_path)) throw new Error('electron.app_path, scene and tmp_dir required');
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, status: 'input', error: 'bad spec: ' + e.message }) + '\n');
    return 2;
  }
  const timer = setInterval(() => hb(), 2000);
  let code, result;
  try {
    [code, result] = await run(spec);
  } catch (e) {
    [code, result] = classify(e);
  }
  clearInterval(timer);
  process.stdout.write(JSON.stringify(result) + '\n');
  return code;
}

if (require.main === module) {
  main(process.argv.slice(2)).then((c) => process.exit(c), (e) => { process.stderr.write(String(e && e.stack || e) + '\n'); process.exit(70); });
}
module.exports = { readFuses, probeFuses, fusesLocked };
