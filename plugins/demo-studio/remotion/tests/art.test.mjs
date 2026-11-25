// Tests for render.mjs --art: lint, size, paths, IHDR. No Remotion, no network, no node_modules.
// Run: node --test plugins/demo-studio/remotion/tests/art.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {checkArt, lintSvg, readPngSize, resolveBrowserExecutable} from '../render.mjs';

const RENDER = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'render.mjs');

const crcTable = Array.from({length: 256}, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
const crc32 = (buf) => {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};
const chunk = (type, data) => {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'latin1'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
};
// Minimal valid opaque RGB PNG, all pixels one colour.
function makePng(w, h) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(w * 3, 0x20)]);
  const raw = Buffer.concat(Array.from({length: h}, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

const svg = (w, h, body = '<rect width="10" height="10" fill="url(#g)"/>') =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">` +
  `<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>${body}</svg>`;

// <tmp>/.demo/<slug>/ fixture folder
const base = fs.mkdtempSync(path.join(os.tmpdir(), 'art-test-'));
const slug = path.join(base, '.demo', 'x');
fs.mkdirSync(path.join(slug, 'art'), {recursive: true});
const f = (name, content) => {
  const p = path.join(slug, 'art', name);
  fs.writeFileSync(p, content);
  return p;
};
test.after(() => fs.rmSync(base, {recursive: true, force: true}));

const args = (over = {}) => ({size: '1280x720', out: path.join(slug, 'art', 'o.png'), ...over});

test('lint rejects script, handlers, foreignObject, image, data:image', () => {
  const bad = [
    '<script>1</script>',
    '<SCRIPT>1</SCRIPT>',
    '<rect onload="x()"/>',
    '<rect  onclick = "x()"/>',
    '<rect &#x6F;nclick="x()"/>',
    '<rect &#111;nclick="x()"/>',
    '<foreignObject><div/></foreignObject>',
    '<image href="#x"/>',
    '<IMAGE href="#x"/>',
    '<use href="data:image/svg+xml;base64,AAAA"/>',
    '<rect style="fill:url(data:image/png;base64,AA)"/>',
  ];
  for (const b of bad) assert.ok(lintSvg(svg(1280, 720, b)).length > 0, b);
});

test('lint rejects external href, xlink:href, url(), @import, bare <a href>', () => {
  const bad = [
    '<use href="http://x.io/a.svg#a"/>',
    '<use xlink:href="https://x.io/a"/>',
    '<use href=http://x.io/a />',
    '<a href="javascript:alert(1)"><rect/></a>',
    '<a href=""><rect/></a>',
    '<rect fill="url(http://x.io/p.svg)"/>',
    '<rect style="fill:url(//x.io/p)"/>',
    '<style>@import "https://x.io/a.css";</style>',
    '<style>@import url(https://x.io/a.css);</style>',
  ];
  for (const b of bad) assert.ok(lintSvg(svg(1280, 720, b)).length > 0, b);
});

test('lint passes #id refs, url(#id) and data:font', () => {
  const ok = [
    '<rect fill="url(#g)"/>',
    '<rect fill="url(\'#g\')"/>',
    '<use href="#g"/>',
    '<use xlink:href="#g"/>',
    '<a href="#g"><rect/></a>',
    '<style>@font-face{font-family:F;src:url(data:font/woff2;base64,AAAA)}</style>',
    '<text x="0" y="20">Month 5, button, online, one 1</text>',
  ];
  for (const b of ok) assert.deepEqual(lintSvg(svg(1280, 720, b)), [], b);
});

test('readPngSize reads IHDR; rejects truncated, non-PNG and missing files', () => {
  const p = f('a.png', makePng(37, 21));
  assert.deepEqual(readPngSize(p), {w: 37, h: 21});
  const trunc = f('trunc.png', makePng(37, 21).subarray(0, 20));
  assert.throws(() => readPngSize(trunc), /not a PNG/);
  const fake = f('fake.png', 'hello world, not a png at all');
  assert.throws(() => readPngSize(fake), /not a PNG/);
  assert.throws(() => readPngSize(path.join(slug, 'art', 'nope.png')), /cannot read/);
});

test('checkArt accepts a valid svg + png stack and reports sizes', () => {
  const frame = f('frame.png', makePng(1280, 720));
  const top = f('top.svg', svg(1280, 720));
  const r = checkArt(args({layer: [frame, top]}));
  assert.equal(r.w, 1280);
  assert.equal(r.h, 720);
  assert.deepEqual(r.layers.map((l) => [l.kind, l.w, l.h]), [['png', 1280, 720], ['svg', 1280, 720]]);
  assert.equal(r.bg, '#0B1020');
});

test('checkArt size and option errors', () => {
  const top = f('s.svg', svg(1280, 720));
  const bad = [
    args({layer: [top], size: '15x15'}),
    args({layer: [top], size: '5000x5000'}),
    args({layer: [top], size: '1280'}),
    args({layer: [top], size: undefined}),
    args({layer: [top], size: '1200x630'}), // top svg size mismatch
    args({layer: [top], out: path.join(slug, 'art', 'o.jpg')}),
    args({layer: [top], out: undefined}),
    args({layer: [top], bg: 'red'}),
    args({layer: [top], bg: '#fff'}),
    args({layer: []}),
    args({layer: [top], project: 'p.json'}),
    args({layer: [top], still: '10'}),
    args({layer: [top], ratio: '16x9'}),
  ];
  for (const a of bad) assert.throws(() => checkArt(a), /Error/, JSON.stringify(a));
  assert.equal(checkArt(args({layer: [top], bg: 'transparent'})).bg, 'transparent');
  assert.equal(checkArt(args({layer: [top], bg: '#aabbcc'})).bg, '#aabbcc');
});

test('checkArt path rules: inside .demo/<slug>, existing, .svg/.png only', () => {
  const top = f('p.svg', svg(1280, 720));
  const outside = path.join(base, 'outside.svg');
  fs.writeFileSync(outside, svg(1280, 720));
  assert.throws(() => checkArt(args({layer: [outside]})), /\.demo/); // no .demo ancestor
  assert.throws(() => checkArt(args({layer: [top, outside]})), /inside/);
  assert.throws(() => checkArt(args({layer: [top, path.join(slug, '..', 'x', '..', '..', 'outside.svg')]})), /inside/);
  assert.throws(() => checkArt(args({layer: [top], out: path.join(base, 'o.png')})), /inside/);
  assert.throws(() => checkArt(args({layer: [top], out: path.join(slug, '..', 'o.png')})), /inside/);
  assert.throws(() => checkArt(args({layer: [path.join(slug, 'art', 'missing.svg')]})), /not found/);
  const txt = f('x.txt', 'x');
  assert.throws(() => checkArt(args({layer: [txt]})), /\.svg or \.png/);
  const notSvg = f('empty.svg', 'plain text');
  assert.throws(() => checkArt(args({layer: [notSvg]})), /no <svg>/);
  const noSize = f('nosize.svg', '<svg xmlns="http://www.w3.org/2000/svg"></svg>');
  assert.throws(() => checkArt(args({layer: [noSize]})), /width\/height/);
  const px = f('px.svg', '<svg xmlns="http://www.w3.org/2000/svg" width="1280px" height="720px"></svg>');
  assert.equal(checkArt(args({layer: [px]})).layers[0].w, 1280);
});

test('checkArt rejects a linted svg and a bad png layer', () => {
  const evil = f('evil.svg', svg(1280, 720, '<image href="#x"/>'));
  assert.throws(() => checkArt(args({layer: [evil]})), /lint failed.*<image>/);
  const fake = f('f2.png', 'nope');
  assert.throws(() => checkArt(args({layer: [fake]})), /not a PNG/);
});

const cli = (argv) => spawnSync(process.execPath, [RENDER, ...argv], {encoding: 'utf8'});

test('CLI --check-only: JSON line exit 0; usage errors exit 2; video flags with --art exit 2', () => {
  const top = f('cli.svg', svg(1200, 630));
  const out = path.join(slug, 'art', 'cli.png');
  const ok = cli(['--art', '--check-only', '--size', '1200x630', '--layer', top, '--out', out]);
  assert.equal(ok.status, 0, ok.stderr);
  const j = JSON.parse(ok.stdout.trim());
  assert.equal(j.ok, true);
  assert.equal(j.mode, 'art');
  assert.deepEqual([j.w, j.h], [1200, 630]);
  assert.deepEqual(j.layers, [{file: top, kind: 'svg', w: 1200, h: 630}]);
  assert.equal(fs.existsSync(out), false); // check-only writes nothing

  const base_ = ['--art', '--check-only', '--size', '1200x630', '--layer', top, '--out', out];
  for (const extra of [['--project', 'p.json'], ['--still', '5'], ['--ratio', '16x9']]) {
    const r = cli([...base_, ...extra]);
    assert.equal(r.status, 2, extra.join(' '));
  }
  assert.equal(cli(['--art', '--check-only', '--size', '15x15', '--layer', top, '--out', out]).status, 2);
  assert.equal(cli(['--art', '--check-only', '--size', '1200x630', '--layer', top, '--out', out.replace('.png', '.jpg')]).status, 2);
  const evil = f('cli-evil.svg', svg(1200, 630, '<script>1</script>'));
  assert.equal(cli(['--art', '--check-only', '--size', '1200x630', '--layer', evil, '--out', out]).status, 2);
  // art-only flags without --art are refused; video mode still demands --project
  assert.equal(cli(['--check-only', '--size', '1200x630']).status, 2);
  assert.equal(cli(['--layer', top]).status, 2);
  assert.equal(cli([]).status, 2);
});

test('lint rejects prefixed image/feImage and CSS-escaped data:image', () => {
  const bad = [
    '<s:image href="data:font/woff2;base64,AAAA"/>',
    '<filter id="f"><feImage href="#g"/></filter>',
    '<style>svg{background:u\\72l(data:\\69mage/png;base64,iVBOR)}</style>',
    '<style>svg{background:url(data:\\000069mage/png;base64,iVBOR)}</style>',
  ];
  for (const b of bad) assert.ok(lintSvg(svg(1280, 720, b)).length > 0, b);
});

test('lint rejects DTD entity split of data:image and CSS image-set strings', () => {
  const bad = [
    '<!DOCTYPE svg [<!ENTITY d "data:im"><!ENTITY i "age/png;base64,iVBO">]><svg width="1280" height="720"><use href="&d;&i;"/></svg>',
    '<!ENTITY x "y">',
    '<style>svg{background:image-set("a.png" 1x)}</style>',
    '<style>svg{background:-webkit-image-set("a.png" 1x)}</style>',
    '<style>svg{background:cross-fade("a.png",#fff)}</style>',
  ];
  for (const b of bad) assert.ok(lintSvg(b).length > 0, b);
});

test('placed PNG layer FILE.png@X,Y,W,H: rect inside canvas, no upscale, PNG only', () => {
  const top = f('place-base.svg', svg(1280, 720));
  const ch = f('char.png', makePng(200, 300));
  const c = checkArt(args({layer: [top, `${ch}@64,100,100,150`]}));
  assert.deepEqual(c.layers[1].place, {x: 64, y: 100, w: 100, h: 150});
  assert.equal(c.layers[0].place, undefined);
  assert.throws(() => checkArt(args({layer: [top, `${ch}@1200,100,100,150`]})), /outside/);
  assert.throws(() => checkArt(args({layer: [top, `${ch}@0,0,400,600`]})), /upscale/);
  assert.throws(() => checkArt(args({layer: [top, `${ch}@0,0,0,150`]})), /W and H > 0/);
  assert.throws(() => checkArt(args({layer: [`${top}@0,0,10,10`]})), /layer must be|only a PNG/);
  const out = path.join(slug, 'art', 'place.png');
  const r = cli(['--art', '--check-only', '--size', '1280x720', '--layer', top, '--layer', `${ch}@64,100,100,150`, '--out', out]);
  assert.equal(r.status, 0, r.stderr);
  const j = JSON.parse(r.stdout.trim());
  assert.deepEqual(j.layers[1], {file: ch, kind: 'png', w: 200, h: 300, place: {x: 64, y: 100, w: 100, h: 150}});
});

test('resolveBrowserExecutable: env, then toolkit.json, else null; a missing file is an error', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ds-browser-'));
  const here = path.join(tmp, 'remotion');
  fs.mkdirSync(here);
  const exe = path.join(tmp, 'chrome');
  fs.writeFileSync(exe, 'bin');
  assert.equal(resolveBrowserExecutable(here, {}), null);
  fs.writeFileSync(path.join(tmp, 'toolkit.json'), JSON.stringify({features: {remotion: {}}}));
  assert.equal(resolveBrowserExecutable(here, {}), null);
  fs.writeFileSync(path.join(tmp, 'toolkit.json'), JSON.stringify({features: {remotion: {browser_executable: exe}}}));
  assert.equal(resolveBrowserExecutable(here, {}), exe);
  assert.equal(resolveBrowserExecutable(here, {DEMO_STUDIO_BROWSER: exe}), exe);
  assert.throws(() => resolveBrowserExecutable(here, {DEMO_STUDIO_BROWSER: path.join(tmp, 'nope')}), /not found/);
  fs.writeFileSync(path.join(tmp, 'toolkit.json'), JSON.stringify({features: {remotion: {browser_executable: path.join(tmp, 'gone')}}}));
  assert.throws(() => resolveBrowserExecutable(here, {}), /missing/);
  fs.rmSync(tmp, {recursive: true, force: true});
});
