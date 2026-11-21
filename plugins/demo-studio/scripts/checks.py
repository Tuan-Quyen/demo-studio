#!/usr/bin/env python3
"""Render checks in code (docs/redesign §4.2, P0 subset): the ONLY writer of project.json#checks
(besides blur.py verify, which writes #checks.blur.<aspect>), through project.write_checks().

Usage:
  checks.py (--project PATH | --slug SLUG) [--only ID[,ID...]] [--media-dir DIR] [--renderer R]
            [--no-write] [--dry-run] [--json]
    ids: blur loudness black freeze captions length sync vo safe_start  (default: all)

Per rendered aspect (demo.yaml `formats`, files media/final-<aspect>.mp4) ONE combined ffmpeg pass
(ebur128 + blackdetect + freezedetect + silencedetect, ~3x faster than separate runs) through
run_bounded (wall 0.3 x duration + 60 s, stall 30 s). Checks:
  blur      aggregates #checks.blur.<aspect> written by `blur.py verify`: a verdict is `pass` only if
            it says pass AND every positive control is true AND it is bound to the exact final file
            (size, mtime_ns, ino) AND the #blur/#timeline/#events versions it was built on are still
            current; a failed control = inconclusive; a missing, unbound or stale verdict = incomplete
            (run blur.py verify again). Also incomplete: a clip with unmaskable[] no region covers.
  safe_start  no #timeline scene `in` before events.clips[sid].safe_from_ms (owner sync-editor).
  loudness  integrated LUFS vs targets.lufs +-1, true peak <= targets.true_peak, and vs #mix.preview
            (> 0.5 LU / 0.5 dB off = chain not reproducible, owner sound-mixer).
  black     black spans (>= 0.2 s) outside #motion.allow.black.   freeze  likewise (>= 3 s).
  captions  final.vtt lint: chars/line, lines/cue, cue length, order. Onset offset is reported
            (`onset_*`, phrase-level from silence ends) but does not gate: word onsets need the
            captions-check of media-specs.
  length    duration vs demo.yaml length_s +-10%.
  sync      total duration vs #timeline end (and audio vs video length) <= targets.max_drift_ms. Per-scene
            drift is not measurable from the file alone.
  vo        every #voice scene file passes vo.check (lead/trail/gaps).
Also aggregates events.clips.*.mask.frames_unmasked into #checks.privacy_capture; clips that capture did
not verify (masked false, mask_style blur, rect_checks 0) are listed as `uncaptured` and, with real data,
need a #blur region (else incomplete, owner privacy-blurrer).

`pass` is recomputed from scratch on every run from THIS run's results and the live blur verdicts: a
subset (`--only`) never inherits an old pass, and any REQUIRED check not run makes `pass` false. #checks
is rewritten (results of older runs dropped; blur.py's verdicts kept).

Result: one JSON line {"status": pass|fail|leak|incomplete, "pass", "elapsed_s", "results", "outputs",
"failures":[{"id","owner","class"}]}; a run line goes to .demo/<slug>/runs.jsonl.
Exit codes: 0 pass | 2 input wrong (project, demo.yaml, missing final video) | 3 incomplete (blur verdict
missing/stale/incomplete, ffmpeg over budget, or `pass` false for a missing required check) | 4 tool
missing (ffmpeg) | 10 finding (a check failed; blur
inconclusive) | 11 leak (blur leak or a frame with unmasked data at capture) | 70 unexpected error.
"""
import argparse
import copy
import json
import math
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_bounded as rbm  # noqa: E402
import project  # noqa: E402

EXIT = {"ok": 0, "input": 2, "incomplete": 3, "tool": 4, "finding": 10, "leak": 11, "bug": 70}
ALL = ["blur", "loudness", "black", "freeze", "captions", "length", "sync", "vo", "safe_start"]
REQUIRED = ("blur", "loudness", "black", "freeze", "length", "safe_start")  # `pass` needs these present
OWNERS = {"sync": "sync-editor", "vo": "voice-producer", "loudness": "sound-mixer",
          "blur": "privacy-blurrer", "black": "capture-operator", "freeze": "capture-operator",
          "captions": "caption-writer", "length": "storyboarder", "safe_start": "sync-editor"}
