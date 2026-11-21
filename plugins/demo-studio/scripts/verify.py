#!/usr/bin/env python3
"""Verify the finished videos: OCR leak scan (one decode per file, OCR engine built once), loudness, duration.

verify.py --slug S [--root .demo] [--budget 300] [--stride 0.5] [--file F ...]
Scans media/final-*.mp4 (or --file) every --stride seconds for demo.yaml privacy.patterns, privacy.seed_values
(only when data_mode is real) and default email / API-key patterns. Matched text is never printed, only pattern ids.
stdout JSON: {pass, leaks:[{file,t_ms,pattern_id}], loudness, duration, sampled, warnings, [reason]}
Exit: 0 pass, 11 leak found, 3 cannot check (no OCR, no files, too few samples or out of time), 2 bad usage/config.
Loudness and duration are reported in `warnings` when off target (+-10% length, +-1.5 LU); they do not fail the run.
"""
import argparse
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import _run, find_ffmpeg, load_config, media_duration, out  # noqa: E402

DEFAULTS = {
    "default:email": r"[A-Za-z0-9._%+-]+@%s[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
    "default:api_key": r"\b(?:[spr]k_(?:live|test)_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[bap]-[A-Za-z0-9-]{10,})",
}


def make_ocr(kind):
    """Return fn(rgb ndarray) -> text, or None when no engine is available."""
    if kind == "none":
        return None
    if kind == "qa-ocr-tesseract":
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return lambda img: pytesseract.image_to_string(img)
        except Exception:
            return None
    try:
        from rapidocr import RapidOCR
        eng = RapidOCR()

        def run(img):
            r = eng(img)
            return "\n".join(r.txts) if r is not None and r.txts else ""
        return run
    except Exception:
        pass
    try:
        from rapidocr_onnxruntime import RapidOCR as Old
        eng = Old()
        return lambda img: "\n".join(x[1] for x in (eng(img)[0] or []))
    except Exception:
        return None


def build_matchers(cfg):
    allow = "|".join(re.escape(str(d)) for d in cfg["privacy"]["allow_domains"])
    skip = "(?!(?:%s)(?![A-Za-z0-9-]))" % allow if allow else ""
    ms = {"default:email": re.compile(DEFAULTS["default:email"] % skip), "default:api_key": re.compile(DEFAULTS["default:api_key"])}
    for i, rx in enumerate(cfg["privacy"]["patterns"]):
        ms["pattern:%d" % i] = re.compile(str(rx))
    if cfg["privacy"]["data_mode"] == "real":
        for i, v in enumerate(cfg["privacy"]["seed_values"]):
            ms["seed:%d" % i] = re.compile(re.escape(str(v)), re.I)
    return ms


def frame_size(ffmpeg, path):
    _, _, err = _run([ffmpeg, "-hide_banner", "-i", path], 30)
    m = re.search(rb"Video:.*?, (\d{2,5})x(\d{2,5})", err)
    if not m:
        return None
    w, h = int(m[1]), int(m[2])
    tw = min(w, 1280) // 2 * 2
    return tw, max(2, round(h * tw / w / 2) * 2)


