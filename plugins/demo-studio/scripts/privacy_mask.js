/*
 * privacy_mask.js - capture-time masking for web recordings (demo-studio, redesign 6.2).
 *
 * Inject with context.addInitScript BEFORE any page load. Config is read from
 * window.__DS_MASK_CONFIG (web_adapter.py prepends `window.__DS_MASK_CONFIG = {...};`):
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
 * Log entry per animation frame and selector group (epoch ms, viewport-clipped CSS px):
 *   {t, kind:"masked", selector, count, rects:[[x,y,w,h]], state:"masked"|"unmasked",
 *    boxes:[idx of rects drawn as box overlay with sentinel border],
 *    occluded:[idx hit-test says something else is on top], skip:[idx proven opaque-occluded], hidden:n (clipped away)}
 *   {t, kind:"tick", items, frames, loading}              (every ~250 ms: proof that the mask loop ran)
 *   entries logged while document.readyState === 'loading' carry loading:true (half-parsed layout: the gate does not
 *   judge frames from them; safe_from_ms starts after the first entry without it)
 *   {t, kind:"unmaskable", surface, selector, reason, rect:[x,y,w,h]}   (surface CSS cannot mask, see detectUnmaskable)
 * Occlusion is NEVER used to drop a rect or skip an overlay (fail closed): the gate decides from pixels; only a
 * DOM-proven opaque occluder (opacity 1 chain, opaque background) lets a rect be skipped (`skip`).
 * The frame loop re-arms itself AFTER the rendering step (MessageChannel), so its callback runs after the
 * app's own animation callbacks of the next frame (overlays do not lag app/scroll updates by one frame).
 * If window.__dsMaskSink exists (context.expose_function), batches are pushed to it every 200 ms.
 */
