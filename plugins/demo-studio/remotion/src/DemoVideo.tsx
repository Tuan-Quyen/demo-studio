import React from 'react';
import {AbsoluteFill, Audio, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from 'remotion';
import {Callout, Captions, Highlight, Ripple, TitleCard, dipOpacity} from './effects';
import {blurBoxAt, cameraAt, pictureBox, unit} from './layout';
import type {DemoProps, Effect, Point, Scene} from './types';

const msToFrame = (ms: number, fps: number) => Math.round((ms / 1000) * fps);

const isCross = (e: Effect) => e.type === 'fade' && (e.params?.mode ?? 'cross') === 'cross';

// A cross-fade whose window contains a scene start overlaps the two scenes.
const crossInto = (sc: Scene, effects: Effect[]) =>
  effects.find((e) => isCross(e) && e.t_start < sc.start && e.t_end >= sc.start) || null;

const SceneLayer: React.FC<{p: DemoProps; sc: Scene; t: number; lead: number; opacity: number}> = ({
  p,
  sc,
  t,
  lead,
  opacity,
}) => {
  const pic = pictureBox(p, sc, p.effects);
  const cam = cameraAt(t, sc, p.effects, pic);
  const px = (unit(p) / cam.s0); // 1 output px at 1080p, in source px before zoom
  const trimBefore = Math.max(0, msToFrame(sc.inMs - lead * sc.speed, p.fps));
  const video = (style: React.CSSProperties) => (
    <OffthreadVideo
      src={staticFile(sc.src)}
      trimBefore={trimBefore}
      playbackRate={sc.speed}
      muted
      style={{position: 'absolute', width: sc.w, height: sc.h, maxWidth: 'none', ...style}}
    />
  );
  const device = p.effects.some((e) => e.type === 'device_frame' && e.scene === sc.id);
  const mine = p.effects.filter((e) => e.scene === sc.id && t >= e.t_start && t <= e.t_end);
  const blurs = p.blur.filter((b) => b.scene === sc.id && t >= b.start && t <= b.end);
  return (
    <AbsoluteFill style={{opacity}}>
      <div
        style={{
          position: 'absolute',
          left: pic.x,
          top: pic.y,
          width: pic.w,
          height: pic.h,
          overflow: 'hidden',
          borderRadius: device ? 36 * unit(p) : 0,
          outline: device ? `${14 * unit(p)}px solid #15171c` : undefined,
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: cam.left - pic.x,
            top: cam.top - pic.y,
            width: sc.w,
            height: sc.h,
            transform: `scale(${cam.s})`,
            transformOrigin: '0 0',
          }}
        >
          {video({left: 0, top: 0})}
          {/* Blur happens on the source frame, before zoom/reframe, so a zoomed region stays covered.
              A blurred copy of the video, clipped to the box. Plain blur() fades to transparent where it
              samples outside the clip or the frame, so the sharp frame showed through near edges; the
              feFuncA table forces alpha to 1 (= normalized blur of the visible pixels, edge-clamp like).
              backdrop-filter is not used: headless Chrome renders it as a no-op. */}
          {blurs.map((b) => {
            const [x, y, w, h] = blurBoxAt(t, b);
            // Whole source px, rounded outward, so no sub-pixel sliver of the sharp frame stays visible.
            const bx = Math.floor(x - b.pad);
            const by = Math.floor(y - b.pad);
            const bw = Math.ceil(x + w + b.pad) - bx;
            const bh = Math.ceil(y + h + b.pad) - by;
            const radius = b.mode === 'pixelate' ? b.strength * 1.6 : b.strength;
            const fid = `blur-${sc.id}-${b.id}`;
            return (
              <React.Fragment key={b.id}>
                <svg width={0} height={0} style={{position: 'absolute'}}>
                  <filter id={fid} x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
                    <feGaussianBlur stdDeviation={radius} />
                    <feComponentTransfer>
                      <feFuncA type="table" tableValues="1 1" />
                    </feComponentTransfer>
                  </filter>
                </svg>
                <div
                  style={{position: 'absolute', left: bx, top: by, width: bw, height: bh, overflow: 'hidden'}}
                >
                  {video({left: -bx, top: -by, filter: `url(#${fid})`})}
                </div>
              </React.Fragment>
            );
          })}
          {mine
            .filter((e) => e.type === 'cursor_highlight')
            .map((e, i) => (
              <Highlight key={`h${i}`} e={e} t={t} px={px} />
            ))}
          {mine
            .filter((e) => e.type === 'ripple')
            .map((e, i) => (
              <Ripple key={`r${i}`} e={e} t={t} px={px} />
            ))}
        </div>
      </div>
      {mine
        .filter((e) => e.type === 'callout')
        .map((e, i) => (
          <Callout
            key={`c${i}`}
            e={e}
            t={t}
            p={p}
            map={([x, y]: Point): Point => [cam.left + x * cam.s, cam.top + y * cam.s]}
          />
        ))}
    </AbsoluteFill>
  );
};

export const DemoVideo: React.FC<DemoProps> = (p) => {
  const frame = useCurrentFrame();
  const t = (frame / p.fps) * 1000;
  const titles = p.effects.filter((e) => e.type === 'title_card' && t >= e.t_start && t < e.t_end);
  const dip = Math.max(
    0,
    ...p.effects.filter((e) => e.type === 'fade' && e.params?.mode === 'dip').map((e) => dipOpacity(t, e)),
  );
  return (
    <AbsoluteFill style={{background: p.bg}}>
      {p.scenes.map((sc, i) => {
        const inCross = crossInto(sc, p.effects);
        const next = p.scenes[i + 1];
        const outCross = next ? crossInto(next, p.effects) : null;
        const lead = inCross ? sc.start - inCross.t_start : 0;
        const from = msToFrame(sc.start - lead, p.fps);
        const to = msToFrame(outCross ? Math.max(sc.end, outCross.t_end) : sc.end, p.fps);
        const opacity = inCross
          ? Math.min(1, Math.max(0, (t - inCross.t_start) / Math.max(1, inCross.t_end - inCross.t_start)))
          : 1;
        return (
          <Sequence key={sc.id} from={from} durationInFrames={Math.max(1, to - from)} layout="none">
            <SceneLayer p={p} sc={sc} t={t} lead={lead} opacity={opacity} />
          </Sequence>
        );
      })}
      {titles.map((e, i) => (
        <TitleCard key={`t${i}`} e={e} t={t} p={p} />
      ))}
      {dip > 0 ? <AbsoluteFill style={{background: '#000', opacity: dip}} /> : null}
      <Captions cues={p.cues} t={t} p={p} />
      {p.audio ? <Audio src={staticFile(p.audio)} /> : null}
    </AbsoluteFill>
  );
};
