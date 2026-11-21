/*
 * privacy_oracle.js - INDEPENDENT oracle for the capture-time mask (demo-studio, redesign 6.4, S-09).
 *
 * privacy_mask.js logs the rects it believes it covered; the gate checks pixels there. If both came from one
 * source, a mispositioned overlay would verify itself. This script shares NO code with privacy_mask.js: it
 * re-discovers what is sensitive from the live DOM (selectors + regexes) and logs where that text really is
 * (Range / element boxes, clipped to the viewport and scroll containers). The gate checks the pixels at THESE
 * rects too: wherever sensitive text really is, the frame must show the mask colour.
 *
 * Config: window.__DS_ORACLE_CONFIG = {selectors:[css], regexes:[source|{source,flags}], probes:[css]}
 * Output: log entries pushed to window.__dsMaskSink (same batches as the mask log):
 *   {t, kind:"oracle", rects:[[x,y,w,h]], skip:[idx proven opaque-occluded]}     (one per animation frame)
 *   {t, kind:"probe", selector, rect}                                              (--probe test selectors)
 * It never touches the DOM. Not injected when the page has no way to run it (still passes through add_init_script).
 */
(() => {
  'use strict';
  if (window.__dsOracle) return;
  const C = window.__DS_ORACLE_CONFIG || {};
  const sels = [];
  for (const s of ['[data-sensitive]'].concat(C.selectors || [])) {
    try { document.createDocumentFragment().querySelector(s); sels.push(s); } catch (e) { /* the mask reports invalid selectors */ }
  }
  const res = [];
  for (const r of C.regexes || []) {
    try { res.push(new RegExp(typeof r === 'string' ? r : r.source, ((typeof r === 'string' ? '' : (r.flags || '')).replace(/[gy]/g, '')) + 'g')); } catch (e) { /* reported by the mask */ }
  }
  const probes = C.probes || [];
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'TITLE', 'META', 'LINK']);
  const FORM = 'input,textarea,select,[contenteditable=""],[contenteditable="true"]';
  const BOXES = new Set(['IMG', 'CANVAS', 'VIDEO', 'IFRAME', 'OBJECT', 'EMBED', 'PICTURE']);
  const cache = new Map();           // key node/element -> {kind:'range', node, spans:[[a,b]]} | {kind:'box', el}
  const out = [];

  function matchesAny(el) { for (const s of sels) { try { if (el.closest(s)) return true; } catch (e) { /* skip */ } } return false; }
  function spansOf(text) {
    const sp = [];
    for (const re of res) { re.lastIndex = 0; let m; while ((m = re.exec(text)) !== null) { if (!m[0].length) { re.lastIndex++; continue; } sp.push([m.index, m.index + m[0].length]); } }
    return sp;
  }
  function addText(t) {
    cache.delete(t);
    const el = t.parentElement;
    if (!el || SKIP.has(el.tagName) || !t.data.trim()) return;
    if (el.matches && el.matches(FORM)) return;
    const sp = matchesAny(el) ? [[0, t.data.length]] : spansOf(t.data);
    if (sp.length) cache.set(t, { kind: 'range', node: t, spans: sp });
  }
  function addEl(el) {
    cache.delete(el);
    if (SKIP.has(el.tagName)) return;
    const form = el.matches && el.matches(FORM);
    let sensitive = false;
    for (const s of sels) { try { if (el.matches(s)) { sensitive = true; break; } } catch (e) { /* skip */ } }
    if (form && (sensitive || matchesAny(el))) { cache.set(el, { kind: 'box', el }); return; }
    if (form && res.length) {
      const v = (el.value != null ? String(el.value) : el.textContent) || '';
      const ph = el.getAttribute('placeholder') || '';
      if (spansOf(v).length || spansOf(ph).length) { cache.set(el, { kind: 'box', el }); return; }
    }
    if (sensitive && (BOXES.has(el.tagName) || (el.namespaceURI === 'http://www.w3.org/2000/svg' && el.tagName.toLowerCase() === 'svg'))) { cache.set(el, { kind: 'box', el }); return; }
    if (sensitive && !el.querySelector('*') && !el.textContent.trim()) cache.set(el, { kind: 'box', el });
  }
  function scan(root) {
    if (!root) return;
    if (root.nodeType === 3) { addText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1) addEl(root);
    const w = document.createTreeWalker(root, 1 | 4);
    let n;
    while ((n = w.nextNode())) { if (n.nodeType === 3) addText(n); else addEl(n); }
  }
  const mo = new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === 'characterData') addText(m.target);
      else if (m.type === 'childList') { for (const n of m.addedNodes) scan(n); if (m.target.nodeType === 1) addEl(m.target); }
      else if (m.type === 'attributes') scan(m.target);
    }
  });
  mo.observe(document, { childList: true, subtree: true, characterData: true, attributes: true });
  for (const ev of ['input', 'change', 'keyup']) document.addEventListener(ev, (e) => { if (e.target && e.target.nodeType === 1) addEl(e.target); }, true);

  function chain(el) {
    const c = [];
    for (let e = el.parentElement; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if ((cs.overflowX !== 'visible' || cs.overflowY !== 'visible') && e !== document.documentElement && e !== document.body) c.push(e);
      if (cs.position === 'fixed') break;
    }
    return c;
  }
  function opaque(e) {
    let bg = false, seen = false;
    for (let n = e; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (parseFloat(cs.opacity) < 1 || (cs.filter && cs.filter !== 'none') || (cs.backdropFilter && cs.backdropFilter !== 'none')) return false;
      if (!bg && !seen) { const m = /^rgba?\(([^)]*)\)$/.exec(cs.backgroundColor || ''); if (m) { const p = m[1].split(','); const al = p.length === 3 ? 1 : parseFloat(p[3]); if (al > 0) { seen = true; bg = al === 1; } } }
    }
    return bg;
  }
  const W = () => document.documentElement.clientWidth || innerWidth, H = () => document.documentElement.clientHeight || innerHeight;
  function emit(raw, owner, rects, skip, cache2) {
    for (const r of raw) {
      if (r.width <= 0 || r.height <= 0) continue;
      let x0 = Math.max(r.left, 0), y0 = Math.max(r.top, 0), x1 = Math.min(r.right, W()), y1 = Math.min(r.bottom, H());
      let cs = cache2.get(owner);
      if (!cs) { cs = chain(owner).map((a) => a.getBoundingClientRect()); cache2.set(owner, cs); }
      for (const b of cs) { x0 = Math.max(x0, b.left); y0 = Math.max(y0, b.top); x1 = Math.min(x1, b.right); y1 = Math.min(y1, b.bottom); }
      if (x1 - x0 < 0.5 || y1 - y0 < 0.5) continue;
      let hit = 0, proven = true;
      for (const f of [0.25, 0.5, 0.75]) {
        const e = document.elementFromPoint(x0 + (x1 - x0) * f, (y0 + y1) / 2);
        if (e && (owner.contains(e) || e === owner || (e.getRootNode && e.getRootNode() !== document))) hit++;
        else if (!e || !opaque(e)) proven = false;
      }
      if (hit < 3 && proven) skip.push(rects.length);
      rects.push([Math.round(x0 * 10) / 10, Math.round(y0 * 10) / 10, Math.round((x1 - x0) * 10) / 10, Math.round((y1 - y0) * 10) / 10]);
    }
  }
  function frame(ts) {
    requestAnimationFrame(frame);   // armed first: one callback per frame (timing deliberately differs from the mask loop)
    try {
      const t = performance.timeOrigin + ts, rects = [], skip = [], c2 = new Map();
      for (const [k, it] of cache) {
        if (!k.isConnected) { cache.delete(k); continue; }
        if (it.kind === 'box') emit([it.el.getBoundingClientRect()], it.el, rects, skip, c2);
        else for (const [a, b] of it.spans) {
          if (b > it.node.data.length) continue;
          const r = document.createRange(); r.setStart(it.node, a); r.setEnd(it.node, b);
          emit(Array.from(r.getClientRects()), it.node.parentElement, rects, skip, c2);
        }
      }
      if (rects.length) { const e = { t, kind: 'oracle', rects }; if (skip.length) e.skip = skip; if (document.readyState === 'loading') e.loading = true; out.push(e); }
      for (const s of probes) { const e = document.querySelector(s); if (!e) continue; const b = e.getBoundingClientRect(); if (b.width > 0) out.push({ t, kind: 'probe', selector: s, rect: [b.left, b.top, b.width, b.height] }); }
      if (out.length > 3) flush();
    } catch (e) { /* oracle must never break the page */ }
  }
  function flush() {
    if (typeof window.__dsMaskSink !== 'function' || !out.length) return;
    try { const p = window.__dsMaskSink(out.splice(0, out.length)); if (p && p.catch) p.catch(() => {}); } catch (e) { /* recorder gone */ }
  }
  Object.defineProperty(window, '__dsOracle', { value: { drain: () => out.splice(0, out.length), flush, size: () => cache.size }, configurable: false, enumerable: false });
  if (document.documentElement) scan(document.documentElement);
  document.addEventListener('DOMContentLoaded', () => scan(document.documentElement), true);
  requestAnimationFrame(frame);
  addEventListener('pagehide', flush, true);
})();
