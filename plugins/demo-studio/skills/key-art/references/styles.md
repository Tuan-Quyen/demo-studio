# Key-art styles catalogue

Style keywords for marketing art. Loaded by `demo-director` (`## Picker` and `## Keyword taxonomy` only), `art-designer` (whole file) and `demo-qa` (hints, for Q10); see "Who loads what" in `../SKILL.md`. Key-art rules (Q1-Q10, P1-P5) always win over a style; a style changes the look only, never copy, privacy or size.

v1 column: `yes` = pure SVG with system fonts; `approx` = SVG approximation (art-designer lists it in `approximated`); `no` rows are recognised when typed and never pickable. English only: the director translates meanings when presenting; codes, keywords and `#art.style` stay English.

## Picker

### List format (director prints, in the user's language)
- Intro: "Pick the look for your marketing images: reply R1-R3, or 1-3 codes from different groups (e.g. A14 + D1 + C1), or describe it, or paste a link, or say skip."
- Top: at most 3 numbered combos from the recommendation rule, each code with its mark and a reason quoting the brief: `R1 A14 Dark UI [yes] + B5 robots [yes] + D1 dark mode [yes] - your brief targets developers of an AI agent tool.`
- Then groups A-G in this order, one line per coded row: `code · keyword - meaning [yes]` or `[approx]` (the v1 column). Example: `A6 · glassmorphism - frosted see-through panels [approx]`.
- Per group, one line for the `no` rows: `Not available yet: grunge [no → A12], punk / zine [no → A12], ...` (keyword, then the nearest coded row).
- The director may print A-D first and offer "more: E, F, G"; every code stays valid. Plain text only, no images.

### Answer grammar
- `R1`-`R3`; or 1-3 codes or keywords (name or code, any case) joined by `+`, commas or spaces; or free text; or a link or image; or `skip` / "you choose".
- Valid pick: 1-3 codes, at most one per group (this also settles pastel vs neon, dark vs light, serif vs mono, flat vs skeuomorphism, minimal vs maximal). A 4th code or two from one group is declined in one line, then re-asked.
- Keywords named in the request run the same validation; valid means no question. Example: "swiss grid, mono type" = A8 + E6 (valid); "swiss minimal" = A8 + A1 (both group A, declined).
- A `no` keyword is never accepted silently: say why v1 cannot do it and offer the nearest code.
- An `approx` keyword is accepted; art-designer lists what it approximated.
- A word not in the catalogue is free text, not an error.

### Free text and references (director maps, then confirms in the same exchange)
- Map to the nearest codes plus at most 3 deltas (hex, type, shape). Echo as one line, then ask yes/no. No match: show the closest 3 codes and ask again.
- Reference (URL or image): read only to describe palette, type feel and layout in words; nothing is copied into `art/` or the repo; no URL, brand name, logo or private text is stored.

### Stored `source`
- R-combo, `skip`, "you choose", auto mode: `recommended`. Typed codes or keywords: `catalogue`. Free text: `custom`. URL or image: `reference`. The `#art.style` shape is in `media-specs` `#art`.

### Recommendation rule
Signals come from `brief.md` or the source doc's first sections. If `#art.style` is already set, keep it and offer "change style". Otherwise offer at most 3 combos, first = R1, each with a reason quoting the signal; a combo has one code per group.

| Signal | Combos |
|---|---|
| brand colours stated as hex | A1 + D13 + C3; A8 + D13; F4 + D13 |
| developers + CLI/terminal product | A20 + C6; A14 + D1 + C6; A28 + F7 |
| AI / agents / LLM product | A14 + B5 + D1; D7 + C5; F4 + D1 |
| infra, cloud, data, pipeline | B3 + C4; A28 + F7; A14 + F7 |
| non-technical / consumer / education | B4 + C2 + D2; F4 + C3; A6 + C5 |
| process / architecture / docs-first repo | B6 + C2; A8 + C10; A28 + F7 |
| creator / indie / playful tone | A13 + C1; B4 + D4 + C1; A11 + C8 |
| no signal | A14 + B5 + D1; A1 + C3; F4 + C3 |

The no-signal R1 (A14 + B5 + D1) is the look the user approved on the v3 README art.

