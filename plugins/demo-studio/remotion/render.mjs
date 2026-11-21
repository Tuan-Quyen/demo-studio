#!/usr/bin/env node
// demo-studio render engine (Remotion). Runs from <project>/.demo/remotion/ (setup_tools.py copies
// this folder there and installs node_modules next to it; the plugin never keeps node_modules).
//
//   node render.mjs --project .demo/<slug>/project.json --ratio 16x9 --out .demo/<slug>/media/final-16x9.mp4
//        [--audio .demo/<slug>/media/render/mix.wav] [--burn-in] [--layout overlay|band]
//        [--level none|basic|cinematic] [--bg #0B1020] [--from-ms A --to-ms B] [--still MS]
//        [--props-out FILE] [--props-only]
//
// Reads #timeline, #events.clips, #blur, #motion and #captions, maps every time to the final timeline
// (media-specs "Spaces and time") and renders blur + motion + captions + audio in ONE pass.
// --still MS writes one PNG frame; --from-ms/--to-ms renders a preview range; --props-only prints
// the normalized props and exits (no Remotion needed).
// Exit codes: 0 ok, 1 render failed, 2 usage / bad project data.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SIZES = {'16x9': [1920, 1080], '9x16': [1080, 1920], '1x1': [1080, 1080]};

class UsageError extends Error {}

function parseArgs(argv) {
  const flags = new Set(['--burn-in', '--props-only']);
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) throw new UsageError(`unexpected argument: ${a}`);
    const key = a.slice(2);
    if (flags.has(a)) out[key] = true;
    else {
      if (i + 1 >= argv.length) throw new UsageError(`${a} needs a value`);
      out[key] = argv[++i];
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

async function main(argv) {
  const a = parseArgs(argv);
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
