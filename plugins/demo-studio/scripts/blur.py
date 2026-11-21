#!/usr/bin/env python3
"""Post-production blur: plan -> graph -> preview -> verify (docs/redesign §4.2, §6.3, §6.4).

Usage:
  blur.py (--project PATH | --slug SLUG) <command> ...
    plan     [--merge-gap-ms N] [--cover-max PX] [--dry-run]
             Normalise #blur (schema 1 or 2), merge duplicate static regions (new plans only),
             split moving regions at jumps (never interpolate), classify static | track | cover |
             needs-input, apply the strength rule, write #blur as privacy-blurrer.
    graph    --space final|source [--scene SID] [--aspect A] [--in-label L] [--out-label L]
             Print ONE ffmpeg filter_complex (JSON): enable= on both blur and overlay, drawbox t=fill
             for secrets/cover, sendcmd for moving regions. Never one encode per region.
    preview  [--dry-run]      positive control per region on an unblurred crop + masked contact sheet
    verify   --video F --aspect A [--budget-s N] [--fullframe-stride-s S] [--ocr rapidocr|python:M:F]
             [--pattern RE ...] [--lang L] [--hmac] [--dry-run]
             --ocr default: demo.yaml tools.ocr (qa-ocr -> rapidocr, qa-ocr-tesseract -> tesseract,
             none -> verdict inconclusive, exit 10, no OCR run). Resets #checks.pass to false and drops
             this aspect's old verdict (and results.blur) BEFORE it starts; its verdict binds the exact
             verified file (size, mtime_ns, ino[, sha256]) and the #blur/#timeline/#events versions;
             it never sets pass true (only checks.py does).
             One sequential decode of the output (a single ffmpeg process piping frames), OCR engine
             built once (worker subprocess), ROI crops stacked in a montage + sparse full-frame regex
             pass, mandatory positive control, hard budget enforced in code.
    set-transform --aspect A (--scale S --ox X --oy Y | --identity) [--segment T0 T1 SCALE OX OY ...]
             The render step records how it mapped source px to output px of aspect A into
             #blur.transforms.A (source px * scale + offset; --segment = a time window in s on the final
             timeline with its own mapping, for zoom/pan). verify REFUSES (exit 2) an aspect that
             needs a non-identity mapping (other aspect ratio, or #motion zoom/pan/reframe for it)
             when #blur.transforms.A is missing.
    ocr-worker --engine E [--lang L]        (internal: the OCR subprocess verify talks to)

Result: one JSON line on stdout {"status","elapsed_s",...,"failures":[{"id","owner","class"}]}.
Exit codes: 0 ok/pass | 2 input or schema wrong (e.g. keyframes jump without a split, needs-input,
              a clip with unmaskable[] no region covers, a timeline scene before safe_from_ms, a
              missing #blur.transforms.<aspect>)
            3 budget exceeded, verdict incomplete | 4 tool missing (ffmpeg / OCR)
            10 finding (verdict inconclusive: positive control failed) | 11 leak (OCR read protected text)
            70 unexpected exception or environment error | 124/125 only run_bounded.
Every external process runs through run_bounded (hard wall, stall timeout, group kill).

#blur schema 2 region: {"id","bbox":[x,y,w,h] (source px),"spans":[[t0,t1] | [t0,t1,scene]] (ms, scene
relative), "scene", "mode": static|track|cover, "style": opaque|boxblur|pixelize, "pad", "text_h",
"secret", "source", "label", "pattern", "keyframes": [[t,x,y,w,h]] (track only, held step-wise)}.
Capture contract: events.clips[sid].unmaskable[] = {surface, selector, reason, t_start, t_end, bbox:[x,y,w,h]}
with t_* in CLIP ms (scene-relative = t - offset_ms) and bbox in clip px; plan turns each into an opaque,
padded region (source "unmaskable") and exits 2 for an entry it cannot (no bbox / no time span).
A region merged across scenes has "scene": null and 3-element spans.
"""
import argparse
import hashlib
import hmac as hmac_mod
import json
import math
import os
import re
import secrets as secrets_mod
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_bounded as rbm  # noqa: E402
import project  # noqa: E402

OWNER = "privacy-blurrer"
DEFAULT_PAD = 12
DEFAULT_FPS = 25.0
COVER_MAX_PX = 8
MERGE_GAP_MS = 100
ROI_STEP_S = 0.5
MIN_ROI_H = 64
BUILTIN_PATTERNS = [r"[\w.+-]+@[\w-]+\.[\w.]+", r"\b(?:sk|pk|api|key|tok)[-_][A-Za-z0-9_-]{8,}"]
SECRET_WORDS = re.compile(r"key|token|secret|passw|credential|api", re.I)
BUDGET_SEEDED_S, BUDGET_REAL_S = 120.0, 300.0
EXIT = {"ok": 0, "input": 2, "incomplete": 3, "tool": 4, "finding": 10, "leak": 11, "bug": 70}


class BlurError(Exception):
    def __init__(self, code, msg, failures=None):
        super().__init__(msg)
        self.code, self.msg, self.failures = code, msg, failures or []


# =========================================================================== regions / plan
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _kf(k):
    """Keyframe in either shape -> [t,x,y,w,h] or None."""
    split = 0
    if isinstance(k, dict) and _num(k.get("t")) and isinstance(k.get("bbox"), list):
        split = 1 if k.get("split") else 0
        k = [k["t"]] + list(k["bbox"])
    if isinstance(k, list) and len(k) in (5, 6) and all(_num(v) for v in k):
        split = split or (1 if len(k) == 6 and k[5] else 0)
        return [float(k[0])] + [int(round(v)) for v in k[1:5]] + ([1] if split else [])
    return None


def norm_region(r):
    """Read a schema 1 or 2 region into a uniform dict, or raise ValueError describing the problem."""
    if not isinstance(r, dict):
        raise ValueError("region is not an object")
    bbox = r.get("bbox")
    if not (isinstance(bbox, list) and len(bbox) == 4 and all(_num(v) for v in bbox)):
        raise ValueError("bbox must be [x,y,w,h]")
    bbox = [int(round(v)) for v in bbox]
    if bbox[2] <= 0 or bbox[3] <= 0:
        raise ValueError("bbox has no area")
    spans = []
    if isinstance(r.get("spans"), list):
        for s in r["spans"]:
            if not (isinstance(s, list) and len(s) in (2, 3) and _num(s[0]) and _num(s[1])
                    and s[1] > s[0]):
                raise ValueError("bad span %r" % (s,))
            sc = s[2] if len(s) == 3 else r.get("scene")
            if not sc:
                raise ValueError("span without a scene")
            spans.append([float(s[0]), float(s[1]), sc])
    elif _num(r.get("t_start")) and _num(r.get("t_end")):
        m = r.get("margin_ms") or 0
        if not r.get("scene"):
            raise ValueError("region without a scene")
        spans.append([max(0.0, r["t_start"] - m), float(r["t_end"] + m), r["scene"]])
    if not spans:
        raise ValueError("region has no time span")
    kfs = None
    if r.get("keyframes"):
        kfs = [_kf(k) for k in r["keyframes"]]
        if any(k is None for k in kfs):
            raise ValueError("bad keyframe")
        kfs.sort(key=lambda k: k[0])
    label = r.get("label") or (r["source"] if str(r.get("source", "")).startswith("events:") else "")
    mode = r.get("mode")
    style = r.get("style")
    if style is None:  # schema 1 stored the filter in "mode"
        style = {"boxblur": "boxblur", "pixelate": "pixelize"}.get(mode)
    secret = bool(r.get("secret")) or bool(SECRET_WORDS.search(str(label)))
    return {"id": str(r.get("id", "")), "bbox": bbox, "spans": spans, "kfs": kfs,
            "pad": int(r.get("pad", DEFAULT_PAD)), "style": style, "secret": secret,
            "text_h": r.get("text_h"), "source": r.get("source"), "label": label,
            "pattern": r.get("pattern"), "mode_in": mode}


def _span_scene(reg, s):
    return s[2] if len(s) == 3 else reg.get("scene")


def _union_bbox(reg):
    kfs = reg.get("kfs") or reg.get("keyframes")
    if kfs:
        xs0 = min(k[1] for k in kfs)
        ys0 = min(k[2] for k in kfs)
        xs1 = max(k[1] + k[3] for k in kfs)
        ys1 = max(k[2] + k[4] for k in kfs)
        return [xs0, ys0, xs1 - xs0, ys1 - ys0]
    return reg["bbox"]


def unmaskable_region(sid, clip, i, u):
    """One events.clips[sid].unmaskable[] entry -> a norm_region-ready dict, or ValueError."""
    if not isinstance(u, dict):
        raise ValueError("unmaskable entry is not an object")
    bb, ts, te = u.get("bbox"), u.get("t_start"), u.get("t_end")
    if not (isinstance(bb, list) and len(bb) == 4 and all(_num(v) for v in bb) and bb[2] > 0 and bb[3] > 0):
        raise ValueError("unmaskable entry %d of %s has no usable bbox (capture must emit "
                         "bbox [x,y,w,h] in clip px)" % (i, sid))
    if not (_num(ts) and _num(te) and te > ts):
        raise ValueError("unmaskable entry %d of %s has no time span t_start/t_end" % (i, sid))
    off = float((clip or {}).get("offset_ms", 0) or 0)
    a, b = max(0.0, ts - off), te - off
    if b <= 0:
        return None  # entirely before the scene starts: not in any render
    return {"id": "um-%s-%d" % (sid, i), "scene": sid, "bbox": list(bb), "spans": [[a, b, sid]],
            "style": "opaque", "secret": True, "pad": DEFAULT_PAD, "source": "unmaskable",
            "label": "unmaskable:%s" % (u.get("reason") or u.get("surface") or "surface")}


