import React from 'react';
import {AbsoluteFill, spring} from 'remotion';
import {fadeInOut, safe, bandHeight, unit} from './layout';
import type {Cue, DemoProps, Effect, Point} from './types';

const FONT = "'Inter', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif";
const ACCENT = '#FFC83D';

// --- inside the camera (source px; scales with zoom) -----------------------

export const Highlight: React.FC<{e: Effect; t: number; px: number}> = ({e, t, px}) => {
  const q = e.params;
  const b = q.bbox as number[] | undefined;
  const c: Point = (q.center as Point) || (b ? [b[0] + b[2] / 2, b[1] + b[3] / 2] : [0, 0]);
  const d = (Number(q.diameter_px_1080p) || 56) * px;
  const stroke = (Number(q.stroke_px) || 3) * px;
  const fill = Number(q.fill_opacity ?? 0.5);
  const o = fadeInOut(t, e.t_start, e.t_end, 100);
  return (
    <div
      style={{
        position: 'absolute',
        left: c[0] - d / 2,
        top: c[1] - d / 2,
        width: d,
        height: d,
        borderRadius: '50%',
        border: `${stroke}px solid ${ACCENT}`,
        background: `rgba(255, 200, 61, ${fill * 0.45})`,
        boxSizing: 'border-box',
        opacity: o,
      }}
    />
  );
};

export const Ripple: React.FC<{e: Effect; t: number; px: number}> = ({e, t, px}) => {
  const q = e.params;
  const b = q.bbox as number[] | undefined;
  const c: Point = (q.center as Point) || (b ? [b[0] + b[2] / 2, b[1] + b[3] / 2] : [0, 0]);
  const base = b ? Math.max(b[2], b[3]) : 56 * px;
  const k = Math.min(1, Math.max(0, (t - e.t_start) / Math.max(1, e.t_end - e.t_start)));
  const d = base * 2 * k;
  return (
    <div
      style={{
        position: 'absolute',
        left: c[0] - d / 2,
        top: c[1] - d / 2,
        width: d,
        height: d,
        borderRadius: '50%',
        border: `${3 * px}px solid ${ACCENT}`,
        boxSizing: 'border-box',
        opacity: 1 - k,
      }}
    />
  );
};

// --- screen space (output px) ----------------------------------------------

export const Callout: React.FC<{
  e: Effect;
  t: number;
  p: DemoProps;
  map: (pt: Point) => Point;
}> = ({e, t, p, map}) => {
  const u = unit(p);
  const q = e.params;
  const anchor = map((q.anchor as Point) || [0, 0]);
  const to = q.arrow_to ? map(q.arrow_to as Point) : null;
  const o = fadeInOut(t, e.t_start, e.t_end, 150);
  const pop =
    p.level === 'cinematic'
      ? spring({frame: ((t - e.t_start) / 1000) * p.fps, fps: p.fps, config: {damping: 14}})
      : 1;
  return (
    <AbsoluteFill style={{opacity: o, pointerEvents: 'none'}}>
      {to && (
        <svg width={p.width} height={p.height} style={{position: 'absolute', left: 0, top: 0}}>
          <defs>
            <marker id={`ah-${e.t_start}`} markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" fill={ACCENT} />
            </marker>
          </defs>
          <line
            x1={anchor[0]}
            y1={anchor[1]}
            x2={to[0]}
            y2={to[1]}
            stroke={ACCENT}
            strokeWidth={4 * u}
            markerEnd={`url(#ah-${e.t_start})`}
          />
        </svg>
      )}
      <div
        style={{
          position: 'absolute',
          left: anchor[0],
          top: anchor[1],
          transform: `translate(-50%, -50%) scale(${pop})`,
          background: 'rgba(11, 16, 32, 0.92)',
          color: '#fff',
          border: `${2 * u}px solid ${ACCENT}`,
          borderRadius: 12 * u,
          padding: `${10 * u}px ${18 * u}px`,
          fontFamily: FONT,
          fontWeight: 600,
          fontSize: 34 * u,
          whiteSpace: 'nowrap',
        }}
      >
        {String(q.text ?? '')}
      </div>
    </AbsoluteFill>
  );
};

export const TitleCard: React.FC<{e: Effect; t: number; p: DemoProps}> = ({e, t, p}) => {
  const u = unit(p);
  const q = e.params;
  const s = safe(p);
  const local = ((t - e.t_start) / 1000) * p.fps;
  const enter = p.level === 'cinematic' ? spring({frame: local, fps: p.fps, config: {damping: 200}}) : 1;
  return (
    <AbsoluteFill
      style={{
        background: String(q.bg || '#0B1020'),
        alignItems: 'center',
        justifyContent: 'center',
        padding: `${s.top * p.height}px ${s.side * p.width}px ${s.bottom * p.height}px`,
        textAlign: 'center',
        fontFamily: FONT,
        color: '#fff',
      }}
    >
      <div style={{opacity: enter, transform: `translateY(${(1 - enter) * 40 * u}px)`}}>
        <div style={{fontSize: 92 * u, fontWeight: 700, lineHeight: 1.1}}>{String(q.title ?? '')}</div>
        {q.subtitle ? (
          <div style={{fontSize: 40 * u, marginTop: 24 * u, opacity: 0.8, lineHeight: 1.3}}>
            {String(q.subtitle)}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const Captions: React.FC<{cues: Cue[]; t: number; p: DemoProps}> = ({cues, t, p}) => {
  const cue = cues.find((c) => t >= c.start && t < c.end);
  if (!cue) return null;
  const u = unit(p);
  const s = safe(p);
  const band = bandHeight(p);
  const style: React.CSSProperties = {
    position: 'absolute',
    left: s.side * p.width,
    right: s.side * p.width,
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
  };
  if (band) {
    Object.assign(style, {top: p.height - band, height: band});
  } else if (cue.pos === 'top') {
    Object.assign(style, {top: s.top * p.height});
  } else {
    Object.assign(style, {bottom: s.bottom * p.height});
  }
  return (
    <div style={style}>
      <div
        style={{
          background: band ? 'transparent' : 'rgba(0, 0, 0, 0.72)',
          color: '#fff',
          fontFamily: FONT,
          fontWeight: 600,
          fontSize: (p.ratio === '16x9' ? 42 : 48) * u,
          lineHeight: 1.3,
          padding: `${8 * u}px ${18 * u}px`,
          borderRadius: 8 * u,
          textAlign: 'center',
        }}
      >
        {cue.lines.map((l, i) => (
          <div key={i}>{l}</div>
        ))}
      </div>
    </div>
  );
};

// Dip through black: opacity 0 -> 1 at black_at (default the middle) -> 0.
export const dipOpacity = (t: number, e: Effect) => {
  const mid = Number(e.params?.black_at ?? (e.t_start + e.t_end) / 2);
  if (t < e.t_start || t > e.t_end) return 0;
  return t <= mid
    ? (t - e.t_start) / Math.max(1, mid - e.t_start)
    : (e.t_end - t) / Math.max(1, e.t_end - mid);
};
