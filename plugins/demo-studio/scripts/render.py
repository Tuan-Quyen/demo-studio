#!/usr/bin/env python3
"""Render .demo/<slug>/edit.json -> media/final-<aspect>.mp4 (+ media/final.vtt): one ffmpeg run per aspect.

render.py --slug S [--aspect 16x9,9x16,1x1] [--root .demo] [--timeout 900] [--burn-in]
edit.json: {"fps","size":[w,h],"scenes":[{"id","clip","in_ms","out_ms","speed","vo","vo_offset_ms"}],
  "captions":[{"start_ms","end_ms","text"}], "title_card":{"text","ms"}|null, "end_card":{"text","ms"}|null,
  "music":null|{"file","gain_db"}, "zooms":[{"scene","t_ms","dur_ms","center":[x,y],"scale"}]}
Times: scene `in/out_ms` are source-clip time; captions are on the final timeline without the title card (the card's
length is added); zoom `t_ms` is scene-local after speed, `center` is in frame pixels of `size`.
Loudness: 2-pass loudnorm to demo.yaml targets.lufs / targets.true_peak (measured once, applied per aspect).
Aspects: 16x9 as is; 1x1 centre crop; 9x16 fit width + black bars. Captions burn in if demo.yaml captions.burn_in.
Exit: 0 ok, 2 error, 3 ffmpeg failed/timeout.
"""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import _run, find_ffmpeg, load_config, out  # noqa: E402