def uncovered_unmaskable(regions, clips, slop_ms=MERGE_GAP_MS):
    """Entries of events.clips[*].unmaskable[] that no region covers (bbox inside the padded region
    bbox, whole time span inside the region's spans of that scene). Regions: plan output or the
    normalised form. Returns [{"scene","index","reason"}]; an entry plan cannot use is uncovered."""
    out = []
    for sid, clip in sorted((clips or {}).items()):
        for i, u in enumerate((clip.get("unmaskable") if isinstance(clip, dict) else None) or []):
            try:
                need = unmaskable_region(sid, clip, i, u)
            except ValueError as e:
                out.append({"scene": sid, "index": i, "reason": str(e)})
                continue
            if need is None:
                continue
            nb, (na, nz, _) = need["bbox"], need["spans"][0]
            ok = False
            for r in regions:
                pad = int(r.get("pad", DEFAULT_PAD))
                rb = _union_bbox(r)
                if not (rb[0] - pad <= nb[0] and rb[1] - pad <= nb[1]
                        and rb[0] + rb[2] + pad >= nb[0] + nb[2] and rb[1] + rb[3] + pad >= nb[1] + nb[3]):
                    continue
                mine = merge_spans([[s[0], s[1], sid] for s in r["spans"] if _span_scene(r, s) == sid],
                                   slop_ms)
                if any(m[0] <= na + 1e-6 and m[1] >= nz - 1e-6 for m in mine):
                    ok = True
                    break
            if not ok:
                out.append({"scene": sid, "index": i, "reason": "no region covers it"})
    return out


def clip_frame_ms(clips, scene):
    try:
        fps = float(clips[scene]["fps"])
        return 1000.0 / fps if fps > 0 else 1000.0 / DEFAULT_FPS
    except (KeyError, TypeError, ValueError):
        return 1000.0 / DEFAULT_FPS


def split_track(reg, frame_ms):
    """Segment a moving region. Keyframes are held step-wise, never interpolated. A new segment
    starts only at a keyframe flagged "split" (the element was gone in between: that gap stays
    uncovered). Consecutive keyframes > pad apart over more than 1.5 frames, without a split, are an
    error: the element moved somewhere unknown in between."""
    kfs, pad = reg["kfs"], reg["pad"]
    scene = reg["spans"][0][2]
    segs = [[kfs[0][:5]]]
    for prev, cur in zip(kfs, kfs[1:]):
        d = max(abs(cur[i] - prev[i]) for i in (1, 2, 3, 4))
        if len(cur) == 6:  # explicit split
            segs.append([cur[:5]])
            continue
        if d > pad and cur[0] - prev[0] > 1.5 * frame_ms:
            raise BlurError(2, "region %s: keyframes jump %d px (> pad %d) across %.0f ms without a "
                               "split: add keyframes for every frame or split the region"
                            % (reg["id"], d, pad, cur[0] - prev[0]),
                            [{"id": reg["id"], "owner": "capture-operator", "class": "jump"}])
        segs[-1].append(cur[:5])
    half = frame_ms / 2.0
    t0, t1 = min(s[0] for s in reg["spans"]), max(s[1] for s in reg["spans"])
    out = []
    for i, seg in enumerate(segs):
        a = seg[0][0] - half
        b = seg[-1][0] + half
        if i == 0:
            a = min(a, t0)
        if i == len(segs) - 1:
            b = max(b, t1)
        out.append(([max(0.0, a), b, scene], seg))
    return out


def text_height(reg):
    th = reg.get("text_h")
    return int(th) if _num(th) and th > 0 else reg["bbox"][3]


def strength(style, text_h):
    """X7: boxblur lr >= ceil(h/4), lp=1; pixelize block >= ceil(h/3)."""
    return math.ceil(text_h / 4.0) if style == "boxblur" else math.ceil(text_h / 3.0)


def plan_regions(regions, clips=None, merge_gap_ms=MERGE_GAP_MS, cover_max=COVER_MAX_PX, unmaskable=True):
    """Return (new_regions, report). Raises BlurError(2) on a jump without a split / needs-input.
    `unmaskable` (default, `plan`) turns clips' unmaskable[] into regions; graph / verify / checks pass
    False: they only READ the stored plan, and an uncovered surface there is exit 2 / incomplete."""
    clips = clips or {}
    report = {"regions_in": len(regions), "dropped": [], "needs_input": [], "merged": 0,
              "unmaskable_regions": 0}
    items, bad = [], []
    for i, raw in enumerate(regions):
        rid = str(raw.get("id", "r%d" % (i + 1))) if isinstance(raw, dict) else "r%d" % (i + 1)
        try:
            reg = norm_region(raw)
            reg["id"] = reg["id"] or rid
            items.append(reg)
        except ValueError as e:
            bad.append({"id": rid, "owner": "capture-operator", "class": "needs-input",
                        "detail": str(e)})
    for sid, clip in sorted(clips.items() if unmaskable else ()):  # capture could not mask these: blur them
        for i, u in enumerate((clip.get("unmaskable") if isinstance(clip, dict) else None) or []):
            try:
                raw = unmaskable_region(sid, clip, i, u)
                if raw is None:
                    continue
                reg = norm_region(raw)
            except ValueError as e:
                bad.append({"id": "um-%s-%d" % (sid, i), "owner": "capture-operator",
                            "class": "needs-input", "detail": str(e)})
                continue
            if not uncovered_unmaskable(items, {sid: dict(clip, unmaskable=[u])}):
                continue  # a region already covers it (idempotent plan)
            items.append(reg)
            report["unmaskable_regions"] += 1
    if bad:
        report["needs_input"] = bad
        raise BlurError(2, "needs-input: %d region(s) unusable: %s"
                        % (len(bad), "; ".join("%s (%s)" % (b["id"], b["detail"]) for b in bad)), bad)
    statics, tracks = [], []
    for reg in items:
        # a region the capture-time mask already covers is redundant, but only when EVERY scene it
        # spans was really masked (masked is true only after the capture gate passed); every other
        # region is kept (RT-10, R-12)
        if reg["source"] == "capture-mask" and all(
                (clips.get(sp[2]) or {}).get("masked") is True for sp in reg["spans"]):
            report["dropped"].append(reg["id"])
            continue
        style = reg["style"]
        th = text_height(reg)
        cover = min(reg["bbox"][2], reg["bbox"][3]) <= cover_max and not reg["kfs"]
        if cover or reg["secret"] or style is None:
            style = "opaque"  # secrets (never pixelated), thin strips and the default are solid (§6.2)
        src = str(reg["source"] or "manual")
        src = "events" if src.startswith("events") else src
        base = {"pad": reg["pad"], "style": style, "text_h": th, "secret": reg["secret"],
                "source": src if src in ("capture-mask", "events", "manual", "legacy", "unmaskable")
                else "manual",
                "label": reg["label"], "pattern": reg["pattern"]}
        if reg["kfs"]:
            frame_ms = clip_frame_ms(clips, reg["spans"][0][2])
            segs = split_track(reg, frame_ms)
            tracks.append(dict(base, id=reg["id"], mode="track", bbox=reg["kfs"][0][1:],
                               spans=[s for s, _ in segs],
                               keyframes=[k for _, seg in segs for k in seg]))
        else:
            statics.append(dict(base, id=reg["id"], mode="cover" if cover else "static",
                                bbox=reg["bbox"], spans=reg["spans"]))
    merged, order = {}, []
    for r in statics:  # identical static regions become one region with many spans
        key = (tuple(r["bbox"]), r["mode"], r["style"], r["pad"], r["text_h"], r["secret"],
               r["pattern"])
        if key in merged:
            merged[key]["spans"].extend(r["spans"])
            merged[key].setdefault("merged_ids", [merged[key]["id"]]).append(r["id"])
            report["merged"] += 1
        else:
            merged[key] = r
            order.append(key)
    out = [merged[k] for k in order]
    for r in out:
        r["spans"] = merge_spans(r["spans"], merge_gap_ms)
    out += tracks
    for r in out:
        scenes = {s[2] for s in r["spans"]}
        r["scene"] = next(iter(scenes)) if len(scenes) == 1 else None
        if r["scene"]:
            r["spans"] = [[s[0], s[1]] for s in r["spans"]]
        r["spans"] = [[int(round(v)) if i < 2 else v for i, v in enumerate(s)] for s in r["spans"]]
        if r.get("keyframes"):
            r["keyframes"] = [[int(round(k[0]))] + k[1:] for k in r["keyframes"]]
    report["regions_out"] = len(out)
    report["by_mode"] = {m: sum(1 for r in out if r["mode"] == m) for m in ("static", "track", "cover")}
    return out, report


def merge_spans(spans, gap_ms):
    """Union of [t0,t1,scene] spans per scene; touching/overlapping (within gap_ms) spans join."""
    by = {}
    for s in spans:
        by.setdefault(s[2], []).append([s[0], s[1]])
    out = []
    for sc in sorted(by, key=str):
        cur = None
        for a, b in sorted(by[sc]):
            if cur and a <= cur[1] + gap_ms:
                cur[1] = max(cur[1], b)
            else:
                cur = [a, b, sc]
                out.append(cur)
    return out