LUFS_TOL, PREVIEW_TOL = 1.0, 0.5
BLACK_D, FREEZE_D = 0.2, 3.0
ALLOW_SLOP_S = 0.15
ONSET_SILENCE_S = 0.15
FORMAT_ASPECT = {"16:9": "16x9", "9:16": "9x16", "1:1": "1x1"}


class CheckError(Exception):
    def __init__(self, code, msg, failures=None):
        super().__init__(msg)
        self.code, self.msg, self.failures = code, msg, failures or []


# =========================================================================== project / config
def load_ctx(args):
    class A:
        pass
    a = A()
    a.project, a.slug = args.project, args.slug
    try:
        path = project.project_path(a)
        data = project.read_project(path)
    except project.CliError as e:
        raise CheckError(e.code, e.msg)
    return path, data


def load_cfg(sdir):
    try:
        import config
        p = os.path.join(sdir, "demo.yaml")
        return config.load_config(p) if os.path.exists(p) else config.defaults()
    except Exception as e:  # config.CliError or parse problems: input is wrong
        raise CheckError(2, "demo.yaml: %s" % getattr(e, "msg", e))


def aspects_of(cfg):
    out = []
    for f in cfg.get("formats") or ["16:9"]:
        a = FORMAT_ASPECT.get(f)
        if a and a not in out:
            out.append(a)
    return out


# =========================================================================== ffmpeg pass
def probe(path, ffprobe="ffprobe"):
    r = rbm.run_bounded([ffprobe, "-v", "error", "-show_entries",
                         "format=duration:stream=codec_type,width,height,avg_frame_rate",
                         "-of", "json", path], wall=30, label="ffprobe")
    if r["status"] != "ok" or r["tool_rc"] != 0:
        raise CheckError(2, "cannot probe %s: %s" % (path, (r.get("stderr_tail") or r["status"]).strip()[-200:]))
    d = json.loads(r["stdout_tail"] or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not v:
        raise CheckError(2, "%s has no video stream" % path)
    n, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    try:
        fps = float(n) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {"duration": float(d.get("format", {}).get("duration") or 0), "w": v.get("width"),
            "h": v.get("height"), "fps": round(fps, 3), "audio": a is not None}


def _f(s):
    try:
        return float(s)
    except ValueError:
        return -math.inf


def parse_pass(text, duration):
    """Parse the stderr of the combined pass into loudness / black / freeze / silence."""
    out = {"lufs": None, "tp_db": None, "black": [], "freeze": [], "silence": []}
    m = re.findall(r"\bI:\s+(-?[\d.]+|-inf)\s+LUFS", text)
    if m:
        out["lufs"] = _f(m[-1])
    m = re.findall(r"\bPeak:\s+(-?[\d.]+|-inf)\s+dBFS", text)
    if m:
        out["tp_db"] = _f(m[-1])
    for a, b in re.findall(r"black_start:(\S+)\s+black_end:(\S+)", text):
        out["black"].append([float(a), float(b)])
    starts = re.findall(r"freeze_start:\s*(\S+)", text)
    ends = re.findall(r"freeze_end:\s*(\S+)", text)
    for i, s in enumerate(starts):
        out["freeze"].append([float(s), float(ends[i]) if i < len(ends) else duration])
    sstarts = re.findall(r"silence_start:\s*(-?[\d.]+)", text)
    sends = re.findall(r"silence_end:\s*(-?[\d.]+)", text)
    for i, s in enumerate(sstarts):
        out["silence"].append([max(0.0, float(s)), float(sends[i]) if i < len(sends) else duration])
    return out


def combined_pass(path, info, ffmpeg="ffmpeg", wall=None):
    """ONE ffmpeg pass: blackdetect + freezedetect on video, ebur128 + silencedetect on audio."""
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-i", path, "-vf",
           "blackdetect=d=%g:pix_th=0.10,freezedetect=n=-60dB:d=%g" % (BLACK_D, FREEZE_D)]
    if info["audio"]:
        cmd += ["-af", "ebur128=peak=true:framelog=quiet,silencedetect=n=-40dB:d=%g" % ONSET_SILENCE_S]
    cmd += ["-f", "null", "-"]
    wall = wall or 0.3 * max(info["duration"], 1.0) + 60
    r = rbm.run_bounded(cmd, wall=wall, stall=30, label="checks:" + os.path.basename(path),
                        heartbeat="ffmpeg", tail_bytes=4000000)
    if r["status"] in ("wall", "stall"):
        raise CheckError(3, "ffmpeg %s on %s after %.0f s (budget %.0f s): verdict incomplete"
                         % (r["status"], path, r["elapsed_s"], wall))
    if r["status"] != "ok" or r["tool_rc"] != 0:
        raise CheckError(70, "ffmpeg failed on %s: %s" % (path, (r.get("stderr_tail") or "").strip()[-300:]))
    return parse_pass(r["stderr_tail"], info["duration"])