### Copy
| Place | Text |
|---|---|
| Echo | "Using Dark UI cards with friendly robots, dark mode, playful tone. OK?" |
| Same group | "D4 and D6 are both colours; keep which?" |
| Not available | "3D render isn't available yet (no raster images). Closest: B13 3D-ish. Use that?" |
| Reference echo | "Closest is D7 aurora + C5 futuristic; changes: accent #FF7A00, square corners. Nothing is copied from the link. OK?" |
| Unreadable link | "Could not read that link; describe it in words or pick codes." |
| Invalid answer | "I didn't get that. Answer R1-R3, 1-3 codes like A14 + D1, a description, a link, or skip." |

## Combination rule (1-3 codes → one recipe; art-designer)
1. One code per group.
2. Core = the first "→ id" found scanning the picked codes in group order A, B, C, D, E, F, G (in C, the first id named). No "→ id" in any pick: `dark-artifact`. Later picks never change the core; they modify it (steps 3-5).
3. A picked B code that does not set the core adds its illustration motif to the core (e.g. isometric blocks); its palette and type are dropped.
4. Each picked code overrides its own layer of the core: D palette, E font stack, F grid, G effect added; C sets tone only. Recompute text pairs (`color.md`); record fixes in `adjusted`, approximations in `approximated`.
5. Hint codes inside Hints (e.g. A22 → G9, A19 → D6, A9 → E4) apply only when the user picked no code in that group; an explicit pick in that group wins.
- Example 1: `A14 + B3`: core `dark-artifact` (A first); B3 adds isometric blocks in dark-artifact colours; type stays sans.
- Example 2: `A9 + E6 + D2`: core `swiss-editorial`; A9's hint E4 serif is dropped because E6 mono was picked; D2 light palette replaces the swiss palette.

