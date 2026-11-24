#!/usr/bin/env node
// demo-studio render engine (Remotion). Runs from <project>/.demo/remotion/ (setup_tools.py copies
// this folder there and installs node_modules next to it; the plugin never keeps node_modules).
//
//   node render.mjs --project .demo/<slug>/project.json --ratio 16x9 --out .demo/<slug>/media/final-16x9.mp4
//        [--audio .demo/<slug>/media/render/mix.wav] [--burn-in] [--layout overlay|band]
//        [--level none|basic|cinematic] [--bg #0B1020] [--from-ms A --to-ms B] [--still MS]
//        [--props-out FILE] [--props-only]
//   node render.mjs --art --size WxH --layer FILE [--layer FILE ...] --out FILE.png
//        [--bg #RRGGBB|transparent] [--check-only]
//
// Reads #timeline, #events.clips, #blur, #motion and #captions, maps every time to the final timeline
// (media-specs "Spaces and time") and renders blur + motion + captions + audio in ONE pass.
// --still MS writes one PNG frame; --from-ms/--to-ms renders a preview range; --props-only prints
// the normalized props and exits (no Remotion needed).
// --art (raster mode) draws .svg/.png layers bottom to top into ONE PNG; it needs no project.json and
// is refused together with --project/--still/--ratio. Every layer and --out must sit inside the nearest
// .demo/<slug>/ folder of the first layer. --check-only runs the checks (size, paths, SVG lint, PNG
// IHDR) and prints JSON without loading Remotion. The output PNG size is read back from its IHDR.
// Exit codes: 0 ok, 1 render failed, 2 usage / bad project data.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SIZES = {'16x9': [1920, 1080], '9x16': [1080, 1920], '1x1': [1080, 1080]};

class UsageError extends Error {}

function parseArgs(argv) {
  const flags = new Set(['--burn-in', '--props-only', '--art', '--check-only']);
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) throw new UsageError(`unexpected argument: ${a}`);
    const key = a.slice(2);
    if (flags.has(a)) out[key] = true;
    else {
      if (i + 1 >= argv.length) throw new UsageError(`${a} needs a value`);
      if (key === 'layer') (out.layer ||= []).push(argv[++i]);
      else out[key] = argv[++i];
    }
  }
  return out;
}

const num = (v, name) => {
  const n = Number(v);
  if (!Number.isFinite(n)) throw new UsageError(`${name} must be a number, got ${v}`);
  return n;
};

const rel = (base, p) => path.relative(base, path.resolve(p)).split(path.sep).join('/');