(() => {
  'use strict';
  if (window.__dsMask) return;

  const RAW = window.__DS_MASK_CONFIG || {};

  // every shadow root (open or closed) created after this point, so its content can be inspected (S-07)
  const shadowRefs = [];
  let selfShadow = false;
  try {
    const orig = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function (init) {
      const root = orig.call(this, init);
      if (!selfShadow) shadowRefs.push({ host: new WeakRef(this), root: new WeakRef(root) });
      return root;
    };
  } catch (e) { /* no WeakRef: shadow content cannot be inspected; reported by detectUnmaskable */ }
  const SEL_STYLE = {
    solid: { kind: 'solid', color: '#9aa3b2', sentinel: '#0b1f4d', blur_px: 10 },
  };
  const style = (() => {
    const m = RAW.mask_style;
    if (m && typeof m === 'object') return Object.assign({}, SEL_STYLE.solid, m);
    if (m === 'blur') return Object.assign({}, SEL_STYLE.solid, { kind: 'blur' });
    return Object.assign({}, SEL_STYLE.solid);
  })();

  // S-17: programmatic `.value` writes (v-model, prefill, page.evaluate) fire no event and no mutation. Every input-like
  // element ever seen is tracked and re-tested each frame, and the value setters are hooked for an immediate re-test.
  const inputs = new Set();
  const touched = [];
  try {
    for (const C of [HTMLInputElement, HTMLTextAreaElement]) {
      const d = Object.getOwnPropertyDescriptor(C.prototype, 'value');
      if (d && d.set) {
        Object.defineProperty(C.prototype, 'value', { configurable: true, enumerable: d.enumerable, get: d.get,
          set: function (v) { d.set.call(this, v); touched.push(this); } });
      }
    }
  } catch (e) { /* the per-frame re-test still covers it */ }

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
      selfShadow = true;
      const sr = host.attachShadow({ mode: 'closed' });
      selfShadow = false;
      wrap = document.createElement('div');
      wrap.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;pointer-events:none';
      sr.appendChild(wrap);
      pool = [];
    }
    root.appendChild(host);
    topShow();
    state.hostOk = host.isConnected;
    return state.hostOk;
  }
  // S-22: <dialog>.showModal() and popovers paint in the top layer, above any z-index. The host is a manual popover
  // so it can join the top layer, and is re-shown (moved on top) whenever the set of top-layer elements changes.
  let topSig = '';
  const HAS_POPOVER = typeof HTMLElement !== 'undefined' && typeof HTMLElement.prototype.showPopover === 'function';
  const topIds = new WeakMap(); let topSeq = 0;
  // identities, not a count: swapping one dialog for another keeps the count but must put the host back on top (S-29)
  function topLayerSig() {
    try {
      return Array.from(document.querySelectorAll(':modal, :popover-open')).filter((e) => e !== host)
        .map((e) => { let i = topIds.get(e); if (!i) { i = ++topSeq; topIds.set(e, i); } return i; }).join(',');
    } catch (e) { return ''; }
  }
  function topLayerCount() { try { return document.querySelectorAll(':modal, :popover-open').length; } catch (e) { return 0; } }
  function topShow() {
    if (!HAS_POPOVER || !host) return;
    try {
      if (!host.hasAttribute('popover')) host.setAttribute('popover', 'manual');
      if (host.matches(':popover-open')) host.hidePopover();
      host.showPopover();
      topSig = topLayerSig();
    } catch (e) { /* not connected yet: retried next frame */ }
  }
  function topCheck() {
    if (!host || !HAS_POPOVER) return;
    const sig = topLayerSig();
    if (sig !== topSig || !host.matches(':popover-open')) topShow();
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
      inputs.add(el);
      const forcedPrev = items.get(el);
      if (forcedPrev && forcedPrev.forced) return;
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
    dirtyDetect = true;
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

  // A DOM proof that `e` paints an opaque surface: no opacity/filter anywhere up the chain and an opaque
  // background on some ancestor-or-self. Anything else (fading backdrop, translucent modal, filter) is NOT proof.
  function opaqueProof(e) {
    let bgOk = false, bgSeen = false;
    for (let n = e; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (parseFloat(cs.opacity) < 1 || (cs.filter && cs.filter !== 'none') || (cs.backdropFilter && cs.backdropFilter !== 'none') ||
          (cs.mixBlendMode && cs.mixBlendMode !== 'normal') || (cs.maskImage && cs.maskImage !== 'none') || (cs.clipPath && cs.clipPath !== 'none')) return false;
      if (!bgOk && !bgSeen) {   // the FIRST painted background decides: a translucent layer over an opaque ancestor is no proof
        const m = /^rgba?\(([^)]*)\)$/.exec(cs.backgroundColor || '');
        if (m) { const p = m[1].split(',').map((x) => parseFloat(x)); const al = p.length === 3 ? 1 : p[3]; if (al > 0) { bgSeen = true; bgOk = al === 1; } }
      }
    }
    return bgOk;
  }

  // returns {rect:[x,y,w,h], occluded, partial, opaque, fixed} or null when the rect is clipped away entirely
  // (outside the viewport / its scroll containers). Occlusion by another element is reported, never used to drop the rect.
  function visibleRect(r, owner, frameCache) {
    let x0 = Math.max(r.left, 0), y0 = Math.max(r.top, 0), x1 = Math.min(r.right, vw()), y1 = Math.min(r.bottom, vh());
    for (const a of clipChain(owner)) {
      let b = frameCache.get(a);
      if (!b) { b = a.getBoundingClientRect(); frameCache.set(a, b); }
      x0 = Math.max(x0, b.left); y0 = Math.max(y0, b.top); x1 = Math.min(x1, b.right); y1 = Math.min(y1, b.bottom);
    }
    if (x1 - x0 < 0.5 || y1 - y0 < 0.5) return null;
    const w = x1 - x0, h = y1 - y0;
    let hit = 0, proven = true;
    for (const f of [0.25, 0.5, 0.75]) {
      const px = x0 + w * f, py = y0 + h / 2;
      const e = document.elementFromPoint(px, py);
      if (e && (owner.contains(e) || e === owner || (host && e === host))) { hit++; continue; }
      // something else answers the hit test: list what is above the owner (S-21: its own ancestors are not occluders,
      // and when the owner is not in the list at all, e.g. pointer-events:none, no opacity proof is possible)
      let reached = false; const occ = [];
      for (const n of document.elementsFromPoint(px, py)) {
        if (n === owner || owner.contains(n)) { reached = true; break; }
        if (n === host || n.contains(owner)) continue;
        occ.push(n);
      }
      if (!occ.length) { hit++; continue; }
      if (!reached || !occ.every(opaqueProof)) proven = false;
    }
    const q = (v) => Math.round(v * 10) / 10;
    return { rect: [q(x0), q(y0), q(w), q(h)], occluded: hit === 0, partial: hit > 0 && hit < 3, opaque: hit < 3 && proven, fixed: !!fixedCache.get(owner) };
  }

  // ------------------------------------------------------------ unmaskable surfaces (S-07)
  // Surfaces CSS/Highlight cannot mask. Detected, logged per frame with their rect, never silently dropped.
  const strHit = (v) => { if (!v) return false; for (const rg of regexes) { rg.re.lastIndex = 0; if (rg.re.test(v)) return true; } return false; };
  const describe = (el) => { try { return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.classList && el.classList.length ? '.' + Array.from(el.classList).slice(0, 2).join('.') : ''); } catch (e) { return '*'; } };
  const unm = new Map();     // key -> {surface, selector, reason, el}
  const ids = new WeakMap(); let idSeq = 0;
  const idOf = (el) => { let i = ids.get(el); if (!i) { i = ++idSeq; ids.set(el, i); } return i; };
  let lastDetect = -1e9, dirtyDetect = false;
  function visibleBox(el) {
    if (!el || !el.isConnected) return null;
    const b = el.getBoundingClientRect();
    if (b.width < 2 || b.height < 2) return null;
    const x0 = Math.max(b.left, 0), y0 = Math.max(b.top, 0), x1 = Math.min(b.right, vw()), y1 = Math.min(b.bottom, vh());
    if (x1 - x0 < 1 || y1 - y0 < 1) return null;
    return [Math.round(x0 * 10) / 10, Math.round(y0 * 10) / 10, Math.round((x1 - x0) * 10) / 10, Math.round((y1 - y0) * 10) / 10];
  }
  function sensitiveEl(el) { return !!matchSel(el); }
  function shadowSensitive(root, depth) {
    if (depth > 6) return true;                               // too deep to prove clean: fail closed
    try {
      for (const s of selectors) { if (root.querySelector(s)) return true; }
      const w = document.createTreeWalker(root, 4);
      let n;
      while ((n = w.nextNode())) { if (n.data && strHit(n.data)) return true; }
    } catch (e) { return true; }
    return false;
  }
  function detectUnmaskable(now) {
    lastDetect = now;
    unm.clear();
    const add = (key, el, surface, reason) => { key = surface + '|' + (key && key.nodeType ? idOf(key) : (typeof key === 'string' ? key : '')); if (!unm.has(key)) unm.set(key, { surface, selector: describe(el), reason, el }); };
    const covered = (el) => { const it = items.get(el); return !!(it && it.kind === 'box'); };
    for (const el of document.querySelectorAll('iframe,frame,canvas,video,object,embed')) {
      if (covered(el) || el === host || !visibleBox(el)) continue;
      const tag = el.tagName.toLowerCase();
      add(el, el, tag === 'iframe' || tag === 'frame' ? 'iframe' : tag === 'canvas' ? 'canvas' : 'embedded-media',
        tag === 'iframe' || tag === 'frame' ? 'frame content is not scanned (cross-origin frames cannot be)' : 'pixel content is not inspectable');
    }
    // shadow DOM: any root whose content holds a selector match or a regex hit (closed roots too, via the attachShadow hook)
    for (let i = shadowRefs.length - 1; i >= 0; i--) {
      const h = shadowRefs[i].host.deref(), r = shadowRefs[i].root.deref();
      if (!h || !r) { shadowRefs.splice(i, 1); continue; }
      if (!h.isConnected || !visibleBox(h)) continue;
      if (shadowSensitive(r, 0)) add(h, h, 'shadow-dom', 'sensitive text or selector inside a shadow root (not scanned)');
    }
    if (!HAS_POPOVER && topLayerCount()) {
      for (const el of document.querySelectorAll(':modal')) { if (visibleBox(el)) add(el, el, 'top-layer', 'top-layer element paints above the overlay host (no popover support)'); }
    }
    // pseudo-element content, broken-image alt text, hovered title tooltips
    const all = document.querySelectorAll('*');
    if (all.length > 30000) {
      unm.set('budget', { surface: 'scan-budget', selector: 'document', reason: 'DOM too large to prove pseudo-element content clean', el: document.documentElement });
    } else {
      for (const el of all) {
        if (el === host || SKIP_TAGS.has(el.tagName)) continue;
        for (const ps of ['::before', '::after']) {
          const c = getComputedStyle(el, ps).content;
          if (!c || c === 'none' || c === 'normal' || c === '""' || c === "''") continue;
          const text = c.replace(/^["']|["']$/g, '');
          if (text && (strHit(text) || sensitiveEl(el)) && visibleBox(el)) add(idOf(el) + ps, el, 'pseudo-element', 'generated content (' + ps + ') is not part of the DOM text');
        }
        if (el.tagName === 'IMG' && el.complete && el.naturalWidth === 0 && el.alt && !covered(el) && (strHit(el.alt) || sensitiveEl(el)) && visibleBox(el)) {
          add(idOf(el) + 'alt', el, 'img-alt', 'alt text of a broken image is painted');
        }
        const ti = el.getAttribute && el.getAttribute('title');
        if (ti && (strHit(ti) || sensitiveEl(el)) && el.matches(':hover') && visibleBox(el)) add(idOf(el) + 'title', el, 'title-tooltip', 'native tooltip is drawn by the browser');
      }
    }
    return Array.from(unm.values());
  }
  function unmaskableSnapshot() {
    const out = [];
    for (const u of detectUnmaskable(performance.now())) { const r = u.surface === 'scan-budget' ? [0, 0, vw(), vh()] : visibleBox(u.el); out.push({ surface: u.surface, selector: u.selector, reason: u.reason, rect: r }); }
    return out.slice(0, 50);
  }

  // ------------------------------------------------------------ frame loop
  let lastFlush = 0, lastTick = 0;
  // Late phase (S-09): once the overlay host exists, the measurement runs in a ResizeObserver callback of a 1 px probe
  // inside it. RO notifications are delivered after the app's animation callbacks and after layout, but before paint,
  // so overlays do not trail app/scroll rAF updates by one frame. A 8 ms timer covers a notification that never comes.
  let roProbe = null, roPending = null, roToggle = 0;
  function ensureRo() {
    if (roProbe || !host || !wrap || typeof ResizeObserver !== 'function') return;
    roProbe = document.createElement('div');
    roProbe.style.cssText = 'position:absolute;left:0;top:0;width:1px;height:1px;visibility:hidden;pointer-events:none';
    wrap.appendChild(roProbe);
    new ResizeObserver(() => { if (roPending !== null) { const ts = roPending; roPending = null; run(ts); } }).observe(roProbe);
  }
  function run(ts) { const f0 = performance.now(); frameBody(ts, f0); ensureRo(); }
  function frame(ts) {
    requestAnimationFrame(frame);          // armed first: one callback per frame, whatever happens below
    if (roProbe && host && host.isConnected) {
      roPending = ts;
      roProbe.style.width = (++roToggle % 2 ? 2 : 1) + 'px';
      setTimeout(() => { if (roPending === ts) { roPending = null; run(ts); } }, 8);
    } else run(ts);
  }
  function frameBody(ts, f0) {
    if (!document.documentElement) return;
    if (touched.length) { for (const el of touched.splice(0)) if (el.isConnected) handleElement(el); }
    for (const el of inputs) { if (!el.isConnected) { inputs.delete(el); dropItem(el); continue; } handleElement(el); }
    if (!state.sheetOk || (HAS_ADOPT && sheet && !document.adoptedStyleSheets.includes(sheet)) || (styleEl && !styleEl.isConnected)) installSheet();
    if (hl && CSS.highlights.get('ds-mask') !== hl) CSS.highlights.set('ds-mask', hl);
    const t = performance.timeOrigin + ts;
    const frameCache = new Map();
    const groups = new Map();
    const overlayRects = [];
    for (const [key, it] of items) {
      if (!(it.kind === 'text' ? it.node.isConnected : it.el.isConnected)) { dropItem(key); continue; }
      let g = groups.get(it.selector);
      if (!g) { g = { rects: [], boxes: [], occluded: [], skip: [], count: 0, hidden: 0, ok: true }; groups.set(it.selector, g); }
      g.count++;
      let raw = [];
      // drawn as cover overlay? (box overlays carry the sentinel border)
      const drawn = it.kind === 'box' || (it.kind === 'input' && it.valueHit) || (it.kind === 'text' && it.overlay) || it.forced;
      const isBox = it.kind === 'box' || (it.kind === 'input' && it.valueHit) || !!it.forced;
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
          if (v.occluded || v.partial) g.occluded.push(i);
          if (v.opaque) g.skip.push(i);
          if (isBox) g.boxes.push(i);
        }
        // S-01: overlays are ALWAYS drawn, whatever the hit-test says (a fading modal backdrop is hit-testable yet translucent)
        if (drawn) overlayRects.push({ x: v.rect[0], y: v.rect[1], w: v.rect[2], h: v.rect[3], box: isBox, fixed: v.fixed });
      }
      // state: the mask surface must really be active for this item
      if (any) {
        if (it.kind === 'text' && !it.overlay && !(hl && state.sheetOk && it.ranges.every((r) => hl.has(r)))) g.ok = false;
        if (it.kind === 'text' && it.overlay && !state.hostOk) g.ok = false;
        if (it.kind === 'input' && !it.valueHit && !it.forced && !state.sheetOk) g.ok = false;
      }
    }
    drawOverlay(overlayRects);
    topCheck();
    for (const [selector, g] of groups) {
      if (!g.rects.length && !g.hidden) continue;
      const entry = { t, kind: 'masked', selector, count: g.count, rects: g.rects, state: g.ok ? 'masked' : 'unmasked' };
      if (document.readyState === 'loading') entry.loading = true;   // half-parsed page: describes no frame the viewer sees
      if (g.boxes.length) entry.boxes = g.boxes;
      if (g.occluded.length) entry.occluded = g.occluded;
      if (g.skip.length) entry.skip = g.skip;
      if (g.hidden) entry.hidden = g.hidden;
      log.push(entry);
    }
    if ((dirtyDetect && ts - lastDetect > 60) || ts - lastDetect > 250) { dirtyDetect = false; detectUnmaskable(ts); }   // S-23: on mutation too
    for (const u of unm.values()) {
      const r = u.surface === 'scan-budget' ? [0, 0, vw(), vh()] : visibleBox(u.el);
      if (r) log.push({ t, kind: 'unmaskable', surface: u.surface, selector: u.selector, reason: u.reason, rect: r });
    }
    stats.frames++;
    if (ts - lastTick > 250) { lastTick = ts; log.push({ t, kind: 'tick', items: items.size, frames: stats.frames, loading: document.readyState === 'loading' }); }
    if (log.length > MAX_BUFFER) { stats.dropped_log += log.length - MAX_BUFFER; log.splice(0, log.length - MAX_BUFFER); }
    if (!state.ready && state.sheetOk && (document.readyState !== 'loading' || state.sheetOk)) {
      state.ready = true; window.__dsMaskReady = true; api.ready = true;
    }
    const dt = performance.now() - f0;
    stats.frame_ms += dt; if (dt > stats.max_frame_ms) stats.max_frame_ms = dt;
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
    let regexHits = 0; const regexLabels = new Set();
    for (const it of items.values()) if (/^regex#/.test(it.selector || '')) { regexHits++; regexLabels.add(it.selector); }
    const unmaskable = unmaskableSnapshot();
    return { ok: failures.length === 0, unmaskable, ready: state.ready, mode: HAS_HL ? 'highlight' : 'overlay', style_sheet: HAS_ADOPT ? 'adopted' : 'element', regex_hits: regexHits, regex_labels: Array.from(regexLabels), checked, failures };
  }

  const api = {
    version: 1, ready: false, mode: HAS_HL ? 'highlight' : 'overlay', sheet_mode: HAS_ADOPT ? 'adopted' : 'element',
    config: { selectors: selectors.slice(), regexes: regexes.length, mask_style: style, errors: configErrors },
    log, drain, flush, assertMasked,
    stats: () => Object.assign({}, stats, { items: items.size, avg_frame_ms: stats.frames ? stats.frame_ms / stats.frames : 0 }),
    rescan: rescanAll,
    // R-08/S-08: JS-semantics regex test of a string (typed text is checked BEFORE the first keystroke)
    testText: (v) => strHit(String(v == null ? '' : v)),
    // S-08: pre-mask the element a regex-matching text is about to be typed into (overlay box from the next frame on)
    forceMask: (el) => {
      if (!el || el.nodeType !== 1 || !el.matches || !el.matches(INPUT_SEL)) return false;
      const had = items.get(el);
      items.set(el, { kind: 'input', el, selector: 'regex#typed', ranges: [], valueHit: true, forced: true });
      inputs.add(el);
      return had && had.forced ? 1 : 2;      // 2 = newly masked (the caller waits for the overlay to paint)
    },
    activeElement: () => document.activeElement,
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
