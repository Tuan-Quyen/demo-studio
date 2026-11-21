#!/usr/bin/env python3
"""capture.py - web capture with capture-time masking (redesign 4.2 / 6.2 / 6.4; fix round F-CAPTURE).

Two commands:

  capture.py run  --url URL --scene s03 --scene-script SCRIPT [--vo-ms N] [--slug S | --out-dir DIR]
                  [--config mask.json] [--selector S ...] [--regex R ...] [--viewport 1280x720] [--probe SEL ...]
                  [--accept-unmaskable DESC ...] [--max-soft N] [--max-resync N] [--no-mask] [--dry-run]
      Spawns the fixed adapter web_adapter.py (Python Playwright; run_bounded, jsonl heartbeat) which runs the
      scene script UNMODIFIED, records to a TEMP dir and writes sidecars. Then runs `gate` on the temp files.
      Only a clip that passes the gate is renamed to <out>/<scene>.raw.webm (+ <scene>.mask.jsonl, <scene>.sync.json)
      and written to #events; on any failure the temp dir is deleted and a previous #events entry of the scene
      is set to masked:false (never a stale masked:true).
  capture.py gate --clip F --mask-log F --sync F [--scene s03] [--slug S] [--config ...] [--selector ...] [--regex ...]
      Pure verification, trusts nothing from the adapter: recomputes `masked` / `frames_unmasked` from the video
      pixels, the mask log (+ the independent DOM oracle entries in it) and the sync file. Also re-verifies an
      existing clip. With --slug it (re)writes that clip's entry in #events.

The gate fails (exit 11) when: the mask log is missing/empty while the mask is enabled; sensitive elements were
present (preflight / ticks) but not one rect could be pixel-checked (rect_checks == 0); any frame shows glyph edges
or the wrong colour at a logged or oracle rect, or the log state says unmasked (never excused by lead-in or
edge grace); soft / resynced frames exceed --max-soft / --max-resync (default 0: secrets get no tolerance; an
unstable alignment is re-calibrated once, then fails); the viewport differs from the clip size; unmaskable surfaces
were detected (status needs-input, clip kept with masked:false and clips.<sid>.unmaskable[]).

#events clips.<sid> fields written: file, w, h, fps, scale, offset_ms, duration_ms, masked, safe_from_ms (first clip
time with verified evidence: never use earlier frames), unmaskable[] = {surface, selector, reason, t_start, t_end
(clip ms), bbox:[x,y,w,h] clip px}, mask_log, sync, mask{mode, style, status, frames_unmasked, frames_total,
frames_with_masks, rects_checked, oracle_rects_checked, frames_soft, frames_resynced, selectors, n_regex}.
`mask_style: blur` always yields masked:false (the post-hoc blur tier covers everything); `privacy.capture_mask:false`
or --no-mask records without a mask (masked:false).

mask.json: {"selectors":[...], "regexes":[...], "mask_style":"solid"|"blur"|{color,sentinel,blur_px}}.
Exit codes (shared table, 4.2): 0 ok | 2 bad input (also: typed text matched a regex and its target cannot be
pre-masked, invalid regex) | 3 over budget (incomplete) | 4 missing tool | 10 scene step failed | 11 leak / unverifiable /
unmaskable (needs-input) | 70 unexpected/env error (retried <= 2 first).
Redaction: runs.jsonl never holds regex literals or URL query strings; dry-run prints regex counts only; the spec
(regexes, typed text) lives in a private temp dir removed on every exit path; the temp video dir likewise.
"""
import argparse
import bisect
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_bounded as rbm  # noqa: E402
import project  # noqa: E402

ADAPTER = os.path.join(HERE, "web_adapter.py")

EXIT_OK, EXIT_INPUT, EXIT_BUDGET, EXIT_TOOL, EXIT_STEP, EXIT_LEAK, EXIT_BUG = 0, 2, 3, 4, 10, 11, 70

DEFAULT_PILL = "#9aa3b2"
STD_MAX = 12.0          # max per-channel std-dev inside a masked rect (VP8 noise tolerated, glyph edges are not)
MIN_RECT_PX = 5         # rects thinner than this are slivers: no evidence either way (soft)
PILL_EDGE_FRAC = 0.5    # a non-uniform rect that is at least this much mask colour is a shifted pill edge (soft), not glyph edges (bad)
COLOR_TOL = 34          # max per-channel |mean - pill| (VP8 chroma shift)
SENTINEL_DROP = 20.0    # box ring must be this much darker (luma) than the interior
FRAME_TOL_MS = 90.0     # log entry <-> frame match window (~2 frames at 25 fps: measured screencast jitter during fast scroll)
GAP_MS = 120.0          # log gap (same selector, rects on both sides) longer than this = missing entries
WIDE_TOL_MS = 260.0     # fallback window when screencast frame stamps lag the page clock (counted as frames_resynced)
REFINE_MS = 120         # calibration refine range (+-) around the pulse-based offset
RECAL_MS = 400          # wide re-calibration range when alignment looks unstable
UNM_PAD_MS = 300       # >= one detection interval (250 ms) + one frame
UNM_GAP_MS = 250.0      # unmaskable log entries closer than this belong to one interval


class Fail(Exception):
    def __init__(self, code, msg, **extra):
        super().__init__(msg)
        self.code, self.msg, self.extra = code, msg, extra


# ------------------------------------------------------------------ tools
_FFMPEG = []


def ffmpeg_exe():
    """ffmpeg on PATH, else the binary bundled with imageio-ffmpeg (feature `capture`). ffprobe is not needed."""
    if _FFMPEG:
        return _FFMPEG[0]
    exe = shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001 - ImportError or a missing bundled binary
            exe = None
    if exe:
        _FFMPEG.append(exe)
    return exe


def need_tools(adapter=True):
    missing = []
    if adapter:
        try:
            import playwright  # noqa: F401
        except ImportError:
            missing.append("playwright")
    if not ffmpeg_exe():
        missing.append("ffmpeg")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    if missing:
        raise Fail(EXIT_TOOL, "missing tools: " + ", ".join(missing) + " (setup_tools.py --plan capture)",
                   feature="capture", missing=missing)


# ------------------------------------------------------------------ video helpers (ffmpeg only)
def _run(cmd, wall, what, tail=16000000):
    r = rbm.run_bounded(cmd, wall=wall, label=what, tail_bytes=tail)
    if r["status"] != "ok":
        raise Fail(EXIT_BUG, "%s failed (%s)" % (what, r["status"]))
    return r