# =========================================================================== individual checks
def covered(span, allowed):
    a, b = span
    return any(a >= s / 1000.0 - ALLOW_SLOP_S and b <= e / 1000.0 + ALLOW_SLOP_S for s, e in allowed)


def scene_at(timeline, t):
    for sc in (timeline or {}).get("scenes") or []:
        try:
            if sc["start"] <= t * 1000 <= sc["end"]:
                return sc.get("id")
        except (KeyError, TypeError):
            pass
    return None


def bound_problem(e, a, files, sdir, data):
    """Why verdict `e` of aspect `a` is not bound to the current output / inputs, or None."""
    f = files.get(a)
    cur = project.stat_fingerprint(f) if f else None
    if cur is None:
        return "final-%s.mp4 is not readable" % a
    if not project.same_fingerprint(e.get("file"), cur):
        return "verdict is not bound to the current final-%s.mp4 (re-rendered since verify, or no fingerprint)" % a
    rel = os.path.relpath(f, sdir).replace(os.sep, "/")
    if e.get("video") not in (rel, os.path.abspath(f)):
        return "verdict was made for another file (%s)" % e.get("video")
    rec = e.get("inputs")
    if not isinstance(rec, dict):
        return "verdict records no #blur/#timeline/#events versions"
    now = project.current_inputs(data, ("blur", "timeline", "events"))
    if rec != now:
        changed = sorted(k for k in set(rec) | set(now) if rec.get(k) != now.get(k))
        return "stale: %s changed since verify" % ", ".join("#" + k for k in changed)
    return None


def unmaskable_problem(data):
    """Clips whose unmaskable[] surfaces no #blur region covers (R-04), as a detail string or None."""
    clips = (data.get("events") or {}).get("clips") if isinstance(data.get("events"), dict) else None
    if not isinstance(clips, dict) or not any(isinstance(c, dict) and c.get("unmaskable") for c in clips.values()):
        return None
    import blur as blurmod
    try:
        blur = data.get("blur") or {}
        regions = blurmod._as_v2((blur.get("regions") if isinstance(blur, dict) else None) or [], clips)
    except blurmod.BlurError as e:
        return "#blur is not plannable: %s" % e.msg
    unc = blurmod.uncovered_unmaskable(regions, clips)
    return ("%d unmaskable surface(s) without a blur region (%s)"
            % (len(unc), ", ".join("%s#%d" % (u["scene"], u["index"]) for u in unc[:5]))) if unc else None


