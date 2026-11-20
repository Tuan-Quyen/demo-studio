#!/usr/bin/env python3
"""Bounded OCR check of blur regions: one ffmpeg call per region, one OCR engine, hard deadline.

Run with the toolkit interpreter (`setup_tools.py --python`), never a loop of your own:
  blur_check.py CLIP --regions blur.json [--scene s03] --ocr qa-ocr --budget-s 300
  blur_check.py CLIP --bbox 820,300,420,60 --pad 12 --t-start 4100 --t-end 9200 --pattern email

Exit: 0 pass | 1 sensitive text found | 2 budget exceeded (partial coverage) | 3 tool/input error.
Stdout: one JSON object (per region frames_sampled/frames_total, matches, control_ok, seconds).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

EXIT_PASS, EXIT_FOUND, EXIT_PARTIAL, EXIT_ERROR = 0, 1, 2, 3
OCR_CHOICES = ("qa-ocr", "qa-ocr-tesseract", "none")
PRESETS = {
    "email": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "key": r"sk-[A-Za-z0-9]{8,}",
}
ANY_TEXT = r"[A-Za-z0-9]{3,}"  # no pattern given: any readable word in a blur region is a leak
FFMPEG_CALL_TIMEOUT_S = 120
TESS_TIMEOUT_S = 20


class CheckError(Exception):
    pass


def compile_pattern(p):
    """Preset name or regex; a bare '@' (or anything that matches it) is refused."""
    if p is None:
        return re.compile(ANY_TEXT)
    src = PRESETS.get(p, p)
    try:
        rx = re.compile(src)
    except re.error as e:
        raise CheckError(f"bad pattern {p!r}: {e}")
    if rx.search("@") or rx.search("the") or rx.search(" "):
        raise CheckError(f"pattern {p!r} matches generic text (bare '@', a plain word or space); use the value's own pattern")
    return rx


def match_texts(rx, texts):
    """Matches of rx in the OCR strings (each alone, then joined so split tokens are caught)."""
    found = []
    for s in list(texts) + [" ".join(texts)] if texts else []:
        for m in rx.finditer(s):
            if m.group(0) not in found:
                found.append(m.group(0))
    return found


def parse_bbox(s):
    try:
        v = [int(float(x)) for x in str(s).split(",")]
    except ValueError:
        v = []
    if len(v) != 4 or v[2] <= 0 or v[3] <= 0:
        raise CheckError(f"bbox must be x,y,w,h with w,h > 0, got {s!r}")
    return v


def load_regions(args):
    """Region dicts from --regions (blur JSON: {"regions":[...]} or a list) or from --bbox."""
    if args.regions:
        try:
            with open(args.regions, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise CheckError(f"cannot read {args.regions}: {e}")
        regs = data.get("regions") if isinstance(data, dict) else data
        if not isinstance(regs, list):
            raise CheckError("regions file has no 'regions' list")
        if args.scene:
            regs = [r for r in regs if r.get("scene") == args.scene]
        if args.region:
            regs = [r for r in regs if r.get("id") in args.region]
        regs = [dict(r) for r in regs]
    elif args.bbox:
        if args.t_start is None or args.t_end is None:
            raise CheckError("--bbox needs --t-start and --t-end (ms)")
        regs = [{"id": "r1", "bbox": parse_bbox(args.bbox), "pad": args.pad, "margin_ms": args.margin_ms,
                 "t_start": args.t_start, "t_end": args.t_end, "mode": args.mode, "strength": args.strength}]
    else:
        raise CheckError("give --regions FILE or --bbox x,y,w,h")
    if not regs:
        raise CheckError("no regions selected")
    for i, r in enumerate(regs):
        r.setdefault("id", f"r{i + 1}")
        r["bbox"] = parse_bbox(",".join(str(x) for x in r.get("bbox") or []))
        for k in ("t_start", "t_end"):
            if not isinstance(r.get(k), (int, float)):
                raise CheckError(f"region {r['id']}: {k} (ms) missing")
        if r["t_end"] <= r["t_start"]:
            raise CheckError(f"region {r['id']}: t_end <= t_start")
        r["pad"] = int(r.get("pad") or 0)
        r["margin_ms"] = int(r.get("margin_ms") or 0)
        if args.pattern:
            r["pattern"] = args.pattern
    return regs


def tracked_box(region):
    """Crop box (x, y, w, h incl. pad). Tracked regions: union of keyframe boxes if they carry one."""
    x, y, w, h = region["bbox"]
    for k in region.get("keyframes") or []:
        if isinstance(k, dict) and k.get("bbox"):
            kx, ky, kw, kh = k["bbox"]
            nx, ny = min(x, kx), min(y, ky)
            w, h = max(x + w, kx + kw) - nx, max(y + h, ky + kh) - ny
            x, y = nx, ny
    p = region["pad"]
    return x - p, y - p, w + 2 * p, h + 2 * p


def clamp_box(box, fw, fh):
    x, y, w, h = box
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x + w), min(fh, y + h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        raise CheckError(f"crop {box} is outside the {fw}x{fh} frame")
    return x0, y0, x1 - x0, y1 - y0


def build_ffmpeg_cmd(clip, out_dir, t0_s, t1_s, box, step, max_frames=None):
    """One call per region: seek, select every `step`-th frame (1 = all), crop, write %04d.png."""
    x, y, w, h = box
    sel = "" if step <= 1 else f"select='not(mod(n\\,{step}))',"
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{t0_s:.3f}", "-to", f"{t1_s:.3f}", "-i", clip,
           "-vf", f"{sel}crop={w}:{h}:{x}:{y}", "-fps_mode", "vfr"]
    if max_frames:
        cmd += ["-frames:v", str(max_frames)]
    return cmd + [os.path.join(out_dir, "%04d.png")]


def probe_size(clip, timeout=30):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
           "-of", "csv=p=0:s=x", clip]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        w, h = (int(v) for v in r.stdout.strip().split("x")[:2])
        return w, h
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        raise CheckError(f"ffprobe failed on {clip}: {e}")


def clear_pngs(d):
    os.makedirs(d, exist_ok=True)
    for n in os.listdir(d):
        if n.endswith(".png"):
            os.remove(os.path.join(d, n))


def extract(cmd, out_dir, timeout):
    """Run ffmpeg once; return the crop files it wrote (sorted)."""
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CheckError(f"ffmpeg timed out after {timeout:.0f}s")
    except OSError as e:
        raise CheckError(f"cannot run ffmpeg: {e}")
    if r.returncode != 0:
        raise CheckError(f"ffmpeg rc={r.returncode}: {r.stderr.strip()[-300:]}")
    return sorted(os.path.join(out_dir, n) for n in os.listdir(out_dir) if n.endswith(".png"))


def apply_blur(img, mode, strength):
    """In-process stand-in for the render blur (boxblur: 3 passes, pixelate: 16x blocks)."""
    import cv2
    h, w = img.shape[:2]
    if mode == "pixelate":
        small = cv2.resize(img, (max(1, w // 16), max(1, h // 16)), interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    lr = int(max(1, min(strength or 25, h / 4)))
    for _ in range(3):
        img = cv2.blur(img, (2 * lr + 1, 2 * lr + 1))
    return img


def make_ocr(kind):
    """Build the OCR engine once; returns fn(bgr_array) -> list[str]. Libs are imported lazily."""
    if kind == "none":
        return None
    if kind == "qa-ocr":
        try:
            from rapidocr import RapidOCR
        except ImportError as e:
            raise CheckError(f"qa-ocr not installed ({e}); setup_tools.py --plan qa-ocr")
        eng = RapidOCR(params={"Global.log_level": "error"})

        def run(img):
            r = eng(img)
            return [str(t) for t in (r.txts or ())]
        return run
    if kind == "qa-ocr-tesseract":
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
        try:
            import cv2
            import pytesseract
        except ImportError as e:
            raise CheckError(f"qa-ocr-tesseract not installed ({e}); setup_tools.py --plan qa-ocr-tesseract")
        if not shutil.which("tesseract"):
            raise CheckError("tesseract program not on PATH")

        def run(img):
            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, timeout=TESS_TIMEOUT_S)
            return [t for t, c in zip(d["text"], d["conf"]) if t.strip() and float(c) > 30]
        return run
    raise CheckError(f"unknown --ocr {kind!r}")


def check_region(clip, region, a, ocr, out_root, deadline, frame_size, control_clip=None):
    """Returns the per-region result dict. Never overruns `deadline` (time.monotonic())."""
    import cv2
    rid = region["id"]
    t_begin = time.monotonic()
    res = {"id": rid, "scene": region.get("scene"), "frames_sampled": 0, "frames_total": 0, "matches": [],
           "control_ok": None, "partial": False, "seconds": 0.0, "crops_dir": None}
    rx = compile_pattern(region.get("pattern"))
    box = clamp_box(tracked_box(region), *frame_size)
    out_dir = os.path.join(out_root, re.sub(r"[^\w.-]", "_", str(rid)))
    res["crops_dir"] = out_dir
    tracked = bool(region.get("keyframes"))
    step = 1 if tracked else max(1, a.step)
    t0 = max(0.0, (region["t_start"] - region["margin_ms"]) / 1000)
    t1 = (region["t_end"] + region["margin_ms"]) / 1000

    def left():
        return deadline - time.monotonic()

    if left() <= 0:
        res["partial"] = True
        res["seconds"] = round(time.monotonic() - t_begin, 2)
        return res
    clear_pngs(out_dir)
    # control source: separate unblurred clip (one frame at t_start) or the first crop of this clip
    if ocr and control_clip:
        cdir = out_dir + "_control"
        clear_pngs(cdir)
        cf = extract(build_ffmpeg_cmd(control_clip, cdir, t0, t1, box, 1, max_frames=1), cdir,
                     max(1, min(FFMPEG_CALL_TIMEOUT_S, left())))
        control_img = cv2.imread(cf[0]) if cf else None
        shutil.rmtree(cdir, ignore_errors=True)
    else:
        control_img = None
    files = extract(build_ffmpeg_cmd(clip, out_dir, t0, t1, box, step), out_dir,
                    max(1, min(FFMPEG_CALL_TIMEOUT_S, left())))
    res["frames_total"] = len(files)
    if not files:
        raise CheckError(f"region {rid}: ffmpeg wrote no crops (time range {t0:.2f}-{t1:.2f}s outside the clip?)")
    if ocr:
        if control_img is None:
            control_img = cv2.imread(files[0])
        res["control_ok"] = bool(match_texts(rx, ocr(control_img)))
    for f in files:
        if left() <= 0:
            res["partial"] = True
            break
        img = cv2.imread(f)
        if img is None:
            continue
        if a.apply_blur:
            img = apply_blur(img, region.get("mode") or "boxblur", region.get("strength"))
            cv2.imwrite(f, img)
        res["frames_sampled"] += 1
        if ocr:
            for m in match_texts(rx, ocr(img)):
                if m not in res["matches"]:
                    res["matches"].append(m)
    res["seconds"] = round(time.monotonic() - t_begin, 2)
    return res


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("clip")
    p.add_argument("--regions", help="#blur JSON file ({'regions': [...]})")
    p.add_argument("--scene", help="only regions of this scene")
    p.add_argument("--region", action="append", help="only this region id (repeatable)")
    p.add_argument("--bbox", help="x,y,w,h (frame px) for a single ad-hoc region")
    p.add_argument("--pad", type=int, default=0)
    p.add_argument("--margin-ms", type=int, default=0)
    p.add_argument("--t-start", type=float)
    p.add_argument("--t-end", type=float)
    p.add_argument("--mode", default="boxblur", choices=("boxblur", "pixelate"))
    p.add_argument("--strength", type=int, default=25)
    p.add_argument("--pattern", help="'email', 'key' or a regex of the sensitive value (never a bare '@'); default: any word")
    p.add_argument("--ocr", default="qa-ocr", choices=OCR_CHOICES)
    p.add_argument("--apply-blur", action="store_true", help="blur the crops in-process first (clip is the unblurred raw)")
    p.add_argument("--control-clip", help="unblurred clip for the positive control (when CLIP is a blurred render)")
    p.add_argument("--step", type=int, default=3, help="every Nth frame (default 3); tracked regions use all frames")
    p.add_argument("--budget-s", type=float, default=300)
    p.add_argument("--out-dir", help="crop folder, must be under media/preview/ (default: <clip dir>/preview/blur_check)")
    return p


def run(argv):
    a = build_parser().parse_args(argv)
    started = time.monotonic()
    deadline = started + a.budget_s
    try:
        if a.budget_s <= 0:
            raise CheckError("--budget-s must be > 0")
        if not os.path.isfile(a.clip):
            raise CheckError(f"clip not found: {a.clip}")
        for tool in ("ffmpeg", "ffprobe"):
            if not shutil.which(tool):
                raise CheckError(f"{tool} not on PATH")
        out_root = a.out_dir or os.path.join(os.path.dirname(os.path.abspath(a.clip)), "preview", "blur_check")
        if "preview" not in os.path.normpath(os.path.abspath(out_root)).split(os.sep):
            raise CheckError("--out-dir must be under media/preview/")
        regions = load_regions(a)
        for r in regions:
            compile_pattern(r.get("pattern"))
        try:
            import cv2  # noqa: F401
        except ImportError as e:
            raise CheckError(f"opencv not installed ({e}); run with the toolkit interpreter (setup_tools.py --python)")
        ocr = make_ocr(a.ocr)
        size = probe_size(a.clip)
        results = []
        for i, r in enumerate(regions):
            share = max(0.0, deadline - time.monotonic()) / (len(regions) - i)
            results.append(check_region(a.clip, r, a, ocr, out_root, time.monotonic() + share, size, a.control_clip))
    except CheckError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return EXIT_ERROR
    found = any(r["matches"] for r in results)
    partial = any(r["partial"] for r in results)
    bad_control = [r["id"] for r in results if r["control_ok"] is False]
    out = {"ok": not (found or partial or bad_control), "ocr": a.ocr, "budget_s": a.budget_s,
           "seconds": round(time.monotonic() - started, 2), "partial": partial, "text_found": found,
           "control_failed": bad_control, "regions": results}
    print(json.dumps(out))
    if found:
        return EXIT_FOUND
    if bad_control:
        out_err = "positive control failed: OCR/pattern is no evidence for " + ", ".join(bad_control)
        print(out_err, file=sys.stderr)
        return EXIT_ERROR
    return EXIT_PARTIAL if partial else EXIT_PASS


def main(argv=None):
    return run(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
