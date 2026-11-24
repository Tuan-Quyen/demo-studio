import React from 'react';
import {Composition, type CalculateMetadataFunction} from 'remotion';
import {DemoVideo} from './DemoVideo';
import {ArtStill} from './ArtStill';
import type {ArtProps, DemoProps} from './types';

// Size, fps and length come from the props render.mjs builds, so one composition
// serves every ratio and every project.
const calculateMetadata: CalculateMetadataFunction<DemoProps> = ({props}) => ({
  width: props.width,
  height: props.height,
  fps: props.fps,
  durationInFrames: Math.max(1, Math.round((props.durationMs / 1000) * props.fps)),
});

// Art mode: one still frame whose size comes from --size.
const calculateArtMetadata: CalculateMetadataFunction<ArtProps> = ({props}) => ({
  width: props.width,
  height: props.height,
  fps: 30,
  durationInFrames: 1,
});

const emptyArt: ArtProps = {width: 1280, height: 720, bg: '#0B1020', layers: []};

const empty: DemoProps = {
  width: 1920,
  height: 1080,
  fps: 25,
  durationMs: 2000,
  ratio: '16x9',
  level: 'basic',
  layout: 'overlay',
  bg: '#0B1020',
  audio: null,
  scenes: [],
  blur: [],
  effects: [
    {scene: null, type: 'title_card', t_start: 0, t_end: 2000, params: {title: 'demo-studio', subtitle: 'no props given'}},
  ],
  cues: [],
};

export const Root: React.FC = () => (
  <>
    <Composition
      id="demo"
      component={DemoVideo as unknown as React.FC<Record<string, unknown>>}
      width={1920}
      height={1080}
      fps={25}
      durationInFrames={50}
      defaultProps={empty as unknown as Record<string, unknown>}
      calculateMetadata={calculateMetadata as unknown as CalculateMetadataFunction<Record<string, unknown>>}
    />
    <Composition
      id="art"
      component={ArtStill as unknown as React.FC<Record<string, unknown>>}
      width={1280}
      height={720}
      fps={30}
      durationInFrames={1}
      defaultProps={emptyArt as unknown as Record<string, unknown>}
      calculateMetadata={calculateArtMetadata as unknown as CalculateMetadataFunction<Record<string, unknown>>}
    />
  </>
);
