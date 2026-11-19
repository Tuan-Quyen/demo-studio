// SAMPLE DATA FOR DEMO ONLY. All creators, numbers and videos are fictional.
window.DEMO_DATA = {
  genres: [
    { slug: "all", label: "All" },
    { slug: "short-form-ads", label: "Short-form ads" },
    { slug: "music-video", label: "Music video" },
    { slug: "explainer", label: "Explainer" },
    { slug: "faceless-youtube", label: "Faceless YouTube" },
    { slug: "ugc-avatar", label: "UGC avatar" },
    { slug: "cinematic-shorts", label: "Cinematic shorts" },
    { slug: "anime", label: "Anime" }
  ],
  videos: [
    { id: "v1", title: "Neon Rain Over Tokyo-esque Streets", creator: "@pixel_harbor", genre: "cinematic-shorts", tool: "text-to-video", views: "2.4M", growth: 182, hues: [265, 190],
      description: "A 30-second moody city sequence with consistent lighting across eight generated shots.",
      prompt: "Rainy neon alley at night, slow dolly forward, reflections on wet asphalt, cinematic 35mm, shallow depth of field.",
      why: "Consistent shots plus a strong mood make it easy to share and remix." },
    { id: "v2", title: "30-Second Sneaker Drop Teaser", creator: "@loop_lantern", genre: "short-form-ads", tool: "image-to-video", views: "1.8M", growth: 140, hues: [20, 330],
      description: "A product still animated into a punchy vertical ad with parallax and light sweeps.",
      prompt: "Animate product photo: slow orbit, soft rim light sweep, subtle dust particles, 9:16.",
      why: "Small brands can ship ad variants in minutes instead of weeks." },
    { id: "v3", title: "Synthwave Sunrise (Full Music Video)", creator: "@echo_meadow", genre: "music-video", tool: "text-to-video", views: "3.1M", growth: 96, hues: [300, 40],
      description: "Beat-synced visuals for an original instrumental, cut to the tempo of the track.",
      prompt: "Retro-futuristic highway at sunrise, pulsing sun, chrome car, loopable, 120 BPM rhythm.",
      why: "Independent artists get a visual identity at near-zero cost." },
    { id: "v4", title: "How Tides Work in 60 Seconds", creator: "@quill_orbit", genre: "explainer", tool: "text-to-video", views: "980K", growth: 74, hues: [200, 160],
      description: "Animated science explainer using clean motion graphics and calm narration.",
      prompt: "Minimal 3D moon and ocean, labeled arrows, soft gradients, educational tone.",
      why: "Short, clear explainers match how people search for quick answers." },
    { id: "v5", title: "10 Habits of Calm Productive People", creator: "@still_atlas", genre: "faceless-youtube", tool: "text-to-video", views: "4.2M", growth: 220, hues: [150, 220],
      description: "A faceless list video with generated b-roll and a synthetic voiceover.",
      prompt: "Warm desk scene, morning light, slow pan, no faces visible, lifestyle b-roll.",
      why: "Repeatable format: one creator can run several channels." },
    { id: "v6", title: "Skincare Review in Five Languages", creator: "@mira_circuit", genre: "ugc-avatar", tool: "avatar", views: "1.2M", growth: 165, hues: [340, 20],
      description: "A synthetic presenter delivers the same review across five languages.",
      prompt: "Friendly presenter at a bright desk, product in hand, natural gestures, direct to camera.",
      why: "Localization with lip-sync removes the cost of re-shooting." },
    { id: "v7", title: "Dubbed Interview Clip, Perfect Sync", creator: "@sync_willow", genre: "ugc-avatar", tool: "lip-sync", views: "760K", growth: 88, hues: [180, 280],
      description: "Existing footage re-dubbed with mouth movements matched to the new audio.",
      prompt: "Match mouth motion to supplied audio track, preserve original expression and lighting.",
      why: "Reuses existing footage for new markets quickly." },
    { id: "v8", title: "Moonlit Blade: Episode 0", creator: "@kite_origami", genre: "anime", tool: "image-to-video", views: "2.0M", growth: 130, hues: [250, 340],
      description: "Hand-drawn style keyframes animated into a short fight teaser.",
      prompt: "Anime key art, swirling cloth, fast camera shake, cel-shaded, 24fps feel.",
      why: "Illustrators animate their own art without a studio." }
  ],
  trends: [
    { id: "t1", title: "Image-to-video overtakes text-only", stat: "+58%", text: "Creators start from a still for tighter control over look and brand." },
    { id: "t2", title: "Lip-sync localization", stat: "+44%", text: "One video, many languages. Dubbing costs drop sharply." },
    { id: "t3", title: "Faceless channels at scale", stat: "+71%", text: "Templated formats let small teams publish daily." },
    { id: "t4", title: "Beat-synced music visuals", stat: "+37%", text: "Audio-reactive generation makes music videos affordable." }
  ],
  chart: [
    { genre: "Faceless YouTube", growth: 71 },
    { genre: "Short-form ads", growth: 64 },
    { genre: "UGC avatar", growth: 52 },
    { genre: "Cinematic shorts", growth: 47 },
    { genre: "Anime", growth: 41 },
    { genre: "Music video", growth: 33 },
    { genre: "Explainer", growth: 28 }
  ],
  promising: [
    { rank: 1, genre: "Faceless YouTube", why: "Low production cost, repeatable formats, strong ad revenue potential." },
    { rank: 2, genre: "Short-form ads", why: "Fast A/B testing of creative; clear ROI for small brands." },
    { rank: 3, genre: "UGC avatar", why: "Localization and scale without hiring presenters." },
    { rank: 4, genre: "Cinematic shorts", why: "Quality is rising quickly; festivals and showreels are opening up." },
    { rank: 5, genre: "Anime", why: "Passionate audiences and a strong fan-art to animation pipeline." }
  ],
  user: { email: "alex.nguyen@example.com", apiKey: "sk-demo-4f9a…c21e" }
};