# =========================================================================== time mapping / geometry
class TimeMap:
    """Scene-relative ms -> seconds on the clip (space source) or on the final timeline."""

    def __init__(self, space, clips, timeline=None, scene=None):
        self.space, self.clips, self.scene = space, clips or {}, scene
        self.tl = {s["id"]: s for s in (timeline or {}).get("scenes", []) if isinstance(s, dict)}
        if space == "final" and not self.tl:
            raise BlurError(2, "space final needs #timeline (run sync-editor first)")
        if space == "source" and not scene:
            raise BlurError(2, "space source needs --scene")

    def usable(self, scene):
        return (scene == self.scene) if self.space == "source" else scene in self.tl

    def t(self, scene, t_ms):
        off = float((self.clips.get(scene) or {}).get("offset_ms", 0))
        if self.space == "source":
            return (t_ms + off) / 1000.0
        s = self.tl[scene]
        speed = float(s.get("speed") or 1.0)
        return (s["start"] + (t_ms + off - s["in"]) / speed) / 1000.0

    def span(self, scene, a, b):
        if not self.usable(scene):
            return None
        a2, b2 = self.t(scene, a), self.t(scene, b)
        if self.space == "final":
            s = self.tl[scene]
            a2, b2 = max(a2, s["start"] / 1000.0), min(b2, s["end"] / 1000.0)
        a2 = max(a2, 0.0)
        return (a2, b2) if b2 > a2 else None


def pad_box(bbox, pad, frame_w, frame_h):
    """Padded box in frame px, clamped to the frame, outward-aligned to even coordinates."""
    x0, y0 = bbox[0] - pad, bbox[1] - pad
    x1, y1 = bbox[0] + bbox[2] + pad, bbox[1] + bbox[3] + pad
    x0, y0 = max(0, x0 - (x0 % 2)), max(0, y0 - (y0 % 2))
    x1, y1 = min(frame_w, x1 + (x1 % 2)), min(frame_h, y1 + (y1 % 2))
    return x0, y0, x1 - x0, y1 - y0


def _f(v):
    return ("%.3f" % v).rstrip("0").rstrip(".") or "0"


def enable_expr(spans):
    return "+".join("between(t,%s,%s)" % (_f(a), _f(b)) for a, b in spans)


def build_graph(placements, in_label="0:v", out_label="vb"):
    """placements: [{"id","kind":static|track,"style","box":(x,y,w,h),"spans":[(a,b)],
    "lr"|"px", "moves":[(t_s,x,y)]}] -> (filter_complex, info). One graph, one encode."""
    if not placements:
        return "[%s]null[%s]" % (in_label, out_label), {"branches": 0}
    cmds = {}
    for n, p in enumerate(placements):
        p["name"] = "tr%d" % n
        if p["kind"] == "track":
            for t, x, y in p["moves"]:
                tgt = ["drawbox"] if p["style"] == "opaque" else ["crop", "overlay"]
                for f in tgt:
                    cmds.setdefault(round(t, 3), []).extend(
                        ["%s@%s x %d" % (f, p["name"], x), "%s@%s y %d" % (f, p["name"], y)])
    parts, cur, n_split = [], "[%s]" % in_label, 0
    if cmds:
        script = ";".join("%s %s" % (_f(t), ",".join(c)) for t, c in sorted(cmds.items()))
        parts.append("%ssendcmd=c='%s'[sc0]" % (cur, script))
        cur = "[sc0]"
    for n, p in enumerate(placements):
        x, y, w, h = p["box"]
        en = enable_expr(p["spans"])
        nxt = "[v%d]" % n if n < len(placements) - 1 else "[%s]" % out_label
        if p["style"] == "opaque":
            parts.append("%sdrawbox@%s=x=%d:y=%d:w=%d:h=%d:color=black:t=fill:enable='%s'%s"
                         % (cur, p["name"], x, y, w, h, en, nxt))
        else:
            eff = ("boxblur=lr=%d:lp=1" % p["lr"]) if p["style"] == "boxblur" \
                else ("pixelize=w=%d:h=%d" % (p["px"], p["px"]))
            n_split += 1
            parts.append("%ssplit[a%d][b%d];[b%d]crop@%s=w=%d:h=%d:x=%d:y=%d,%s:enable='%s'[bl%d];"
                         "[a%d][bl%d]overlay@%s=x=%d:y=%d:enable='%s'%s"
                         % (cur, n, n, n, p["name"], w, h, x, y, eff, en, n, n, n, p["name"], x, y,
                            en, nxt))
        cur = nxt
    return ";".join(parts), {"branches": len(placements), "blur_branches": n_split,
                             "sendcmd_times": len(cmds)}


def make_placements(regions, tmap, frame_w, frame_h):
    """Regions + time map -> graph placements. Static regions with the same padded box and style are
    one branch whose enable= is the union of all their spans (across scenes)."""
    statics, placements, notes = {}, [], []
    for reg in regions:
        mode = reg.get("mode", "static")
        spans = []
        for s in reg["spans"]:
            sc = s[2] if len(s) == 3 else reg.get("scene")
            sp = tmap.span(sc, s[0], s[1])
            if sp:
                spans.append((sc, s, sp))
        if not spans:
            continue
        style = reg.get("style") or "opaque"
        th = reg.get("text_h") or reg["bbox"][3]
        if mode == "track":
            boxes = [pad_box(k[1:], reg["pad"], frame_w, frame_h) for k in reg["keyframes"]]
            w, h = max(b[2] for b in boxes), max(b[3] for b in boxes)
            sc0 = spans[0][0]
            fm = clip_frame_ms(tmap.clips, sc0)
            moves, prev_t = [], None
            for k, b in zip(reg["keyframes"], boxes):
                eff = k[0] - fm / 2.0 if prev_t is None else (prev_t + k[0]) / 2.0
                prev_t = k[0]
                tt = tmap.t(sc0, max(eff, 0.0)) if tmap.usable(sc0) else None
                if tt is not None:
                    moves.append((max(tt, 0.0), min(b[0], frame_w - w), min(b[1], frame_h - h)))
            box = (moves[0][1], moves[0][2], w, h) if moves else None
            if box is None:
                continue
            pl = {"id": reg["id"], "kind": "track", "style": style, "box": box,
                  "spans": [sp for _, _, sp in spans], "moves": moves}
            lr_h = h
        else:
            box = pad_box(reg["bbox"], reg["pad"], frame_w, frame_h)
            pl = {"id": reg["id"], "kind": "static", "style": style, "box": box,
                  "spans": [sp for _, _, sp in spans]}
            lr_h = box[3]
        if style == "boxblur":
            lr = strength("boxblur", th)
            if lr > min(box[2], lr_h) // 4:  # ffmpeg limit (chroma radius): too small a region
                notes.append("%s: boxblur radius %d does not fit its box; drawn opaque" % (reg["id"], lr))
                pl["style"] = "opaque"
            pl["lr"] = lr
        elif style == "pixelize":
            pl["px"] = strength("pixelize", th)
        if pl["kind"] == "static":
            key = (pl["style"], pl["box"], pl.get("lr"), pl.get("px"))
            if key in statics:
                statics[key]["spans"].extend(pl["spans"])
                statics[key]["ids"].append(pl["id"])
                continue
            pl["ids"] = [pl["id"]]
            statics[key] = pl
        placements.append(pl)
    for pl in placements:
        pl["spans"] = merge_pairs(pl["spans"])
    return placements, notes


def merge_pairs(spans, gap=0.0):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(s) for s in out]


# =========================================================================== project access
def slug_dir_of(pj_path):
    return os.path.dirname(pj_path)


def load_ctx(args):
    class A:
        pass
    a = A()
    a.project, a.slug = getattr(args, "project", None), getattr(args, "slug", None)
    try:
        path = project.project_path(a)
        data = project.read_project(path)
    except project.CliError as e:
        raise BlurError(e.code, e.msg)
    return path, data


def frame_size(clips, scenes):
    sizes = {(int(clips[s]["w"]), int(clips[s]["h"])) for s in scenes if s in clips}
    if len(sizes) != 1:
        raise BlurError(2, "cannot determine one source frame size from #events.clips (got %s)"
                        % sorted(sizes))
    return next(iter(sizes))


def load_privacy(slug_dir):
    try:
        import config
        p = os.path.join(slug_dir, "demo.yaml")
        cfg = config.load_config(p) if os.path.exists(p) else config.defaults()
        return cfg.get("privacy", {})
    except Exception:  # config problems are reported by config.py validate, not here
        return {}


# =========================================================================== commands: plan / graph
def cmd_plan(args):
    path, data = load_ctx(args)
    blur = data.get("blur") or {}
    regions = blur.get("regions") if isinstance(blur, dict) else None
    if not isinstance(regions, list):
        raise BlurError(2, "#blur has no regions list (privacy-blurrer writes candidates first)")
    clips = (data.get("events") or {}).get("clips") or {}
    new, report = plan_regions(regions, clips, args.merge_gap_ms, args.cover_max)
    doc = {"schema": 2, "space": "source", "time": "scene", "regions": new}
    for k in ("transforms",):
        if k in blur:
            doc[k] = blur[k]
    res = dict(report, status="ok", dry_run=args.dry_run)
    if not args.dry_run:
        res["version"] = project.store_key(path, "blur", project.OWNERS["blur"], doc, args.timeout)
    else:
        res["regions"] = new
    return res, 0


def cmd_graph(args):
    path, data = load_ctx(args)
    blur = data.get("blur") or {}
    clips = (data.get("events") or {}).get("clips") or {}
    if args.space == "final":
        require_safe_timeline(data, clips)
    norm = load_regions(blur, clips)
    tmap = TimeMap(args.space, clips, data.get("timeline"), args.scene)
    scenes = {s[2] if len(s) == 3 else r.get("scene") for r in norm for s in r["spans"]}
    scenes = [s for s in scenes if tmap.usable(s)] or list(clips)[:1]
    fw, fh = frame_size(clips, scenes)
    pls, notes = make_placements(norm, tmap, fw, fh)
    fc, info = build_graph(pls, args.in_label, args.out_label)
    res = dict(info, status="ok", space=args.space, aspect=args.aspect, filter_complex=fc,
               in_label=args.in_label, out_label=args.out_label, frame=[fw, fh], notes=notes)
    return res, 0


