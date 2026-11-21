import type {Box, DemoProps, Effect, Point, Scene} from './types';

export const easeInOut = (x: number) =>
  x <= 0 ? 0 : x >= 1 ? 1 : x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

// Output-relative unit: 1 px at 1080 p of the short side.
export const unit = (p: DemoProps) => Math.min(p.width, p.height) / 1080;

// Safe-area margins (fractions) from motion-fx.
export const safe = (p: DemoProps) =>
  p.ratio === '9x16'
    ? {top: 0.14, bottom: 0.2, side: 0.06}
    : p.ratio === '1x1'
      ? {top: 0.08, bottom: 0.08, side: 0.08}
      : {top: 0.05, bottom: 0.08, side: 0.05};

export const bandHeight = (p: DemoProps) =>
  p.layout === 'band' ? Math.round(p.height * (p.ratio === '16x9' ? 1 / 6 : 0.22)) : 0;

export type Picture = {x: number; y: number; w: number; h: number; mode: 'fit' | 'cover'};

export const pictureBox = (p: DemoProps, scene: Scene, effects: Effect[]): Picture => {
  const h = p.height - bandHeight(p);
  const device = effects.some((e) => e.type === 'device_frame' && e.scene === scene.id);
  const fitAsked = effects.some(
    (e) => e.type === 'reframe' && e.scene === scene.id && e.params?.mode === 'fit',
  );
  const clipAspect = scene.w / scene.h;
  const boxAspect = p.width / h;
  // Clip much wider than the picture (16:9 clip -> 9:16 / 1:1): crop a window that follows the focus.
  // Otherwise (same aspect, band layout, portrait clip in 16:9, device frame): show the whole frame.
  const mode = !device && !fitAsked && clipAspect / boxAspect > 1.5 ? 'cover' : 'fit';
  if (device) {
    const m = 0.06 * p.height;
    return {x: m, y: m, w: p.width - 2 * m, h: h - 2 * m, mode};
  }
  return {x: 0, y: 0, w: p.width, h, mode};
};

const centerOf = (e: Effect): Point | null => {
  const q = e.params || {};
  if (Array.isArray(q.center)) return q.center as Point;
  if (q.to && Array.isArray(q.to.center)) return q.to.center as Point;
  if (Array.isArray(q.bbox)) {
    const b = q.bbox as Box;
    return [b[0] + b[2] / 2, b[1] + b[3] / 2];
  }
  return null;
};

// Focus for the cover crop: last click/zoom target, eased over 500 ms.
const focusAt = (t: number, scene: Scene, effects: Effect[]): Point => {
  const pts = effects
    .filter((e) => e.scene === scene.id && e.t_start <= t)
    .map((e) => ({t: e.t_start, c: centerOf(e)}))
    .filter((x): x is {t: number; c: Point} => x.c !== null)
    .sort((a, b) => a.t - b.t);
  const mid: Point = [scene.w / 2, scene.h / 2];
  if (!pts.length) return mid;
  const cur = pts[pts.length - 1];
  const prev = pts.length > 1 ? pts[pts.length - 2].c : mid;
  const k = easeInOut((t - cur.t) / 500);
  return [lerp(prev[0], cur.c[0], k), lerp(prev[1], cur.c[1], k)];
};

// Camera = zoom factor + center (source px) at time t, from zoom / pan effects.
export const cameraAt = (t: number, scene: Scene, effects: Effect[], pic: Picture) => {
  const active = effects
    .filter(
      (e) =>
        (e.type === 'zoom' || e.type === 'pan') &&
        (e.scene === scene.id || e.scene === null) &&
        t >= e.t_start &&
        t <= e.t_end,
    )
    .sort((a, b) => b.t_start - a.t_start)[0];
  const base: Point = pic.mode === 'cover' ? focusAt(t, scene, effects) : [scene.w / 2, scene.h / 2];
  let z = 1;
  let c = base;
  if (active?.type === 'zoom') {
    const q = active.params;
    const zmax = Number(q.scale) || 1.6;
    const ein = Number(q.ease_in_ms ?? 500);
    const eout = Number(q.ease_out_ms ?? 400);
    const kin = ein > 0 ? easeInOut((t - active.t_start) / ein) : 1;
    const kout = eout > 0 ? easeInOut((active.t_end - t) / eout) : 1;
    const k = Math.min(kin, kout);
    z = lerp(1, zmax, k);
    const target = (q.center as Point) || base;
    c = [lerp(base[0], target[0], k), lerp(base[1], target[1], k)];
  } else if (active?.type === 'pan') {
    const q = active.params;
    const k = easeInOut((t - active.t_start) / Math.max(1, active.t_end - active.t_start));
    const from = q.from || {};
    const to = q.to || {};
    z = lerp(Number(from.scale) || 1, Number(to.scale) || 1, k);
    const fc = (from.center as Point) || base;
    const tc = (to.center as Point) || fc;
    c = [lerp(fc[0], tc[0], k), lerp(fc[1], tc[1], k)];
  }
  // The cover crop is already a ~2.7x window: a zoom only moves it to the target, it does not scale it.
  if (pic.mode === 'cover') z = 1;
  const s0 =
    pic.mode === 'cover' ? Math.max(pic.w / scene.w, pic.h / scene.h) : Math.min(pic.w / scene.w, pic.h / scene.h);
  const s = s0 * z;
  // Keep the visible window inside the clip; a window wider than the clip stays centered.
  const vw = pic.w / s;
  const vh = pic.h / s;
  const cx = vw >= scene.w ? scene.w / 2 : clamp(c[0], vw / 2, scene.w - vw / 2);
  const cy = vh >= scene.h ? scene.h / 2 : clamp(c[1], vh / 2, scene.h - vh / 2);
  return {s0, s, z, cx, cy, left: pic.x + pic.w / 2 - cx * s, top: pic.y + pic.h / 2 - cy * s};
};

export const blurBoxAt = (t: number, b: {bbox: Box; keyframes: {t: number; bbox: Box}[] | null}): Box => {
  const kf = b.keyframes;
  if (!kf || !kf.length) return b.bbox;
  if (t <= kf[0].t) return kf[0].bbox;
  for (let i = 1; i < kf.length; i++) {
    if (t <= kf[i].t) {
      const a = kf[i - 1];
      const z = kf[i];
      const k = (t - a.t) / Math.max(1, z.t - a.t);
      return a.bbox.map((v, j) => lerp(v, z.bbox[j], k)) as Box;
    }
  }
  return kf[kf.length - 1].bbox;
};

export const fadeInOut = (t: number, a: number, b: number, ms: number) =>
  Math.min(clamp((t - a) / ms, 0, 1), clamp((b - t) / ms, 0, 1));