## Keyword taxonomy
Src ids resolve in `## Sources`. `S0` is a repo file and is used only by A14 (the project's own approved style); every other row cites an external source.

### A · Overall style / movement
| Code | Keyword | Meaning | v1 | Hints | Src |
|---|---|---|---|---|---|
| A1 | minimalism | very few elements, lots of empty space | yes | → minimal-type | S2 |
| A2 | flat design | 2D shapes, no shadows or depth | yes | → flat-mascot without characters | S2 S5 |
| A3 | material design | flat cards with soft layered shadows | yes | white cards, `feDropShadow` 2–8 px, radius 8 | S2 |
| A4 | skeuomorphism | things look like real objects | approx | gradients + highlights; heavy SVG | S2 |
| A5 | neumorphism | soft shapes pressed out of the background | approx | twin shadows; low contrast, never under text | S24 S13 |
| A6 | glassmorphism | frosted see-through panels | approx | → glass-layers | S6 |
| A7 | claymorphism | puffy clay-like 3D shapes | approx | inset + outer shadows; reads childish | S13 S14 |
| A8 | Swiss / International | strict grid, flush-left, poster-like | yes | → swiss-editorial | S17 |
| A9 | editorial | magazine layout, big headline | yes | → swiss-editorial + E4 serif | S2 |
| A10 | Bauhaus | circles, squares, primary colours | yes | bg `#F2EFE6`, ink `#111111` 16.4; red `#D0021B`, blue `#1F4E9E`, yellow `#F5C400` shapes | S1 |
| A11 | Memphis | loud 80s squiggles and confetti shapes | yes | pastel bg, squiggle paths, dots, ink `#111111` | S1 |
| A12 | brutalism | raw, stark, monochrome, unpolished | yes | black/white, mono, radius 0 | S1 |
| A13 | neo-brutalism | thick outlines, hard shadows, bold flat colours | yes | → neo-brutalism | S20 S15 |
| A14 | dark UI / artifact | dark canvas with glowing app cards | yes | → dark-artifact | S0 S25 |
| A15 | Art Deco | symmetric stepped lines, gold on dark | approx | gold `#D4AF37` on `#111111` 9.0; no deco font | S1 |
| A16 | Y2K | chrome, bubbly, neon 2000s | approx | gradient strokes; bubbly type not portable | S1 |
| A17 | vaporwave | pink and cyan retro web, grids | approx | A18 colours; no glitch | S1 |
| A18 | synthwave / outrun | neon sunset with perspective grid | yes | bg `#14002B`, text `#FFFFFF` 19.7, sun `#FF2E88`→`#FFC83D`, grid `#00E5FF` | S1 |
| A19 | cyberpunk | neon on black, high energy | yes | → dark-artifact + D6 | S2 |
| A20 | retro terminal / CLI | green or amber text on black | yes | → terminal-retro | S3 S22 |
| A21 | pixel art / 8-bit | tiny square pixels, game look | approx | `rect` + `crispEdges`; text stays mono | S1 |
| A22 | pop art / comic | halftone dots, bold outlines | yes | G9 + 3 px black outlines | S1 S2 |
| A23 | risograph | layered spot colours, print feel | approx | 2 spot colours, `mix-blend-mode: multiply`; no grain | S1 |
| A24 | Japandi / Japanese minimal | calm, neutral, natural | yes | → minimal-type + D8 | S1 |
| A25 | corporate illustration | modular friendly figures, consistent system | yes | → flat-mascot | S5 |
| A26 | kawaii | cute round pastel characters | yes | → flat-mascot + D4 | S1 |
| A27 | maximalism | many layers, everything at once | approx | breaks one-focal rule; not recommended | S2 |
| A28 | blueprint / technical | white lines on engineering blue | yes | → blueprint | S27 S28 |
| – | grunge | dirty textures, smudges | no | nearest A12 · raster textures (P2) | S2 S1 |
| – | punk / zine | photocopied cut-and-paste look | no | nearest A12 · raster textures (P2) | S2 |
| – | Victorian | ornate floral maximal decoration | no | nearest A15 · ornament too heavy for budget (Q8) | S1 |
| – | boho / cottagecore | earthy rustic handmade textures | no | nearest A24 · textures and photos (P2) | S1 S2 |

### B · Illustration type
| Code | Keyword | Meaning | v1 | Hints | Src |
|---|---|---|---|---|---|
| B1 | line art | drawn only with outlines | yes | 2–3 px strokes, no fills, one accent | S5 |
| B2 | flat illustration | simple filled shapes, no shading | yes | → flat-mascot | S5 |
| B3 | isometric | little 3D blocks drawn at 30° | yes | → isometric | S18 S5 |
| B4 | mascot / character | a recurring friendly figure | yes | → flat-mascot | S5 |
| B5 | anthropomorphic objects | objects with faces, like robots | yes | → dark-artifact (v3 robots) | S1 |
| B6 | doodle / hand-drawn | whiteboard sketch look | yes | → sketch-notes | S19 S5 |
| B7 | geometric abstract | circles, bars and triangles composition | yes | A10 shapes, any palette | S5 |
| B8 | organic / blobs | soft rounded nature-like shapes | yes | 2–3 bezier blobs behind the visual | S1 |
| B9 | icons / pictograms | small symbol for each idea | yes | 24-grid icons, 2 px stroke | S5 |
| B10 | diagram / infographic | boxes and arrows that explain | yes | → blueprint | S19 |
| B11 | UI mockup / wireframe | stylised app windows, no real data | yes | → dark-artifact | S25 |
| B12 | low-poly | shapes made of flat triangles | approx | triangle paths; size grows fast (Q8) | S2 |
| B13 | 3D-ish | depth from gradients and shadows | approx | 2-stop gradients on faces | S2 |
| B14 | halftone | pictures made of dots | yes | G9 | S2 |
| – | 3D render | realistic rendered 3D objects | no | nearest B13 · raster (P2) | S25 |
| – | photography | real photos | no | nearest B11 · raster (P2) | S17 |
| – | collage / mixed media | cut-out photos and textures | no | nearest B7 · raster (P2) | S1 S5 |
| – | realistic painting | detailed painted rendering | no | nearest B13 · raster or huge SVG (P2, Q8) | S5 |
| – | duotone photo | photo in two colours | no | nearest D10 · raster (P2) | S8 |

### C · Mood / tone
| Code | Keyword | Meaning | v1 | Hints | Src |
|---|---|---|---|---|---|
| C1 | playful | fun, light, a bit cheeky | yes | → flat-mascot or neo-brutalism | S12 S2 |
| C2 | friendly / warm | approachable and human | yes | → flat-mascot or sketch-notes | S12 |
| C3 | corporate / professional | safe and businesslike | yes | → minimal-type or bento-grid | S12 S5 |
| C4 | trustworthy / calm | quiet and reliable | yes | → minimal-type or swiss-editorial | S12 S15 |
| C5 | futuristic | ahead of its time, glowing | yes | → aurora-mesh or dark-artifact | S2 S4 |
| C6 | techy / hacker | for engineers and the command line | yes | → terminal-retro or blueprint | S3 |
| C7 | elegant / premium | refined and expensive | yes | → minimal-type + E4, or aurora-mesh | S12 S4 |
| C8 | bold / loud | stands out in a feed | yes | → neo-brutalism | S20 |
| C9 | nostalgic / retro | reminds of older tech | yes | → terminal-retro | S2 S3 |
| C10 | serious / editorial | thoughtful and informative | yes | → swiss-editorial | S17 |
| C11 | energetic | fast and vibrant | yes | → neo-brutalism + D6 | S9 |

### D · Colour direction
| Code | Keyword | Meaning | v1 | Hints | Src |
|---|---|---|---|---|---|
| D1 | dark mode | dark background, light text | yes | `#FFFFFF` on `#0B1020` 18.9 | S25 S2 |
| D2 | light mode | light background, dark text | yes | `#111827` on `#FFFFFF` 17.7 | S2 |
| D3 | monochrome | one colour in light and dark shades | yes | `#0F172A` on `#E2E8F0` 14.5; `#334155` shapes | S7 S8 |
| D4 | pastel | soft light colours | yes | fills `#FDE2E4` `#E2ECE9` `#DFE7FD`; text `#1F2937` 11.9–12.0 | S8 |
| D5 | vibrant / saturated | strong bright colours | yes | → neo-brutalism fills, black text | S9 |
| D6 | neon | glowing electric colours on dark | yes | `#33FF66` 14.1 / `#00E5FF` 12.3 on `#0B1020`; `#FF2E88` shapes | S9 |
| D7 | gradient / aurora | colours blending into each other | yes | → aurora-mesh | S4 |
| D8 | earthy / natural | browns, greens, sand | yes | `#2B2A26` on `#F3EEE3` 12.4; olive `#556B2F`, clay `#9C4A2F` | S9 |
| D9 | jewel tones | deep emerald, sapphire, ruby | yes | white on `#0F5257` 8.9, `#1E3A8A` 10.4, `#9B1B30` 8.1 | S26 |
| D10 | duotone (vector) | only two colours | yes | 2 hex + black/white text, recompute | S8 |
| D11 | primary colours | red, blue and yellow | yes | → A10 colours | S1 |
| D12 | black & white | maximum contrast, no colour | yes | `#000000` / `#FFFFFF` 21 | S1 |
| D13 | brand colours | the product's own colours | yes | only hex stated in the brief (`color.md`) | S9 |
| D14 | muted / desaturated | greyish calm colours | yes | `#1E293B` on `#F8FAFC` 14.0; `#64748B` shapes | S7 |

### E · Typography direction
| Code | Keyword | Meaning | v1 | Hints | Src |
|---|---|---|---|---|---|
| E1 | bold sans / grotesk | heavy modern letters | yes | sans stack 700–800 | S11 |
| E2 | geometric sans | round Futura-like letters | approx | no portable geometric font; sans stack | S11 |
| E3 | humanist sans | friendly readable letters | yes | sans stack (Segoe UI is humanist) | S11 |
| E4 | serif editorial | newspaper and book letters | yes | `Georgia,'Times New Roman','Liberation Serif','DejaVu Serif',serif`; budget below | S10 S11 |
| E5 | slab serif | letters with blocky feet | approx | E4 at 700; true slab not portable | S11 |
| E6 | monospace | typewriter or code letters | yes | mono stack, 0.62 em | S10 |
| E7 | oversized / type-first | the words are the picture | yes | title up to 160 px, few words | S2 |
| E8 | all caps, wide spacing | spaced capital letters | yes | `letter-spacing` 0.08–0.15 em; budget +15% | S10 |
| – | display / decorative | unusual headline fonts | no | nearest E7 · not in system stacks (rule 4) | S10 |
| – | script / handwriting | joined handwritten letters | no | nearest E3 · not in system stacks (rule 4) | S10 |
| – | condensed | narrow tall letters | no | nearest E1 · no portable condensed face | S11 |
| – | pixel font | blocky bitmap letters | no | nearest E6 · not in system stacks (rule 4) | S1 |

### F · Layout
| Code | Keyword | Meaning | v1 | Hints | Src |
|---|---|---|---|---|---|
| F1 | split hero | text left, picture right | yes | default; `composition.md` hero | S29 |
| F2 | centered hero | everything on one centre line | yes | one centre axis | S25 |
| F3 | asymmetric grid | off-centre poster layout | yes | → swiss-editorial | S17 |
| F4 | bento grid | tiles of different sizes | yes | → bento-grid | S16 S1 |
| F5 | 3×3 / equal grid | nine equal boxes | yes | roster-style cards | S1 |
| F6 | layered cards | overlapping cards with depth | yes | → dark-artifact (v3 hero) | S6 |
| F7 | diagram / flow | boxes and arrows left to right | yes | `composition.md` diagram rules | S19 |
| F8 | full-bleed type | text fills the whole image | yes | E7 + safe margins | S2 |
| F9 | device frame | product inside a drawn window or phone | yes | vector frame, no screenshot (P2) | S25 |

### G · Effects
| Code | Keyword | Meaning | v1 | Hints | Src |
|---|---|---|---|---|---|
| G1 | glow | soft light around shapes | yes | `feDropShadow` dx 0 in accent; never on body text | S4 S3 |
| G2 | soft shadow | subtle depth under cards | yes | `feDropShadow` dy 8–10, opacity 0.4–0.5 | S2 |
| G3 | hard shadow | solid offset shadow, no blur | yes | duplicate shape offset (8,8) black | S20 S15 |
| G4 | frosted glass | blurred see-through panel | approx | → glass-layers; never `backdrop-filter` | S6 |
| G5 | gradient | colour fades | yes | linear/radial inside an opaque bg | S4 |
| G6 | blur | soft out-of-focus shapes | approx | `feGaussianBlur` on bg shapes, never on text | S23 |
| G7 | dot / grid pattern | subtle dotted or squared background | yes | `pattern` 24 px, low contrast | S28 |
| G8 | scanlines | old monitor horizontal lines | yes | 2 px `pattern`, ≤ 8% opacity | S3 |
| G9 | halftone dots | comic print dots | yes | dot `pattern`, radial size steps | S2 |
| G10 | outline / stroke | everything outlined | yes | 2–4 px ink stroke | S20 |
| G11 | rounded or sharp corners | soft or strict shapes | yes | radius 16–24 or 0 | S4 |
| G12 | metallic / chrome | shiny metal look | approx | multi-stop grey gradients | S2 S1 |
| – | grain / noise | film-like speckle texture | no | nearest G7 · `feTurbulence` breaks PNG budget (Q8) | S4 |
| – | paper texture | real paper surface | no | nearest G7 · raster texture (P2) | S1 |
| – | glitch | broken digital distortion | no | nearest G8 · noise/raster, budget (Q8) | S2 |

## Core recipes (12)
Contrast pairs computed with the `color.md` formula (python, 2026-11-24). Text pairs ≥ 4.5:1; "shape only" values never sit under text.

| id | Palette (hex) · text pairs | Type | Shapes / effects | Illustration · mascot |
|---|---|---|---|---|
| dark-artifact | bg `#0B1020`, surface `#151B2E`, text `#FFFFFF` 18.9, muted `#B8C0D9`/surface 9.4, accent `#FFC83D` (ink `#0B1020` 12.2), glow `#5EEAD4` 12.8 | sans | radius 10–14 cards, glow, dot pattern, radial bg gradients | line robots per role · yes (v3) |
| minimal-type | bg `#FFFFFF`, text `#111827` 17.7, muted `#4B5563` 7.6, accent `#2563EB` 5.2 (white on it 5.2) | sans 700, title up to 120 px | none or one thin rule | none · no |
| swiss-editorial | bg `#F4F1EA`, text `#111111` 16.7, muted `#4A4A4A` 7.9, accent `#D0021B` (white on it 5.7; on bg 5.0) | sans, flush-left | asymmetric 12-col grid, one red block, 2 px rules | none · no |
| bento-grid | bg `#F5F5F7`, tile `#FFFFFF`, text `#1D1D1F` 16.8 on tile, muted `#6E6E73` 5.1, accent `#0066CC` 5.6 | sans; tile title 28–32 | 4–6 tiles, radius 20, gap 16–24, one large focal tile | icon/diagram per tile · no |
| aurora-mesh | bg `#0A0A1A`, blobs `#7C3AED` `#06B6D4` `#EC4899` (shape only), text `#FFFFFF` 19.6, muted `#C4C9E8` 12.0 | sans | 2–4 radial gradients + `feGaussianBlur`; calm zone behind text | none · no |
| glass-layers | aurora bg; panel = blurred bg copy clipped to panel + white 10% + 1 px white 30% stroke; on `#2A2350`: `#FFFFFF` 14.4, `#D6D9F0` 10.3 | sans | `clipPath` + blurred duplicate | none · no |
| neo-brutalism | bg `#FFF4D6`, ink `#000000` 19.2; fills `#FF6B6B` 7.6, `#A3E635` 13.9, `#FDE047` 15.9 (black text) | sans 800, oversized | 3–4 px black stroke, hard shadow (8,8), radius 0–8 | stickers/arrows · optional |
| isometric | bg `#EEF2FF`, text `#1E1B4B` 14.3, muted `#4338CA` 7.1, faces `#4F46E5`/`#818CF8`/`#C7D2FE` (white on `#4F46E5` 6.3) | sans | 30° axes, 3 face tones, light top-left | blocks/servers · no |
| flat-mascot | bg `#FFF7ED`, text `#1C1917` 16.5, muted `#57534E` 7.2, accent `#C2410C` (white on it 5.2); `#EA580C` 3.4 shape only | sans | rounded flat shapes | 1–3 characters · yes |
| sketch-notes | paper `#FFFDF7`, ink `#1F2937` 14.4, highlight `#FDE68A` (ink on it 11.8), red pen `#B91C1C` 6.4 | sans (text stays straight) | jittered paths with a fixed seed, double strokes, hachure | doodles · optional stick figures |
| blueprint | bg `#0B3D91`, text `#FFFFFF` 10.0, muted `#CFE0FF` 7.5, accent `#FFD166` 7.0, grid `#7FA6E0` 4.0 (lines only) | mono labels, sans titles | grid pattern, 1.5 px white strokes, dimension arrows | technical diagram · no |
| terminal-retro | bg `#0C0C0C`, green `#33FF66` 14.6, amber `#FFB000` 10.7, dim `#9CA3AF` 7.7 | mono for all text | 1 px panes, `$` prompt, block cursor, faint scanlines | ASCII-like boxes · no |

### Do / don't and risks
| id | Do | Don't | Risks (Q3, Q8, legibility at ~830 px) |
|---|---|---|---|
| dark-artifact | one glow colour | glow on text | Q8: roster.png is 1.28 MB today |
| minimal-type | huge whitespace, one accent | decoration "to fill space" | looks empty in a feed |
| swiss-editorial | one red block = accent | centred text, illustration | thin rules vanish; use ≥ 2 px |
| bento-grid | one focal tile, ≤ 6 tiles | equal tiles | tile text hits 22 px floor; Q5 |
| aurora-mesh | blobs behind the visual side | text over the brightest blob | Q3 measured on pixels; PNG size |
| glass-layers | blur a duplicate of the bg | `backdrop-filter`/`blur()` (leak, CLAUDE.md) | lowest contrast; Q8 |
| neo-brutalism | black text on every fill | coloured text, soft shadows | clashes with trust-first B2B (S15) |
| isometric | one 30° grid for everything | mixed angles, perspective | labels don't fit faces → beside |
| flat-mascot | one character model | many detailed characters | childish for enterprise |
| sketch-notes | fixed jitter seed (Q7) | random jitter per render | text must stay straight |
| blueprint | mono labels, white on blue | colour fills | grid competes with text |
| terminal-retro | one phosphor colour + amber | glow on body text, curvature | mono is wide (0.62 em) |


## Sources
- S0 · project-own style, A14 only (the approved v3 art; its palette is the default in the key-art skill) · `plugins/demo-studio/skills/key-art/references/color.md` · read 2026-11-24 · repo file
- S1 · Kittl, graphic design styles name guide · https://kittl.com/article/graphic-design-styles-name-guide · accessed 2026-11-24 · fetched
- S2 · daisyUI UI trends index · https://trends.daisyui.com/ · accessed 2026-11-24 · fetched
- S3 · daisyUI, Terminal / CLI UI · https://trends.daisyui.com/trend/terminal-cli-ui/ · accessed 2026-11-24 · fetched
- S4 · daisyUI, Mesh Gradient / Aurora UI · https://trends.daisyui.com/trend/mesh-gradient-aurora-ui/ · accessed 2026-11-24 · fetched
- S5 · Linearity, illustration styles guide · https://www.linearity.io/guide/illustration-styles · accessed 2026-11-24 · fetched
- S6 · IxDF, Glassmorphism · https://ixdf.org/literature/topics/glassmorphism · accessed 2026-11-24 · fetched
- S7 · Figma, types of colour palettes · https://www.figma.com/resource-library/types-of-color-palettes/ · accessed 2026-11-24 · search summary
- S8 · Adobe Express, 101 colour combinations · https://www.adobe.com/express/learn/blog/101-brilliant-color-combinations · accessed 2026-11-24 · search summary
- S9 · Wix, logo colour combinations · https://www.wix.com/blog/logo-color-combinations · accessed 2026-11-24 · search summary
- S10 · Toptal, typeface classification · https://www.toptal.com/designers/typography/typeface-classification · accessed 2026-11-24 · search summary
- S11 · Fonts.com, type classifications · https://www.fonts.com/content/learning/fontology/level-1/type-anatomy/type-classifications · accessed 2026-11-24 · search summary
- S12 · Ramotion, branding mood board (3–5 tone adjectives) · https://www.ramotion.com/blog/branding-mood-board/ · accessed 2026-11-24 · search summary
- S13 · Smashing Magazine, Claymorphism · https://www.smashingmagazine.com/2022/03/claymorphism-css-ui-design-trend · accessed 2026-11-24 · search summary
- S14 · Hype4, Claymorphism in UI · https://hype4.academy/articles/design/claymorphism-in-user-interfaces · accessed 2026-11-24 · search summary
- S15 · SaaS Hero, landing page design trends · https://www.saashero.net/design/top-landing-page-design-trends/ · accessed 2026-11-24 · search summary
- S16 · freeCodeCamp, Bento grids in web design · https://www.freecodecamp.org/news/bento-grids-in-web-design/ · accessed 2026-11-24 · search summary
- S17 · Wikipedia, Swiss Style (design) · https://en.wikipedia.org/wiki/Swiss_Style_(design) · accessed 2026-11-24 · search summary
- S18 · Linearity, isometric design · https://www.linearity.io/blog/isometric-design/ · accessed 2026-11-24 · search summary
- S19 · hackdesign, Excalidraw · https://www.hackdesign.org/toolkit/excalidraw/ · accessed 2026-11-24 · search summary
- S20 · SVGator, What is neubrutalism · https://www.svgator.com/blog/what-is-neubrutalism/ · accessed 2026-11-24 · search summary
- S21 · W3C, Understanding SC 1.4.3 Contrast (Minimum) · https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html · accessed 2026-11-24 · fetched (via `color.md`)
- S22 · readme-ai, header styles · https://eli64s.github.io/readme-ai/concepts/customize/headers · accessed 2026-11-24 · search summary
- S23 · MDN, Applying effects with SVG filters · https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/Filters · accessed 2026-11-24 · search summary
- S24 · UX Planet, The rise and fall of neumorphism · https://uxplanet.org/the-rise-and-fall-of-neumorphism-613795fc6f8d · accessed 2026-11-24 · search summary
- S25 · The Swift Kit, app landing page design trends 2026 · https://theswiftk.it.com/blog/app-landing-page-design-trends-2026 · accessed 2026-11-24 · search summary
- S26 · DesignCrowd, colour palette trends · https://blog.designcrowd.com/article/1896/color-palette-trends-to-liven-your-brand · accessed 2026-11-24 · search summary
- S27 · Kittl, blueprint graphic design trend · https://www.kittl.com/blogs/blueprint-graphic-design-trend-stl/ · accessed 2026-11-24 · search summary
- S28 · Wikipedia, Blueprint · https://en.wikipedia.org/wiki/Blueprint · accessed 2026-11-24 · search summary
- S29 · shadcn.io, Hero Two Columns · https://www.shadcn.io/blocks/hero-two-columns · accessed 2026-11-24 · search summary
- Trend sources are mostly vendor blogs (opinion); hex values and recipes are project decisions.