def blur_result(data, aspects, rendered, files=None, sdir=""):
    """Aggregate #checks.blur.<aspect> (written by `blur.py verify`) for every rendered aspect. A verdict
    counts only when bound to the current file and inputs (R-02, R-13)."""
    stored = ((data.get("checks") or {}).get("blur") or {}) if isinstance(data.get("checks"), dict) else {}
    verdicts, bad, hits = {}, [], 0
    for a in aspects:
        if a not in rendered:
            continue
        e = stored.get(a)
        if not isinstance(e, dict):
            verdicts[a] = "incomplete"
            bad.append("%s: no blur.py verify verdict (run blur.py verify --aspect %s)" % (a, a))
            continue
        v = e.get("verdict")
        ctrl = e.get("positive_control") or {}
        if v == "pass" and any(not ok for ok in ctrl.values()):
            v = "inconclusive"  # a failed positive control is no evidence, never a pass
        if v == "pass" and e.get("hits"):
            v = "leak"
        if v not in ("pass", "leak", "inconclusive", "incomplete"):
            v = "incomplete"
        if v == "pass" and not e.get("total") and not (e.get("fullframe") or {}).get("sampled"):
            v = "incomplete"  # nothing was sampled: no evidence
        if v in ("pass", "inconclusive") and files is not None:
            why = bound_problem(e, a, files, sdir, data)
            if why:
                v = "incomplete"
                bad.append("%s: %s" % (a, why))
        verdicts[a] = v
        hits += len(e.get("hits") or [])
        if v != "pass" and not any(b.startswith(a + ":") for b in bad):
            bad.append("%s: %s" % (a, v))
    un = unmaskable_problem(data)
    if un:
        bad.append(un)
    worst = next((v for v in ("leak", "inconclusive", "incomplete") if v in verdicts.values()), "pass")
    if un and worst == "pass":
        worst = "incomplete"
    if not verdicts:
        worst = "incomplete"
        bad.append("no rendered aspect to verify")
    return {"pass": worst == "pass", "verdict": worst, "verdicts": verdicts, "hits": hits,
            "owner": OWNERS["blur"] if worst in ("leak", "inconclusive") or un else "render-engineer",
            "detail": "; ".join(bad)}


def safe_start_result(data):
    clips = (data.get("events") or {}).get("clips") if isinstance(data.get("events"), dict) else None
    bad = project.unsafe_scenes(data.get("timeline"), clips or {})
    return {"pass": not bad, "scenes": bad, "owner": OWNERS["safe_start"],
            "detail": "; ".join("%s in=%s ms < safe_from_ms=%s" % (b["scene"], b["in"], b["safe_from_ms"])
                                for b in bad)}


def loudness_result(per, cfg, mix):
    t = cfg["targets"]
    prev = (mix or {}).get("preview") or {}
    rows, bad = {}, []
    for a, m in per.items():
        lufs, tp = m["lufs"], m["tp_db"]
        row = {"lufs": lufs, "tp_db": tp}
        if lufs is None or lufs == -math.inf:
            bad.append("%s: no measurable audio" % a)
        else:
            if abs(lufs - t["lufs"]) > LUFS_TOL:
                bad.append("%s: %.1f LUFS vs target %s +-%g" % (a, lufs, t["lufs"], LUFS_TOL))
            if tp is not None and tp > t["true_peak"]:
                bad.append("%s: true peak %.1f dBTP > %s" % (a, tp, t["true_peak"]))
            if prev.get("lufs") is not None and abs(lufs - prev["lufs"]) > PREVIEW_TOL:
                bad.append("%s: %.1f LUFS is %.1f off #mix.preview (%.1f): chain not reproducible"
                           % (a, lufs, abs(lufs - prev["lufs"]), prev["lufs"]))
            if prev.get("tp_db") is not None and tp is not None and abs(tp - prev["tp_db"]) > PREVIEW_TOL:
                bad.append("%s: true peak %.1f is %.1f dB off #mix.preview (%.1f)"
                           % (a, tp, abs(tp - prev["tp_db"]), prev["tp_db"]))
        rows[a] = row
    first = next(iter(rows.values()), {})
    return {"pass": not bad, "lufs": first.get("lufs"), "tp_db": first.get("tp_db"),
            "target_lufs": t["lufs"], "target_tp_db": t["true_peak"], "by_aspect": rows,
            "owner": OWNERS["loudness"], "detail": "; ".join(bad)}