def scan(ffmpeg, path, stride, ocr, matchers, deadline, np):
    """One sequential decode; returns (leaks, sampled, finished)."""
    size = frame_size(ffmpeg, path)
    if not size:
        return [], 0, False
    w, h = size
    p = subprocess.Popen([ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-vf", "fps=1/%g,scale=%d:%d" % (stride, w, h),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    killed = []

    def stop():
        killed.append(1)
        os.killpg(p.pid, signal.SIGKILL)

    kill = threading.Timer(max(1, deadline - time.monotonic()), stop)
    kill.start()
    seen, n, size_b = {}, 0, w * h * 3
    try:
        while time.monotonic() < deadline:
            buf = p.stdout.read(size_b)
            if len(buf) < size_b:
                return _leaks(seen, path), n, not killed
            text = ocr(np.frombuffer(buf, np.uint8).reshape(h, w, 3))
            for pid, rx in matchers.items():
                if (path, pid) not in seen and rx.search(text):
                    seen[(path, pid)] = int(n * stride * 1000)
            n += 1
        return _leaks(seen, path), n, False
    finally:
        kill.cancel()
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        p.wait()


def _leaks(seen, path):
    return [{"file": Path(f).name, "t_ms": t, "pattern_id": pid} for (f, pid), t in seen.items()]


def loudness(ffmpeg, path, timeout=300):
    rc, _, err = _run([ffmpeg, "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], timeout)
    s = err.decode(errors="replace").rsplit("Summary:", 1)[-1]
    i, tp = re.search(r"I:\s+(-?[\d.]+) LUFS", s), re.search(r"Peak:\s+(-?[\d.]+) dBFS", s)
    return {"lufs": float(i[1]) if i else None, "true_peak": float(tp[1]) if tp else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--root", default=".demo")
    ap.add_argument("--budget", type=float, default=300, help="total seconds for the whole run")
    ap.add_argument("--stride", type=float, default=0.5, help="seconds between sampled frames")
    ap.add_argument("--file", action="append", default=[])
    a = ap.parse_args(argv)
    start = time.monotonic()
    deadline = start + a.budget
    # backstop: a hung OCR call cannot outlive the budget
    guard = threading.Timer(a.budget + 15, lambda: (print('{"pass": false, "reason": "time budget exceeded"}'), os._exit(3)))
    guard.daemon = True
    guard.start()
    proj = Path(a.root) / a.slug
    try:
        cfg = load_config(proj / "demo.yaml")
        matchers = build_matchers(cfg)
    except (ValueError, re.error) as e:
        out({"pass": False, "reason": str(e)}, 2)
    ffmpeg = find_ffmpeg()
    files, stale = [Path(f) for f in a.file], []
    if not files:
        srcs = [proj / n for n in ("edit.json", "motion.json", "captions.json", "mix.json") if (proj / n).exists()]
        newest = max((s.stat().st_mtime for s in srcs), default=0)
        for f in sorted((proj / "media").glob("final-*.mp4")):
            (stale if f.stat().st_mtime < newest else files).append(f)
    if not ffmpeg or not files:
        out({"pass": False, "reason": "ffmpeg missing" if not ffmpeg else "no up-to-date final-*.mp4 found (stale: %s)" % ", ".join(f.name for f in stale)}, 3)
    ocr = make_ocr(cfg["ocr"])
    if ocr is None:
        out({"pass": False, "reason": "no OCR engine (tools.ocr=%s); run setup_tools.py --install qa-ocr" % cfg["ocr"]}, 3)
    import numpy as np
    leaks, sampled, loud, dur, incomplete = [], 0, {}, {}, []
    warnings = ["%s is older than the edit files: skipped, re-render" % f.name for f in stale]
    for f in files:
        lk, n, done = scan(ffmpeg, f, a.stride, ocr, matchers, deadline, np)
        leaks += lk
        sampled += n
        d = media_duration(str(f), ffmpeg)
        dur[f.name] = d
        if not done or d is None or n < 0.9 * (d / a.stride) - 1:
            incomplete.append(f.name)
        if d and abs(d - cfg["length_s"]) > 0.1 * cfg["length_s"]:
            warnings.append("%s duration %.1fs vs length_s %s" % (f.name, d, cfg["length_s"]))
        if time.monotonic() < deadline + 60:
            loud[f.name] = loudness(ffmpeg, f, 120)
            v = loud[f.name]["lufs"]
            if v is None or abs(v - cfg["targets"]["lufs"]) > 1.5:
                warnings.append("%s loudness %s LUFS vs target %s" % (f.name, v, cfg["targets"]["lufs"]))
    res = {"pass": not leaks and not incomplete, "leaks": leaks, "loudness": loud, "duration": dur, "sampled": sampled,
           "warnings": warnings}
    if incomplete:
        res["reason"] = "not fully sampled (time budget or decode problem): " + ", ".join(incomplete)
    out(res, 11 if leaks else 3 if incomplete else 0)


if __name__ == "__main__":
    main()
