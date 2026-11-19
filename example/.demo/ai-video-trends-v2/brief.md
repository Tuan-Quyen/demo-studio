# Brief: AI Video Trends, the full tour

Prose only. Video properties (platform, length, formats, voice, motion, music, captions, targets, privacy, installs) live in `demo.yaml`, not here.

- Slug: ai-video-trends-v2
- Audience: Content creators and marketers who already make or commission short videos and have heard of AI video tools, but don't know which formats are actually taking off. (given: audience; "already make videos" = assumption)
- Goal: The viewer has seen every part of the page (trending videos, trends, the genre ranking) and wants to open AI Video Trends to plan their next video. (given: full tour, re-brief; "plan next video" = assumption)
- Key message: See what's trending in AI video and which genres are worth betting on, all in one place. (from index.html hero sub-line)
- Opening: the title card and the first spoken line introduce the product by name, "AI Video Trends". (given: user request, re-brief)
- Tour (replaces the 3 proof points; every item must appear on screen, sample data only, no real-world claims) (given: user decisions, re-brief):
  1. Navigation: the hero's "Explore trends" button and the header nav (Trending / Trends / Genres) move between sections. (given; elements from index.html)
  2. Trending grid: all 8 videos visible; filter with 2-3 genre chips (e.g. Music video, Anime, Faceless YouTube); reset to All. (given; chips and videos from data.js)
  3. Detail popup: from Faceless YouTube, open a video's detail popup (prompt example, tool category, why it trends), then close it. (given; modal fields from index.html)
  4. Trends: the 4 trend cards, shown before the genre growth chart. (given; from index.html, data.js; chart labelled "sample")
  5. Promising genres: the full ranking, all 5 ranks with their reasons. (given; from data.js)
- Pacing: comfortable, with a 1-2 s reading hold on each screen. The previous cut felt too fast to the user, so the content sets the length, not the other way round. (given: user feedback)
- Tone: upbeat, practical, creator-to-creator; spoken in English. (tone = assumption; English = given)
- Structure: Hook (product intro over the hero) -> Solution (the tour in the order above: nav -> trending + chips -> popup -> trends -> chart -> genres) -> Outcome (a clear pick of a genre to try) + CTA. (order = assumption, per demo-storytelling; the user can reorder it)
- CTA: Open AI Video Trends and pick your next genre to try. (assumption: the app has no real URL or sign-up; "Explore trends" is used in the tour, from index.html)
- Out of scope: the creator dashboard / API key panel and the signed-in email pill. Both are sensitive, so blur them if they come into frame. All numbers are fictional sample data and must not be presented as real market statistics. (given: user decision; from README.md, data.js, index.html `data-sensitive`)

## Open questions
1. Where the "Explore trends" button fits: it jumps straight to Trends, which skips the Trending grid. Options: (a) use the header nav for Trending first, then click the hero button on the way back up to reach Trends, (b) click the hero button first, then go back to Trending with the nav, (c) end the video on the hero button as the CTA. Recommended default: (a). (assumption)
2. Numbers in narration: Options: (a) speak no figures, say "sample data" on screen only, (b) speak one figure with a "sample" caveat. Recommended default: (a). (assumption)
3. Reading the ranking aloud: Options: (a) name all 5 genres and give a short reason for the top 2-3, letting the screen hold the rest, (b) read all 5 reasons in full (needs a longer video). Recommended default: (a). (assumption)

## Approval
G1: approved (test run: auto-approved by the director at the user's instruction, 2026-11-19; re-brief after /fix)