def span_result(kind, per, motion, timeline, dur):
    allow = ((motion or {}).get("allow") or {}).get(kind) or []
    hits, allowed_s = [], 0.0
    for a, m in per.items():
        for s, e in m[kind]:
            if covered((s, e), allow):
                allowed_s += e - s
                continue
            hits.append({"aspect": a, "t_start": round(s, 2), "t_end": round(e, 2),
                         "scene": scene_at(timeline, s)})
    detail = "; ".join("%s %.2f-%.2f s%s" % (h["aspect"], h["t_start"], h["t_end"],
                                              " (%s)" % h["scene"] if h["scene"] else "") for h in hits)
    if dur and sum(e - s for s, e in [(x[0] / 1000.0, x[1] / 1000.0) for x in allow]) / dur > 0.30:
        detail += ("; " if detail else "") + "allow.%s covers > 30%% of the video: check is blind there" % kind
    return {"pass": not hits, "hits": hits, "owner": OWNERS[kind], "detail": detail}


def parse_vtt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, l in enumerate(lines):
            m = re.match(r"\s*(?:(\d+):)?(\d+):(\d+)[.,](\d+)\s+-->\s+(?:(\d+):)?(\d+):(\d+)[.,](\d+)", l)
            if m:
                g = m.groups()
                t0 = (int(g[0] or 0) * 3600 + int(g[1]) * 60 + int(g[2])) * 1000 + int(g[3].ljust(3, "0")[:3])
                t1 = (int(g[4] or 0) * 3600 + int(g[5]) * 60 + int(g[6])) * 1000 + int(g[7].ljust(3, "0")[:3])
                cues.append({"t0": t0, "t1": t1, "lines": lines[i + 1:]})
                break
    return cues


def captions_result(sdir, media, cfg, onsets_s, duration, lang_suffix=""):
    f = os.path.join(media, "final%s.vtt" % lang_suffix)
    if not os.path.exists(f):
        return {"pass": False, "owner": OWNERS["captions"], "detail": "%s missing" % os.path.relpath(f, sdir)}
    with open(f, encoding="utf-8-sig") as fh:
        cues = parse_vtt(fh.read())
    mx = cfg["captions"]["max_chars"]
    bad, longest, prev_end, over_lines, off = [], 0, -1, 0, []
    for i, c in enumerate(cues, 1):
        longest = max([longest] + [len(l) for l in c["lines"]])
        if len(c["lines"]) > 2:
            over_lines += 1
            bad.append("cue %d has %d lines" % (i, len(c["lines"])))
        for l in c["lines"]:
            if len(l) > mx:
                bad.append("cue %d line is %d chars > %d" % (i, len(l), mx))
                break
        if not 1000 <= c["t1"] - c["t0"] <= 6500:
            bad.append("cue %d lasts %.1f s (1-6 s)" % (i, (c["t1"] - c["t0"]) / 1000.0))
        if c["t0"] < prev_end or c["t1"] <= c["t0"]:
            bad.append("cue %d overlaps or is empty" % i)
        prev_end = c["t1"]
        if duration and c["t1"] > duration * 1000 + 500:
            bad.append("cue %d ends after the video" % i)
        near = min(onsets_s, key=lambda o: abs(o * 1000 - c["t0"]), default=None)
        if near is not None and abs(near * 1000 - c["t0"]) <= 1000:
            off.append(int(abs(near * 1000 - c["t0"])))
    if not cues:
        bad.append("no cues in final.vtt")
    return {"pass": not bad, "max_chars": longest, "cues": len(cues), "cues_over_lines": over_lines,
            "onset_max_ms": max(off) if off else None, "onset_checked": len(off),
            "onset_gate": False, "owner": OWNERS["captions"], "detail": "; ".join(bad[:8])}


