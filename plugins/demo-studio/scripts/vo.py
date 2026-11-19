#!/usr/bin/env python3
"""Voice-over audio helpers shared by the agents: trim, join, check. Stdlib only, Python 3.9+.

Raw TTS WAVs keep ~0.85 s of trailing silence and ~0.9 s between sentences; joined naively
they sound choppy. These commands cut and measure that, so agents never improvise audio code.
Input/output: 16-bit PCM WAV (mono or stereo). Loudness is measured on 10 ms RMS windows.

  vo.py trim IN OUT [--lead-ms 200] [--trail-ms 150] [--threshold-db -50]
      Trim leading/trailing silence to at most the given ms (that much is kept before the first
      and after the last sound). Prints JSON {lead_ms, trail_ms, duration_ms} of OUT.
  vo.py join OUT IN1 IN2 ... [--gap-ms 300] [--edge-ms 50] [--threshold-db -50]
      Trim each input's edges to <= edge-ms, join with exactly gap-ms of silence. Inputs must
      share rate/channels (else exit 2). Prints the JSON above plus segments [{start_ms,end_ms}]
      (each trimmed input on the OUT timeline).
  vo.py check IN [--lead-max 200] [--trail-max 150] [--gap-max 500] [--pause-ms N ...]
                 [--threshold-db -45]
      Prints JSON {lead_ms, trail_ms, duration_ms, internal_gaps:[{start_ms,len_ms,allowed}],
      pass, failures:[...]}. An internal gap is a silent run longer than gap-max; each
      --pause-ms declares one intentional gap (allowed within +-150 ms of a declared value).

Exit codes: 0 ok / pass, 1 check failed, 2 usage, unreadable or mismatched input.
"""
import argparse
import array
import json
import math
import sys
import wave

WINDOW_MS = 10
PAUSE_TOLERANCE_MS = 150


class VoError(Exception):
    pass


class Audio(object):
    def __init__(self, rate, channels, samples):
        self.rate = rate
        self.channels = channels
        self.samples = samples  # array('h'), interleaved

    @property
    def frames(self):
        return len(self.samples) // self.channels

    def ms(self, frames):
        return frames * 1000.0 / self.rate


def read_wav(path):
    try:
        with wave.open(path, "rb") as w:
            channels, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if width != 2:
                raise VoError("%s: only 16-bit PCM WAV is supported (got %d-bit)" % (path, width * 8))
            data = w.readframes(n)
    except (wave.Error, EOFError, OSError) as e:
        raise VoError("cannot read %s: %s" % (path, e))
    samples = array.array("h")
    samples.frombytes(data[:len(data) - len(data) % (2 * channels)])
    if sys.byteorder == "big":
        samples.byteswap()
    return Audio(rate, channels, samples)


def write_wav(path, audio):
    samples = array.array("h", audio.samples)
    if sys.byteorder == "big":
        samples.byteswap()
    try:
        with wave.open(path, "wb") as w:
            w.setnchannels(audio.channels)
            w.setsampwidth(2)
            w.setframerate(audio.rate)
            w.writeframes(samples.tobytes())
    except (wave.Error, OSError) as e:
        raise VoError("cannot write %s: %s" % (path, e))