def _as_v2(regions, clips, unmaskable=False):
    """Graph/verify accept #blur as plan wrote it; a schema 1 blur is planned in memory first
    (nothing is written, nothing dropped). Unmaskable surfaces are NOT added here: they must already
    be in the stored plan (load_regions refuses otherwise)."""
    if regions and all(isinstance(r, dict) and r.get("mode") in ("static", "track", "cover")
                       and "spans" in r for r in regions):
        return regions
    return plan_regions(regions, clips, unmaskable=unmaskable)[0]


# =========================================================================== frame decoding
_VSYNC = None


def vsync_args(ffmpeg="ffmpeg"):
    """`-fps_mode passthrough` (ffmpeg >= 5.1) else `-vsync 0`."""
    global _VSYNC
    if _VSYNC is None:
        r = rbm.run_bounded([ffmpeg, "-version"], wall=10)
        m = re.search(r"version\D*(\d+)\.(\d+)", r.get("stdout_tail", ""))
        new = bool(m) and (int(m.group(1)), int(m.group(2))) >= (5, 1)
        _VSYNC = ["-fps_mode", "passthrough"] if new else ["-vsync", "0"]
    return _VSYNC


def select_script(times):
    """select= expression: for each requested time T the first frame at/after T (VFR safe)."""
    terms = ["if(isnan(prev_selected_t),1,lt(prev_selected_t,%s))*gte(t,%s)" % (_f(t), _f(t))
             for t in times]
    return "select='%s',showinfo" % "+".join(terms)


def probe(video, ffprobe="ffprobe"):
    r = rbm.run_bounded([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=width,height,r_frame_rate,avg_frame_rate:format=duration",
                         "-of", "json", video], wall=30)
    if r["status"] != "ok" or r["tool_rc"] != 0:
        raise BlurError(2 if r["status"] == "ok" else 70, "ffprobe failed on %s: %s"
                        % (video, (r.get("stderr_tail") or r.get("error") or r["status"])[-200:]))
    j = json.loads(r["stdout_tail"])
    st = j["streams"][0]
    num, _, den = (st.get("avg_frame_rate") or st["r_frame_rate"]).partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else DEFAULT_FPS
    return {"w": int(st["width"]), "h": int(st["height"]), "fps": fps or DEFAULT_FPS,
            "duration": float(j["format"]["duration"])}


class FrameStream:
    """One ffmpeg process piping the selected frames (rgb24) of `video`; yields (pts_s, bytes).
    The process is bounded: hard wall and stall (no frame for `stall` s) -> group kill."""

    def __init__(self, video, times, w, h, wall, stall=30.0, ffmpeg="ffmpeg", tmpdir=None):
        self.video, self.times, self.w, self.h = video, sorted(set(times)), w, h
        self.wall, self.stall, self.ffmpeg, self.tmpdir = wall, stall, ffmpeg, tmpdir
        self.reason = None
        self.pts = []

    def __iter__(self):
        if not self.times:
            return
        d = self.tmpdir or tempfile.mkdtemp(prefix="blur-sel-")
        script = os.path.join(d, "select.txt")
        with open(script, "w", encoding="utf-8") as f:
            f.write(select_script(self.times))
        cmd = [self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "info", "-i", self.video,
               "-filter_script:v", script] + vsync_args(self.ffmpeg) + \
              ["-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        size = self.w * self.h * 3
        b = rbm.Bounded(cmd, self.wall, self.stall, "verify-decode")
        b.__enter__()
        pts = self.pts

        def drain():
            for raw in iter(b.proc.stderr.readline, b""):
                m = re.search(rb"pts_time:\s*([0-9.]+)", raw)
                if m:
                    pts.append(float(m.group(1)))
                    b.touch()

        th = threading.Thread(target=drain, daemon=True)
        th.start()
        try:
            k = 0
            while True:
                buf = b.proc.stdout.read(size)
                if len(buf) < size:
                    break
                b.touch()
                for _ in range(100):  # showinfo (stderr) can lag the pipe by a moment
                    if len(pts) > k:
                        break
                    time.sleep(0.01)
                yield (pts[k] if len(pts) > k else -1.0), buf
                k += 1
        finally:
            b.__exit__(None, None, None)
            self.reason = b.reason
            if not self.tmpdir:
                shutil.rmtree(d, ignore_errors=True)


def crop_rgb(buf, w, x, y, cw, ch):
    return b"".join(buf[((y + j) * w + x) * 3:((y + j) * w + x + cw) * 3] for j in range(ch))


def montage(crops, min_h=MIN_ROI_H, gap=8):
    """Stack crops (cw, ch, bytes) vertically on a mid-gray canvas, each at least min_h high.
    Returns (w, h, bytes, [(y0, y1)] band per crop)."""
    gray = bytes([128])
    w = max(c[0] for c in crops)
    rows, bands, y = [], [], 0
    for cw, ch, data in crops:
        hh = max(ch, min_h)
        for j in range(hh):
            if j < ch:
                row = data[j * cw * 3:(j + 1) * cw * 3] + gray * (3 * (w - cw))
            else:
                row = gray * (3 * w)
            rows.append(row)
        bands.append((y, y + ch))
        y += hh
        for _ in range(gap):
            rows.append(gray * (3 * w))
        y += gap
    return w, y, b"".join(rows), bands


# =========================================================================== OCR
def make_matcher(patterns, generic_ok=True):
    """Return text -> match_len (0 = no hit). With patterns: regex; without: any readable text."""
    rx = [re.compile(p) for p in patterns]

    def m(text):
        best = 0
        for r in rx:
            for mm in r.finditer(text):
                best = max(best, len(mm.group(0)))
        if not rx and generic_ok:
            alnum = re.findall(r"\w", text)
            best = len(text.strip()) if len(alnum) >= 4 else 0
        return best
    return m


def build_ocr(engine, lang, wall, tmpdir, stall=30.0):
    """OCR callable ocr(rgb, w, h) -> [{"text","box"}]; an object is used as is, 'rapidocr' or
    'python:module:factory' string spawns the worker subprocess (built once, killed on stall)."""
    if callable(engine):
        return engine
    return OcrWorker(engine, lang, wall, tmpdir, stall)


class OcrWorker:
    def __init__(self, engine, lang, wall, tmpdir, stall=30.0):
        self.tmpdir = tmpdir
        cmd = [sys.executable, os.path.abspath(__file__), "ocr-worker", "--engine", engine,
               "--lang", lang or "en", "--call-limit", str(max(stall - 5, 1))]
        self.b = rbm.Bounded(cmd, wall, stall, "ocr-worker", stdin=rbm.subprocess.PIPE)
        self.b.__enter__()
        self.n = 0
        self.err = []
        self.dead = None
        threading.Thread(target=self._drain, daemon=True).start()
        line = self._readline()  # worker says ready once the engine is built (or why not)
        if not line or not line.get("ready"):
            self.close()
            raise BlurError(4, "OCR engine %r unavailable: %s (setup_tools.py --plan blur,qa-ocr)"
                            % (engine, (line or {}).get("error", "worker died")))

    def _drain(self):
        for raw in iter(self.b.proc.stderr.readline, b""):
            s = raw.strip()
            if s.startswith(b"{") and s.endswith(b"}"):
                self.b.touch()
            else:
                self.err.append(raw.decode("utf-8", "replace"))

    def _readline(self):
        raw = self.b.proc.stdout.readline()
        if not raw:
            return None
        self.b.touch()
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def __call__(self, rgb, w, h):
        path = os.path.join(self.tmpdir, "ocr-%d.rgb" % self.n)
        self.n += 1
        with open(path, "wb") as f:
            f.write(rgb)
        try:
            self.b.proc.stdin.write((json.dumps({"file": path, "w": w, "h": h}) + "\n").encode())
            self.b.proc.stdin.flush()
            rep = self._readline()
        except (OSError, ValueError):
            rep = None
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if rep is None:
            raise BlurError(70, "OCR worker died or stalled (%s)" % (self.b.reason or "exit"),
                            [{"id": "ocr-worker", "owner": "plugin", "class": "bug"}])
        if "error" in rep:
            raise BlurError(70, "OCR worker error: %s" % rep["error"])
        return rep["items"]

    def close(self):
        try:
            self.b.proc.stdin.close()
        except OSError:
            pass
        self.b.__exit__(None, None, None)


def load_engine(spec, lang):
    if spec == "rapidocr":
        import numpy as np
        from rapidocr import RapidOCR
        eng = RapidOCR(params={"Global.log_level": "error", "Det.limit_type": "max",
                               "Det.limit_side_len": 960})

        def run(rgb, w, h):
            arr = np.frombuffer(rgb, dtype=np.uint8).reshape(h, w, 3)[:, :, ::-1]
            r = eng(np.ascontiguousarray(arr))
            txts = list(r.txts or ())
            boxes = list(r.boxes) if r.boxes is not None else [None] * len(txts)
            out = []
            for t, bx in zip(txts, boxes):
                box = None
                if bx is not None:
                    xs, ys = [float(p[0]) for p in bx], [float(p[1]) for p in bx]  # numpy floats are not JSON
                    box = [min(xs), min(ys), max(xs), max(ys)]
                out.append({"text": str(t), "box": box})
            return out
        return run
    if spec == "tesseract":
        import numpy as np
        import pytesseract
        tl = {"en": "eng"}.get(lang or "en", lang or "eng")

        def run_t(rgb, w, h):
            arr = np.frombuffer(rgb, dtype=np.uint8).reshape(h, w, 3)
            d = pytesseract.image_to_data(arr, lang=tl, output_type=pytesseract.Output.DICT)
            lines = {}
            for i, t in enumerate(d["text"]):
                if not str(t).strip() or float(d["conf"][i]) < 0:
                    continue
                k = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
                x0, y0, x1, y1 = d["left"][i], d["top"][i], d["left"][i] + d["width"][i], d["top"][i] + d["height"][i]
                e = lines.setdefault(k, {"words": [], "box": [x0, y0, x1, y1]})
                e["words"].append(t)
                e["box"] = [min(e["box"][0], x0), min(e["box"][1], y0), max(e["box"][2], x1), max(e["box"][3], y1)]
            return [{"text": " ".join(e["words"]), "box": e["box"]} for e in lines.values()]
        return run_t
    if spec.startswith("python:"):
        import importlib
        _, mod, fn = spec.split(":", 2)
        return getattr(importlib.import_module(mod), fn)(lang)
    raise ValueError("unknown OCR engine %r" % spec)


def cmd_ocr_worker(args):
    """stdin: {"file","w","h"} per line; stdout: {"ready":true} then {"items":[...]} per request.
    stderr: JSON heartbeat every 2 s, but only while the current call is younger than --call-limit,
    so a hung native call goes silent and the parent's stall timeout kills us."""
    out = sys.stdout
    state = {"busy": None}
    try:
        eng = load_engine(args.engine, args.lang)
    except Exception as e:  # noqa: BLE001 - report to the parent instead of a traceback
        out.write(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}) + "\n")
        out.flush()
        return 4

    def tick():
        while True:
            busy = state["busy"]
            if busy is None or time.monotonic() - busy < args.call_limit:
                sys.stderr.write(json.dumps({"hb": "ocr-worker", "t": round(time.time(), 1)}) + "\n")
                sys.stderr.flush()
            time.sleep(1.0)

    threading.Thread(target=tick, daemon=True).start()
    out.write(json.dumps({"ready": True}) + "\n")
    out.flush()
    for line in sys.stdin:
        req = json.loads(line)
        state["busy"] = time.monotonic()
        try:
            with open(req["file"], "rb") as f:
                rgb = f.read()
            items = eng(rgb, req["w"], req["h"])
            out.write(json.dumps({"items": items}) + "\n")
        except Exception as e:  # noqa: BLE001
            out.write(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}) + "\n")
        out.flush()
        state["busy"] = None
    return 0


