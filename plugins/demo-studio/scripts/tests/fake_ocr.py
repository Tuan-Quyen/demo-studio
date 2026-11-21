"""OCR test doubles (no rapidocr needed). `band_ocr` "reads" text wherever rows have strong contrast."""
import time


def _bands(rgb, w, h, thresh=160, max_gap=12):
    rows = []
    for y in range(h):
        row = rgb[y * w * 3:(y + 1) * w * 3]
        rows.append(max(row) - min(row) > thresh)
    out, start, last = [], None, None
    for y, hot in enumerate(rows):
        if hot:
            if start is None:
                start = y
            last = y
        elif start is not None and y - last > max_gap:
            out.append((start, last + 1))
            start = None
    if start is not None:
        out.append((start, last + 1))
    return out


def band_ocr(rgb, w, h):
    return [{"text": "demo@example.com", "box": [0, a, w, b]} for a, b in _bands(rgb, w, h)]


def slow_band_ocr(delay):
    def f(rgb, w, h):
        time.sleep(delay)
        return band_ocr(rgb, w, h)
    return f


def echo(lang):
    return band_ocr


def hang(lang):
    def f(rgb, w, h):
        time.sleep(300)
    return f


def broken(lang):
    raise RuntimeError("engine cannot start")


def hang_now(rgb, w, h):
    raise RuntimeError("engine crashed mid-run")
