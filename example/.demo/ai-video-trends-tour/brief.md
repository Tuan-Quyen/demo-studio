# Brief: AI Video Trends — quick tour

Prose only. Video properties (platform, length, formats, voice, motion, music, captions, targets, privacy, installs) live in `demo.yaml`, not here.

- Slug: ai-video-trends-tour
- Audience: Content creators and marketers who already make or commission short videos and have heard of AI video tools, but don't track which AI-made formats are actually taking off. (given: audience guess from user; "what they know" is an assumption)
- Goal: After watching, the viewer understands that one page shows them what's trending in AI video and which genre to bet on next, and opens the page to pick a genre to try. (assumption)
- Key message: See what's trending in AI video and which genres are worth betting on — all in one place. (from index.html hero copy: "Popular videos, rising techniques and the genres worth betting on, all in one place.")
- Proof points (max 3, all shown on screen from sample data):
  1. Filter trending AI-made videos by genre and open one to see its prompt example, tool category and why it trends. (from index.html, data.js)
  2. Trend cards and a 90-day genre growth chart show which techniques are rising. (from index.html, data.js — figures are sample data; narration must not present them as real market numbers)
  3. A ranked "Promising genres" list says where to focus next, with a reason for each. (from index.html, data.js)
- Tone: Upbeat, fast, practical — a creator talking to creators; no hype superlatives, no invented statistics. (assumption)
- Structure: Problem (too many AI video formats, hard to know what's working) → Solution (trending grid + genre filter + detail, trends + chart, promising genres) → Outcome (you know which genre to try next) → CTA. (from skill demo-storytelling)
- CTA: "Open AI Video Trends and pick your next genre to try." Spoken in the narration language, shown on an end card. (assumption: the app has no sign-up or public URL, so the CTA points at the page itself)
- Out of scope: Creator dashboard and its API key panel (sensitive, not part of the message — avoid on screen or blur); signed-in email pill (sensitive — blur or keep out of frame); nav links, footer; any claim that data is real (README: all data is fictional sample data).

## Notes for downstream (facts, not properties)
- All data is fictional sample data (from README.md); a "sample data" note exists in the footer and chart caption.
- Sensitive on-screen elements: signed-in email pill and API key (`data-sensitive="true"`, from index.html / README.md).
- On-screen UI text is English while narration is in the language set in `demo.yaml`; narration should describe outcomes, not read English labels aloud.

## Open questions
1. CTA wording — (a) "Open AI Video Trends and pick your next genre" [recommended default, used above]; (b) "Explore this week's trends" mirroring the hero button; (c) none / end card only. Not material for a test run.
2. Showing the creator dashboard — (a) skip it entirely [recommended default]; (b) show briefly with API key blurred. Not material.
3. Proof-point order — (a) trending grid → trends/chart → promising genres, matching page order [recommended default]; (b) open on the promising-genres ranking as the hook. Not material.

## Approval
G1: pending (test run: director auto-approves)