# =========================================================================== verify
def default_transform(aspect, src, out):
    """source px -> output px: uniform scale, centred; cover-crop when the aspect differs."""
    sw, sh = src
    ow, oh = out
    s = max(ow / float(sw), oh / float(sh)) if abs(ow / oh - sw / sh) > 0.01 else ow / float(sw)
    return {"scale": s, "ox": (ow - sw * s) / 2.0, "oy": (oh - sh * s) / 2.0}


MOTION_REMAP = ("zoom", "pan", "reframe")
CONTROL_TEXT = "Invoice 48213 Acme Corp"


def _valid_tr(t):
    return isinstance(t, dict) and all(_num(t.get(k)) for k in ("scale", "ox", "oy")) and t["scale"] > 0


def motion_remaps(motion, aspect):
    """#motion effects (zoom / pan / reframe) that move source pixels in `aspect`'s output."""
    out = []
    for e in (motion or {}).get("effects") or []:
        if not isinstance(e, dict) or e.get("type") not in MOTION_REMAP:
            continue
        asp = (e.get("params") or {}).get("aspects")
        if not asp or aspect in asp:
            out.append(e)
    return out


def resolve_transform(blur, motion, aspect, src, out):
    """Mapping source px -> output px for `aspect` (R-05). The default (uniform scale, centred) is only
    right for the same aspect ratio and no motion remap; otherwise #blur.transforms.<aspect> written by
    the render step (blur.py set-transform) is required, else exit 2. A zoom/pan needs a `segments`
    key (may be empty) proving the render step accounted for it."""
    tr = (blur.get("transforms") or {}).get(aspect) if isinstance(blur, dict) else None
    if tr is not None and not _valid_tr(tr):
        raise BlurError(2, "#blur.transforms.%s is not {scale>0, ox, oy[, segments]}" % aspect,
                        [{"id": "transforms.%s" % aspect, "owner": "render-engineer", "class": "needs-input"}])
    differs = abs(out[0] / float(out[1]) - src[0] / float(src[1])) > 0.01
    moves = motion_remaps(motion, aspect)
    if (differs or moves) and tr is None:
        why = "aspect %s needs a reframe" % aspect if differs else "#motion has %d zoom/pan/reframe effect(s)" % len(moves)
        raise BlurError(2, "verify cannot map the blur regions to %s: %s and #blur.transforms.%s is missing; "
                           "the render step must record its mapping with `blur.py set-transform --aspect %s ...`"
                        % (aspect, why, aspect, aspect),
                        [{"id": "transforms.%s" % aspect, "owner": "render-engineer", "class": "needs-input"}])
    if moves and not isinstance(tr.get("segments"), list):
        raise BlurError(2, "#blur.transforms.%s has no `segments` list although #motion zooms/pans this "
                           "aspect: record every zoom window (set-transform --segment) or an empty list"
                        % aspect, [{"id": "transforms.%s" % aspect, "owner": "render-engineer",
                                    "class": "needs-input"}])
    return tr or default_transform(aspect, src, out)


def tr_pieces(tr, spans):
    """Split final-timeline `spans` [(a,b)] (s) by the transform's `segments` [{t0,t1,scale,ox,oy}]:
    [(transform, spans)] (segment mappings first, the base mapping for the rest)."""
    segs = sorted((float(g["t0"]), float(g["t1"]), g) for g in (tr.get("segments") or [])
                  if isinstance(g, dict) and _num(g.get("t0")) and _num(g.get("t1")) and _valid_tr(g)
                  and g["t1"] > g["t0"])
    rest, pieces = list(spans), []
    for a, b, g in segs:
        inside, nxt = [], []
        for x, y in rest:
            lo, hi = max(x, a), min(y, b)
            if hi > lo:
                inside.append((lo, hi))
            if x < min(y, a):
                nxt.append((x, min(y, a)))
            if y > max(x, b):
                nxt.append((max(x, b), y))
        rest = nxt
        if inside:
            pieces.append((g, inside))
    if rest:
        pieces.append((tr, rest))
    return pieces


