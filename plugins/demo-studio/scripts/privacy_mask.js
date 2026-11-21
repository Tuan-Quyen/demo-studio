/*
 * privacy_mask.js - capture-time masking for web recordings (demo-studio, redesign 6.2).
 *
 * Inject with context.addInitScript BEFORE any page load. Config is read from
 * window.__DS_MASK_CONFIG (capture.py / the recorder prepend `window.__DS_MASK_CONFIG = {...};`):
 *   { selectors: [css...],            // SENSITIVE selectors (default always includes [data-sensitive])
 *     regexes:   [source | {source, flags}],  // matched against text nodes, input values, placeholders
 *     mask_style: "solid" | "blur" | {kind, color, sentinel, blur_px},
 *     force_overlay: bool,            // test hook: skip the CSS Custom Highlight API
 *     force_style_element: bool }     // test hook: skip adoptedStyleSheets (<style> fallback)
 *
 * It never mutates the app DOM (no wrapper nodes, no attributes, no classes):
 *   - text nodes        -> CSS Custom Highlight API (::highlight(ds-mask)); fallback overlay divs
 *   - input/textarea    -> stylesheet rule (transparent text, pill background, no caret/placeholder)
 *   - regex-matched input value / placeholder, SVG text, textless boxes (img, canvas...)
 *                       -> cover overlay in a closed shadow root (the only node we add: its host,
 *                          created lazily and appended to <html>, never to <body>)
 *   - ::selection       -> rule on masked selectors
 * The stylesheet goes in via document.adoptedStyleSheets (no DOM node, no <head> timing issue);
 * fallback is a <style> element that waits for <head> with a MutationObserver and is re-attached
 * if the parser or the app drops it.
 *
 * Output (window.__dsMask):
 *   ready (bool, mirrored in window.__dsMaskReady), mode, log[], drain(), flush(), stats(),
 *   assertMasked() -> {ok, ready, mode, failures[], checked[]}   (fail-closed API)
 * Log entry per requestAnimationFrame and selector group (epoch ms, viewport-clipped CSS px):
 *   {t, kind:"masked", selector, count, rects:[[x,y,w,h]], state:"masked"|"unmasked",
 *    boxes:[idx of rects drawn as box overlay with sentinel border], partial:[idx], hidden:n}
 * If window.__dsMaskSink exists (context.exposeFunction), batches are pushed to it every 200 ms.
 */
