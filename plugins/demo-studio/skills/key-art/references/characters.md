# Characters (every style)

Every key-art set shows its roles as chibi characters, whatever `#art.style` is (and with `style: null`). The characters carry the image: a reader tells the roles apart from the characters before reading a label. The style changes only the treatment (outline, fills, effects), named per recipe in `styles.md` `## Core recipes`; a B code never removes the characters (B1 line art, B5 robot details such as a visor or antenna, B6 doodle lines change the treatment only). Model = the user-approved README art set (`styles.md` Sources notes). Checks that enforce it: P2, Q5, Q7, Q10 (`checks.md`).

## Model
- Chibi, about 3 heads tall; big head, large dark eyes with one highlight, small mouth; full body, standing, front or three-quarter view; same height and line weight across the set.
- Default treatment: dark outline 2–3 px, flat fills with one shadow tone per colour (cel shading), no gradients or textures. A recipe treatment replaces it.
- Shared kit (it ties the set together): same hair and face model with small variations (ponytail, glasses, cap), ID badge on a lanyard, dark trousers, boots or sneakers.
- Role identity: one jacket colour per role (distinct within one image, from the recipe palette) + 1–2 props in hand that name the job. Examples: orchestrator = cape + compass; developer = laptop `</>` + wrench; qa = clipboard with ticks + test tube; debugger = magnifier + bug tablet; reviewer = magnifier + checklist; security = sunglasses + shield with lock; database = cylinder stack; devops = cap + rocket + server box; writer = open book; architect = ruler + set square; pm = task board; designer = colour palette; analyst = magnifier + chart; retrospective = binoculars. A role not listed: pick the object its source line names.
- A role appears with the same model in every image of the set. A product with no roles (video title, end and thumbnail art of a single app) shows one character as the user of the product, holding the product's main object.
- Jacket colours are shapes, never under text; labels sit on the card or background, never on a character.

## Size and placement
Heights are the character's drawn height; width follows the aspect.

| Image | Characters | Layout (px) |
|---|---|---|
| hero 1280x640 | 3: main role in the middle + 2 others | disc in the recipe's light shape tone (isometric `#C7D2FE`) c(983,330) r232; middle 320 tall, top 200, centred on the disc x; sides 0.8x (about 250), feet on the same baseline y 520, overlapping the middle by about 35 px; middle drawn last (on top); group width ≈ disc diameter |
| social 1200x630 | 3, as hero | disc c(930,340) r215; middle 320 tall, top 220, centred on x 930; sides 0.75x (about 240); baseline y 540 |
| pipeline 1280x720, up to 5 stages (node 200x290) | 1 per node | 190 tall, top = node top + 12, centred in the node; label below at node top + 250 |
| pipeline 1280x720, more than 5 stages (node 166 tall, width fits its characters) | 1 per character (a grouped stage holds several) | 120 tall, top = node top + 10, centred; label below; rows may snake with explicit arrows (user decision 2026-11-25, 17-character README pipeline) |
| command pipeline (node 140x204) | 1 per node | 120 tall, top = node top + 10, centred; label below |
| roster 1280x1600 (card 466x184; 368x184 with 15+ roles, `composition.md`) | 1 per card | 168 tall, top = card top + 8, centred in the card's left 172 px (148 px on a 368 card); name + job text from card x + 172 (x + 148) |
| video title / end card | 1–3 | group height = 50% of the canvas height, on the visual side (`composition.md`) |
| thumbnail | 1 | 50% of the height, outside the transparent window and the badge keep-out |
- The main character fills about half the hero height: never shrink the group to fit; shorten text instead. A character smaller than these sizes is a Q10 finding.

## Source
- In this order: (1) the user's own character images, one per role, when the director recorded the user's approval (`#art.assets`; placed as PNG layers, `svg-craft.md` Verify 4; P2; never on `thumb`, which falls back to a vector character); (2) otherwise drawn as vector by art-designer in the recipe treatment, under ~60 paths each, simplifications listed in `style.approximated`. Never mix the two in one set; never draw over or recolour an asset.
- An approved asset comes either as one image per role, or as one character sheet the user generated from `art/prompts.md` (`## Sheet prompt`) and art-designer cut with `scripts/art_assets.py split` (crops in reading order = the approved role order; `#art.assets.sheet`).
- Assets keep their aspect; scale them down only (never up) to the sizes above; text never sits on an asset.

## Sheet prompt
`art/prompts.md` (art-designer, `Mode: sheet-prompt`) holds one English prompt in a fenced block, then a short list: the roles in order, the minimum crop height, and the background rule. The user runs it in their own image tool; nothing in it is private.
- One image, every role of the run, each exactly once; reading order (row by row, left to right) = the role list; at most 5 per row; same model, height and line weight for all (`## Model`), each with its jacket colour (hex from the recipe palette) and props.
- Background: transparent; if the tool cannot, one solid flat `#FF00FF` (no gradient, floor, shadow or vignette). Never white, grey or black (`art_assets.py` refuses them: keying would cut the characters' own whites).
- Separation: every character fully inside the image with a clear empty gap (at least 5% of the image width) to its neighbours and the edges; no overlap, no shared prop, no cast or ground shadow, no sparkles between them.
- No text, letters, numbers, labels, logos, watermark or UI anywhere (a `</>` or tick drawn as a prop shape is fine); no real person's face or brand.
- Size: ask for the largest size the tool offers (portrait when there are more than 2 rows). Every crop must be at least as tall as the largest height this run places that role at (`## Size and placement`; hero main 320 px); `facts` states that minimum. A shorter crop is never upscaled: regenerate or use vector characters.
- Privacy: role names, props and visual words only; never the product name, customer, user or app data, nor anything from `brief.md` beyond the roles. An asset is used as is in every style (its own colours); the style applies to everything around it.
