#!/usr/bin/env python3
"""capture.py - web capture with capture-time masking (redesign 4.2 / 6.2 / 6.4, ticket P0-B).

Orchestrates the Node Playwright recorder (capture_recorder.js), which injects privacy_mask.js, asserts
that every SENSITIVE selector present is masked (fail-closed, in a non-recording preflight and again
before the scene starts), records with recordVideo, and writes the mask log. This script then:
  * probes the clip (ffprobe), calibrates log time -> video time (calibration flash at clip start),
  * cross-checks pixels at every logged rect (gate `privacy_capture`): interior must be the opaque mask
    colour (low variance, no glyph edges); box overlays must also show the 1 px sentinel border,
  * writes an #events-compatible JSON (`clips.<sid>.masked`, `unmaskable[]`) and prints ONE JSON line.

  capture.py --url URL --scene s03 --out-dir DIR [--config mask.json | --selector S ... --regex R ...]
             [--actions actions.json] [--viewport 1280x720] [--probe SEL ...] [--no-mask] [--dry-run]
             [--slug S]   (default out dir .demo/<S>/media; runs.jsonl line appended if .demo/<S>/ exists)

mask.json: {"selectors":[...], "regexes":[...], "mask_style":"solid"|"blur"|{color,sentinel,blur_px}}.
Exit codes (shared table, 4.2): 0 ok | 2 bad input | 3 over budget (incomplete) | 4 missing tool |
11 leak (assertion failed or pixel cross-check failed) | 70 unexpected/env error (retried <= 2 first).
Bounded: every recorder wait has a timeout, the recorder is killed as a process group on wall/stall.
Dependency note: run_bounded.py (other ticket) is not imported; an internal group-killing runner with the
same semantics (wall + heartbeat stall, TERM -> KILL on the group) is used so this works stand-alone.
"""
import argparse
import bisect
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDER = os.path.join(HERE, "capture_recorder.js")

EXIT_OK, EXIT_INPUT, EXIT_BUDGET, EXIT_TOOL, EXIT_LEAK, EXIT_BUG = 0, 2, 3, 4, 11, 70

DEFAULT_PILL = "#9aa3b2"
STD_MAX = 12.0          # max per-channel std-dev inside a masked rect (VP8 noise tolerated, glyph edges are not)
COLOR_TOL = 34          # max per-channel |mean - pill| (VP8 chroma shift)
SENTINEL_DROP = 20.0    # box ring must be this much darker (luma) than the interior
FRAME_TOL_MS = 90.0     # log entry <-> frame match window (~2 frames at 25 fps: measured screencast jitter during fast scroll)
LEADIN_TOL_MS = 250.0   # clip start to scene start (calibration pulses + page load): layout and screencast lag are loose
GAP_MS = 120.0
EDGE_GRACE_MS = 50.0    # +-1 frame around the first log entry of an element run (appearance)
WIDE_TOL_MS = 260.0     # fallback window when screencast frame stamps lag the page clock (counted as frames_resynced)
REFINE_MS = 120         # calibration refine range (+-) around the pulse-based offset          # log gap (same selector, rects on both sides) longer than this = missing entries


class Fail(Exception):
    def __init__(self, code, msg, **extra):
        super().__init__(msg)
        self.code, self.msg, self.extra = code, msg, extra


# ------------------------------------------------------------------ bounded subprocess
def run_group(cmd, wall_s, stall_s=None, on_stderr=None, capture_stdout=True):
    """Run cmd in its own process group. Kill the group on wall timeout or heartbeat stall.
    Returns (rc, stdout_bytes, reason) with reason in (None, 'wall', 'stall')."""
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True)
    state = {"last": time.monotonic(), "reason": None}

    def _kill(reason):
        state["reason"] = reason
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.killpg(p.pid, 0)
            except ProcessLookupError:
                return
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _err():
        for line in iter(p.stderr.readline, b""):
            state["last"] = time.monotonic()
            if on_stderr:
                on_stderr(line)

    te = threading.Thread(target=_err, daemon=True)
    te.start()
    out = []

    def _out():
        out.append(p.stdout.read())

    to = threading.Thread(target=_out, daemon=True)
    to.start()
    t0 = time.monotonic()
    while p.poll() is None:
        time.sleep(0.1)
        if time.monotonic() - t0 > wall_s:
            _kill("wall")
            break
        if stall_s and time.monotonic() - state["last"] > stall_s:
            _kill("stall")
            break
    p.wait()
    to.join(5)
    te.join(2)
    return p.returncode, (out[0] if out else b""), state["reason"]