def window_db(audio):
    """(frames per window, [dB per 10 ms window]); -inf for digital silence."""
    win = max(1, audio.rate * WINDOW_MS // 1000)
    step = win * audio.channels
    out = []
    s = audio.samples
    for i in range(0, len(s), step):
        chunk = s[i:i + step]
        rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
        out.append(-math.inf if rms == 0 else 20 * math.log10(rms / 32768.0))
    return win, out


def active_span(dbs, threshold):
    idx = [i for i, d in enumerate(dbs) if d >= threshold]
    if not idx:
        return None
    return idx[0], idx[-1]


def edges(audio, threshold):
    """(first sound frame, end frame of the last sound) at window resolution."""
    win, dbs = window_db(audio)
    span = active_span(dbs, threshold)
    if span is None:
        raise VoError("no audio above %s dB" % threshold)
    return span[0] * win, min((span[1] + 1) * win, audio.frames)


def measure(audio, threshold):
    first, last_end = edges(audio, threshold)
    return {"lead_ms": int(round(audio.ms(first))),
            "trail_ms": int(round(audio.ms(audio.frames - last_end))),
            "duration_ms": int(round(audio.ms(audio.frames)))}


def trim_audio(audio, lead_ms, trail_ms, threshold):
    first, last_end = edges(audio, threshold)
    start = max(0, first - int(round(lead_ms * audio.rate / 1000.0)))
    end = min(audio.frames, last_end + int(round(trail_ms * audio.rate / 1000.0)))
    n = audio.channels
    return Audio(audio.rate, n, audio.samples[start * n:end * n])


def join_audio(inputs, gap_ms, edge_ms, threshold):
    first = inputs[0]
    for a in inputs[1:]:
        if (a.rate, a.channels) != (first.rate, first.channels):
            raise VoError("inputs differ in format: %d Hz/%d ch vs %d Hz/%d ch"
                          % (first.rate, first.channels, a.rate, a.channels))
    gap_frames = int(round(gap_ms * first.rate / 1000.0))
    gap = array.array("h", [0]) * (gap_frames * first.channels)
    out = array.array("h")
    segments = []
    pos = 0
    for i, a in enumerate(inputs):
        t = trim_audio(a, edge_ms, edge_ms, threshold)
        if i:
            out.extend(gap)
            pos += gap_frames
        segments.append({"start_ms": int(round(t.ms(pos))), "end_ms": int(round(t.ms(pos + t.frames)))})
        out.extend(t.samples)
        pos += t.frames
    return Audio(first.rate, first.channels, out), segments


def check_audio(audio, lead_max, trail_max, gap_max, pauses, threshold):
    win, dbs = window_db(audio)
    span = active_span(dbs, threshold)
    if span is None:
        raise VoError("no audio above %s dB" % threshold)
    res = measure(audio, threshold)
    gaps, run_start = [], None
    for i in range(span[0], span[1] + 1):
        silent = dbs[i] < threshold
        if silent and run_start is None:
            run_start = i
        if run_start is not None and (not silent or i == span[1]):
            end = i if not silent else i + 1
            start_ms = int(round(audio.ms(run_start * win)))
            len_ms = int(round(audio.ms((end - run_start) * win)))
            if len_ms > gap_max:
                allowed = any(abs(len_ms - p) <= PAUSE_TOLERANCE_MS for p in pauses)
                gaps.append({"start_ms": start_ms, "len_ms": len_ms, "allowed": allowed})
            run_start = None
    failures = []
    if res["lead_ms"] > lead_max:
        failures.append("leading silence %d ms > %d ms" % (res["lead_ms"], lead_max))
    if res["trail_ms"] > trail_max:
        failures.append("trailing silence %d ms > %d ms" % (res["trail_ms"], trail_max))
    for g in gaps:
        if not g["allowed"]:
            failures.append("internal gap %d ms at %d ms > %d ms and not a declared pause"
                            % (g["len_ms"], g["start_ms"], gap_max))
    res.update({"internal_gaps": gaps, "pass": not failures, "failures": failures})
    return res


def dump(obj):
    print(json.dumps(obj, indent=2))


def cmd_trim(args):
    out = trim_audio(read_wav(args.input), args.lead_ms, args.trail_ms, args.threshold_db)
    write_wav(args.output, out)
    dump(measure(out, args.threshold_db))
    return 0


def cmd_join(args):
    out, segments = join_audio([read_wav(p) for p in args.inputs], args.gap_ms, args.edge_ms,
                               args.threshold_db)
    write_wav(args.output, out)
    res = measure(out, args.threshold_db)
    res["segments"] = segments
    dump(res)
    return 0


def cmd_check(args):
    res = check_audio(read_wav(args.input), args.lead_max, args.trail_max, args.gap_max,
                      args.pause_ms, args.threshold_db)
    dump(res)
    return 0 if res["pass"] else 1


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(2)


def build_parser():
    p = Parser(description="Trim, join and check voice-over WAVs (16-bit PCM).")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    t = sub.add_parser("trim", help="trim leading/trailing silence")
    t.add_argument("input")
    t.add_argument("output")
    t.add_argument("--lead-ms", type=float, default=200)
    t.add_argument("--trail-ms", type=float, default=150)
    t.add_argument("--threshold-db", type=float, default=-50)
    j = sub.add_parser("join", help="trim edges and join with an exact gap")
    j.add_argument("output")
    j.add_argument("inputs", nargs="+")
    j.add_argument("--gap-ms", type=float, default=300)
    j.add_argument("--edge-ms", type=float, default=50)
    j.add_argument("--threshold-db", type=float, default=-50)
    c = sub.add_parser("check", help="measure edges and internal gaps; exit 1 on failure")
    c.add_argument("input")
    c.add_argument("--lead-max", type=float, default=200)
    c.add_argument("--trail-max", type=float, default=150)
    c.add_argument("--gap-max", type=float, default=500)
    c.add_argument("--pause-ms", type=float, action="append", default=[],
                   help="an allowed intentional gap (repeatable)")
    c.add_argument("--threshold-db", type=float, default=-45)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {"trim": cmd_trim, "join": cmd_join, "check": cmd_check}
    try:
        return handlers[args.cmd](args)
    except VoError as e:
        sys.stderr.write("error: %s\n" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