def vtt_time(ms):
    return "%02d:%02d:%02d.%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def write_vtt(path, captions, offset_ms):
    lines = ["WEBVTT", ""]
    for c in captions:
        lines += [vtt_time(c["start_ms"] + offset_ms) + " --> " + vtt_time(c["end_ms"] + offset_ms), c["text"], ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def zoom_filter(zooms, w, h):
    """Smooth zoom-in/out windows via scale(eval=frame)+crop; t is scene-local seconds."""
    if not zooms:
        return ""
    z = "1"
    for k in zooms:
        a, b, s = k["t_ms"] / 1000, (k["t_ms"] + k["dur_ms"]) / 1000, k["scale"]
        z += "+%g*clip(min((t-%g)/0.3\\,(%g-t)/0.3)\\,0\\,1)" % (s - 1, a, b)
    k = zooms[0]  # one centre per scene: the first zoom's
    cx, cy = k["center"]
    return (",scale=w='%d*(%s)':h='%d*(%s)':eval=frame,"
            "crop=%d:%d:x='clip(%g*(%s)-%d\\,0\\,%d*(%s)-%d)':y='clip(%g*(%s)-%d\\,0\\,%d*(%s)-%d)'"
            % (w, z, h, z, w, h, cx, z, w // 2, w, z, w, cy, z, h // 2, h, z, h))


def build(edit, tmp):
    """Return (input args, video graph, audio graph) with labels [v] (before aspect) and [araw]."""
    fps, (w, h) = edit.get("fps", 25), edit["size"]
    ins, vg, ag, vl, al = [], [], [], [], []
    for i, sc in enumerate(edit["scenes"]):
        ins += ["-i", sc["clip"]]
    nclip = len(ins) // 2
    cards = {}
    for name in ("title_card", "end_card"):
        c = edit.get(name)
        if c:
            tf = Path(tmp) / (name + ".txt")
            tf.write_text(c["text"], encoding="utf-8")
            cards[name] = (c["ms"] / 1000, tf)
    nvo = 0

    def card(name):
        d, tf = cards[name]
        n = len(vl)
        vg.append("color=c=0x111111:s=%dx%d:r=%d:d=%g,drawtext=textfile=%s:fontcolor=white:fontsize=%d:"
                  "x=(w-text_w)/2:y=(h-text_h)/2,setsar=1,format=yuv420p[c%d]" % (w, h, fps, d, tf, h // 16, n))
        ag.append("anullsrc=r=48000:cl=stereo,atrim=0:%g,asetpts=PTS-STARTPTS[ca%d]" % (d, n))
        vl.append("[c%d]" % n)
        al.append("[ca%d]" % n)

    if "title_card" in cards:
        card("title_card")
    for i, sc in enumerate(edit["scenes"]):
        sp = sc.get("speed", 1.0) or 1.0
        d = (sc["out_ms"] - sc["in_ms"]) / 1000 / sp
        zs = [z for z in edit.get("zooms", []) if z["scene"] == sc["id"]]
        n = len(vl)
        vg.append("[%d:v]trim=start=%g:end=%g,setpts=(PTS-STARTPTS)/%g,fps=%d,scale=%d:%d:force_original_aspect_ratio=decrease,"
                  "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1%s,format=yuv420p[sv%d]"
                  % (i, sc["in_ms"] / 1000, sc["out_ms"] / 1000, sp, fps, w, h, w, h, zoom_filter(zs, w, h), n))
        vl.append("[sv%d]" % n)
        if sc.get("vo"):
            ins += ["-i", sc["vo"]]
            idx = nclip + nvo
            nvo += 1
            ag.append("[%d:a]aresample=48000,aformat=channel_layouts=stereo,adelay=%d:all=1,apad,atrim=0:%g,asetpts=PTS-STARTPTS[sa%d]"
                      % (idx, sc.get("vo_offset_ms", 0), d, n))
        else:
            ag.append("anullsrc=r=48000:cl=stereo,atrim=0:%g,asetpts=PTS-STARTPTS[sa%d]" % (d, n))
        al.append("[sa%d]" % n)
    if "end_card" in cards:
        card("end_card")
    total = len(vl)
    vg.append("%sconcat=n=%d:v=1:a=0[v]" % ("".join(vl), total))
    ag.append("%sconcat=n=%d:v=0:a=1[narr]" % ("".join(al), total))
    mus = edit.get("music")
    if mus:
        ins += ["-stream_loop", "-1", "-i", mus["file"]]
        idx = nclip + nvo
        ag.append("[%d:a]aresample=48000,aformat=channel_layouts=stereo,volume=%gdB[mus]" % (idx, mus.get("gain_db", -20)))
        ag.append("[narr][mus]amix=inputs=2:duration=first:normalize=0[araw]")
    else:
        ag.append("[narr]anull[araw]")
    return ins, vg, ag


def aspect_tail(aspect):
    return {"16x9": "", "1x1": ",crop=ih:ih,scale=1080:1080,setsar=1",
            "9x16": ",scale=1080:-2,pad=1080:1920:0:(oh-ih)/2:black,setsar=1"}[aspect]


def measure(ffmpeg, ins, ag, tgt, timeout):
    g = ";".join(ag) + ";[araw]loudnorm=I=%g:TP=%g:LRA=11:print_format=json[o]" % (tgt["lufs"], tgt["true_peak"])
    rc, _, err = _run([ffmpeg, "-hide_banner", *ins, "-filter_complex", g, "-map", "[o]", "-f", "null", "-"], timeout)
    m = re.findall(rb"\{[^{}]*\}", err)
    if rc != 0 or not m:
        return None
    try:
        j = json.loads(m[-1])
        vals = {k: float(j[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (ValueError, KeyError):
        return None
    return vals if all(math.isfinite(v) for v in vals.values()) else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--aspect", default=None, help="comma list of 16x9,9x16,1x1 (default: demo.yaml formats)")
    ap.add_argument("--root", default=".demo")
    ap.add_argument("--timeout", type=int, default=900, help="per ffmpeg run, seconds")
    ap.add_argument("--burn-in", action="store_true")
    a = ap.parse_args(argv)
    proj = (Path(a.root) / a.slug).resolve()
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        out({"ok": False, "error": "ffmpeg not found (run setup_tools.py --install capture)"}, 2)
    try:
        cfg = load_config(proj / "demo.yaml") if (proj / "demo.yaml").exists() else load_config_default()
        edit = json.loads((proj / "edit.json").read_text())
        aspects = a.aspect.split(",") if a.aspect else cfg["formats"]
        assert edit["scenes"], "edit.json has no scenes"
        bad = [x for x in aspects if x not in ("16x9", "9x16", "1x1")]
        assert not bad, "unknown aspect %s" % bad
    except (ValueError, OSError, KeyError, AssertionError) as e:
        out({"ok": False, "error": str(e)}, 2)
    os.chdir(proj)  # clip/vo paths in edit.json are relative to the project
    Path("media").mkdir(exist_ok=True)
    offset = edit["title_card"]["ms"] if edit.get("title_card") else 0
    write_vtt("media/final.vtt", edit.get("captions", []), offset)
    burn = a.burn_in or bool(cfg["captions"].get("burn_in"))
    import tempfile
    with tempfile.TemporaryDirectory(prefix="demo-render-") as tmp:
        ins, vg, ag = build(edit, tmp)
        norm = measure(ffmpeg, ins, ag, cfg["targets"], a.timeout)
        ln = "loudnorm=I=%g:TP=%g:LRA=11" % (cfg["targets"]["lufs"], cfg["targets"]["true_peak"])
        if norm:
            ln += ":measured_I=%g:measured_TP=%g:measured_LRA=%g:measured_thresh=%g:offset=%g:linear=true" % (
                norm["input_i"], norm["input_tp"], norm["input_lra"], norm["input_thresh"], norm["target_offset"])
        files = []
        for asp in aspects:
            tail = aspect_tail(asp) + (",subtitles=media/final.vtt" if burn else "")
            g = ";".join(vg + ag + ["[v]%s[vout]" % (tail[1:] or "null"), "[araw]%s[aout]" % ln])
            dst = "media/final-%s.mp4" % asp
            rc, _, err = _run([ffmpeg, "-hide_banner", "-y", *ins, "-filter_complex", g, "-map", "[vout]", "-map", "[aout]",
                               "-r", str(edit.get("fps", 25)), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
                               dst], a.timeout)
            if rc != 0:
                out({"ok": False, "error": "ffmpeg failed for %s (rc %d)" % (asp, rc), "tail": err.decode(errors="replace")[-800:]}, 3)
            files.append(str(proj / dst))
    out({"ok": True, "files": files, "vtt": str(proj / "media/final.vtt"), "loudnorm_two_pass": bool(norm)})


def load_config_default():
    return {"formats": ["16x9"], "captions": {}, "targets": {"lufs": -16, "true_peak": -1.5}}


if __name__ == "__main__":
    main()