def _fwd_stderr(line):
    """Forward recorder heartbeats (JSON lines) to our stderr."""
    try:
        sys.stderr.write(line.decode(errors="replace"))
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 - stderr may be captured/closed (tests, pipes)
        pass


def need_tools():
    missing = []
    if not shutil.which("node"):
        missing.append("node")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        missing.append("ffmpeg")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    if missing:
        raise Fail(EXIT_TOOL, "missing tools: " + ", ".join(missing), feature="capture", missing=missing)


# ------------------------------------------------------------------ video helpers
def ffprobe_clip(path):
    rc, out, _ = run_group(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,r_frame_rate,avg_frame_rate:format=duration", "-of", "json", path], 30)
    if rc != 0:
        raise Fail(EXIT_BUG, "ffprobe failed on " + path)
    j = json.loads(out)
    s = j["streams"][0]
    num, den = (s.get("avg_frame_rate") or "25/1").split("/")
    fps = float(num) / float(den) if float(den) else 25.0
    return {"w": s["width"], "h": s["height"], "fps": round(fps, 3), "duration_ms": round(float(j["format"]["duration"]) * 1000)}


def frame_times(path):
    rc, out, _ = run_group(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "frame=best_effort_timestamp_time", "-of", "csv=p=0", path], 60)
    if rc != 0:
        raise Fail(EXIT_BUG, "ffprobe frames failed")
    return [float(x) for x in out.decode().split() if x.strip()]


def iter_frames(path, w, h, wall_s):
    """Yield (index, ndarray HxWx3 uint8) decoded once, sequentially, in a killable group."""
    import numpy as np
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0", "-fps_mode", "passthrough",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    timer = threading.Timer(wall_s, lambda: os.killpg(p.pid, signal.SIGKILL))
    timer.start()
    n = w * h * 3
    i = 0
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            yield i, np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        timer.cancel()
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait()


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
    inset = 2 if (x1 - x0 >= 8 and y1 - y0 >= 8) else 1 if (x1 - x0 >= 4 and y1 - y0 >= 4) else 0
    ix0, iy0, ix1, iy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    if ix1 - ix0 < 1 or iy1 - iy0 < 1:
        return "rect_too_small"
    reg = frame[iy0:iy1, ix0:ix1].reshape(-1, 3).astype(np.float32)
    mean, std = reg.mean(0), reg.std(0)
    if float(std.max()) > STD_MAX:
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


# ------------------------------------------------------------------ cross-check
def load_log(path):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    entries.sort(key=lambda e: e["t"])
    return entries


def _entry_ok(fr, e, pill):
    """True if every non-partial rect of log entry e shows the mask in frame fr."""
    if e.get("state") != "masked":
        return False
    for ri, r in enumerate(e["rects"]):
        if ri in (e.get("partial") or []):
            continue
        if check_rect(fr, r, pill, ri in (e.get("boxes") or [])):
            return False
    return True


