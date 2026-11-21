"""Tests for common, capture, render, verify (real ffmpeg / Chromium / OCR; each skips when its tool is missing)."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

S = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(S))
import common  # noqa: E402

FF = common.find_ffmpeg()
FIX = Path(__file__).parent / "fixtures" / "react-list"
OCR_PY = os.environ.get("DEMO_STUDIO_OCR_PYTHON")


def have(mod, py=sys.executable):
    return subprocess.run([py, "-c", "import " + mod], capture_output=True).returncode == 0


def test_run_timeout_kills_group(tmp_path):
    t = time.time()
    rc, _, err = common._run(["sh", "-c", "sleep 60 & sleep 60"], 1)
    assert rc == 124 and time.time() - t < 10 and b"timeout" in err


def test_yaml_and_validation(tmp_path):
    p = tmp_path / "demo.yaml"
    p.write_text('length_s: 30\nformats: ["16:9", "9:16"]\nprivacy:\n  mask: [".a", "#b"]\n  patterns:\n    - "x+"\n')
    cfg = common.load_config(p)
    assert cfg["formats"] == ["16x9", "9x16"] and cfg["privacy"]["mask"] == [".a", "#b"] and cfg["privacy"]["patterns"] == ["x+"]
    for bad in ("privacy:\n  data_mode: real\n", "privacy:\n  patterns: ['(']\n", "bogus: 1\n"):
        p.write_text(bad)
        with pytest.raises(ValueError):
            common.load_config(p)


@pytest.mark.skipif(not have("playwright"), reason="playwright missing")
def test_capture_masks_selector(tmp_path):
    def shoot(sel):
        cmd = [sys.executable, str(S / "capture.py"), "--scenes", str(FIX / "scenes.web.py"), "--scene", "s01",
               "--url", (FIX / "index.html").as_uri(), "--out", str(tmp_path / sel[0]), "--viewport", "960x540", "--timeout", "90"]
        for s in sel[1:]:
            cmd += ["--mask-selector", s]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        d = tmp_path / sel[0]
        assert [m["name"] for m in json.loads((d / "s01.marks.json").read_text())["marks"]] == ["start", "end"]
        png = d / "f.png"
        subprocess.run([FF, "-y", "-v", "error", "-ss", "0.5", "-i", str(d / "s01.raw.webm"), "-frames:v", "1", str(png)], check=True)
        # white "pill" holding the email sits at the right of the header: count white pixels there
        raw = subprocess.run([FF, "-v", "error", "-i", str(png), "-vf", "crop=460:40:500:20", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, check=True).stdout
        return sum(1 for b in raw if b > 200)

    shown, hidden = shoot(["plain"]), shoot(["masked", "#hdr-email"])
    assert shown > 1000 and hidden < shown / 10


def make_clip(path, color="white", text=None, d=4):
    vf = "null" if not text else "drawtext=text='%s':fontsize=48:x=40:y=200" % text
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=%s:s=960x540:r=25:d=%s" % (color, d), "-vf", vf,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


@pytest.mark.skipif(not FF, reason="ffmpeg missing")
def test_render_duration(tmp_path):
    media = tmp_path / ".demo" / "x" / "media"
    media.mkdir(parents=True)
    make_clip(media / "s01.raw.mp4", "blue", d=5)
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=2", str(media / "s01.vo.wav")], check=True)
    edit = {"fps": 25, "size": [640, 360], "scenes": [{"id": "s01", "clip": "media/s01.raw.mp4", "in_ms": 500, "out_ms": 4500,
            "speed": 2.0, "vo": "media/s01.vo.wav", "vo_offset_ms": 200}],
            "captions": [{"start_ms": 200, "end_ms": 1800, "text": "Hi"}], "title_card": {"text": "T", "ms": 1000},
            "end_card": {"text": "E", "ms": 500}, "music": None,
            "zooms": [{"scene": "s01", "t_ms": 500, "dur_ms": 1000, "center": [320, 180], "scale": 1.4}]}
    (media.parent / "edit.json").write_text(json.dumps(edit))
    r = subprocess.run([sys.executable, str(S / "render.py"), "--slug", "x", "--root", str(tmp_path / ".demo"), "--aspect", "16x9,9x16"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WEBVTT" in (media / "final.vtt").read_text() and "00:00:01.200" in (media / "final.vtt").read_text()
    for asp in ("16x9", "9x16"):
        assert abs(common.media_duration(str(media / ("final-%s.mp4" % asp)), FF) - 3.5) < 0.2


def run_verify(tmp_path, clip, yaml):
    proj = tmp_path / ".demo" / "x"
    (proj / "media").mkdir(parents=True)
    (proj / "demo.yaml").write_text(yaml)
    shutil.copy(clip, proj / "media" / "final-16x9.mp4")
    r = subprocess.run([OCR_PY or sys.executable, str(S / "verify.py"), "--slug", "x", "--root", str(tmp_path / ".demo"), "--budget", "120"],
                       capture_output=True, text=True, timeout=200)
    return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not FF, reason="ffmpeg missing")
def test_verify_no_ocr_exits_3(tmp_path):
    make_clip(tmp_path / "c.mp4", d=1)
    proj = tmp_path / ".demo" / "x"
    (proj / "media").mkdir(parents=True)
    (proj / "demo.yaml").write_text("length_s: 1\ntools:\n  ocr: none\n")
    shutil.copy(tmp_path / "c.mp4", proj / "media" / "final-16x9.mp4")
    r = subprocess.run([sys.executable, str(S / "verify.py"), "--slug", "x", "--root", str(tmp_path / ".demo")], capture_output=True, text=True)
    assert r.returncode == 3 and "OCR" in json.loads(r.stdout)["reason"]


@pytest.mark.skipif(not FF or not have("rapidocr", OCR_PY or sys.executable), reason="ffmpeg or rapidocr missing")
def test_verify_flags_email_and_passes_clean(tmp_path):
    y = "length_s: 3\n"
    make_clip(tmp_path / "leak.mp4", text="contact bob.smith@acme-corp.io now", d=3)
    rc, res = run_verify(tmp_path, tmp_path / "leak.mp4", y)
    assert rc == 11 and not res["pass"] and res["leaks"][0]["pattern_id"] == "default:email"
    assert "acme-corp" not in json.dumps(res)
    clean = tmp_path / "clean"
    clean.mkdir()
    make_clip(clean / "ok.mp4", text="Dashboard overview", d=3)
    rc, res = run_verify(clean, clean / "ok.mp4", y)
    assert rc == 0 and res["pass"] and res["leaks"] == [] and res["sampled"] >= 5