export function buildProps(project, slugDir, opts) {
  const ratio = opts.ratio || '16x9';
  if (!SIZES[ratio]) throw new UsageError(`--ratio must be one of ${Object.keys(SIZES).join(', ')}`);
  const tl = project.timeline;
  const clips = project.events?.clips;
  if (!tl?.scenes?.length) throw new UsageError('project.json has no #timeline.scenes');
  if (!clips) throw new UsageError('project.json has no #events.clips');
  const scenes = tl.scenes.map((s) => {
    const c = clips[s.id];
    if (!c || !c.w || !c.h) throw new UsageError(`#events.clips.${s.id} needs w and h`);
    return {
      id: s.id,
      src: String(s.clip || c.file).replace(/\\/g, '/'),
      w: c.w,
      h: c.h,
      inMs: s.in ?? 0,
      speed: s.speed || 1,
      start: s.start,
      end: s.end,
      fps: c.fps,
      offset: c.offset_ms ?? 0,
    };
  });
  const byId = Object.fromEntries(scenes.map((s) => [s.id, s]));
  // #blur is scene-relative: final = start + (t + offset_ms - in) / speed
  const toFinal = (sc, t) => sc.start + (t + sc.offset - sc.inMs) / sc.speed;
  const blur = (project.blur?.regions || []).map((r, i) => {
    const sc = byId[r.scene];
    if (!sc) throw new UsageError(`#blur region ${r.id || i} names unknown scene ${r.scene}`);
    const m = r.margin_ms ?? 0;
    return {
      id: r.id || `b${i + 1}`,
      scene: r.scene,
      start: toFinal(sc, r.t_start) - m,
      end: toFinal(sc, r.t_end) + m,
      bbox: r.bbox,
      pad: r.pad ?? 0,
      mode: r.mode === 'pixelate' ? 'pixelate' : 'boxblur',
      strength: r.strength ?? 25,
      keyframes: r.keyframes ? r.keyframes.map((k) => ({t: toFinal(sc, k.t), bbox: k.bbox})) : null,
    };
  });
  const level = opts.level || project.motion?.level || 'basic';
  const effects =
    level === 'none'
      ? []
      : (project.motion?.effects || []).filter(
          (e) => !e.params?.aspects || e.params.aspects.includes(ratio),
        );
  // title_card params.image: a project-relative PNG/JPG inside the slug folder; a missing file is exit 2.
  for (const e of effects) {
    if (e.type !== 'title_card' || e.params?.image === undefined || e.params?.image === null) continue;
    const img = String(e.params.image).replace(/\\/g, '/');
    const abs = path.resolve(slugDir, img);
    if (!img || path.isAbsolute(img) || !inside(slugDir, abs)) {
      throw new UsageError(`title_card image must be inside the .demo/<slug>/ folder: ${img}`);
    }
    if (!fs.existsSync(abs) || !fs.statSync(abs).isFile()) throw new UsageError(`title_card image not found: ${img}`);
    e.params = {...e.params, image: img};
  }
  const cues = opts.burnIn
    ? (project.captions?.cues || []).map((c) => ({
        start: c.t_start,
        end: c.t_end,
        pos: c.pos === 'top' ? 'top' : 'bottom',
        lines: c.lines || [],
      }))
    : [];
  const fpsList = scenes.map((s) => s.fps).filter(Boolean);
  const fps = fpsList.length ? Math.min(...fpsList) : 25; // never fake a higher fps
  const durationMs = tl.total_s ? Math.round(tl.total_s * 1000) : Math.max(...scenes.map((s) => s.end));
  const [width, height] = SIZES[ratio];
  let audio = null;
  if (opts.audio) {
    audio = rel(slugDir, opts.audio);
    if (audio.startsWith('..')) throw new UsageError('--audio must be inside the .demo/<slug>/ folder');
    if (!fs.existsSync(path.resolve(opts.audio))) throw new UsageError(`audio not found: ${opts.audio}`);
  }
  for (const s of scenes) {
    if (!fs.existsSync(path.join(slugDir, s.src))) throw new UsageError(`clip not found: ${s.src}`);
  }
  return {
    width,
    height,
    fps,
    durationMs,
    ratio,
    level,
    layout: opts.layout === 'band' ? 'band' : 'overlay',
    bg: opts.bg || '#0B1020',
    audio,
    scenes: scenes.map(({fps: _f, offset: _o, ...s}) => s),
    blur,
    effects,
    cues,
  };
}

// ---- art mode (--art): layered SVG/PNG -> one PNG -------------------------------------------------

const ART_MIN = 16;
const ART_MAX = 4096;
const PNG_SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

// Width/height from the PNG IHDR chunk (first chunk, bytes 16..24). Throws UsageError on anything else.
export function readPngSize(file) {
  let head;
  try {
    const fd = fs.openSync(file, 'r');
    try {
      head = Buffer.alloc(24);
      const n = fs.readSync(fd, head, 0, 24, 0);
      head = head.subarray(0, n);
    } finally {
      fs.closeSync(fd);
    }
  } catch (e) {
    throw new UsageError(`cannot read ${file}: ${e.message}`);
  }
  if (head.length < 24 || !head.subarray(0, 8).equals(PNG_SIG) || head.toString('latin1', 12, 16) !== 'IHDR') {
    throw new UsageError(`not a PNG (bad signature or IHDR): ${file}`);
  }
  const w = head.readUInt32BE(16);
  const h = head.readUInt32BE(20);
  if (!w || !h) throw new UsageError(`PNG has a zero size: ${file}`);
  return {w, h};
}