(() => {
  'use strict';
  if (window.__dsMask) return;

  const RAW = window.__DS_MASK_CONFIG || {};
  const SEL_STYLE = {
    solid: { kind: 'solid', color: '#9aa3b2', sentinel: '#0b1f4d', blur_px: 10 },
  };
  const style = (() => {
    const m = RAW.mask_style;
    if (m && typeof m === 'object') return Object.assign({}, SEL_STYLE.solid, m);
    if (m === 'blur') return Object.assign({}, SEL_STYLE.solid, { kind: 'blur' });
    return Object.assign({}, SEL_STYLE.solid);
  })();

  const configErrors = [];
  const selectors = [];
  for (const s of ['[data-sensitive]'].concat(RAW.selectors || [])) {
    if (selectors.includes(s)) continue;
    try { document.createDocumentFragment().querySelector(s); selectors.push(s); }
    catch (e) { configErrors.push({ selector: s, reason: 'invalid_selector' }); }
  }
  const regexes = [];
  (RAW.regexes || []).forEach((r, i) => {
    try {
      const src = typeof r === 'string' ? r : r.source;
      let flags = (typeof r === 'string' ? '' : (r.flags || '')).replace(/[gy]/g, '');
      regexes.push({ re: new RegExp(src, flags + 'g'), label: 'regex#' + i });
    } catch (e) { configErrors.push({ selector: 'regex#' + i, reason: 'invalid_regex' }); }
  });

  const HAS_HL = !RAW.force_overlay && typeof Highlight === 'function' && typeof CSS !== 'undefined' && !!CSS.highlights;
  const HAS_ADOPT = !RAW.force_style_element && typeof CSSStyleSheet === 'function' &&
    'adoptedStyleSheets' in Document.prototype && (() => { try { new CSSStyleSheet().replaceSync(''); return true; } catch (e) { return false; } })();
  const SVGNS = 'http://www.w3.org/2000/svg';
  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'TITLE', 'META', 'LINK']);
  const INPUT_SEL = 'input,textarea,select,[contenteditable=""],[contenteditable="true"]';
  const BOX_TAGS = new Set(['IMG', 'CANVAS', 'VIDEO', 'IFRAME', 'OBJECT', 'EMBED', 'PICTURE']);
  const MAX_RECTS = 64;
  const MAX_BUFFER = 40000;

  // ---------------------------------------------------------------- state
  // text items: Text node -> {kind:'text', node, el, selector, ranges[], overlay:bool}
  // el items:   Element    -> {kind:'input'|'box', el, selector, ranges:[] , valueHit:bool}
  const items = new Map();
  const stats = { mutation_batches: 0, scan_ms: 0, frames: 0, frame_ms: 0, max_frame_ms: 0, dropped_log: 0 };
  const state = { ready: false, sheetOk: false, hostOk: true };
  const log = [];
  let clipCache = new WeakMap();
  let hl = null;
  let sheet = null;
  let styleEl = null;
  let host = null, wrap = null, pool = [];

  const pill = style.color;
  function buildCss() {
    const out = [];
    out.push('::highlight(ds-mask){color:transparent;-webkit-text-fill-color:transparent;background-color:' + pill + ';text-shadow:none;text-decoration:none}');
    for (const s of selectors) {
      if (style.kind === 'blur') {
        out.push(s + '{filter:blur(' + style.blur_px + 'px)!important}');
      }
      out.push(s + ':is(' + INPUT_SEL + '){-webkit-text-fill-color:transparent!important;color:transparent!important;caret-color:transparent!important;background-color:' + pill + '!important;background-image:none!important;text-shadow:none!important}');
      out.push(s + '::placeholder{color:transparent!important;-webkit-text-fill-color:transparent!important;opacity:1!important}');
      out.push(s + '::selection,' + s + ' ::selection{color:transparent!important;-webkit-text-fill-color:transparent!important;background-color:' + pill + '!important;text-shadow:none!important}');
      out.push(s + ' text,' + s + ' tspan,text' + s + ',tspan' + s + '{fill:transparent!important;stroke:none!important}');
    }
    return out.join('\n');
  }

  // ------------------------------------------------------- stylesheet install
  function installSheet() {
    if (HAS_ADOPT) {
      try {
        if (!sheet) { sheet = new CSSStyleSheet(); sheet.replaceSync(buildCss()); }
        if (!document.adoptedStyleSheets.includes(sheet)) {
          document.adoptedStyleSheets = Array.from(document.adoptedStyleSheets).concat([sheet]);
        }
        state.sheetOk = document.adoptedStyleSheets.includes(sheet);
        return;
      } catch (e) { /* fall through to <style> */ }
    }
    // <style> fallback: needs <head> (or documentElement once the parser made it). Appending to a
    // documentElement that the parser has not finished creating gets dropped, so require isConnected
    // and re-check on every sweep.
    if (styleEl && styleEl.isConnected && styleEl.sheet) { state.sheetOk = true; return; }
    const parent = document.head || null;
    if (!parent) { state.sheetOk = false; return; }
    if (!styleEl) { styleEl = document.createElement('style'); styleEl.textContent = buildCss(); }
    try { parent.appendChild(styleEl); } catch (e) { /* retried next sweep */ }
    state.sheetOk = !!(styleEl.isConnected && styleEl.sheet);
  }
  function ensureHighlight() {
    if (!HAS_HL) return;
    if (!hl) { hl = new Highlight(); }
    if (CSS.highlights.get('ds-mask') !== hl) CSS.highlights.set('ds-mask', hl);
  }

  // ----------------------------------------------------------- overlay host
  function ensureHost() {
    if (host && host.isConnected) return true;
    const root = document.documentElement;
    if (!root) { state.hostOk = false; return false; }
    if (!host) {
      host = document.createElement('div');
      host.style.cssText = 'all:initial;position:absolute;left:0;top:0;width:0;height:0;overflow:visible;pointer-events:none;z-index:2147483647;contain:none';
      const sr = host.attachShadow({ mode: 'closed' });
      wrap = document.createElement('div');
      wrap.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;pointer-events:none';
      sr.appendChild(wrap);
      pool = [];
    }
    root.appendChild(host);
    state.hostOk = host.isConnected;
    return state.hostOk;
  }
  function drawOverlay(rects) { // rects: [{x,y,w,h,box}] viewport px
    if (!rects.length && !host) return;
    if (!ensureHost()) return;
    const sx = window.scrollX, sy = window.scrollY;
    while (pool.length < rects.length) {
      const d = document.createElement('div');
      d.style.cssText = 'position:absolute;left:0;top:0;box-sizing:border-box;pointer-events:none';
      wrap.appendChild(d); pool.push(d);
    }
    for (let i = 0; i < pool.length; i++) {
      const d = pool[i], r = rects[i];
      if (!r) { if (d.style.display !== 'none') d.style.display = 'none'; continue; }
      d.style.display = 'block';
      // document-anchored overlays scroll with the page on the compositor (no lag); fixed/sticky owners need viewport anchoring
      if (r.fixed) { d.style.position = 'fixed'; d.style.transform = 'translate(' + r.x + 'px,' + r.y + 'px)'; }
      else { d.style.position = 'absolute'; d.style.transform = 'translate(' + (r.x + sx) + 'px,' + (r.y + sy) + 'px)'; }
      d.style.width = r.w + 'px'; d.style.height = r.h + 'px';
      d.style.background = pill;
      d.style.border = r.box ? '1px solid ' + style.sentinel : '0';
    }
  }

  // ------------------------------------------------------------ item mgmt
  function dropItem(key) {
    const it = items.get(key);
    if (!it) return;
    if (hl) for (const r of it.ranges) hl.delete(r);
    items.delete(key);
  }
  function matchSel(el) {
    for (const s of selectors) { try { if (el.closest(s)) return s; } catch (e) { /* skip */ } }
    return null;
  }
  function selfMatchSel(el) {
    for (const s of selectors) { try { if (el.matches(s)) return s; } catch (e) { /* skip */ } }
    return null;
  }
  function isSvg(el) { return el.namespaceURI === SVGNS; }

  function handleText(t) {
    dropItem(t);
    const el = t.parentElement;
    if (!el || SKIP_TAGS.has(el.tagName)) return;
    const data = t.data;
    if (!data || !data.trim()) return;
    const sel = matchSel(el);
    const spans = [];
    let label = sel;
    if (sel) spans.push([0, data.length]);
    else {
      for (const rg of regexes) {
        rg.re.lastIndex = 0;
        let m;
        while ((m = rg.re.exec(data)) !== null) {
          if (m[0].length === 0) { rg.re.lastIndex++; continue; }
          spans.push([m.index, m.index + m[0].length]); label = label || rg.label;
        }
      }
    }
    if (!spans.length) return;
    const overlay = !HAS_HL || isSvg(el);
    const ranges = spans.map(([a, b]) => { const r = document.createRange(); r.setStart(t, a); r.setEnd(t, b); return r; });
    if (!overlay) { ensureHighlight(); ranges.forEach((r) => hl.add(r)); }
    items.set(t, { kind: 'text', node: t, el, selector: label, ranges, overlay });
  }

  function handleElement(el) {
    if (SKIP_TAGS.has(el.tagName)) return;
    const self = selfMatchSel(el);
    const inputLike = el.matches(INPUT_SEL);
    // input / textarea: value and placeholder
    if (inputLike) {
      let label = self || matchSel(el);
      let valueHit = false;
      if (!label && regexes.length) {
        const v = (el.value != null ? String(el.value) : el.textContent) || '';
        const ph = el.getAttribute('placeholder') || '';
        for (const rg of regexes) {
          rg.re.lastIndex = 0; if (v && rg.re.test(v)) { label = rg.label; valueHit = true; break; }
          rg.re.lastIndex = 0; if (ph && rg.re.test(ph)) { label = rg.label; valueHit = true; break; }
        }
      }
      if (label) {
        const prev = items.get(el);
        if (!prev || prev.valueHit !== valueHit || prev.selector !== label) {
          items.set(el, { kind: 'input', el, selector: label, ranges: [], valueHit });
        }
      } else dropItem(el);
      return;
    }
    // textless replaced boxes (img, canvas, ...) or SVG root marked by selector: cover box
    if (self && (BOX_TAGS.has(el.tagName) || (isSvg(el) && el.tagName.toLowerCase() === 'svg'))) {
      items.set(el, { kind: 'box', el, selector: self, ranges: [] });
      return;
    }
    if (self && !el.textContent.trim() && !el.querySelector('*')) { // empty element with selector: cover its box
      items.set(el, { kind: 'box', el, selector: self, ranges: [] });
    }
  }

  function scanSubtree(root) {
    if (!root) return;
    if (root.nodeType === 3) { handleText(root); return; }
    if (root.nodeType !== 1) { // document / fragment
      for (let c = root.firstChild; c; c = c.nextSibling) scanSubtree(c);
      return;
    }
    if (SKIP_TAGS.has(root.tagName)) return;
    if (root === host) return;
    handleElement(root);
    const w = document.createTreeWalker(root, 1 | 4, {
      acceptNode: (n) => (n.nodeType === 1 && (SKIP_TAGS.has(n.tagName) || n === host)) ? 2 : 1,
    });
    let n;
    while ((n = w.nextNode())) { if (n.nodeType === 3) handleText(n); else handleElement(n); }
  }

  function rescanAll() { scanSubtree(document.documentElement || document); }

  function onMutations(muts) {
    const t0 = performance.now();
    stats.mutation_batches++;
    clipCache = new WeakMap();
    for (const m of muts) {
      const tg = m.target;
      if (host && (tg === host || (tg.nodeType === 1 && host.contains && tg !== document.documentElement && host.contains(tg)))) continue;
      if (m.type === 'characterData') { handleText(tg); }
      else if (m.type === 'childList') {
        for (const n of m.addedNodes) if (n !== host) scanSubtree(n);
        // a text node removed/added inside a matched element: re-evaluate parent's text children
        if (tg.nodeType === 1) { handleElement(tg); }
      } else if (m.type === 'attributes') {
        // selector membership or value/placeholder may have changed; inline-style churn cannot change either
        if (tg !== host && m.attributeName !== 'style') scanSubtree(tg);
      }
    }
    // input.value is a property, not an attribute: handled in the 'input'/'change' listeners below
    if (document.documentElement && !state.sheetOk) installSheet();
    stats.scan_ms += performance.now() - t0;
  }
  const mo = new MutationObserver(onMutations);
  mo.observe(document, { childList: true, subtree: true, characterData: true, attributes: true });

  function onInput(e) { const t = e.target; if (t && t.nodeType === 1 && t.matches && t.matches(INPUT_SEL)) handleElement(t); }
  document.addEventListener('input', onInput, true);
  document.addEventListener('change', onInput, true);
  document.addEventListener('keyup', onInput, true);

  // ------------------------------------------------------------ geometry
  const fixedCache = new WeakMap();
  function clipChain(el) {
    let c = clipCache.get(el);
    if (c) return c;
    c = [];
    let fixed = false;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (e !== el && (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') && e !== document.documentElement) c.push(e);
      if (cs.position === 'fixed' || cs.position === 'sticky') fixed = true;   // does not scroll with the document
      if (cs.position === 'fixed') break;
    }
    clipCache.set(el, c);
    fixedCache.set(el, fixed);
    return c;
  }
  const vw = () => document.documentElement.clientWidth || window.innerWidth;
  const vh = () => document.documentElement.clientHeight || window.innerHeight;

  // returns {rect:[x,y,w,h]|null, partial:bool}
  function visibleRect(r, owner, frameCache) {
    let x0 = Math.max(r.left, 0), y0 = Math.max(r.top, 0), x1 = Math.min(r.right, vw()), y1 = Math.min(r.bottom, vh());
    for (const a of clipChain(owner)) {
      let b = frameCache.get(a);
      if (!b) { b = a.getBoundingClientRect(); frameCache.set(a, b); }
      x0 = Math.max(x0, b.left); y0 = Math.max(y0, b.top); x1 = Math.min(x1, b.right); y1 = Math.min(y1, b.bottom);
    }
    if (x1 - x0 < 0.5 || y1 - y0 < 0.5) return null;
    const w = x1 - x0, h = y1 - y0;
    let hit = 0;
    for (const f of [0.25, 0.5, 0.75]) {
      const e = document.elementFromPoint(x0 + w * f, y0 + h / 2);
      if (e && (owner.contains(e) || e === owner)) hit++;
    }
    if (hit === 0) return null; // occluded (e.g. under a sticky header): nothing painted there
    const q = (v) => Math.round(v * 10) / 10;
    return { rect: [q(x0), q(y0), q(w), q(h)], partial: hit < 3, fixed: !!fixedCache.get(owner) };
  }

  // ------------------------------------------------------------ frame loop
  let lastFlush = 0;
  function frame(ts) {
    const f0 = performance.now();
    requestAnimationFrame(frame);
    if (!document.documentElement) return;
    if (!state.sheetOk || (HAS_ADOPT && sheet && !document.adoptedStyleSheets.includes(sheet)) || (styleEl && !styleEl.isConnected)) installSheet();
    if (hl && CSS.highlights.get('ds-mask') !== hl) CSS.highlights.set('ds-mask', hl);
    const t = performance.timeOrigin + ts;
    const frameCache = new Map();
    const groups = new Map();
    const overlayRects = [];
    for (const [key, it] of items) {
      if (!(it.kind === 'text' ? it.node.isConnected : it.el.isConnected)) { dropItem(key); continue; }
      let g = groups.get(it.selector);
      if (!g) { g = { rects: [], boxes: [], partial: [], count: 0, hidden: 0, ok: true }; groups.set(it.selector, g); }
      g.count++;
      let raw = [];
      // drawn as cover overlay? (box overlays carry the sentinel border)
      const drawn = it.kind === 'box' || (it.kind === 'input' && it.valueHit) || (it.kind === 'text' && it.overlay);
      const isBox = it.kind === 'box' || (it.kind === 'input' && it.valueHit);
      if (it.kind === 'text') { for (const r of it.ranges) raw.push(...r.getClientRects()); }
      else { const b = it.el.getBoundingClientRect(); if (b.width > 0 && b.height > 0) raw.push(b); }
      const owner = it.el;
      let any = false;
      for (const r of raw) {
        if (r.width <= 0 || r.height <= 0) continue;
        const v = visibleRect(r, owner, frameCache);
        if (!v) { g.hidden++; continue; }
        any = true;
        if (g.rects.length < MAX_RECTS) {
          const i = g.rects.length;
          g.rects.push(v.rect);
          if (v.partial) g.partial.push(i);
          if (isBox) g.boxes.push(i);
        }
        if (drawn) overlayRects.push({ x: v.rect[0], y: v.rect[1], w: v.rect[2], h: v.rect[3], box: isBox, fixed: v.fixed });
      }
      // state: the mask surface must really be active for this item
      if (any) {
        if (it.kind === 'text' && !it.overlay && !(hl && state.sheetOk && it.ranges.every((r) => hl.has(r)))) g.ok = false;
        if (it.kind === 'text' && it.overlay && !state.hostOk) g.ok = false;
        if (it.kind === 'input' && !it.valueHit && !state.sheetOk) g.ok = false;
      }
    }
    drawOverlay(overlayRects);
    for (const [selector, g] of groups) {
      if (!g.rects.length && !g.hidden) continue;
      const entry = { t, kind: 'masked', selector, count: g.count, rects: g.rects, state: g.ok ? 'masked' : 'unmasked' };
      if (g.boxes.length) entry.boxes = g.boxes;
      if (g.partial.length) entry.partial = g.partial;
      if (g.hidden) entry.hidden = g.hidden;
      log.push(entry);
    }
    if (log.length > MAX_BUFFER) { stats.dropped_log += log.length - MAX_BUFFER; log.splice(0, log.length - MAX_BUFFER); }
    if (!state.ready && state.sheetOk && (document.readyState !== 'loading' || state.sheetOk)) {
      state.ready = true; window.__dsMaskReady = true; api.ready = true;
    }
    const dt = performance.now() - f0;
    stats.frames++; stats.frame_ms += dt; if (dt > stats.max_frame_ms) stats.max_frame_ms = dt;
    if (ts - lastFlush > 200) { lastFlush = ts; flush(); }
  }

  function drain() { return log.splice(0, log.length); }
  function flush() {
    if (typeof window.__dsMaskSink !== 'function' || !log.length) return;
    try { const batch = drain(); const p = window.__dsMaskSink(batch); if (p && p.catch) p.catch(() => {}); } catch (e) { /* recorder gone */ }
  }

  // --------------------------------------------------------- fail-closed API
  function computedMasked(el) {
    const cs = getComputedStyle(el);
    if (style.kind === 'blur') return cs.filter && cs.filter !== 'none';
    const fill = cs.webkitTextFillColor;
    return (fill === 'rgba(0, 0, 0, 0)' || fill === 'transparent') && cs.backgroundColor !== 'rgba(0, 0, 0, 0)';
  }
  function assertMasked() {
    installSheet(); ensureHighlight();
    rescanAll(); // fresh view: never trust incremental state for the gate
    const failures = [], checked = [];
    for (const e of configErrors) failures.push({ selector: e.selector, reason: e.reason });
    if (!state.sheetOk) failures.push({ selector: '*', reason: 'stylesheet_not_applied' });
    if (!HAS_HL && !HAS_ADOPT && !state.sheetOk) failures.push({ selector: '*', reason: 'no_mask_surface' });
    for (const s of selectors) {
      let els = [];
      try { els = Array.from(document.querySelectorAll(s)); } catch (e) { continue; }
      let rendered = 0, masked = 0;
      for (const el of els) {
        if (SKIP_TAGS.has(el.tagName)) continue;
        if (!el.getClientRects().length && !isSvg(el)) continue; // display:none etc: nothing painted
        rendered++;
        let ok = true, reason = '';
        const inputs = el.matches(INPUT_SEL) ? [el] : Array.from(el.querySelectorAll(INPUT_SEL));
        for (const inp of inputs) {
          if (!inp.getClientRects().length) continue;
          const it = items.get(inp);
          if (style.kind === 'blur' ? !computedMasked(inp) : (!it && !computedMasked(inp))) { ok = false; reason = 'input_not_masked'; }
          else if (style.kind !== 'blur' && !computedMasked(inp) && !(it && it.valueHit)) { ok = false; reason = 'input_style_missing'; }
        }
        if (ok && !el.matches(INPUT_SEL)) {
          const w = document.createTreeWalker(el, 4);
          let tn;
          while ((tn = w.nextNode())) {
            if (!tn.data.trim() || (tn.parentElement && SKIP_TAGS.has(tn.parentElement.tagName))) continue;
            if (tn.parentElement && tn.parentElement.matches(INPUT_SEL)) continue;
            const it = items.get(tn);
            const live = it && it.ranges.length && (it.overlay ? state.hostOk : (hl && it.ranges.every((r) => hl.has(r))));
            if (!live) { ok = false; reason = 'text_unmasked'; break; }
          }
          if (ok && !el.textContent.trim() && !inputs.length && !items.get(el)) { ok = false; reason = 'box_unmasked'; }
        }
        if (style.kind === 'blur' && !computedMasked(el)) { ok = false; reason = 'blur_not_applied'; }
        if (ok) masked++; else failures.push({ selector: s, reason, tag: el.tagName.toLowerCase() });
      }
      checked.push({ selector: s, matched: els.length, rendered, masked });
    }
    // regex hits must be registered too (rescanAll just did it; verify the registry is live)
    let regexHits = 0;
    for (const it of items.values()) if (/^regex#/.test(it.selector || '')) regexHits++;
    // surfaces CSS cannot mask (native tooltips, a11y labels): report for the post-hoc tier
    const unmaskable = [];
    for (const el of document.querySelectorAll('[title],[aria-label],[alt]')) {
      for (const attr of ['title', 'aria-label', 'alt']) {
        const v = el.getAttribute(attr);
        if (!v) continue;
        const sel = selfMatchSel(el);
        const hit = sel || regexes.some((rg) => { rg.re.lastIndex = 0; return rg.re.test(v); });
        if (hit && unmaskable.length < 50) unmaskable.push({ surface: 'attribute', attr, tag: el.tagName.toLowerCase(), selector: sel || 'regex' });
      }
    }
    return { ok: failures.length === 0, unmaskable, ready: state.ready, mode: HAS_HL ? 'highlight' : 'overlay', style_sheet: HAS_ADOPT ? 'adopted' : 'element', regex_hits: regexHits, checked, failures };
  }

  const api = {
    version: 1, ready: false, mode: HAS_HL ? 'highlight' : 'overlay', sheet_mode: HAS_ADOPT ? 'adopted' : 'element',
    config: { selectors: selectors.slice(), regexes: regexes.length, mask_style: style, errors: configErrors },
    log, drain, flush, assertMasked,
    stats: () => Object.assign({}, stats, { items: items.size, avg_frame_ms: stats.frames ? stats.frame_ms / stats.frames : 0 }),
    rescan: rescanAll,
  };
  Object.defineProperty(window, '__dsMask', { value: api, configurable: false, enumerable: false });
  window.__dsMaskReady = false;

  // ------------------------------------------------------------- bootstrap
  installSheet();
  ensureHighlight();
  if (document.documentElement) rescanAll();
  requestAnimationFrame(frame);
  addEventListener('pagehide', flush, true);
  // <style> fallback needs <head>; poll cheaply through the observer already attached, plus DOMContentLoaded.
  document.addEventListener('DOMContentLoaded', () => { installSheet(); rescanAll(); }, true);
})();