def probe_clip(path):
    """{w,h,fps,duration_ms,times} from one ffmpeg pass (showinfo): frame times in seconds, no ffprobe."""
    r = _run([ffmpeg_exe(), "-nostdin", "-hide_banner", "-v", "info", "-i", path, "-map", "0:v:0", "-fps_mode", "passthrough",
              "-vf", "showinfo", "-f", "null", "-"], 120, "ffmpeg probe")
    err = r["stderr_tail"]
    m = re.search(r"Stream #0:\d.*?Video:.*?,\s*(\d{2,5})x(\d{2,5})", err)
    if not m:
        raise Fail(EXIT_BUG, "ffmpeg could not read the video stream of %s" % path)
    w, h = int(m.group(1)), int(m.group(2))
    times = [float(x) for x in re.findall(r"pts_time:\s*(-?[0-9.]+)", err)]
    if not times:
        raise Fail(EXIT_BUG, "no frames decoded from %s" % path)
    fm = re.search(r"([0-9.]+) fps", err)
    fps = float(fm.group(1)) if fm else (len(times) - 1) / max(times[-1] - times[0], 1e-6)
    dm = re.search(r"Duration:\s*(\d+):(\d+):([0-9.]+)", err)
    dur = (int(dm.group(1)) * 3600 + int(dm.group(2)) * 60 + float(dm.group(3))) if dm else times[-1] + 1.0 / max(fps, 1)
    return {"w": w, "h": h, "fps": round(fps, 3), "duration_ms": round(dur * 1000), "times": times}