def length_result(per_dur, cfg):
    target = cfg.get("length_s")
    if not target:
        return {"pass": True, "skipped": True, "owner": OWNERS["length"], "detail": "demo.yaml length_s is not set"}
    d = max(per_dur.values()) if per_dur else 0.0
    pct = (d - target) * 100.0 / target
    return {"pass": abs(pct) <= 10.0, "target_s": target, "actual_s": round(d, 2),
            "delta_pct": round(pct, 1), "owner": OWNERS["length"], "detail": ""}


def sync_result(per_info, timeline, cfg):
    scenes = (timeline or {}).get("scenes") or []
    if not scenes:
        return {"pass": True, "skipped": True, "owner": OWNERS["sync"], "detail": "no #timeline"}
    lim = cfg["targets"]["max_drift_ms"]
    try:
        end_ms = max(s["end"] for s in scenes)
    except (KeyError, TypeError):
        return {"pass": True, "skipped": True, "owner": OWNERS["sync"], "detail": "#timeline has no scene ends"}
    worst, bad = 0.0, []
    for a, i in per_info.items():
        d = abs(i["duration"] * 1000 - end_ms)
        worst = max(worst, d)
        if d > lim:
            bad.append("%s: %.0f ms from #timeline end" % (a, d))
    return {"pass": not bad, "measured_ms_max": round(worst), "threshold_ms": lim,
            "scope": "total duration vs #timeline end (per-scene drift not measured here)",
            "owner": OWNERS["sync"], "detail": "; ".join(bad)}


def vo_result(sdir, voice):
    scenes = (voice or {}).get("scenes") or []
    if not scenes:
        return {"pass": True, "skipped": True, "owner": OWNERS["vo"], "detail": "no #voice scenes"}
    import vo
    fails = []
    for sc in scenes:
        f = os.path.join(sdir, sc.get("file") or "media/%s.vo.wav" % sc.get("id"))
        miss = [k for k in ("lead_ms", "trail_ms", "sentences", "words_per_s", "pauses_ms") if k not in sc]
        if miss:
            fails.append("%s: #voice lacks %s" % (sc.get("id"), ",".join(miss)))
            continue
        try:
            r = vo.check_audio(vo.read_wav(f), 200, 150, 500, sc.get("pauses_ms") or [], vo.SILENCE_DB)
        except (vo.VoError, OSError) as e:
            fails.append("%s: %s" % (sc.get("id"), e))
            continue
        if not r["pass"]:
            fails.append("%s: %s" % (sc.get("id"), "; ".join(r["failures"])))
    return {"pass": not fails, "scenes_checked": len(scenes), "failures": fails,
            "owner": OWNERS["vo"], "detail": "; ".join(fails[:5])}


def clip_uncaptured(c):
    """A clip whose capture-time mask is no proof: not masked, blur style, or no rect ever checked."""
    m = c.get("mask") if isinstance(c.get("mask"), dict) else {}
    style = m.get("mask_style") or m.get("style") or c.get("mask_style")
    return (not c.get("masked") or style == "blur" or int(m.get("rects_checked", m.get("rect_checks")) or 0) == 0)


def privacy_capture(data, real=True):
    clips = (data.get("events") or {}).get("clips") if isinstance(data.get("events"), dict) else None
    if not isinstance(clips, dict) or not clips:
        return None
    cl = {k: c for k, c in clips.items() if isinstance(c, dict)}
    unc = sorted(k for k, c in cl.items() if clip_uncaptured(c))
    regs = (data.get("blur") or {}).get("regions") if isinstance(data.get("blur"), dict) else None
    covered = set()
    for r in regs or []:
        if isinstance(r, dict):
            if r.get("scene"):
                covered.add(r["scene"])
            covered.update(sp[2] for sp in r.get("spans") or [] if isinstance(sp, list) and len(sp) == 3)
    return {"clips": len(clips),
            "masked": sum(1 for c in cl.values() if c.get("masked")),
            "frames_unmasked": sum(int(((c.get("mask") or {}).get("frames_unmasked")) or 0)
                                   for c in cl.values()),
            "rects_checked": sum(int(((c.get("mask") or {}).get("rects_checked")) or 0)
                                 for c in cl.values()),
            "uncaptured": unc,
            "needs_blur": [k for k in unc if real and k not in covered]}