def eval_group(fr, cands, te, narrow, pill, res, lead=False):
    """Verdict for one selector group in one frame, from the log entries near it (cands).
    strict = mask colour (and sentinel for boxes) seen at every logged rect of some entry within `narrow` ms;
    resync = same but only for an entry further away (screencast stamp lag; counted);
    soft   = rects uniform but not mask-coloured everywhere (page/toast not painted yet, no glyph to read);
    empty  = nothing logged on screen near this frame; bad = glyph edges / wrong colour / state unmasked."""
    cands = sorted(cands, key=lambda e: abs(e["t"] - te))
    near = [e for e in cands if abs(e["t"] - te) <= narrow]
    if not near or not near[0]["rects"] or not any(e["rects"] for e in near):
        return "empty", None, None   # log says nothing is on screen near this frame (or the element is only about to appear)
    if lead and any(not e["rects"] for e in near):
        return "empty", None, None   # lead-in: the first rAF entries come from a half-parsed layout, so a nearby empty entry wins
    soft, last = False, ("no_entry_with_rects", None)
    for e in cands:
        if not e["rects"]:
            continue
        if e.get("state") != "masked":
            last = ("state_unmasked", None)
            continue
        e_soft, bad = False, None
        for ri, r in enumerate(e["rects"]):
            if ri in (e.get("partial") or []):
                res["rects_skipped_partial"] += 1
                continue
            res["rect_checks"] += 1
            why = check_rect(fr, r, pill, ri in (e.get("boxes") or []))
            if why is None:
                continue
            if why.startswith("interior_not_mask_colour"):
                e_soft = True
                res["rects_uniform_nopill"] += 1
                continue
            bad = (why, r)
            res["rects_failed"] += 1
            break
        if bad:
            last = bad
        elif not e_soft:
            return ("strict" if abs(e["t"] - te) <= narrow else "resync"), None, None
        else:
            soft = True
    if soft:
        return "soft", None, None
    if any(e.get("_start") and abs(e["t"] - te) <= EDGE_GRACE_MS for e in cands):
        res["frames_edge_grace"] += 1   # an element appears within one frame of this one: its first mask paint is not resolvable
        return "empty", None, None
    return "bad", last[0], last[1]