def iter_frames(path, w, h, wall_s):
    """Yield (index, ndarray HxWx3 uint8) decoded once, sequentially, in a killable group (run_bounded)."""
    import numpy as np
    cmd = [ffmpeg_exe(), "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0", "-fps_mode", "passthrough",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    n = w * h * 3
    i = 0
    with rbm.Bounded(cmd, wall_s, stderr=rbm.subprocess.DEVNULL) as b:
        while True:
            buf = b.proc.stdout.read(n)
            if len(buf) < n:
                break
            b.touch()
            yield i, np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
            i += 1


def frame_times(path):
    return probe_clip(path)["times"]


def hex_rgb(c):
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def luma(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def check_rect(frame, rect, pill, is_box):
    """Return None if the mask is visibly present at rect, else a reason string."""
    import numpy as np
    h, w = frame.shape[:2]
    x, y, rw, rh = rect
    x0, y0, x1, y1 = int(round(x)), int(round(y)), int(round(x + rw)), int(round(y + rh))
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 - x0 < MIN_RECT_PX or y1 - y0 < MIN_RECT_PX:
        return "rect_too_small"   # a sliver (element entering/leaving the viewport edge) carries no evidence and shows no readable glyph
    inset = 2 if (x1 - x0 >= 8 and y1 - y0 >= 8) else 1 if (x1 - x0 >= 4 and y1 - y0 >= 4) else 0
    ix0, iy0, ix1, iy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    if ix1 - ix0 < 1 or iy1 - iy0 < 1:
        return "rect_too_small"
    reg = frame[iy0:iy1, ix0:ix1].reshape(-1, 3).astype(np.float32)
    mean, std = reg.mean(0), reg.std(0)
    if float(std.max()) > STD_MAX:
        near_pill = float((np.abs(reg - np.array(pill, dtype=np.float32)).max(1) <= COLOR_TOL).mean())
        if near_pill >= PILL_EDGE_FRAC:   # mostly mask colour: a rect shifted by scroll/pts jitter over the pill edge, not glyphs
            return "interior_pill_edge(pill=%.2f)" % near_pill
        return "interior_not_uniform(std=%.1f)" % float(std.max())
    dev = np.abs(mean - np.array(pill, dtype=np.float32))
    if float(dev.max()) > COLOR_TOL:
        return "interior_not_mask_colour(dev=%.0f)" % float(dev.max())
    if is_box and x0 > 0 and y0 > 0 and x1 < w and y1 < h and (x1 - x0) >= 8 and (y1 - y0) >= 6:
        inner = float(luma(reg).mean())
        top = luma(frame[max(y0 - 1, 0):y0 + 2, x0 + 2:x1 - 2].astype(np.float32)).mean(axis=1).min()
        bot = luma(frame[y1 - 2:min(y1 + 1, h), x0 + 2:x1 - 2].astype(np.float32)).mean(axis=1).min()
        if min(float(top), float(bot)) > inner - SENTINEL_DROP:
            return "sentinel_missing"
    return None


# ------------------------------------------------------------------ log
def load_log(path):
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    entries.sort(key=lambda e: e["t"])
    return entries


def split_log(entries):
    """-> (group entries by selector incl. the 'oracle' group, ticks, unmaskable entries)."""
    groups, ticks, unm = {}, [], []
    for e in entries:
        k = e.get("kind")
        if e.get("loading") and k in ("masked", "oracle", "tick"):
            continue     # half-parsed page (readyState 'loading'): describes no frame the viewer is shown, never judged
        if k == "masked":
            groups.setdefault(e["selector"], []).append(e)
        elif k == "oracle":
            groups.setdefault("oracle", []).append(dict(e, selector="oracle", state="masked"))
        elif k == "tick":
            ticks.append(e)
        elif k == "unmaskable":
            unm.append(e)
    return groups, ticks, unm


def _skipped(e):
    return set(e.get("skip") or [])


def entry_verdict(fr, e, pill, res):
    """One log entry against one frame -> ('strict'|'soft'|'bad'|'skipped', why, rect).
    bad = glyph edges / wrong shape / state unmasked; soft = uniform but not mask-coloured (no glyph readable);
    skipped = every rect is DOM-proven opaque-occluded (no evidence either way)."""
    if e.get("state", "masked") != "masked":
        return "bad", "state_unmasked", None
    skip, boxes = _skipped(e), set(e.get("boxes") or [])
    soft = checked = False
    for ri, r in enumerate(e["rects"]):
        if ri in skip:
            res["rects_skipped_proven"] += 1
            continue
        checked = True
        res["rect_checks"] += 1
        if e.get("selector") == "oracle":
            res["oracle_rect_checks"] += 1
        why = check_rect(fr, r, pill, ri in boxes)
        if why is None:
            continue
        if why.startswith("interior_not_mask_colour") or why.startswith("interior_pill_edge") or why == "rect_too_small":
            soft = True
            res["rects_uniform_nopill"] += 1
            continue
        res["rects_failed"] += 1
        return "bad", why, r
    if not checked:
        return "skipped", None, None
    return ("soft" if soft else "strict"), None, None


BOUNDARY_OUTER_MS = 35.0  # outer slice of the window (about 2 rAF) that must hold an entry on each side, else a run starts/ends here
EDGE_MS = 100.0         # soft frames this close to the start/end of an element's run carry no information (it appears/disappears)
NEAR_MS = 37.0          # an entry this close counts as the frame's own: video pts are quantised to 40 ms (+-20) plus one rAF (16.7)


def _boundary(cands, te, narrow):
    """A run of log entries starts or ends inside this frame's window (no entry in the outer ~2 frames of one side):
    the element appears/disappears around this frame, so uniform non-pill pixels carry no information."""
    w = [e["t"] for e in cands if abs(e["t"] - te) <= narrow]
    return not w or not any(t >= te + narrow - BOUNDARY_OUTER_MS for t in w) or not any(t <= te - narrow + BOUNDARY_OUTER_MS for t in w)


def run_edges(es):
    """Times at which a run of rect-bearing log entries of one group starts or ends (element appears / disappears)."""
    out, prev = [], None
    for e in es:
        if not e["rects"]:
            continue
        if prev is None or e["t"] - prev > GAP_MS:
            out += ([prev] if prev is not None else []) + [e["t"]]
        prev = e["t"]
    if prev is not None:
        out.append(prev)
    return out


def eval_group(fr, cands, te, narrow, pill, res, edges=None):
    """Verdict for one selector group in one frame (S-02/S-19). "Nearest" = entries within NEAR_MS of the frame; entries
    further out (up to `narrow`) can only produce resync. Returns (verdict, why, rect):
      empty   - the log says nothing is on screen near this frame (also soft frames within EDGE_MS of a run edge)
      strict  - mask colour (+ sentinel for boxes) at every rect of some entry within NEAR_MS
      bad     - glyph edges / wrong shape / state unmasked at an entry within NEAR_MS and no strict one there (a bad entry
                further out, within `narrow`, does not fail the frame by itself)
      soft    - rects uniform but not mask-coloured (counted, fails above --max-soft)
      resync  - the nearest entry is not strict but another one (or one further away) matches strictly (counted)
    Nothing excuses `bad`: not lead-in, not an element appearing (no edge grace)."""
    near = [e for e in cands if abs(e["t"] - te) <= narrow and e["rects"]]
    if not near:
        return "empty", None, None
    near.sort(key=lambda e: abs(e["t"] - te))                            # nearest first
    vs = [entry_verdict(fr, e, pill, res) for e in near]
    inner = [v for e, v in zip(near, vs) if abs(e["t"] - te) <= NEAR_MS] or vs[:1]   # "nearest" = within ~1.5 rAF (video pts are quantised to 40 ms)
    bad = next((v for v in inner if v[0] == "bad"), None)
    if bad:      # S-19: ANY glyph-edge entry within NEAR_MS fails the frame; a strict neighbour rescues only uniform / pill-edge ones
        return "bad", bad[1], bad[2]
    if any(v[0] == "strict" for v in inner):
        return "strict", None, None
    if any(v[0] == "strict" for v in vs):
        return "resync", None, None      # the nearest entries are soft/skipped, a neighbour matches strictly: counted
    if all(v[0] == "skipped" for v in vs):
        return "skipped", None, None
    for e in sorted(cands, key=lambda e: abs(e["t"] - te)):
        if e["rects"] and abs(e["t"] - te) > narrow and entry_verdict(fr, e, pill, res)[0] == "strict":
            return "resync", None, None
    if any(not e["rects"] for e in cands if abs(e["t"] - te) <= narrow) or _boundary(cands, te, narrow) \
            or (edges and any(abs(t - te) <= EDGE_MS for t in edges)):
        return "empty", "edge_soft", None      # the element appears/disappears around this frame: uniform pixels, nothing readable
    return "soft", None, None


def _entry_ok(fr, e, pill):
    """True if every non-skipped rect of log entry e shows the mask in frame fr (calibration scoring)."""
    if e.get("state", "masked") != "masked":
        return False
    sk, bx = _skipped(e), set(e.get("boxes") or [])
    return all(check_rect(fr, r, pill, ri in bx) is None for ri, r in enumerate(e["rects"]) if ri not in sk)


def calibrate(video, clip, times, entries, t_flashes, t_page_epoch, scene_start, pill, budget_s, rng=REFINE_MS, step=10, base=None):
    """Map rAF epoch ms -> video time. Coarse: first calibration pulse. Refine (+-rng) on in-scene frames by
    agreement between log rects and pixels (screencast stamps lag/lead the page clock by tens of ms). One global
    scalar: it cannot hide an unmasked frame (such a frame fails at every offset)."""
    if base is None:
        first = None
        for i, fr in iter_frames(video, clip["w"], clip["h"], budget_s):
            c = fr[clip["h"] // 2, clip["w"] // 2]
            if c[0] > 200 and c[1] < 60 and c[2] > 200:
                first = i
                break
        if t_flashes and first is None:
            raise Fail(EXIT_LEAK, "calibration flash not found in video (cannot align the mask log)")
        base = (t_flashes[0] - times[first] * 1000.0) if t_flashes else t_page_epoch
    sel = [e for e in entries if e["rects"] and e.get("state", "masked") == "masked"]
    ts = [e["t"] for e in sel]
    scene_frames = [i for i, tv in enumerate(times) if base + tv * 1000.0 > scene_start + 300]
    if not scene_frames or not sel:
        return base, "flash" if t_flashes else "page-start", 0
    want = set(scene_frames[:: max(1, len(scene_frames) // 70)])
    sample = {i: fr.copy() for i, fr in iter_frames(video, clip["w"], clip["h"], budget_s) if i in want}
    scores = {}
    for d in range(-rng, rng + 1, step):
        ok = 0
        for i, fr in sample.items():
            te = base + d + times[i] * 1000.0
            lo, hi = bisect.bisect_left(ts, te - 12), bisect.bisect_right(ts, te + 12)
            if any(_entry_ok(fr, e, pill) for e in sel[lo:hi]):
                ok += 1
        scores[d] = ok
    best = max(scores.values())
    near_best = [d for d, v in scores.items() if v >= best - max(1, len(sample) // 30)]
    delta = min(near_best, key=lambda d: (abs(d), d))   # prefer the pulse-based offset when scores tie
    return base + delta, "flash+refine", delta


def _new_res(mask_kind):
    return {"frames_total": 0, "frames_with_masks": 0, "frames_unmasked": 0, "rect_checks": 0, "oracle_rect_checks": 0,
            "rects_failed": 0, "frames_resynced": 0, "frames_soft": 0, "rects_uniform_nopill": 0,
            "rects_skipped_proven": 0, "frames_unverified": 0, "frames_carried": 0, "strict_frames": 0, "frames_edge_soft": 0, "skipped_blur": mask_kind == "blur", "failures": [], "sync": None}


def ready_time(groups, ticks):
    """Epoch ms of the first log entry of a fully parsed page (None when there is none)."""
    return min([t["t"] for t in ticks] + [e["t"] for es in groups.values() for e in es], default=None)


DUP_MAX = 16     # a region whose every pixel is within this of the anchor frame is unchanged (stale screencast frame)
CARRY_RECTS_MAX = 400   # above this many rects the carry compares the whole frame (fail closed)
CARRY_MAX = 6    # consecutive frames that may be carried from one anchor (measured stale-screencast runs: 3-5 frames)


def _same_region(fr, anchor, rects=None):
    """True when fr equals the anchor frame everywhere that matters: the whole frame, or (rects given) every rect
    position dilated by 6 px (the app may repaint elsewhere without touching them)."""
    import numpy as np
    if anchor is None:
        return False
    if not rects:
        return int(np.abs(fr.astype(np.int16) - anchor.astype(np.int16)).max()) <= DUP_MAX
    h, w = fr.shape[:2]
    for x, y, rw, rh in rects:
        x0, y0, x1, y1 = max(int(x) - 6, 0), max(int(y) - 6, 0), min(int(x + rw) + 6, w), min(int(y + rh) + 6, h)
        if x1 > x0 and y1 > y0 and int(np.abs(fr[y0:y1, x0:x1].astype(np.int16) - anchor[y0:y1, x0:x1].astype(np.int16)).max()) > DUP_MAX:
            return False
    return True


_is_repeat = _same_region   # kept for older tests


def _pass(video, clip, times, by_sel, epoch0, ready_t, pill, budget_s, scene_start=None):
    """One evaluation of every frame against the log at alignment epoch0. A frame the log cannot match is `carried`
    only when it is pixel-identical (at the failing rects, +-DUP_MAX) to the last STRICTLY verified frame (the anchor,
    never to a previous carried frame: no drift), for at most CARRY_MAX consecutive frames; a log-gap failure needs a
    whole-frame repeat. Identical pixels show identical content, so a carried frame is exactly as safe as its anchor."""
    res = _new_res("solid")
    sel_t = {k: [e["t"] for e in es] for k, es in by_sel.items()}
    sel_edges = {k: run_edges(es) for k, es in by_sel.items()}
    bad_f, soft_f, resync_f, masked_f = set(), set(), set(), set()
    n = unverified = carried = strict_frames = edge_soft_frames = 0
    anchor, run_len, seen_strict, leadin_end = None, 0, False, None
    for i, fr in iter_frames(video, clip["w"], clip["h"], budget_s):
        n += 1
        if i >= len(times):
            raise Fail(EXIT_BUG, "frame count mismatch between the two ffmpeg passes")
        te = epoch0 + times[i] * 1000.0
        if ready_t is None or te < ready_t - FRAME_TOL_MS:
            unverified += 1     # before the page was fully parsed: not judged, safe_from_ms starts after these
            continue
        fbad, fsoft, fres, anym, wide_rects, fstrict, gap = [], False, False, False, [], False, False
        others, edge_soft = False, False      # a group that is not strict and not simply empty / an edge-exempt soft frame
        for sel, es in by_sel.items():
            ts = sel_t[sel]
            lo, hi = bisect.bisect_left(ts, te - WIDE_TOL_MS), bisect.bisect_right(ts, te + WIDE_TOL_MS)
            cands = es[lo:hi]
            if not cands:
                k = bisect.bisect_left(ts, te)   # gap rule: rects logged on both sides but nothing near this frame
                if sel != "oracle" and 0 < k < len(ts) and es[k - 1]["rects"] and es[k]["rects"] \
                        and ts[k] - ts[k - 1] > GAP_MS and ts[k - 1] > epoch0:
                    gap = True
                    fbad.append({"frame": i, "t_ms": round(times[i] * 1000), "selector": sel, "reason": "log_gap"})
                continue
            verdict, why, rect = eval_group(fr, cands, te, FRAME_TOL_MS, pill, res, sel_edges[sel])
            anym = anym or verdict != "empty"
            fstrict = fstrict or verdict == "strict"
            if verdict == "empty" and why == "edge_soft":
                edge_soft = True
            elif verdict not in ("strict", "empty"):
                others = True
            if verdict in ("soft", "resync", "bad"):    # carry only needs these groups' positions unchanged
                wide_rects.extend(r for e in cands if abs(e["t"] - te) <= FRAME_TOL_MS for r in e["rects"])
            if verdict == "soft":
                fsoft = True
            elif verdict == "resync":
                fres = True
            elif verdict == "bad":
                f = {"frame": i, "t_ms": round(times[i] * 1000), "selector": sel, "reason": why}
                if rect:
                    f["rect"] = rect
                fbad.append(f)
        ok = not (fbad or fsoft or fres)
        if (fsoft or fres) and not fbad and not seen_strict and (scene_start is None or te < scene_start):
            # first paint not reached yet (uniform, nothing readable, no strict evidence so far): not judged, and
            # safe_from_ms starts after it. Glyph edges (bad) are never excused this way.
            unverified += 1
            leadin_end = i
            continue
        was_carried = False
        if not ok and anchor is not None and run_len < CARRY_MAX and _same_region(fr, anchor, None if (gap or len(wide_rects) > CARRY_RECTS_MAX) else wide_rects):
            carried += 1
            run_len += 1
            fbad, fsoft, fres, ok, was_carried = [], False, False, True, True
        if not was_carried:
            seen_strict = seen_strict or fstrict
            if edge_soft:
                edge_soft_frames += 1          # S-27: uniform frames next to an appearing/disappearing element: counted, never an anchor
            if ok:
                run_len = 0
                if fstrict and not others and not edge_soft:     # S-26: only a STRICTLY verified frame can anchor a carry
                    anchor = fr
        if fstrict and not was_carried:
            strict_frames += 1
        if anym:
            masked_f.add(i)
        if fbad:
            bad_f.add(i)
            for f in fbad:
                if len(res["failures"]) < 25:
                    res["failures"].append(f)
        elif fsoft:
            soft_f.add(i)
            if len(res.get("soft_detail", [])) < 12:
                res.setdefault("soft_detail", []).append({"frame": i, "t_ms": round(times[i] * 1000), "kind": "soft"})
        elif fres:
            resync_f.add(i)
            if len(res.get("soft_detail", [])) < 12:
                res.setdefault("soft_detail", []).append({"frame": i, "t_ms": round(times[i] * 1000), "kind": "resync"})
    if n != len(times):
        raise Fail(EXIT_BUG, "decoded %d frames, the probe lists %d" % (n, len(times)))
    res.update(frames_total=n, frames_with_masks=len(masked_f | bad_f), frames_unmasked=len(bad_f),
               frames_soft=len(soft_f), frames_resynced=len(resync_f), frames_unverified=unverified, frames_carried=carried,
               strict_frames=strict_frames, frames_edge_soft=edge_soft_frames,
               leadin_end_ms=round(times[leadin_end + 1] * 1000) if leadin_end is not None and leadin_end + 1 < len(times) else None)
    return res


def cross_check(video, clip, log, t_flashes, t_page_epoch, scene_start, pill, mask_kind, budget_s=120,
                max_soft=0, max_resync=0, times=None):
    """Gate privacy_capture (6.4): pixel check on every logged and oracle rect, per frame. `log` = raw log entries
    (kinds masked/oracle; others ignored). If soft/resynced frames exceed the thresholds the alignment is
    re-calibrated once over a wider range (S-02: unstable alignment must not pass); the better pass is returned."""
    t_start = time.monotonic()
    times = times or frame_times(video)
    groups, _ticks, _unm = split_log(log)
    entries = sorted((e for es in groups.values() for e in es), key=lambda e: e["t"])
    if mask_kind == "blur":   # blur has no opaque colour/sentinel to check: masked is false for this style (R-07)
        res = _new_res(mask_kind)
        res["frames_total"] = len(times)
        return res
    ready_t = ready_time(groups, _ticks)
    epoch0, sync, delta = calibrate(video, clip, times, entries, t_flashes, t_page_epoch, scene_start, pill, budget_s)
    res = _pass(video, clip, times, groups, epoch0, ready_t, pill, budget_s, scene_start)
    recal = 0
    if res["frames_unmasked"] or res["frames_soft"] > max_soft or res["frames_resynced"] > max_resync:
        e2, s2, d2 = calibrate(video, clip, times, entries, t_flashes, t_page_epoch, scene_start, pill, budget_s,
                               rng=RECAL_MS, step=5, base=epoch0 - delta)
        if abs(e2 - epoch0) >= 5:
            res2 = _pass(video, clip, times, groups, e2, ready_t, pill, budget_s, scene_start)
            recal = 1
            worse = lambda r: (r["frames_unmasked"], r["frames_soft"] + r["frames_resynced"])  # noqa: E731
            if worse(res2) < worse(res):
                res, epoch0, sync, delta = res2, e2, s2 + "+recal", d2
    res.update(check_s=round(time.monotonic() - t_start, 2), recalibrated=bool(recal),
               sync={"method": sync, "epoch0_ms": epoch0, "refine_delta_ms": delta, "tolerance_ms": FRAME_TOL_MS})
    return res


# ------------------------------------------------------------------ unmaskable + safe_from
def aggregate_unmaskable(entries, epoch0, accepted=(), duration_ms=None, pad_ms=0):
    """Log entries kind 'unmaskable' -> contract list {surface, selector, reason, t_start, t_end (clip ms),
    bbox:[x,y,w,h] clip px, [accepted]} (one interval per surface/selector run, bbox = union)."""
    runs, open_ = [], {}
    for e in sorted(entries, key=lambda e: e["t"]):
        k = (e["surface"], e["selector"], e["reason"])
        r = open_.get(k)
        x, y, w, h = e["rect"]
        if r and e["t"] - r["_last"] <= UNM_GAP_MS:
            r["_last"] = e["t"]
            r["_box"] = [min(r["_box"][0], x), min(r["_box"][1], y), max(r["_box"][2], x + w), max(r["_box"][3], y + h)]
            r["t_end"] = round(e["t"] - epoch0)
        else:
            r = {"surface": e["surface"], "selector": e["selector"], "reason": e["reason"], "t_start": round(e["t"] - epoch0),
                 "t_end": round(e["t"] - epoch0), "_last": e["t"], "_box": [x, y, x + w, y + h]}
            open_[k] = r
            runs.append(r)
    out = []
    for r in runs:
        b = r.pop("_box")
        r.pop("_last")
        cap = duration_ms if duration_ms is not None else 1 << 62
        # S-23: detection runs at most every UNM_DETECT_MS after a mutation (250 ms poll otherwise): pad by that + a frame
        r["t_start"], r["t_end"] = min(max(r["t_start"] - pad_ms, 0), cap), min(max(r["t_end"] + pad_ms, 0), cap)
        r["bbox"] = [int(b[0] // 1), int(b[1] // 1), int(-(-b[2] // 1) - int(b[0] // 1)), int(-(-b[3] // 1) - int(b[1] // 1))]
        if r["selector"] in accepted or r["surface"] in accepted:
            r["accepted"] = True
        out.append(r)
    return out


# ------------------------------------------------------------------ config / spec
def parse_viewport(s):
    m = re.fullmatch(r"(\d+)x(\d+)", s or "")
    if not m:
        raise Fail(EXIT_INPUT, "bad --viewport %r (want WxH)" % s)
    return {"width": int(m.group(1)), "height": int(m.group(2))}


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise Fail(EXIT_INPUT, "cannot read %s %s: %s" % (what, path, e))


def slug_dir(slug):
    """Project folder of --slug (nearest .demo/<slug> above cwd, else ./.demo/<slug>)."""
    try:
        return os.path.dirname(project.project_path(type("A", (), {"project": None, "slug": slug})()))
    except project.CliError:
        return os.path.abspath(os.path.join(".demo", slug))


def privacy_of(slug):
    """demo.yaml `privacy` of the project, {} when there is no demo.yaml."""
    p = os.path.join(slug_dir(slug), "demo.yaml")
    if not os.path.exists(p):
        return {}
    try:
        import config
        return config.load_config(p).get("privacy", {})
    except Exception as e:  # noqa: BLE001 - config.CliError: invalid demo.yaml is bad input
        raise Fail(EXIT_INPUT, "demo.yaml: %s" % getattr(e, "msg", e))


def build_mask(a):
    cfg = load_json(a.config, "config") if a.config else {}
    priv = privacy_of(a.slug) if a.slug else {}
    style = cfg.get("mask_style") or {"opaque": "solid"}.get(priv.get("mask_style"), priv.get("mask_style")) or "solid"
    mask = {"enabled": not a.no_mask and priv.get("capture_mask", True),
            "selectors": list(cfg.get("selectors", [])) + list(priv.get("selectors", [])) + (a.selector or []),
            "regexes": list(cfg.get("regexes", [])) + list(priv.get("regexes", [])) + (a.regex or []),
            "mask_style": style}
    for k in ("force_overlay", "force_style_element"):
        if cfg.get(k) or getattr(a, k, False):
            mask[k] = True
    if not isinstance(mask["mask_style"], (str, dict)):
        raise Fail(EXIT_INPUT, "mask_style must be a string or object")
    return mask


def style_of(mask):
    st = mask["mask_style"]
    kind = st if isinstance(st, str) else st.get("kind", "solid")
    pill = hex_rgb(DEFAULT_PILL if isinstance(st, str) else st.get("color", DEFAULT_PILL))
    return kind, pill


redact_url = rbm.redact_url      # shared helpers (run_bounded): URL query/credentials, --regex/--url flags incl. abbreviations
redact_argv = rbm.redact_argv


def public_spec(spec):
    """Spec for dry-run output: regex literals and the URL query are never printed."""
    s = json.loads(json.dumps(spec))
    s["mask"]["regexes"] = ["<regex:%d chars>" % len(r if isinstance(r, str) else r.get("source", "")) for r in spec["mask"]["regexes"]]
    s["url"] = redact_url(s["url"])
    return s


# ------------------------------------------------------------------ gate
def gate(clip_path, log_path, sync_path, scene, mask, accepted=(), max_soft=0, max_resync=0, budget_s=120):
    """Verify one clip from files only. Returns the result dict; res['gate_fail'] lists the reasons (empty = pass)."""
    need_tools(adapter=False)
    if not os.path.isfile(clip_path):
        raise Fail(EXIT_INPUT, "clip not found: %s" % clip_path)
    sync = load_json(sync_path, "sync") if sync_path else {}
    probe = probe_clip(clip_path)
    clip = {k: probe[k] for k in ("w", "h", "fps", "duration_ms")}
    times = probe["times"]
    kind, pill = style_of(mask)
    reasons = []
    enabled = bool(mask["enabled"])
    entries = load_log(log_path) if (log_path and os.path.isfile(log_path)) else None
    groups, ticks, unm = split_log(entries or [])
    vp = sync.get("viewport") or {}
    if vp and (vp.get("width"), vp.get("height")) != (clip["w"], clip["h"]):
        reasons.append("viewport_ne_clip_size")
    res = _new_res(kind)
    res["frames_total"] = len(times)
    epoch0 = None
    scene_start = sync.get("scene_start_epoch")
    if enabled:
        if not entries or (not ticks and not groups):
            reasons.append("mask_log_missing_or_empty")
        elif not scene_start:
            reasons.append("sync_missing_scene_start")
        elif "viewport_ne_clip_size" not in reasons:
            res = cross_check(clip_path, clip, [e for e in entries if e.get("kind") in ("masked", "oracle", "tick")], sync.get("t_flashes"),
                              sync.get("t_page_epoch"), scene_start, pill, kind, budget_s, max_soft, max_resync, times)
            epoch0 = (res.get("sync") or {}).get("epoch0_ms")
            any_rects = any(e["rects"] for es in groups.values() for e in es)   # something sensitive was on screen
            if kind != "blur":
                if any_rects and res["rect_checks"] == 0:
                    reasons.append("no_rect_pixel_checked")
                if any_rects and res["strict_frames"] == 0 and res["rect_checks"] > 0:
                    reasons.append("no_strict_evidence")     # S-20: soft/unverified through the last frame, never one strict match
                if res["frames_unmasked"]:
                    reasons.append("frames_unmasked")
                # S-17: a regex hit seen by the page's own assertions must have produced log entries
                seen = set()
                for k in ("preflight", "inline", "final"):
                    seen |= set(((sync.get(k) or {}).get("regex_labels")) or [])
                missing = sorted(l for l in seen if l not in groups)
                if missing:
                    reasons.append("regex_hits_not_logged")
                    res["regex_labels_missing"] = missing
                if res["frames_soft"] > max_soft:
                    reasons.append("soft_frames_over_threshold")
                if res["frames_resynced"] > max_resync:
                    reasons.append("alignment_unstable")
    if epoch0 is None:
        epoch0 = sync.get("t_page_epoch") or 0
    first_t = ready_time(groups, ticks)
    safe_from = None
    if enabled and first_t is not None:
        safe_from = next((round(tv * 1000) for tv in times if epoch0 + tv * 1000.0 >= first_t - FRAME_TOL_MS), None)
        if safe_from is not None and res.get("leadin_end_ms"):
            safe_from = max(safe_from, res["leadin_end_ms"])
    unmaskable = aggregate_unmaskable(unm, epoch0, accepted, clip["duration_ms"], UNM_PAD_MS) if enabled else []
    offset_ms = round(scene_start - epoch0) if scene_start else 0
    if enabled and kind != "blur" and "mask_log_missing_or_empty" not in reasons and (safe_from is None or safe_from > offset_ms):
        reasons.append("scene_start_before_safe_from")   # S-06: the scene must start on verified frames
    live_unm = [u for u in unmaskable if not u.get("accepted")]
    blocking = [r for r in reasons]
    masked = bool(enabled and kind != "blur" and not blocking and not live_unm)
    res.update(thresholds={"max_soft": max_soft, "max_resync": max_resync, "accepted_unmaskable": sorted(accepted)},
               clip=clip, reasons=reasons, gate_fail=blocking, masked=masked, unmaskable=unmaskable, offset_ms=offset_ms,
               safe_from_ms=safe_from, mask_kind=kind, enabled=enabled, ticks=len(ticks), scene_ms=
               round(sync.get("scene_end_epoch", 0) - scene_start) if scene_start else None)
    res["tail_ms"] = clip["duration_ms"] - offset_ms - (res["scene_ms"] or 0) if res["scene_ms"] is not None else None
    return res


def clip_record(rel_file, g, mask, sync_rel, log_rel, mode):
    kind = g["mask_kind"]
    status = ("failed" if g["gate_fail"] else "needs-input" if [u for u in g["unmaskable"] if not u.get("accepted")]
              else "blur-only" if kind == "blur" else "unmasked" if not g["enabled"] else "verified")
    c = g["clip"]
    return {"file": rel_file, "w": c["w"], "h": c["h"], "fps": c["fps"], "scale": 1.0, "offset_ms": g["offset_ms"],
            "duration_ms": c["duration_ms"], "masked": g["masked"], "safe_from_ms": g["safe_from_ms"],
            "unmaskable": g["unmaskable"], "mask_log": log_rel, "sync": sync_rel,
            "mask": {"mode": mode, "style": kind, "status": status, "frames_unmasked": g["frames_unmasked"],
                     "frames_total": g["frames_total"], "frames_with_masks": g["frames_with_masks"],
                     "rects_checked": g["rect_checks"], "oracle_rects_checked": g["oracle_rect_checks"],
                     "frames_soft": g["frames_soft"], "frames_resynced": g["frames_resynced"], "frames_edge_soft": g.get("frames_edge_soft", 0), "thresholds": g["thresholds"],
                     "reasons": g["reasons"], "selectors": mask["selectors"], "n_regex": len(mask["regexes"])}}


# ------------------------------------------------------------------ #events
def _project_file(slug):
    path = project.project_path(type("A", (), {"project": None, "slug": slug})())
    if not os.path.exists(path):
        raise Fail(EXIT_INPUT, "no project.json for slug %r: run project.py --slug %s init first" % (slug, slug))
    return path


def write_events(slug, clip_rec, scene, markers=None, timeout=10.0):
    """Merge this scene's clip (+ markers when given) into project.json#events as capture-operator; other scenes stay."""
    try:
        path = _project_file(slug)
        old = project.read_project(path).get("events")
        old = old if isinstance(old, dict) else {}
        merged = dict(old, schema=1, platform="web")
        merged["clips"] = dict(old.get("clips") or {}, **{scene: clip_rec})
        c = clip_rec
        merged["bbox_space"] = {"unit": "px", "frame": [c["w"], c["h"]], "scale": 1.0, "origin": [0, 0]}
        if markers is not None:
            masked = c["masked"]
            merged["markers"] = [m for m in old.get("markers") or [] if m.get("scene") != scene] + \
                [dict(m, scene=scene, **({"masked": masked} if m.get("type") == "sensitive" else {})) for m in markers]
        return project.store_key(path, "events", project.OWNERS["events"], merged, timeout)
    except project.CliError as e:
        raise Fail(EXIT_INPUT if e.code == 2 else EXIT_BUG, "project.json: %s" % e.msg)


def invalidate_events(slug, scene, reason, timeout=10.0):
    """S-03: a failed (re-)shoot must never leave masked:true behind for the scene."""
    try:
        path = project.project_path(type("A", (), {"project": None, "slug": slug})())
        if not os.path.exists(path):
            return None
        old = project.read_project(path).get("events")
        clips = (old or {}).get("clips") or {}
        if scene not in clips:
            return None
        c = dict(clips[scene], masked=False, safe_from_ms=None)
        c["mask"] = dict(c.get("mask") or {}, status="failed", reasons=[reason])
        merged = dict(old, clips=dict(clips, **{scene: c}))
        return project.store_key(path, "events", project.OWNERS["events"], merged, timeout)
    except (project.CliError, OSError):
        return None


# ------------------------------------------------------------------ run
def _rm(path):
    shutil.rmtree(path, ignore_errors=True)


def spawn_adapter(spec, tmp_dir, label, wall, retries=2):
    """Run web_adapter.py bounded; the spec (regexes, typed-text safe) is a 0600 file in a private temp dir."""
    sdir = tempfile.mkdtemp(prefix="dscap-")
    try:
        sp = os.path.join(sdir, "spec.json")
        fd = os.open(sp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(spec, f)
        attempt = 0
        while True:
            attempt += 1
            _rm(tmp_dir)
            r = rbm.run_bounded([sys.executable, ADAPTER, sp], wall=wall, stall=30, label="capture:" + label,
                                heartbeat="jsonl", tail_bytes=4000000)
            lines = [x for x in r["stdout_tail"].splitlines() if x.strip().startswith("{")]
            try:
                rec = json.loads(lines[-1]) if lines else {"status": "error", "error": "no adapter output"}
            except ValueError:
                rec = {"status": "error", "error": "unreadable adapter output"}
            if r["status"] in ("wall", "stall"):
                raise Fail(EXIT_BUDGET, "adapter killed (%s)" % r["status"], adapter=_slim(rec))
            rc = r["tool_rc"] if r["status"] == "ok" else EXIT_BUG
            if rc == 70 and attempt <= retries:
                continue
            return rc, rec, attempt
    finally:
        _rm(sdir)


def _slim(rec):
    return {k: rec.get(k) for k in ("status", "reason", "error", "error_class", "at", "preflight", "inline") if k in rec}


def build_spec(a):
    mask = build_mask(a)
    out_dir = a.out_dir or (os.path.join(slug_dir(a.slug), "media") if a.slug else None)
    if not a.url or not out_dir:
        raise Fail(EXIT_INPUT, "--url and --out-dir (or --slug) are required")
    if a.scene_script and not os.path.isfile(a.scene_script):
        raise Fail(EXIT_INPUT, "scene script not found: %s" % a.scene_script)
    return {"url": a.url, "viewport": parse_viewport(a.viewport), "out_dir": os.path.abspath(out_dir), "scene": a.scene,
            "scene_script": os.path.abspath(a.scene_script) if a.scene_script else None, "vo_ms": a.vo_ms,
            "mask": mask, "probes": a.probe or [], "preflight": True,
            "timeouts": {"load_ms": int(a.load_s * 1000), "assert_ms": int(a.assert_s * 1000),
                         "step_ms": int(a.step_s * 1000), "total_ms": int(a.total_s * 1000)}}


def cmd_run(a):
    t0 = time.monotonic()
    spec = build_spec(a)
    if a.dry_run:
        return EXIT_OK, {"status": "ok", "dry_run": True, "spec": public_spec(spec)}
    need_tools()
    out_dir, sid, mask = spec["out_dir"], spec["scene"], spec["mask"]
    os.makedirs(out_dir, exist_ok=True)
    for d in os.listdir(out_dir):               # leftovers of a killed earlier run of this scene
        if d.startswith(".tmp-" + sid + "-"):
            _rm(os.path.join(out_dir, d))
    tmp = os.path.join(out_dir, ".tmp-%s-%d" % (sid, os.getpid()))
    spec["tmp_dir"] = tmp
    old_term = signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # finally blocks (temp cleanup) run on TERM
    try:
        wall = spec["timeouts"]["total_ms"] / 1000.0 + 30
        try:
            rc, rec, attempts = spawn_adapter(spec, tmp, sid, wall)
        except Fail as f:
            if a.slug:
                invalidate_events(a.slug, sid, "capture_failed:" + f.msg)
            raise
        if rc != 0:
            if a.slug:
                invalidate_events(a.slug, sid, "adapter_exit_%d" % rc)
            status = {EXIT_LEAK: "leak", EXIT_BUDGET: "incomplete", EXIT_INPUT: "input", EXIT_STEP: "step"}.get(rc, "bug")
            raise Fail(rc if rc in (EXIT_LEAK, EXIT_BUDGET, EXIT_INPUT, EXIT_STEP) else EXIT_BUG,
                       rec.get("reason") or rec.get("error", "adapter failed rc=%s" % rc), adapter=_slim(rec), attempts=attempts,
                       adapter_status=status)
        res = finish_run(a, spec, rec, tmp, t0, attempts)
        return res
    finally:
        signal.signal(signal.SIGTERM, old_term)
        _rm(tmp)


def finish_run(a, spec, rec, tmp, t0, attempts):
    sid, out_dir, mask = spec["scene"], spec["out_dir"], spec["mask"]
    sync = load_json(rec["sync"], "sync")
    g = gate(rec["video"], rec["mask_log"], rec["sync"], sid, mask, tuple(a.accept_unmaskable or ()), a.max_soft, a.max_resync)
    live_unm = [u for u in g["unmaskable"] if not u.get("accepted")]
    if g["gate_fail"]:
        if a.slug:
            invalidate_events(a.slug, sid, ",".join(g["gate_fail"]))
        return EXIT_LEAK, _result(a, g, rec, sync, attempts, t0, "leak", video=None)
    base = slug_dir(a.slug) if a.slug else None
    final = os.path.join(out_dir, sid + ".raw.webm")
    logp, syncp = os.path.join(out_dir, sid + ".mask.jsonl"), os.path.join(out_dir, sid + ".sync.json")
    pairs = [(rec["video"], final), (rec["mask_log"], logp), (rec["sync"], syncp)]
    if rec.get("probe_log"):
        pairs.append((os.path.join(tmp, sid + ".probe.jsonl"), os.path.join(out_dir, sid + ".probe.jsonl")))
    bak = os.path.join(tmp, "bak")
    os.makedirs(bak, exist_ok=True)
    moved = []
    try:
        for src, dst in pairs:     # S-25: keep the previous files until #events is written; roll back on any failure
            if os.path.exists(dst):
                os.replace(dst, os.path.join(bak, os.path.basename(dst)))
            moved.append(dst)
            os.replace(src, dst)
        if rec.get("probe_log"):
            rec["probe_log"] = pairs[-1][1]
        rel = lambda f: os.path.relpath(f, base).replace(os.sep, "/") if base and f.startswith(base + os.sep) else f  # noqa: E731
        mode = (sync.get("mask_mode") or None)
        crec = clip_record(rel(final), g, mask, rel(syncp), rel(logp), mode)
        res = _result(a, g, rec, sync, attempts, t0, "needs-input" if live_unm else "ok", video=final)
        res["mask_log"], res["sync"] = logp, syncp
        if a.slug:
            res["project_events_version"] = write_events(a.slug, crec, sid, sync.get("markers") or [])
        else:
            ev = {"schema": 1, "platform": "web", "clips": {sid: crec},
                  "bbox_space": {"unit": "px", "frame": [g["clip"]["w"], g["clip"]["h"]], "scale": 1.0, "origin": [0, 0]},
                  "markers": [dict(m, scene=sid, **({"masked": g["masked"]} if m.get("type") == "sensitive" else {})) for m in sync.get("markers") or []],
                  "retries": attempts - 1}
            evp = os.path.join(out_dir, sid + ".events.json")
            with open(evp, "w", encoding="utf-8") as f:
                json.dump(ev, f, indent=1)
            res["events"] = evp
    except BaseException:
        for dst in moved:
            try:
                os.remove(dst)
            except OSError:
                pass
            b0 = os.path.join(bak, os.path.basename(dst))
            if os.path.exists(b0):
                os.replace(b0, dst)
        if a.slug:
            invalidate_events(a.slug, sid, "events_write_failed")
        raise
    res["clip_record"] = crec
    return (EXIT_LEAK if live_unm else EXIT_OK), res


def _result(a, g, rec, sync, attempts, t0, status, video):
    res = {"status": status, "elapsed_s": round(time.monotonic() - t0, 2), "video": video, "clip": g["clip"],
           "masked": g["masked"], "offset_ms": g["offset_ms"], "scene_ms": g["scene_ms"], "tail_ms": g["tail_ms"],
           "safe_from_ms": g["safe_from_ms"], "gate_fail": g["gate_fail"], "unmaskable": g["unmaskable"],
           "cross_check": {k: g.get(k) for k in ("frames_total", "frames_with_masks", "frames_unmasked", "rect_checks",
                                                 "oracle_rect_checks", "rects_failed", "frames_soft", "frames_resynced",
                                                 "rects_skipped_proven", "frames_unverified", "frames_carried", "strict_frames", "frames_edge_soft", "leadin_end_ms", "soft_detail", "rects_uniform_nopill", "failures", "sync", "check_s",
                                                 "recalibrated")},
           "assertion": {k: _brief(sync.get(k)) for k in ("preflight", "inline", "final")},
           "overhead": sync.get("perf"), "probe_log": rec.get("probe_log"), "retries": attempts - 1,
           "calibration": {"t_flashes": sync.get("t_flashes"), "t_page_epoch": sync.get("t_page_epoch"),
                           "scene_start_epoch": sync.get("scene_start_epoch")}}
    res["failures"] = []
    if g["gate_fail"]:
        res["failures"] = [{"id": "privacy_capture", "owner": "capture-operator", "class": "leak", "reasons": g["gate_fail"]}]
    elif [u for u in g["unmaskable"] if not u.get("accepted")]:
        res["failures"] = [{"id": "privacy_capture", "owner": "privacy-blurrer", "class": "unmaskable"}]
    return res


def _brief(a):
    return None if not a else {"ok": a.get("ok"), "mode": a.get("mode"), "failures": a.get("failures")}


def cmd_gate(a):
    t0 = time.monotonic()
    mask = build_mask(a)
    sid = a.scene or (re.match(r"(s\d+)", os.path.basename(a.clip)) or [None, None])[1]
    if not sid:
        raise Fail(EXIT_INPUT, "--scene is required (cannot derive it from %s)" % a.clip)
    g = gate(a.clip, a.mask_log, a.sync, sid, mask, tuple(a.accept_unmaskable or ()), a.max_soft, a.max_resync)
    live_unm = [u for u in g["unmaskable"] if not u.get("accepted")]
    res = _result(a, g, {}, load_json(a.sync, "sync") if a.sync else {}, 1, t0, "leak" if g["gate_fail"] else "needs-input" if live_unm else "ok", video=a.clip)
    if a.slug:
        base = slug_dir(a.slug)
        rel = lambda f: os.path.relpath(os.path.abspath(f), base).replace(os.sep, "/") if f else None  # noqa: E731
        crec = clip_record(rel(a.clip), g, mask, rel(a.sync), rel(a.mask_log), (res["assertion"].get("final") or {}).get("mode"))
        res["project_events_version"] = write_events(a.slug, crec, sid)
        res["clip_record"] = crec
    return (EXIT_LEAK if (g["gate_fail"] or live_unm) else EXIT_OK), res


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], allow_abbrev=False)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--slug")
        p.add_argument("--scene", default=None)
        p.add_argument("--config")
        p.add_argument("--selector", action="append")
        p.add_argument("--regex", action="append")
        p.add_argument("--accept-unmaskable", dest="accept_unmaskable", action="append",
                       help="selector description or surface of an unmaskable item a person has accepted (listed, not blocking)")
        p.add_argument("--max-soft", dest="max_soft", type=int, default=0, help="soft (uniform, not mask-coloured) frames tolerated; default 0")
        p.add_argument("--max-resync", dest="max_resync", type=int, default=0, help="resynced frames tolerated; default 0")
        p.add_argument("--no-mask", action="store_true", help="record without mask (positive control only)")

    r = sub.add_parser("run", allow_abbrev=False)
    common(r)
    r.set_defaults(scene="s01")
    r.add_argument("--url")
    r.add_argument("--out-dir")
    r.add_argument("--scene-script")
    r.add_argument("--vo-ms", type=int, default=0)
    r.add_argument("--probe", action="append")
    r.add_argument("--viewport", default="1280x720")
    r.add_argument("--force-overlay", dest="force_overlay", action="store_true")
    r.add_argument("--force-style-element", dest="force_style_element", action="store_true")
    r.add_argument("--load-s", type=float, default=15)
    r.add_argument("--assert-s", type=float, default=5)
    r.add_argument("--step-s", type=float, default=15)
    r.add_argument("--total-s", type=float, default=90)
    r.add_argument("--dry-run", action="store_true")
    g = sub.add_parser("gate", allow_abbrev=False)
    common(g)
    g.add_argument("--clip", required=True)
    g.add_argument("--mask-log", dest="mask_log", required=True)
    g.add_argument("--sync", required=True)
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_INPUT if e.code else 0
    t0 = time.monotonic()
    try:
        code, res = cmd_run(a) if a.cmd == "run" else cmd_gate(a)
    except Fail as f:
        code = f.code
        res = dict({"status": {EXIT_LEAK: "leak", EXIT_BUDGET: "incomplete", EXIT_INPUT: "input", EXIT_TOOL: "missing-tool",
                               EXIT_STEP: "step"}.get(f.code, "bug"), "error": f.msg}, **f.extra)
        res["failures"] = [{"id": "privacy_capture" if f.code == EXIT_LEAK else "capture", "owner": "scene-automator" if f.code == EXIT_STEP else "capture-operator",
                            "class": {EXIT_LEAK: "leak", EXIT_BUG: "bug", EXIT_STEP: "step"}.get(f.code, "finding")}]
    except Exception as e:  # noqa: BLE001 - top-level handler: exit 70, never Python's 1
        code, res = EXIT_BUG, {"status": "bug", "error": "%s: %s" % (type(e).__name__, e),
                               "failures": [{"id": "capture", "owner": "plugin", "class": "bug"}]}
    res.setdefault("elapsed_s", round(time.monotonic() - t0, 2))
    print(json.dumps(res))
    if getattr(a, "slug", None):
        d = slug_dir(a.slug)
        if os.path.isdir(d):
            rbm.append_run(d, "capture.py", argv, dict(res, status=res.get("status")))
    return code


if __name__ == "__main__":
    sys.exit(rbm.guard_main(main))