# =========================================================================== command
def run(args):
    path, data = load_ctx(args)
    sdir = os.path.dirname(path)
    cfg = load_cfg(sdir)
    only = [x for s in (args.only or []) for x in s.split(",") if x] or list(ALL)
    unknown = [x for x in only if x not in ALL]
    if unknown:
        raise CheckError(2, "unknown check id(s) %s; valid: %s" % (",".join(unknown), ",".join(ALL)))
    media = os.path.abspath(args.media_dir) if args.media_dir else os.path.join(sdir, "media")
    aspects = aspects_of(cfg)
    files = {a: os.path.join(media, "final-%s.mp4" % a) for a in aspects}
    rendered = [a for a in aspects if os.path.exists(files[a])]
    if not rendered:
        raise CheckError(2, "no rendered output found: %s" % ", ".join(
            os.path.relpath(f, sdir) for f in files.values()),
            [{"id": "outputs", "owner": "render-engineer", "class": "input"}])
    media_checks = {"loudness", "black", "freeze", "captions", "length", "sync"} & set(only)
    if args.dry_run:
        return {"status": "ok", "dry_run": True, "aspects": rendered, "checks": only,
                "ffmpeg_passes": len(rendered) if media_checks else 0}, 0
    if media_checks and (not shutil.which(args.ffmpeg) or not shutil.which(args.ffprobe)):
        raise CheckError(4, "ffmpeg/ffprobe not found (setup_tools.py --plan capture)")
    infos, meas = {}, {}
    if media_checks:
        for a in rendered:
            infos[a] = probe(files[a], args.ffprobe)
            meas[a] = combined_pass(files[a], infos[a], args.ffmpeg)
    timeline, motion, mix = data.get("timeline"), data.get("motion"), data.get("mix")
    dur = max((i["duration"] for i in infos.values()), default=0.0)
    results = {}
    for cid in only:
        if cid == "blur":
            results["blur"] = blur_result(data, aspects, rendered, files, sdir)
        elif cid == "loudness":
            results["loudness"] = loudness_result(meas, cfg, mix)
        elif cid in ("black", "freeze"):
            results[cid] = span_result(cid, meas, motion, timeline, dur)
        elif cid == "captions":
            onsets = sorted({e for m in meas.values() for _, e in m["silence"]})
            results["captions"] = captions_result(sdir, media, cfg, onsets, dur)
        elif cid == "length":
            results["length"] = length_result({a: i["duration"] for a, i in infos.items()}, cfg)
        elif cid == "sync":
            results["sync"] = sync_result(infos, timeline, cfg)
        elif cid == "vo":
            results["vo"] = vo_result(sdir, data.get("voice"))
        elif cid == "safe_start":
            results["safe_start"] = safe_start_result(data)
    real = cfg["privacy"]["data_mode"] != "seeded"
    outputs = {}
    old = (data.get("checks") or {}) if isinstance(data.get("checks"), dict) else {}
    for a, i in infos.items():
        outputs[a] = {"file": os.path.relpath(files[a], sdir).replace(os.sep, "/"), "w": i["w"],
                      "h": i["h"], "fps": i["fps"], "duration_s": round(i["duration"], 2),
                      "renderer": args.renderer or (old.get("outputs") or {}).get(a, {}).get("renderer")}
    allow = {"black": ((motion or {}).get("allow") or {}).get("black") or [],
             "freeze": ((motion or {}).get("allow") or {}).get("freeze") or []}
    box = {}

    def build(cur):
        """The whole #checks value, built from the project as it is UNDER THE LOCK: blur verdicts are
        re-read live, `pass` is recomputed from this run's results only, older results are dropped."""
        res = dict(results)
        if "blur" in res:
            res["blur"] = blur_result(cur, aspects, rendered, files, sdir)
        pc = privacy_capture(cur, real)
        missing = [r for r in REQUIRED if r not in res]
        failures = [{"id": k, "owner": r["owner"],
                     "class": "leak" if (k == "blur" and r.get("verdict") == "leak")
                     else "incomplete" if (k == "blur" and r.get("verdict") == "incomplete") else "finding"}
                    for k, r in res.items() if not r.get("pass")]
        if pc and pc["frames_unmasked"] > 0:
            failures.append({"id": "privacy_capture", "owner": "capture-operator", "class": "leak"})
        if pc and pc["needs_blur"]:
            failures.append({"id": "privacy_capture", "owner": "privacy-blurrer", "class": "incomplete"})
        total_pass = (all(r.get("pass") for r in res.values()) and not missing
                      and not any(f["id"] == "privacy_capture" for f in failures))
        value = {"schema": 2, "results": res, "pass": total_pass}
        if isinstance(cur.get("checks"), dict) and isinstance(cur["checks"].get("blur"), dict):
            value["blur"] = cur["checks"]["blur"]  # blur.py's verdicts stay
        if outputs:
            value["outputs"] = outputs
            value["allow"] = allow
        if pc:
            value["privacy_capture"] = pc
        box.update(res=res, pc=pc, missing=missing, failures=failures, total_pass=total_pass)
        return value

    if args.no_write:
        build(data)
    else:
        version = project.write_checks(path, None, writer="checks.py", transform=build)
    results, pc, missing = box["res"], box["pc"], box["missing"]
    failures, total_pass = box["failures"], box["total_pass"]
    leak = any(f["class"] == "leak" for f in failures)
    inc = any(f["class"] == "incomplete" for f in failures)
    other = any(f["class"] == "finding" for f in failures)
    status = "leak" if leak else "fail" if other else "incomplete" if inc else "pass" if total_pass else "incomplete"
    out = {"status": status, "pass": total_pass, "aspects": rendered, "results": results,
           "outputs": outputs, "failures": failures}
    if pc:
        out["privacy_capture"] = pc
    if missing:
        out["missing_checks"] = missing
    if not args.no_write:
        out["checks_version"] = version
    if leak:
        code = EXIT["leak"]
    elif other:
        code = EXIT["finding"]
    elif inc or not total_pass:
        code = EXIT["incomplete"]  # incomplete evidence (R-03): never exit 0 with pass false
    else:
        code = 0
    return out, code