def calibrate(video, clip, times, log, t_flashes, t_page_epoch, scene_start, pill, budget_s):
    """Map rAF epoch ms -> video time. Coarse: first calibration pulse. Refine (+-REFINE_MS) on in-scene frames
    by agreement between log rects and pixels: the video clock lags/leads the page clock by tens of ms and the
    pulse edges alone are not accurate enough for fast scroll. One global scalar: it cannot hide a frame that
    is unmasked (such a frame fails at every offset)."""
    first = None
    for i, fr in iter_frames(video, clip["w"], clip["h"], budget_s):
        c = fr[clip["h"] // 2, clip["w"] // 2]
        if c[0] > 200 and c[1] < 60 and c[2] > 200:
            first = i
            break
    if t_flashes and first is None:
        raise Fail(EXIT_BUG, "calibration flash not found in video (cannot align mask log)")
    base = (t_flashes[0] - times[first] * 1000.0) if t_flashes else t_page_epoch
    sel = [e for e in log if e["rects"] and e.get("state") == "masked"]
    ts = [e["t"] for e in sel]
    scene_frames = [i for i, tv in enumerate(times) if base + tv * 1000.0 > scene_start + 300]
    if not scene_frames or not sel:
        return base, "flash" if t_flashes else "page-start", 0
    want = set(scene_frames[:: max(1, len(scene_frames) // 70)])
    sample = {i: fr.copy() for i, fr in iter_frames(video, clip["w"], clip["h"], budget_s) if i in want}
    scores = {}
    for d in range(-REFINE_MS, REFINE_MS + 1, 10):
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


def cross_check(video, clip, log, t_flashes, t_page_epoch, scene_start, pill, mask_kind, budget_s=120):
    """Gate privacy_capture (6.4): pixel check on every logged rect, per frame. Returns dict."""
    t_start = time.monotonic()
    times = frame_times(video)
    by_sel = {}
    for e in log:
        by_sel.setdefault(e["selector"], []).append(e)
    for es in by_sel.values():   # run start = entry with rects whose predecessor has none (or a long gap)
        prev = None
        for e in es:
            if e["rects"] and (prev is None or not prev["rects"] or e["t"] - prev["t"] > GAP_MS):
                e["_start"] = True
            prev = e
    sel_t = {k: [e["t"] for e in es] for k, es in by_sel.items()}
    res = {"frames_total": 0, "frames_with_masks": 0, "frames_unmasked": 0, "rect_checks": 0,
           "rects_failed": 0, "frames_resynced": 0, "frames_edge_grace": 0, "frames_no_pill_evidence": 0, "rects_uniform_nopill": 0, "rects_skipped_partial": 0, "skipped_blur": mask_kind == "blur",
           "failures": [], "sync": None}
    if mask_kind == "blur":  # blur has no opaque colour/sentinel: only the DOM log + assertions gate it
        res["frames_total"] = len(times)
        return res
    epoch0, sync, delta = calibrate(video, clip, times, log, t_flashes, t_page_epoch, scene_start, pill, budget_s)
    unmasked_frames, masked_frames = set(), set()
    n_frames = 0
    for i, fr in iter_frames(video, clip["w"], clip["h"], budget_s):
        n_frames += 1
        if i >= len(times):
            raise Fail(EXIT_BUG, "frame count mismatch between ffprobe and ffmpeg")
        te = epoch0 + times[i] * 1000.0
        lead = te < scene_start + 150
        any_entry = False
        for sel, es in by_sel.items():
            ts = sel_t[sel]
            narrow = LEADIN_TOL_MS if lead else FRAME_TOL_MS
            lo, hi = bisect.bisect_left(ts, te - WIDE_TOL_MS), bisect.bisect_right(ts, te + WIDE_TOL_MS)
            cands = es[lo:hi]
            if not cands:
                k = bisect.bisect_left(ts, te)  # gap rule: rects logged on both sides but nothing near this frame
                if 0 < k < len(ts) and es[k - 1]["rects"] and es[k]["rects"] and ts[k] - ts[k - 1] > GAP_MS \
                        and ts[k - 1] > epoch0:
                    unmasked_frames.add(i)
                    if len(res["failures"]) < 25:
                        res["failures"].append({"frame": i, "t_ms": round(times[i] * 1000), "selector": sel, "reason": "log_gap"})
                continue
            verdict, why, rect = eval_group(fr, cands, te, narrow, pill, res, lead)
            if verdict != "empty":
                any_entry = True
            if verdict == "soft":
                res["frames_no_pill_evidence"] += 1
            elif verdict == "resync":
                res["frames_resynced"] += 1
            elif verdict == "bad":
                unmasked_frames.add(i)
                if len(res["failures"]) < 25:
                    f = {"frame": i, "t_ms": round(times[i] * 1000), "selector": sel, "reason": why}
                    if rect:
                        f["rect"] = rect
                    res["failures"].append(f)
        if any_entry:
            masked_frames.add(i)
    if n_frames != len(times):
        raise Fail(EXIT_BUG, "decoded %d frames, ffprobe lists %d" % (n_frames, len(times)))
    res.update(frames_total=n_frames, frames_with_masks=len(masked_frames | unmasked_frames),
               frames_unmasked=len(unmasked_frames), check_s=round(time.monotonic() - t_start, 2),
               sync={"method": sync, "epoch0_ms": epoch0, "refine_delta_ms": delta, "tolerance_ms": FRAME_TOL_MS})
    return res


# ------------------------------------------------------------------ main flow
def parse_viewport(s):
    m = re.fullmatch(r"(\d+)x(\d+)", s or "")
    if not m:
        raise Fail(EXIT_INPUT, "bad --viewport %r (want WxH)" % s)
    return {"width": int(m.group(1)), "height": int(m.group(2))}


def load_json(path, what):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise Fail(EXIT_INPUT, "cannot read %s %s: %s" % (what, path, e))


def build_spec(a):
    cfg = load_json(a.config, "config") if a.config else {}
    mask = {"enabled": not a.no_mask,
            "selectors": list(cfg.get("selectors", [])) + (a.selector or []),
            "regexes": list(cfg.get("regexes", [])) + (a.regex or []),
            "mask_style": cfg.get("mask_style", "solid")}
    for k in ("force_overlay", "force_style_element"):
        if cfg.get(k) or getattr(a, k):
            mask[k] = True
    if not isinstance(mask["mask_style"], (str, dict)):
        raise Fail(EXIT_INPUT, "mask_style must be a string or object")
    out_dir = a.out_dir or (os.path.join(".demo", a.slug, "media") if a.slug else None)
    if not a.url or not out_dir:
        raise Fail(EXIT_INPUT, "--url and --out-dir (or --slug) are required")
    actions = load_json(a.actions, "actions") if a.actions else []
    if not isinstance(actions, list):
        raise Fail(EXIT_INPUT, "actions must be a JSON list")
    total = int(a.total_s * 1000)
    return {"url": a.url, "viewport": parse_viewport(a.viewport), "out_dir": os.path.abspath(out_dir), "name": a.scene,
            "mask": mask, "actions": actions, "probes": a.probe or [], "preflight": True, "sync": True,
            "timeouts": {"load_ms": int(a.load_s * 1000), "assert_ms": int(a.assert_s * 1000),
                         "step_ms": int(a.step_s * 1000), "total_ms": total}}


def redact_argv(argv):
    out, redact = [], False
    for x in argv:
        if x.startswith("--regex="):
            x = "--regex=<redacted:%d>" % (len(x) - 8)
        out.append("<redacted:%d>" % len(x) if redact else x)
        redact = x == "--regex"
    return out


def append_run(slug, line):
    d = os.path.join(".demo", slug)
    if os.path.isdir(d):
        try:
            with open(os.path.join(d, "runs.jsonl"), "a") as f:
                f.write(json.dumps(line) + "\n")
        except OSError:
            pass


def run(a):
    t0 = time.monotonic()
    spec = build_spec(a)
    if a.dry_run:
        return EXIT_OK, {"status": "ok", "dry_run": True, "spec": spec}
    need_tools()
    os.makedirs(spec["out_dir"], exist_ok=True)
    spec_path = os.path.join(spec["out_dir"], spec["name"] + ".spec.json")
    with open(spec_path, "w") as f:
        json.dump(spec, f)
    wall = spec["timeouts"]["total_ms"] / 1000.0 + 30
    rec, attempt = None, 0
    while True:
        attempt += 1
        rc, out, why = run_group(["node", RECORDER, spec_path], wall, stall_s=30,
                                 on_stderr=_fwd_stderr)
        lines = [x for x in out.decode(errors="replace").splitlines() if x.strip().startswith("{")]
        rec = json.loads(lines[-1]) if lines else {"status": "error", "error": "no recorder output"}
        if why:
            raise Fail(EXIT_BUDGET, "recorder killed (%s)" % why, recorder=rec)
        if rc == 70 and attempt <= 2:
            continue
        break
    os.remove(spec_path)
    if rc == EXIT_LEAK:
        raise Fail(EXIT_LEAK, rec.get("reason", "mask assertion failed"), recorder=_slim(rec))
    if rc in (EXIT_BUDGET, EXIT_INPUT):
        raise Fail(rc, rec.get("error", "recorder failed"), recorder=_slim(rec))
    if rc != 0:
        raise Fail(EXIT_BUG, rec.get("error", "recorder failed rc=%s" % rc), recorder=_slim(rec), attempts=attempt)

    video = rec["video"]
    clip = ffprobe_clip(video)
    style = spec["mask"]["mask_style"]
    kind = style if isinstance(style, str) else style.get("kind", "solid")
    pill = hex_rgb(DEFAULT_PILL if isinstance(style, str) else style.get("color", DEFAULT_PILL))
    log = load_log(rec["mask_log"]) if spec["mask"]["enabled"] else []
    xc = {"frames_total": 0, "frames_with_masks": 0, "frames_unmasked": 0}
    if spec["mask"]["enabled"]:
        xc = cross_check(video, clip, log, rec.get("t_flashes"), rec.get("t_page_epoch"), rec["scene_start_epoch"], pill, kind)
    epoch0 = (xc.get("sync") or {}).get("epoch0_ms") or rec.get("t_page_epoch")
    offset_ms = round(rec["scene_start_epoch"] - epoch0)
    scene_ms = rec["scene_end_epoch"] - rec["scene_start_epoch"]
    final = rec.get("final") or {}
    masked = bool(spec["mask"]["enabled"] and xc["frames_unmasked"] == 0 and final.get("ok", False) and kind != "blur")
    unmask = final.get("unmaskable", [])
    events = {"schema": 1, "platform": "web",
              "clips": {a.scene: {"file": video, "w": clip["w"], "h": clip["h"], "fps": clip["fps"], "scale": 1.0,
                                  "offset_ms": offset_ms, "duration_ms": clip["duration_ms"], "masked": masked,
                                  "unmaskable": unmask, "mask_log": rec["mask_log"],
                                  "mask": {"mode": final.get("mode"), "style": kind, "frames_unmasked": xc["frames_unmasked"],
                                           "selectors": spec["mask"]["selectors"], "n_regex": len(spec["mask"]["regexes"])}}},
              "bbox_space": {"unit": "px", "frame": [clip["w"], clip["h"]], "scale": 1.0, "origin": [0, 0]},
              "markers": rec.get("markers", []), "retries": attempt - 1}
    ev_path = os.path.join(spec["out_dir"], spec["name"] + ".events.json")
    with open(ev_path, "w") as f:
        json.dump(events, f, indent=1)
    res = {"status": "ok" if (masked or not spec["mask"]["enabled"] or kind == "blur") and xc["frames_unmasked"] == 0 else "leak",
           "elapsed_s": round(time.monotonic() - t0, 2), "video": video, "events": ev_path, "mask_log": rec["mask_log"],
           "clip": clip, "offset_ms": offset_ms, "scene_ms": scene_ms, "tail_ms": clip["duration_ms"] - offset_ms - scene_ms,
           "masked": masked, "cross_check": xc, "assertion": {"preflight": _brief(rec.get("preflight")), "inline": _brief(rec.get("inline")),
                                                              "final": _brief(rec.get("final"))},
           "overhead": rec.get("perf"), "probe_log": rec.get("probe_log"),
           "calibration": {"t_flashes": rec.get("t_flashes"), "t_page_epoch": rec.get("t_page_epoch"),
                           "scene_start_epoch": rec["scene_start_epoch"]},
           "failures": []}
    code = EXIT_OK
    if res["status"] == "leak":
        code = EXIT_LEAK
        res["failures"] = [{"id": "privacy_capture", "owner": "capture-operator", "class": "leak"}]
    return code, res


def _brief(a):
    return None if not a else {"ok": a.get("ok"), "mode": a.get("mode"), "checked": a.get("checked"), "failures": a.get("failures")}


def _slim(rec):
    return {k: rec.get(k) for k in ("status", "reason", "error", "at", "preflight", "inline", "final") if k in rec}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url")
    ap.add_argument("--slug")
    ap.add_argument("--scene", default="s01")
    ap.add_argument("--out-dir")
    ap.add_argument("--config")
    ap.add_argument("--actions")
    ap.add_argument("--selector", action="append")
    ap.add_argument("--regex", action="append")
    ap.add_argument("--probe", action="append")
    ap.add_argument("--viewport", default="1280x720")
    ap.add_argument("--no-mask", action="store_true", help="record without mask (positive control only)")
    ap.add_argument("--force-overlay", dest="force_overlay", action="store_true")
    ap.add_argument("--force-style-element", dest="force_style_element", action="store_true")
    ap.add_argument("--load-s", type=float, default=15)
    ap.add_argument("--assert-s", type=float, default=5)
    ap.add_argument("--step-s", type=float, default=15)
    ap.add_argument("--total-s", type=float, default=90)
    ap.add_argument("--dry-run", action="store_true")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_INPUT if e.code else 0
    t0 = time.monotonic()
    try:
        code, res = run(a)
    except Fail as f:
        code, res = f.code, dict({"status": {EXIT_LEAK: "leak", EXIT_BUDGET: "incomplete", EXIT_INPUT: "input", EXIT_TOOL: "missing-tool"}.get(f.code, "bug"),
                                  "error": f.msg}, **f.extra)
        res["failures"] = [{"id": "privacy_capture" if f.code == EXIT_LEAK else "capture", "owner": "capture-operator",
                            "class": {EXIT_LEAK: "leak", EXIT_BUG: "bug"}.get(f.code, "finding")}]
    except Exception as e:  # noqa: BLE001 - top-level handler: exit 70, never Python's 1
        code, res = EXIT_BUG, {"status": "bug", "error": "%s: %s" % (type(e).__name__, e),
                               "failures": [{"id": "capture", "owner": "plugin", "class": "bug"}]}
    res.setdefault("elapsed_s", round(time.monotonic() - t0, 2))
    print(json.dumps(res))
    if a.slug:
        append_run(a.slug, {"argv": redact_argv(argv), "status": res.get("status"), "exit": code, "elapsed_s": res["elapsed_s"]})
    return code


if __name__ == "__main__":
    sys.exit(main())
