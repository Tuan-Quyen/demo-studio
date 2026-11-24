import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import type {ArtProps} from './types';

// One frame: the layers of render.mjs --art, bottom to top, each covering the whole canvas.
// <Img> delays the frame until the image has loaded. An SVG loaded as <img> cannot run script.
export const ArtStill: React.FC<ArtProps> = ({bg, layers}) => (
  <AbsoluteFill style={bg === 'transparent' ? undefined : {backgroundColor: bg}}>
    {layers.map((l, i) => (
      <Img
        key={`${i}-${l.src}`}
        src={staticFile(l.src)}
        style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}}
      />
    ))}
  </AbsoluteFill>
);