def map_bbox(b, tr, out_w, out_h):
    x0, y0 = b[0] * tr["scale"] + tr["ox"], b[1] * tr["scale"] + tr["oy"]
    x1, y1 = x0 + b[2] * tr["scale"], y0 + b[3] * tr["scale"]
    x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(out_w, int(math.ceil(x1))), \
        min(out_h, int(math.ceil(y1)))
    return (x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None


def build_rois(regions, tmap, clips, tr, out_wh, fps, patterns_cfg):
    """Output-space ROIs: [{"id","spans":[(a,b)],"boxes":[(t_s, bbox)] | bbox, "matcher"}]. A transform
    with `segments` splits a region into one ROI per mapping window (same id)."""
    ow, oh = out_wh
    rois = []
    sw, sh = frame_size(clips, {s[2] if len(s) == 3 else r.get("scene") for r in regions
                                for s in r["spans"]})
    for reg in regions:
        spans = []
        for s in reg["spans"]:
            sc = s[2] if len(s) == 3 else reg.get("scene")
            sp = tmap.span(sc, s[0], s[1])
            if sp:
                spans.append(sp)
        if not spans:
            continue
        pats = [reg["pattern"]] if reg.get("pattern") else list(patterns_cfg)
        ctrl = ctrl_point(reg, clips)
        for trp, pspans in tr_pieces(tr, merge_pairs(spans)):
            roi = {"id": reg["id"], "spans": merge_pairs(pspans), "pad": reg["pad"],
                   "matcher": make_matcher(pats), "has_pattern": bool(pats),
                   "src_bbox": reg["bbox"], "scene": reg.get("scene"), "ctrl": ctrl}
            if reg.get("mode") == "track":
                sc0 = (reg["spans"][0][2] if len(reg["spans"][0]) == 3 else reg.get("scene"))
                roi["boxes"] = [(tmap.t(sc0, k[0]), map_bbox(pad_box(k[1:], reg["pad"], sw, sh), trp, ow, oh))
                                for k in reg["keyframes"]]
                roi["boxes"] = [(t, bb) for t, bb in roi["boxes"] if bb]
                if not roi["boxes"]:
                    continue
            else:
                bb = map_bbox(pad_box(reg["bbox"], reg["pad"], sw, sh), trp, ow, oh)
                if not bb:
                    continue
                roi["bbox"] = bb
            rois.append(roi)
    return rois


def ctrl_point(reg, clips):
    """(scene, raw clip time in s, source bbox) of the frame used as positive control."""
    s0 = reg["spans"][0]
    sc = s0[2] if len(s0) == 3 else reg.get("scene")
    mid = (s0[0] + s0[1]) / 2.0
    bb = reg["bbox"]
    if reg.get("mode") == "track":
        bb = min(reg["keyframes"], key=lambda k: abs(k[0] - mid))[1:]
    return (sc, (mid + float((clips.get(sc) or {}).get("offset_ms", 0))) / 1000.0, bb)


def roi_box_at(roi, t):
    if "bbox" in roi:
        return roi["bbox"]
    return min(roi["boxes"], key=lambda tb: abs(tb[0] - t))[1]


def sample_schedule(rois, dur, fps, stride_s, fullframe):
    """{time_s: {"rois": [roi,...], "full": bool}} sorted by time."""
    fr = 1.0 / fps
    sched = {}

    def add(t, roi=None, full=False):
        t = round(min(max(t, 0.0), max(dur - fr, 0.0)), 3)
        e = sched.setdefault(t, {"rois": [], "full": False})
        if roi is not None and roi not in e["rois"]:
            e["rois"].append(roi)
        e["full"] = e["full"] or full

    for roi in rois:
        for a, b in roi["spans"]:
            t = a
            while t < b:
                add(t, roi)
                t += ROI_STEP_S
            add(a, roi)
            add(b - fr, roi)
            if "boxes" in roi:  # every frame of a moving span
                for kt, _ in roi["boxes"]:
                    if a <= kt <= b:
                        add(kt, roi)
    if fullframe:
        t = 0.0
        while t < dur:
            add(t, None, True)
            t += stride_s
        add(0.0, None, True)
        add(dur - fr, None, True)
    return dict(sorted(sched.items()))


def similar_text(a, b, min_run=4, min_ratio=0.5):
    """True when two OCR texts share a common run of >= min_run alphanumerics (case-insensitive) or are
    >= min_ratio similar: the blurred text is still (partly) the protected one."""
    import difflib
    x = "".join(re.findall(r"[a-z0-9]", a.lower()))
    y = "".join(re.findall(r"[a-z0-9]", b.lower()))
    if not x or not y:
        return False
    sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
    return sm.find_longest_match(0, len(x), 0, len(y)).size >= min_run or sm.ratio() >= min_ratio


def hit_hash(key, text):
    return hmac_mod.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def run_verify(video, rois, ocr, dur, fps, wh, *, budget_s, stride_s, fullframe, full_matcher,
               controls=None, hmac_key=None, ffmpeg="ffmpeg", clock=time.monotonic, tmpdir=None,
               full_control=None):
    """Core of `blur.py verify` (pure of project access, so tests can drive it). `controls` is
    {roi id: bool} from the positive-control phase (None = not required); `full_control` is the
    full-frame OCR positive control (rendered known text read back; None = not required). A run that
    OCR-sampled nothing is `incomplete`, never `pass`."""
    t0 = clock()
    ow, oh = wh
    sched = sample_schedule(rois, dur, fps, stride_s, fullframe)
    total = sum(len(e["rois"]) for e in sched.values()) + sum(1 for e in sched.values() if e["full"])
    sampled = full_done = 0
    hits = []
    incomplete = None
    stream = FrameStream(video, list(sched), ow, oh, wall=max(budget_s - (clock() - t0), 1.0) + 5.0,
                         ffmpeg=ffmpeg, tmpdir=tmpdir)
    times = sorted(sched)
    seen = 0           # requested sample times delivered so far
    prev_pts = -1.0
    it = iter(stream)
    for pts, buf in it:
        if clock() - t0 >= budget_s:
            incomplete = "budget"
            break
        # this frame answers every requested time in (prev_pts, pts]
        ents = [sched[t] for t in times if prev_pts < t <= pts + 1e-6]
        prev_pts = pts
        seen += len(ents)
        rs, full = [], False
        for e in ents:
            for roi in e["rois"]:
                if roi not in rs:
                    rs.append(roi)
            full = full or e["full"]
        if rs:
            crops = []
            for roi in rs:
                x, y, w, h = roi_box_at(roi, pts)
                crops.append((w, h, crop_rgb(buf, ow, x, y, w, h)))
            mw, mh, mbuf, bands = montage(crops)
            items = ocr(mbuf, mw, mh)
            for roi, (y0, y1) in zip(rs, bands):
                texts = [it_["text"] for it_ in items if it_.get("box") is None
                         or y0 - 2 <= (it_["box"][1] + it_["box"][3]) / 2 <= y1 + 2]
                cands = texts
                if roi.get("ctrl_text") and not roi.get("has_pattern"):
                    # generic matcher (no pattern): blur fuzz is not a leak. Count only text that shares
                    # a >= 4 char run or >= 50% similarity with what the raw crop reads (R-16)
                    cands = [t for t in texts if similar_text(t, roi["ctrl_text"])]
                n = max([roi["matcher"](t) for t in cands] or [0])
                if n:
                    hit = {"region": roi["id"], "t_ms": int(round(pts * 1000)), "match_len": n}
                    if hmac_key:
                        hit["hmac"] = hit_hash(hmac_key, max(cands, key=roi["matcher"]))
                    hits.append(hit)
            sampled += sum(len(e["rois"]) for e in ents)
        if full:
            if clock() - t0 >= budget_s:
                incomplete = "budget"
                break
            items = ocr(buf, ow, oh)
            n = max([full_matcher(i["text"]) for i in items] or [0])
            full_done += 1
            sampled += sum(1 for e in ents if e["full"])
            if n:
                hit = {"region": "fullframe", "t_ms": int(round(pts * 1000)), "match_len": n}
                if hmac_key:
                    hit["hmac"] = hit_hash(hmac_key, max((i["text"] for i in items), key=full_matcher))
                hits.append(hit)
    it.close()
    if stream.reason in ("wall", "stall") and not incomplete:
        incomplete = stream.reason
    elif not incomplete and seen < len(times):
        incomplete = "frames"  # the decode ended before delivering every requested sample
    ctrl = controls if controls is not None else {}
    failed_ctrl = [r["id"] for r in rois if controls is not None and not ctrl.get(r["id"])]
    if fullframe and full_control is False:
        failed_ctrl.append("fullframe")
    if not hits and not incomplete and (total == 0 or sampled == 0):
        incomplete = "no-samples"  # nothing was OCR'd: that is no evidence (S-05)
    if hits:
        verdict = "leak"
    elif incomplete:
        verdict = "incomplete"
    elif failed_ctrl:
        verdict = "inconclusive"
    else:
        verdict = "pass"
    return {"verdict": verdict, "sampled": sampled, "total": total,
            "seconds": round(clock() - t0, 2),
            "fullframe": {"sampled": full_done, "stride_s": stride_s if fullframe else None},
            "positive_control": dict(
                ({r["id"]: bool(ctrl.get(r["id"])) for r in rois} if controls is not None else {}),
                **({"fullframe": bool(full_control)} if full_control is not None else {})),
            "hits": hits, "incomplete_reason": incomplete,
            "not_machine_readable": verdict == "pass"}


def positive_controls(rois, clips, slug_dir, ocr, budget_s, ffmpeg="ffmpeg", tmpdir=None,
                      clock=time.monotonic):
    """OCR one UNBLURRED crop (from the raw clip) of every region: it must read something the region's
    matcher accepts, else the OCR/pattern is no evidence. Each roi carries "ctrl": (scene, clip time
    s, source bbox). Crops live only in memory / tmpdir."""
    t0 = clock()
    res, by_clip, seen, ctext = {}, {}, set(), {}
    for roi in rois:
        if roi["id"] in seen:  # a region split by transform segments has one control
            continue
        seen.add(roi["id"])
        sc, t_s, _ = roi["ctrl"]
        info = clips.get(sc) or {}
        f = os.path.join(slug_dir, info["file"]) if info.get("file") else None
        if not f or not os.path.exists(f):
            res[roi["id"]] = False  # raw clip gone (raw_retention) or never recorded: no control
            continue
        by_clip.setdefault(sc, []).append(roi)
    for sc, lst in by_clip.items():
        info = clips[sc]
        f = os.path.join(slug_dir, info["file"])
        w, h = int(info["w"]), int(info["h"])
        stream = FrameStream(f, [r["ctrl"][1] for r in lst], w, h,
                             wall=max(budget_s - (clock() - t0), 1.0) + 5.0, ffmpeg=ffmpeg,
                             tmpdir=tmpdir)
        it = iter(stream)
        frames = list(it)
        it.close()
        for roi in lst:
            if not frames:
                res[roi["id"]] = False
                continue
            _, t_s, bb = roi["ctrl"]
            _, buf = min(frames, key=lambda fr: abs(fr[0] - t_s))
            x, y, bw, bh = pad_box(bb, roi["pad"], w, h)
            mw, mh, mbuf, _ = montage([(bw, bh, crop_rgb(buf, w, x, y, bw, bh))])
            if clock() - t0 >= budget_s:  # every OCR call is budget-checked (R-14)
                raise BlurError(3, "budget of %.0f s exceeded during the positive controls: verdict "
                                   "incomplete" % budget_s)
            readable = [i["text"] for i in ocr(mbuf, mw, mh) if roi["matcher"](i["text"])]
            res[roi["id"]] = bool(readable)
            if readable:  # kept in memory only (never stored): what the UNBLURRED region reads as
                ctext[roi["id"]] = max(readable, key=len)
    for roi in rois:
        if roi["id"] in ctext:
            roi["ctrl_text"] = ctext[roi["id"]]
    return res


def hmac_key_for(slug_dir, create=False):
    p = os.path.join(slug_dir, ".secret", "key")
    if os.path.exists(p):
        with open(p, "rb") as f:
            return f.read()
    if not create:
        return None
    d = os.path.dirname(p)
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    key = secrets_mod.token_bytes(32)
    try:  # created 0600 atomically: there is no window with a wider mode
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:  # a concurrent run won the race: use its key
        with open(p, "rb") as f:
            return f.read()
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def fullframe_control(ocr, wh, ffmpeg, tmpdir):
    """Positive control of the full-frame OCR tier: render a frame of the OUTPUT size with a known text
    and require the OCR to read readable text off it. Failure = the full-frame pass is blind."""
    ow, oh = wh
    dst = os.path.join(tmpdir, "fullframe-control.rgb")
    vf = ("drawtext=text='%s':fontsize=%d:fontcolor=black:x=(w-text_w)/2:y=(h-text_h)/2"
          % (CONTROL_TEXT, max(oh // 10, 24)))
    r = rbm.run_bounded([ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i",
                         "color=c=white:s=%dx%d:r=1:d=1" % (ow, oh), "-vf", vf, "-frames:v", "1",
                         "-f", "rawvideo", "-pix_fmt", "rgb24", dst], wall=30, stall=20,
                        heartbeat="ffmpeg")
    try:
        with open(dst, "rb") as f:
            rgb = f.read()
    except OSError:
        return False
    if r["status"] != "ok" or r["tool_rc"] != 0 or len(rgb) != ow * oh * 3:
        return False
    readable = make_matcher([], True)
    return any(readable(i.get("text", "")) for i in ocr(rgb, ow, oh))


def resolve_ocr(args, sdir):
    """--ocr, else demo.yaml tools.ocr (qa-ocr -> rapidocr, qa-ocr-tesseract -> tesseract,
    none -> none, null -> rapidocr)."""
    if getattr(args, "ocr", None):
        return args.ocr
    try:
        import config
        p = os.path.join(sdir, "demo.yaml")
        cfg = config.load_config(p) if os.path.exists(p) else config.defaults()
        return {"qa-ocr": "rapidocr", "qa-ocr-tesseract": "tesseract", "none": "none"}.get(
            (cfg.get("tools") or {}).get("ocr"), "rapidocr")
    except Exception:  # noqa: BLE001 - config problems are config.py validate's business
        return "rapidocr"


def reset_checks(path, aspect):
    """Verify starts: nothing may stay `pass` while the new verdict is unknown (R-01). pass -> false,
    this aspect's old verdict and results.blur are dropped."""
    def tf(data):
        ck = dict(data["checks"]) if isinstance(data.get("checks"), dict) else {}
        ck["schema"] = 2
        ck["pass"] = False
        res = dict(ck["results"]) if isinstance(ck.get("results"), dict) else {}
        res.pop("blur", None)
        ck["results"] = res
        bl = dict(ck["blur"]) if isinstance(ck.get("blur"), dict) else {}
        bl.pop(aspect, None)
        ck["blur"] = bl
        return ck
    project.write_checks(path, None, writer="blur.py", transform=tf)


def store_verdict(path, aspect, entry):
    """Write one aspect's verdict. `pass` stays false: only checks.py may set it true."""
    def tf(data):
        ck = dict(data["checks"]) if isinstance(data.get("checks"), dict) else {}
        ck["schema"] = 2
        ck["pass"] = False
        res = dict(ck["results"]) if isinstance(ck.get("results"), dict) else {}
        res.pop("blur", None)
        ck["results"] = res
        bl = dict(ck["blur"]) if isinstance(ck.get("blur"), dict) else {}
        bl[aspect] = entry
        ck["blur"] = bl
        return ck
    return project.write_checks(path, None, writer="blur.py", transform=tf)


def video_fingerprint(video, sdir):
    """{size, mtime_ns, ino[, sha256]} of the verified file + its path relative to the slug folder.
    sha256 goes through project.py's cache (computed only when the triple changed), skipped > 512 MB."""
    fp = project.stat_fingerprint(video)
    if fp is None:
        return None, None
    rel = os.path.relpath(os.path.realpath(video), os.path.realpath(sdir))
    inside = not rel.startswith("..") and not os.path.isabs(rel)
    if inside and fp["size"] <= (512 << 20):
        try:
            fp = project.file_fingerprint(sdir, rel, with_sha=True)
        except (project.CliError, OSError):
            pass
    return fp, (rel.replace(os.sep, "/") if inside else os.path.abspath(video))


def verdict_inputs(data):
    """Upstream versions a verdict is built on: stale as soon as any of them changes."""
    return project.current_inputs(data, ("blur", "timeline", "events"))


def load_regions(blur, clips):
    """Planned regions; a clip with unmaskable[] no region covers is exit 2 (fail closed, R-04)."""
    regions = _as_v2((blur.get("regions") if isinstance(blur, dict) else None) or [], clips)
    unc = uncovered_unmaskable(regions, clips)
    if unc:
        raise BlurError(2, "needs-input: %d unmaskable surface(s) have no blur region (%s): run "
                           "`blur.py plan` (capture-operator must emit bbox + t_start/t_end)"
                        % (len(unc), "; ".join("%s#%d %s" % (u["scene"], u["index"], u["reason"])
                                               for u in unc[:4])),
                        [{"id": "unmaskable:%s#%d" % (u["scene"], u["index"]), "owner": "privacy-blurrer",
                          "class": "needs-input"} for u in unc])
    return regions


def require_safe_timeline(data, clips):
    bad = project.unsafe_scenes(data.get("timeline"), clips)
    if bad:
        raise BlurError(2, "timeline scene(s) start before the clip's verified-safe time: %s "
                           "(sync-editor: `in` >= events.clips[sid].safe_from_ms)"
                        % ", ".join("%s in=%s < safe_from_ms=%s" % (b["scene"], b["in"], b["safe_from_ms"])
                                    for b in bad),
                        [{"id": b["scene"], "owner": "sync-editor", "class": "needs-input"} for b in bad])


def cmd_verify(args, ocr=None):
    path, data = load_ctx(args)
    sdir = slug_dir_of(path)
    if os.path.exists(path) and not args.dry_run:
        reset_checks(path, args.aspect)  # pass false + old verdict gone before anything can fail (R-01)
    if shutil.which(args.ffmpeg) is None:
        raise BlurError(4, "ffmpeg not found (setup_tools.py --plan capture)")
    clips = (data.get("events") or {}).get("clips") or {}
    require_safe_timeline(data, clips)
    blur = data.get("blur") or {}
    regions = load_regions(blur, clips)
    priv = load_privacy(sdir)
    real = priv.get("data_mode", "real-redacted") != "seeded"
    cfg_patterns = list(priv.get("regexes", [])) + [re.escape(v) for v in priv.get("seed_values", [])]
    cfg_patterns += list(args.pattern or [])
    info = probe(args.video, args.ffprobe)
    budget = args.budget_s or (BUDGET_REAL_S if real else BUDGET_SEEDED_S)
    tmap = TimeMap("final", clips, data.get("timeline")) if regions else None
    sw, sh = frame_size(clips, {s[2] if len(s) == 3 else r.get("scene") for r in regions
                                for s in r["spans"]}) if regions else (info["w"], info["h"])
    tr = resolve_transform(blur, data.get("motion"), args.aspect, (sw, sh), (info["w"], info["h"])) \
        if regions else default_transform(args.aspect, (sw, sh), (info["w"], info["h"]))
    rois = build_rois(regions, tmap, clips, tr, (info["w"], info["h"]), info["fps"], cfg_patterns) \
        if regions else []
    stride = args.fullframe_stride_s
    fullframe = True  # seeded too: seed_values are searched full-frame (S-05)
    if args.dry_run:
        sched = sample_schedule(rois, info["duration"], info["fps"], stride, fullframe)
        return {"status": "ok", "dry_run": True, "rois": len(rois), "frames": len(sched),
                "ocr_calls": sum(len(e["rois"]) > 0 for e in sched.values()) +
                sum(e["full"] for e in sched.values()), "budget_s": budget}, 0
    fp0, vrel = video_fingerprint(args.video, sdir)
    engine = resolve_ocr(args, sdir) if ocr is None else "injected"
    t0 = time.monotonic()
    if engine == "none":  # no OCR tool: the aspect cannot be verified, that is not exit 4 (R-10)
        res = {"verdict": "inconclusive", "sampled": 0, "total": 0, "seconds": 0.0,
               "fullframe": {"sampled": 0, "stride_s": None}, "positive_control": {"ocr": False},
               "hits": [], "incomplete_reason": None, "not_machine_readable": False,
               "budget_s": budget, "note": "tools.ocr is none: no OCR, the verdict is inconclusive"}
    else:
        tmp = tempfile.mkdtemp(prefix="blur-verify-")
        own = None
        try:
            if ocr is None:
                own = OcrWorker(engine, args.lang, budget + 10, tmp)
                ocr = own
            controls = positive_controls(rois, clips, sdir, ocr, budget, args.ffmpeg, tmp) if rois else {}
            full_ctrl = fullframe_control(ocr, (info["w"], info["h"]), args.ffmpeg, tmp)
            key = hmac_key_for(sdir, create=args.hmac) if (args.hmac or os.path.exists(
                os.path.join(sdir, ".secret", "key"))) else None
            remaining = max(budget - (time.monotonic() - t0), 1.0)
            res = run_verify(args.video, rois, ocr, info["duration"], info["fps"],
                             (info["w"], info["h"]), budget_s=remaining, stride_s=stride,
                             fullframe=fullframe, full_matcher=make_matcher(cfg_patterns, generic_ok=False)
                             if cfg_patterns else make_matcher(BUILTIN_PATTERNS),
                             controls=controls, hmac_key=key, ffmpeg=args.ffmpeg, tmpdir=tmp,
                             full_control=full_ctrl)
            res["seconds"] = round(time.monotonic() - t0, 2)
            res["budget_s"] = budget
        finally:
            if own:
                own.close()
            shutil.rmtree(tmp, ignore_errors=True)  # raw crops / frames never outlive the run
    fp1 = project.stat_fingerprint(args.video)
    if fp0 is None or not project.same_fingerprint(fp0, fp1):
        if res["verdict"] != "leak":  # a leak stays a leak; anything else on a moving file is no evidence
            res["verdict"] = "incomplete"
            res["incomplete_reason"] = "video-changed"
    code = {"pass": 0, "leak": EXIT["leak"], "inconclusive": EXIT["finding"],
            "incomplete": EXIT["incomplete"]}[res["verdict"]]
    failures = []
    if res["verdict"] in ("leak", "inconclusive"):
        failures = [{"id": h["region"], "owner": OWNER, "class": res["verdict"]} for h in res["hits"]] \
            or [{"id": "ocr" if engine == "none" else "positive_control", "owner": OWNER,
                 "class": "inconclusive"}]
    out = {"status": res["verdict"], "aspect": args.aspect, "failures": failures, **res}
    if os.path.exists(path):
        entry = {k: res[k] for k in ("verdict", "sampled", "total", "seconds", "fullframe",
                                     "positive_control", "hits")}
        entry.update({"file": fp0, "video": vrel, "inputs": verdict_inputs(data),
                      "incomplete_reason": res.get("incomplete_reason")})
        out["checks_version"] = store_verdict(path, args.aspect, entry)
    return out, code


def cmd_set_transform(args):
    """The render step records its source->output mapping for one aspect (R-05)."""
    path, data = load_ctx(args)
    if args.identity:
        tr = {"scale": 1.0, "ox": 0.0, "oy": 0.0}
    else:
        if args.scale is None or args.ox is None or args.oy is None:
            raise BlurError(2, "set-transform needs --scale --ox --oy (or --identity)")
        tr = {"scale": args.scale, "ox": args.ox, "oy": args.oy}
    if not _valid_tr(tr):
        raise BlurError(2, "--scale must be > 0")
    segs = []
    for t0, t1, sc, ox, oy in args.segment or []:
        g = {"t0": t0, "t1": t1, "scale": sc, "ox": ox, "oy": oy}
        if t1 <= t0 or not _valid_tr(g):
            raise BlurError(2, "bad --segment %s" % [t0, t1, sc, ox, oy])
        segs.append(g)
    if args.segment is not None or args.zoom_free:
        tr["segments"] = segs
    blur = dict(data.get("blur") or {})
    tfs = dict(blur.get("transforms") or {})
    tfs[args.aspect] = tr
    blur["transforms"] = tfs
    blur.setdefault("schema", 2)
    blur.setdefault("regions", [])
    ver = project.store_key(path, "blur", project.OWNERS["blur"], blur, args.timeout)
    return {"status": "ok", "aspect": args.aspect, "transform": tr, "version": ver}, 0


# =========================================================================== preview
def cmd_preview(args, ocr=None):
    path, data = load_ctx(args)
    sdir = slug_dir_of(path)
    clips = (data.get("events") or {}).get("clips") or {}
    blur = data.get("blur") or {}
    regions = load_regions(blur, clips)
    priv = load_privacy(sdir)
    pats = list(priv.get("regexes", [])) + [re.escape(v) for v in priv.get("seed_values", [])]
    if args.dry_run:
        return {"status": "ok", "dry_run": True, "regions": len(regions)}, 0
    engine = resolve_ocr(args, sdir) if ocr is None else "injected"
    if engine == "none":
        return {"status": "inconclusive", "positive_control": {"ocr": False}, "contact_sheets": {},
                "failures": [{"id": "ocr", "owner": OWNER, "class": "inconclusive"}],
                "note": "tools.ocr is none: the positive control cannot run"}, EXIT["finding"]
    tmp = tempfile.mkdtemp(prefix="blur-preview-")
    own = None
    try:
        if ocr is None:
            own = OcrWorker(engine, args.lang, 120, tmp)
            ocr = own
        rois = []
        for reg in regions:
            rois.append({"id": reg["id"], "pad": reg["pad"], "ctrl": ctrl_point(reg, clips),
                         "matcher": make_matcher([reg["pattern"]] if reg.get("pattern") else pats)})
        controls = positive_controls(rois, clips, sdir, ocr, 120, args.ffmpeg, tmp)
        sheets = contact_sheets(regions, clips, sdir, args.ffmpeg)
    finally:
        if own:
            own.close()
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [k for k, v in controls.items() if not v]
    return {"status": "ok" if not bad else "inconclusive", "positive_control": controls,
            "contact_sheets": sheets,
            "failures": [{"id": b, "owner": OWNER, "class": "inconclusive"} for b in bad]}, \
        (0 if not bad else EXIT["finding"])


def contact_sheets(regions, clips, sdir, ffmpeg):
    """One masked contact sheet per scene: the blur graph is applied BEFORE the frame is saved, so
    the sheet never shows unmasked pixels (G3 shows only this)."""
    out = {}
    pdir = os.path.join(sdir, "media", "preview")
    for sc in sorted({s[2] if len(s) == 3 else r.get("scene") for r in regions for s in r["spans"]}):
        info = clips.get(sc) or {}
        f = os.path.join(sdir, info.get("file", ""))
        if not info.get("file") or not os.path.exists(f):
            continue
        tmap = TimeMap("source", clips, None, sc)
        pls, _ = make_placements(regions, tmap, int(info["w"]), int(info["h"]))
        if not pls:
            continue
        fc, _ = build_graph(pls, "0:v", "vb")
        times = sorted({round((pl["spans"][0][0] + pl["spans"][0][1]) / 2, 3) for pl in pls})[:6]
        os.makedirs(pdir, exist_ok=True)
        dst = os.path.join(pdir, "contact-%s.png" % sc)
        fg = "%s;[vb]%s,scale=480:-1,tile=%dx1[o]" % (
            fc, select_script(times).replace(",showinfo", ""), len(times))
        r = rbm.run_bounded([ffmpeg, "-y", "-v", "error", "-i", f, "-filter_complex", fg, "-map", "[o]",
                             "-frames:v", "1", dst], wall=60, stall=30, heartbeat="ffmpeg")
        if r["status"] == "ok" and r["tool_rc"] == 0:
            out[sc] = os.path.relpath(dst, sdir)
    return out


# =========================================================================== CLI
class Parser(argparse.ArgumentParser):
    def __init__(self, *a, **k):
        k.setdefault("allow_abbrev", False)  # `--rege=` must not dodge argv redaction (S-12)
        super().__init__(*a, **k)

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(2)


def build_parser():
    def common(p, sub):
        d = argparse.SUPPRESS if sub else None
        p.add_argument("--project", default=d, help="path to project.json")
        p.add_argument("--slug", default=d, help="use .demo/<slug>/project.json")
        p.add_argument("--timeout", type=float, default=argparse.SUPPRESS if sub else 10.0)

    c = argparse.ArgumentParser(add_help=False)
    common(c, True)
    p = Parser(description="Blur plan / graph / preview / verify.")
    common(p, False)
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    a = sub.add_parser("plan", parents=[c])
    a.add_argument("--merge-gap-ms", type=float, default=MERGE_GAP_MS, dest="merge_gap_ms")
    a.add_argument("--cover-max", type=int, default=COVER_MAX_PX, dest="cover_max")
    a.add_argument("--dry-run", action="store_true", dest="dry_run")
    g = sub.add_parser("graph", parents=[c])
    g.add_argument("--space", choices=["final", "source"], required=True)
    g.add_argument("--scene")
    g.add_argument("--aspect", default="16x9")
    g.add_argument("--in-label", default="0:v", dest="in_label")
    g.add_argument("--out-label", default="vb", dest="out_label")
    for name in ("preview", "verify"):
        v = sub.add_parser(name, parents=[c])
        v.add_argument("--dry-run", action="store_true", dest="dry_run")
        v.add_argument("--ocr", default=None,
                       help="rapidocr | tesseract | none | python:<module>:<factory> "
                            "(default: demo.yaml tools.ocr, else rapidocr)")
        v.add_argument("--lang", default="en")
        v.add_argument("--ffmpeg", default="ffmpeg")
        v.add_argument("--ffprobe", default="ffprobe")
        if name == "verify":
            v.add_argument("--video", required=True)
            v.add_argument("--aspect", required=True)
            v.add_argument("--budget-s", type=float, default=None, dest="budget_s")
            v.add_argument("--fullframe-stride-s", type=float, default=2.0, dest="fullframe_stride_s")
            v.add_argument("--pattern", action="append", help="extra sensitive regex (repeatable)")
            v.add_argument("--hmac", action="store_true",
                           help="store an HMAC of each hit (key in .demo/<slug>/.secret/key)")
    t = sub.add_parser("set-transform", parents=[c])
    t.add_argument("--aspect", required=True)
    t.add_argument("--scale", type=float)
    t.add_argument("--ox", type=float)
    t.add_argument("--oy", type=float)
    t.add_argument("--identity", action="store_true")
    t.add_argument("--segment", nargs=5, type=float, action="append",
                   metavar=("T0", "T1", "SCALE", "OX", "OY"),
                   help="final-timeline window (s) with its own mapping (zoom/pan); repeatable")
    t.add_argument("--zoom-free", action="store_true", dest="zoom_free",
                   help="declare that no zoom/pan window applies (empty segments list)")
    w = sub.add_parser("ocr-worker")
    w.add_argument("--engine", required=True)
    w.add_argument("--lang", default="en")
    w.add_argument("--call-limit", type=float, default=25.0, dest="call_limit")
    return p


def main(argv=None, ocr=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    if args.cmd == "ocr-worker":
        return cmd_ocr_worker(args)
    t0 = time.monotonic()
    handlers = {"plan": cmd_plan, "graph": cmd_graph, "preview": cmd_preview, "verify": cmd_verify,
                "set-transform": cmd_set_transform}
    try:
        if args.cmd in ("preview", "verify"):
            res, code = handlers[args.cmd](args, ocr)
        else:
            res, code = handlers[args.cmd](args)
    except BlurError as e:
        res = {"status": "error", "error": e.msg, "failures": e.failures}
        code = e.code
        sys.stderr.write("error: %s\n" % e.msg)
    res.setdefault("failures", [])
    res["elapsed_s"] = round(time.monotonic() - t0, 2)
    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
    try:
        path = project.project_path(type("A", (), {"project": getattr(args, "project", None),
                                                    "slug": getattr(args, "slug", None)})())
        priv = load_privacy(os.path.dirname(path))
        secrets = list(priv.get("regexes", [])) + list(priv.get("seed_values", [])) \
            + list(getattr(args, "pattern", None) or [])
        if os.path.isdir(os.path.dirname(path)):
            rbm.append_run(os.path.dirname(path), "blur.py", argv if argv is not None else sys.argv[1:],
                           res, secrets)
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(rbm.guard_main(main))