def build_parser():
    p = argparse.ArgumentParser(description="Render checks in code; the only writer of #checks.",
                                allow_abbrev=False)
    p.add_argument("--project")
    p.add_argument("--slug")
    p.add_argument("--only", action="append", help="check id(s), comma separated or repeated")
    p.add_argument("--media-dir", dest="media_dir")
    p.add_argument("--renderer", choices=["ffmpeg", "opencv", "remotion"],
                   help="engine render-engineer actually used (stored in #checks.outputs.<aspect>.renderer)")
    p.add_argument("--no-write", action="store_true", dest="no_write")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--json", action="store_true", help="accepted for symmetry: output is always JSON")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--ffprobe", default="ffprobe")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return EXIT["input"] if e.code else 0
    t0 = time.monotonic()
    try:
        res, code = run(args)
    except CheckError as e:
        res = {"status": {2: "input", 3: "incomplete", 4: "missing-tool"}.get(e.code, "bug"),
               "error": e.msg, "failures": e.failures}
        code = e.code
        sys.stderr.write("error: %s\n" % e.msg)
    res.setdefault("failures", [])
    res["elapsed_s"] = round(time.monotonic() - t0, 2)
    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
    try:
        path = project.project_path(type("A", (), {"project": args.project, "slug": args.slug})())
        if os.path.isdir(os.path.dirname(path)):
            rbm.append_run(os.path.dirname(path), "checks.py",
                           argv if argv is not None else sys.argv[1:], res)
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(rbm.guard_main(main))