const NAMED = {amp: '&', lt: '<', gt: '>', quot: '"', apos: "'"};
const safeChar = (cp) => (cp > 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : '');
function decodeEntities(t) {
  return t
    .replace(/&#x([0-9a-f]+);?/gi, (_, h) => safeChar(parseInt(h, 16)))
    .replace(/&#(\d+);?/g, (_, d) => safeChar(parseInt(d, 10)))
    .replace(/&(amp|lt|gt|quot|apos);/g, (_, n) => NAMED[n]);
}

// CSS escapes (a backslash plus hex digits, e.g. inside `url(`) are legal in <style>, so lint the unescaped text too.
function cssUnescape(t) {
  return t
    .replace(/\\([0-9a-f]{1,6})[ \t\r\n\f]?/gi, (_, h) => safeChar(parseInt(h, 16)))
    .replace(/\\([^\n])/g, '$1');
}

// An SVG may only reference `#id` and `data:font/*` (KART-E13, E18).
const refOk = (v) => /^#\S+$/.test(v.trim()) || /^data:font\//i.test(v.trim());

// Returns a list of problems; empty = clean. Lints the raw text and the entity-decoded text
// so `&#x6F;nclick` cannot hide.
export function lintSvg(text) {
  const problems = new Set();
  const variants = [text];
  const decoded = decodeEntities(text);
  if (decoded !== text) variants.push(decoded);
  for (const v of [...variants]) {
    const u = cssUnescape(v);
    if (u !== v) variants.push(u);
  }
  for (const t of variants) {
    if (/<\s*(?:[\w.-]+:)?script/i.test(t)) problems.add('<script');
    if (/(^|[\s"'/;])on[a-z]+\s*=/i.test(t)) problems.add('on*= event attribute');
    if (/<\s*(?:[\w.-]+:)?foreignObject/i.test(t)) problems.add('<foreignObject>');
    if (/<\s*(?:[\w.-]+:)?(?:image|feImage)\b/i.test(t)) problems.add('<image>');
    if (/data:\s*image/i.test(t)) problems.add('data:image');
    // A DTD can split a forbidden string across entities; no SVG layer needs a DOCTYPE or ENTITY.
    if (/<!\s*(?:DOCTYPE|ENTITY)/i.test(t)) problems.add('DOCTYPE/ENTITY declaration');
    // CSS image functions take a bare string that url() lint does not see.
    for (const m of t.matchAll(/(?:^|[^\w-])((?:-webkit-)?(?:image-set|cross-fade|image|element))\s*\(/gi)) problems.add(`${m[1]}()`);
    for (const m of t.matchAll(/href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/gi)) {
      const v = m[1] ?? m[2] ?? m[3] ?? '';
      if (!refOk(v)) problems.add(`href to ${v.slice(0, 40) || '(empty)'}`);
    }
    for (const m of t.matchAll(/url\(\s*(["']?)(.*?)\1\s*\)/gis)) {
      if (!refOk(m[2])) problems.add(`url(${m[2].slice(0, 40)})`);
    }
    for (const m of t.matchAll(/@import\b\s*(?:url\(\s*)?["']?([^"')\s;]*)/gi)) {
      if (!/^data:font\//i.test(m[1])) problems.add(`@import ${m[1].slice(0, 40)}`);
    }
  }
  return [...problems];
}

function svgRootSize(text) {
  const m = /<svg\b[^>]*>/i.exec(text.replace(/<!--[\s\S]*?-->/g, ''));
  if (!m) return null;
  const attr = (n) => {
    const r = new RegExp(`\\s${n}\\s*=\\s*["']\\s*([0-9.]+)\\s*(?:px)?\\s*["']`, 'i').exec(m[0]);
    return r ? Number(r[1]) : null;
  };
  return {w: attr('width'), h: attr('height')};
}

const inside = (base, p) => {
  const r = path.relative(base, p);
  return r !== '' && !r.startsWith('..') && !path.isAbsolute(r);
};

// Nearest ancestor folder of `file` that is `.demo/<slug>`.
function demoSlugRoot(file) {
  let dir = path.dirname(path.resolve(file));
  for (;;) {
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    if (path.basename(parent) === '.demo') return dir;
    dir = parent;
  }
}

// All pre-render checks; this is everything --check-only does. Throws UsageError (exit 2).
export function checkArt(a) {
  for (const k of ['project', 'still', 'ratio']) {
    if (a[k] !== undefined) throw new UsageError(`--art cannot be combined with --${k}`);
  }
  const sm = /^(\d+)x(\d+)$/.exec(a.size || '');
  if (!sm) throw new UsageError('--size WxH is required (integers)');
  const w = Number(sm[1]);
  const h = Number(sm[2]);
  if (w < ART_MIN || h < ART_MIN || w > ART_MAX || h > ART_MAX) {
    throw new UsageError(`--size must be ${ART_MIN}..${ART_MAX} on each side, got ${w}x${h}`);
  }
  if (!a.out) throw new UsageError('--out <file>.png is required');
  if (path.extname(a.out).toLowerCase() !== '.png') throw new UsageError('--out must be a .png file');
  const bg = a.bg ?? '#0B1020';
  if (bg !== 'transparent' && !/^#[0-9a-fA-F]{6}$/.test(bg)) {
    throw new UsageError('--bg must be #RRGGBB or transparent');
  }
  const files = a.layer || [];
  if (!files.length) throw new UsageError('at least one --layer FILE is required');
  const root = demoSlugRoot(files[0]);
  if (!root) throw new UsageError('first --layer must be inside a .demo/<slug>/ folder');
  const out = path.resolve(a.out);
  if (!inside(root, out)) throw new UsageError(`--out must be inside ${root}`);
  const layers = files.map((f) => {
    const abs = path.resolve(f);
    const ext = path.extname(abs).toLowerCase();
    if (ext !== '.svg' && ext !== '.png') throw new UsageError(`layer must be .svg or .png: ${f}`);
    if (!inside(root, abs)) throw new UsageError(`layer must be inside ${root}: ${f}`);
    if (!fs.existsSync(abs) || !fs.statSync(abs).isFile()) throw new UsageError(`layer not found: ${f}`);
    if (ext === '.png') return {file: f, abs, kind: 'png', ...readPngSize(abs)};
    const text = fs.readFileSync(abs, 'utf8');
    const bad = lintSvg(text);
    if (bad.length) throw new UsageError(`SVG lint failed for ${f}: ${bad.join('; ')}`);
    const size = svgRootSize(text);
    if (!size) throw new UsageError(`not an SVG (no <svg> root): ${f}`);
    return {file: f, abs, kind: 'svg', w: size.w, h: size.h};
  });
  const top = [...layers].reverse().find((l) => l.kind === 'svg');
  if (top && (top.w !== w || top.h !== h)) {
    throw new UsageError(`top SVG ${top.file} must have width/height ${w}x${h}, got ${top.w}x${top.h}`);
  }
  return {w, h, bg, root, out, layers};
}

async function mainArt(a) {
  const c = checkArt(a);
  const list = c.layers.map(({file, kind, w, h}) => ({file, kind, w, h}));
  if (a['check-only']) {
    process.stdout.write(JSON.stringify({ok: true, mode: 'art', w: c.w, h: c.h, layers: list}) + '\n');
    return 0;
  }
  // Remotion finds its headless Chrome under <cwd>/node_modules/.remotion: run from this folder.
  process.chdir(HERE);
  const {bundle} = await import('@remotion/bundler');
  const {selectComposition, renderStill} = await import('@remotion/renderer');
  const props = {
    width: c.w,
    height: c.h,
    bg: c.bg,
    layers: c.layers.map((l) => ({src: rel(c.root, l.abs), kind: l.kind})),
  };
  const serveUrl = await bundle({entryPoint: path.join(HERE, 'src', 'index.ts'), rootDir: HERE, publicDir: c.root});
  const composition = await selectComposition({serveUrl, id: 'art', inputProps: props});
  fs.mkdirSync(path.dirname(c.out), {recursive: true});
  await renderStill({composition, serveUrl, output: c.out, frame: 0, inputProps: props, imageFormat: 'png'});
  let got;
  try {
    got = readPngSize(c.out);
  } catch (e) {
    throw new Error(`render produced no valid PNG: ${e.message}`);
  }
  if (got.w !== c.w || got.h !== c.h) throw new Error(`PNG is ${got.w}x${got.h}, expected ${c.w}x${c.h}`);
  const pkg = JSON.parse(fs.readFileSync(path.join(HERE, 'node_modules', 'remotion', 'package.json'), 'utf8'));
  process.stdout.write(
    JSON.stringify({
      ok: true,
      renderer: 'remotion',
      mode: 'art',
      remotion: pkg.version,
      out: c.out,
      w: got.w,
      h: got.h,
      bytes: fs.statSync(c.out).size,
      layers: list,
    }) + '\n',
  );
  return 0;
}

async function main(argv) {
  const a = parseArgs(argv);
  if (a.art) return mainArt(a);
  for (const k of ['check-only', 'layer', 'size']) {
    if (a[k] !== undefined) throw new UsageError(`--${k} needs --art`);
  }
  if (!a.project) throw new UsageError('--project <.demo/<slug>/project.json> is required');
  const projectPath = path.resolve(a.project);
  let project;
  try {
    project = JSON.parse(fs.readFileSync(projectPath, 'utf8'));
  } catch (e) {
    throw new UsageError(`cannot read ${a.project}: ${e.message}`);
  }
  const slugDir = path.dirname(projectPath);
  const props = buildProps(project, slugDir, {
    ratio: a.ratio,
    audio: a.audio,
    burnIn: Boolean(a['burn-in']),
    layout: a.layout,
    level: a.level,
    bg: a.bg,
  });
  if (a['props-out']) fs.writeFileSync(a['props-out'], JSON.stringify(props, null, 2));
  if (a['props-only']) {
    process.stdout.write(JSON.stringify(props, null, 2) + '\n');
    return 0;
  }
  if (!a.out) throw new UsageError('--out <file> is required');
  const out = path.resolve(a.out);
  // Remotion finds its headless Chrome under <cwd>/node_modules/.remotion: run from this folder.
  process.chdir(HERE);

  const {bundle} = await import('@remotion/bundler');
  const {selectComposition, renderMedia, renderStill} = await import('@remotion/renderer');
  const serveUrl = await bundle({
    entryPoint: path.join(HERE, 'src', 'index.ts'),
    rootDir: HERE,
    publicDir: slugDir,
  });
  const composition = await selectComposition({serveUrl, id: 'demo', inputProps: props});
  const frameOf = (ms) => Math.max(0, Math.min(composition.durationInFrames - 1, Math.round((ms / 1000) * props.fps)));
  fs.mkdirSync(path.dirname(out), {recursive: true});

  if (a.still !== undefined) {
    await renderStill({composition, serveUrl, output: out, frame: frameOf(num(a.still, '--still')), inputProps: props, imageFormat: 'png'});
  } else {
    const frameRange =
      a['from-ms'] !== undefined || a['to-ms'] !== undefined
        ? [frameOf(num(a['from-ms'] ?? 0, '--from-ms')), frameOf(num(a['to-ms'] ?? props.durationMs, '--to-ms'))]
        : null;
    let last = -1;
    await renderMedia({
      composition,
      serveUrl,
      outputLocation: out,
      inputProps: props,
      codec: 'h264',
      crf: 18,
      x264Preset: 'slow',
      pixelFormat: 'yuv420p',
      colorSpace: 'bt709', // limited (tv) range BT.709; the v4 default writes full-range yuvj420p
      imageFormat: 'jpeg',
      jpegQuality: 95,
      audioCodec: 'aac',
      audioBitrate: '192k',
      encodingMaxRate: '20M',
      encodingBufferSize: '40M',
      enforceAudioTrack: Boolean(props.audio),
      frameRange,
      onProgress: ({progress}) => {
        const pct = Math.floor(progress * 10) * 10;
        if (pct !== last) {
          last = pct;
          process.stderr.write(`render ${pct}%\n`);
        }
      },
    });
  }
  const pkg = JSON.parse(fs.readFileSync(path.join(HERE, 'node_modules', 'remotion', 'package.json'), 'utf8'));
  process.stdout.write(
    JSON.stringify({
      ok: true,
      renderer: 'remotion',
      remotion: pkg.version,
      out,
      ratio: props.ratio,
      w: props.width,
      h: props.height,
      fps: props.fps,
      duration_s: props.durationMs / 1000,
      burn_in: props.cues.length > 0,
      effects: props.effects.length,
      blur_regions: props.blur.length,
    }) + '\n',
  );
  return 0;
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  main(process.argv.slice(2)).then(
    (code) => process.exit(code),
    (e) => {
      process.stderr.write(`error: ${e.message}\n`);
      process.exit(e instanceof UsageError ? 2 : 1);
    },
  );
}
