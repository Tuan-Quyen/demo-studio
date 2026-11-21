// Normalized render props. Built by render.mjs from project.json + demo.yaml values;
// every time is ms on the FINAL timeline, every coordinate is source-frame px of the
// scene's clip (media-specs "Spaces and time"). The composition never reads project.json.

export type Box = [number, number, number, number]; // x, y, w, h
export type Point = [number, number];

export type Scene = {
  id: string;
  src: string; // path relative to the public dir (the .demo/<slug>/ folder)
  w: number;
  h: number;
  inMs: number; // clip time where the scene starts
  speed: number;
  start: number; // final timeline
  end: number;
};

export type BlurRegion = {
  id: string;
  scene: string;
  start: number; // already widened by margin_ms
  end: number;
  bbox: Box;
  pad: number;
  mode: 'boxblur' | 'pixelate';
  strength: number;
  keyframes: {t: number; bbox: Box}[] | null; // t on the final timeline
};

export type Effect = {
  scene: string | null;
  type: string;
  t_start: number;
  t_end: number;
  params: Record<string, any>;
};

export type Cue = {start: number; end: number; pos: 'bottom' | 'top'; lines: string[]};

export type DemoProps = {
  width: number;
  height: number;
  fps: number;
  durationMs: number;
  ratio: '16x9' | '9x16' | '1x1';
  level: 'none' | 'basic' | 'cinematic';
  layout: 'overlay' | 'band';
  bg: string;
  audio: string | null;
  scenes: Scene[];
  blur: BlurRegion[];
  effects: Effect[];
  cues: Cue[]; // empty unless captions are burned in
};
