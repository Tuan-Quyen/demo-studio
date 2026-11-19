"""Tests for scripts/config.py. Run: python -m unittest discover -s scripts/tests -v"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import config  # noqa: E402
import project  # noqa: E402

def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = config.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class ParserSubset(unittest.TestCase):
    def test_maps_lists_scalars(self):
        text = (
            "# top comment\n"
            "a: 1\n"
            "b: -2.5   # trailing\n"
            "c: true\n"
            "d: null\n"
            "e: ~\n"
            "f: hello world\n"
            "g: \"quoted # not comment: x\"\n"
            "h: 'it''s'\n"
            "flow: [\"16:9\", 'x', 3, true, null]\n"
            "empty: []\n"
            "block:\n"
            "  - one\n"
            "  - two # c\n"
            "same:\n"
            "- p\n"
            "- q\n"
            "nested:\n"
            "  inner:\n"
            "    deep: 7\n"
            "  after: x\n"
            "nothing:\n"
        )
        got = config.parse_builtin(text)
        self.assertEqual(got["a"], 1)
        self.assertEqual(got["b"], -2.5)
        self.assertIs(got["c"], True)
        self.assertIsNone(got["d"])
        self.assertIsNone(got["e"])
        self.assertEqual(got["f"], "hello world")
        self.assertEqual(got["g"], "quoted # not comment: x")
        self.assertEqual(got["h"], "it's")
        self.assertEqual(got["flow"], ["16:9", "x", 3, True, None])
        self.assertEqual(got["empty"], [])
        self.assertEqual(got["block"], ["one", "two"])
        self.assertEqual(got["same"], ["p", "q"])
        self.assertEqual(got["nested"], {"inner": {"deep": 7}, "after": "x"})
        self.assertIsNone(got["nothing"])

    def test_empty_file(self):
        self.assertEqual(config.parse_builtin("# only a comment\n\n"), {})

    def test_errors_have_line_numbers(self):
        cases = {
            "a: 1\n\tb: 2\n": (2, "tabs"),
            "a: 1\nb: {x: 1}\n": (2, "flow maps"),
            "a: &x 1\n": (1, "unsupported"),
            "a: |\n  text\n": (1, "unsupported"),
            "a: [1, 2\n": (1, "one line"),
            "a: [[1], 2]\n": (1, "nested"),
            "a: 1\na: 2\n": (2, "duplicate"),
            "a: 1\n  b: 2\n": (2, "indentation"),
            "a: 1\nb: \"open\n": (2, "unterminated"),
            "list:\n  - k: v\n": (2, "':'"),
            "---\na: 1\n": (1, "document"),
            "- x\n": (1, "key"),
            "a: [1,,2]\n": (1, "empty item"),
            "  a: 1\n": (1, "column 0"),
            "just text\n": (1, "key: value"),
        }
        for text, (line, frag) in cases.items():
            with self.assertRaises(config.ParseError, msg=text) as cm:
                config.parse_builtin(text)
            self.assertEqual(cm.exception.line, line, text)
            self.assertIn(frag, str(cm.exception), text)

    def test_yes_no_stay_strings(self):
        got = config.parse_builtin("a: no\nb: yes\nc: on\nd: off\ne: 16:9\n")
        self.assertEqual(got, {"a": "no", "b": "yes", "c": "on", "d": "off", "e": "16:9"})

    def test_duplicate_key_is_error(self):
        with self.assertRaises(config.ParseError) as cm:
            config.parse_builtin("voice:\n  engine: edge\n  engine: kokoro\n")
        self.assertEqual(cm.exception.line, 3)

    def test_template_parses_to_defaults(self):
        with open(config.TEMPLATE, encoding="utf-8") as f:
            self.assertEqual(config.merge(config.defaults(), config.parse_builtin(f.read())),
                             config.defaults())


class Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.path = os.path.join(self.dir, "demo.yaml")

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def cli(self, *argv):
        return run("--project", self.path, *argv)


class Validation(Workspace):
    def test_template_valid_all_defaults(self):
        code, out, err = self.cli("init")
        self.assertEqual(code, 0, err)
        code, out, err = self.cli("validate")
        self.assertEqual(code, 0, err)
        self.assertIn("not set yet", out)
        self.assertEqual(config.load_config(self.path), config.defaults())

    def test_init_keeps_existing(self):
        self.write("length_s: 60\n")
        code, out, _ = self.cli("init")
        self.assertEqual((code, out.split(":")[0]), (0, "exists"))
        self.assertEqual(config.load_config(self.path)["length_s"], 60)

    def test_defaults_match_specs(self):
        d = config.defaults()
        self.assertEqual(d["targets"], {"lufs": -14, "true_peak": -1, "max_drift_ms": 80,
                                        "caption_offset_ms": 200})
        self.assertEqual(d["captions"], {"burn_in": False, "layout": "overlay", "max_chars": 42})
        self.assertEqual(d["formats"], ["16:9"])

    def test_partial_file_gets_defaults(self):
        self.write("voice:\n  engine: kokoro\nlength_s: 90\n")
        cfg = config.load_config(self.path)
        self.assertEqual(cfg["voice"], {"engine": "kokoro", "name": None, "rate": "+0%", "pitch": "+0Hz", "language": "en",
                                      "lexicon": {}})
        self.assertEqual(cfg["length_s"], 90)
        self.assertEqual(cfg["targets"]["lufs"], -14)

    def bad(self, text, *fragments):
        self.write(text)
        code, _, err = self.cli("validate")
        self.assertEqual(code, 2, err)
        for f in fragments:
            self.assertIn(f, err)

    def test_unknown_keys(self):
        self.bad("voice:\n  speed: 2\nbogus: 1\n", "voice.speed: unknown key", "bogus: unknown key")

    def test_enum_errors(self):
        self.bad("platform: windows\nvoice:\n  engine: azure\nmotion:\n  level: wild\n",
                 "platform: must be one of", "voice.engine", "motion.level")

    def test_formats_errors(self):
        self.bad('formats: ["4:3"]\n', "formats[0]: must be one of")
        self.bad('formats: []\n', "at least 1")
        self.bad('formats: ["16:9", "16:9"]\n', "duplicate")

    def test_type_errors(self):
        self.bad('length_s: "ninety"\n', "length_s: must be a whole number")
        self.bad("length_s: 60.5\n", "whole number")
        self.bad("captions:\n  burn_in: 1\n", "true or false")
        self.bad("captions:\n  layout: top\n", "captions.layout")
        self.write("captions:\n  layout: band\n")
        self.assertEqual(config.load_config(self.path)["captions"]["layout"], "band")
        self.bad("targets:\n  lufs: loud\n", "must be a number")
        self.bad("voice:\n  engine: null\n", "must not be null")
        self.bad("targets:\n  lufs: true\n", "must be a number")

    def test_range_errors(self):
        self.bad("length_s: 4\n", "between 5 and 600")
        self.bad("length_s: 601\n", "between 5 and 600")
        self.write("length_s: 600\n")
        self.assertEqual(config.load_config(self.path)["length_s"], 600)
        self.bad("targets:\n  true_peak: 3\n", "targets.true_peak")
        self.bad("captions:\n  max_chars: 5\n", "captions.max_chars")
        self.bad("targets:\n  max_drift_ms: -1\n", "targets.max_drift_ms")
        self.bad("music:\n  duck_db: 6\n", "music.duck_db")

    def test_install_lists(self):
        self.bad("install:\n  approved: [a]\n  declined: [a]\n", "both approved and declined")
        self.bad("install:\n  approved: [Bad Name]\n", "not a valid feature")

    def test_language(self):
        self.bad("voice:\n  language: english language\n", "voice.language")
        self.write("voice:\n  language: pt-BR\n")
        self.assertEqual(config.load_config(self.path)["voice"]["language"], "pt-BR")
        self.write('voice:\n  language: "no"\n')
        self.assertEqual(config.load_config(self.path)["voice"]["language"], "no")

    def test_syntax_error_reports_line(self):
        self.write("length_s: 60\nvoice: {engine: edge}\n")
        code, _, err = self.cli("validate")
        self.assertEqual(code, 2)
        self.assertIn("line 2", err)

    def test_missing_file(self):
        code, _, err = self.cli("validate")
        self.assertEqual(code, 2)
        self.assertIn("run init", err)

    def test_no_target(self):
        code, _, err = run("validate")
        self.assertEqual(code, 2)
        self.assertIn("--project or --slug", err)


class Lexicon(Workspace):
    def test_block_form_quoted_keys(self):
        self.write('voice:\n  lexicon:\n    "AI": ây ai\n    "AI Video Trends: 2026": "ây ai # vi-đi-ô"\n'
                   "    'It''s': it is\n    plain: x\n")
        lex = config.load_config(self.path)["voice"]["lexicon"]
        self.assertEqual(lex, {"AI": "ây ai", "AI Video Trends: 2026": "ây ai # vi-đi-ô",
                               "It's": "it is", "plain": "x"})

    def test_flow_form(self):
        self.write('voice:\n  lexicon: {"AI": "ây ai", "You, Tube": "diu-tíu", "a: b": "c"}\n')
        self.assertEqual(config.load_config(self.path)["voice"]["lexicon"],
                         {"AI": "ây ai", "You, Tube": "diu-tíu", "a: b": "c"})
        self.write("voice:\n  lexicon: {}\n")
        self.assertEqual(config.load_config(self.path)["voice"]["lexicon"], {})

    def test_flow_map_errors(self):
        for text in ('a: {x: 1}\n', 'a: {"x": 1, "x": 2}\n', 'a: {"x": [1]}\n', 'a: {"x": 1\n',
                     'a: {"x"}\n'):
            with self.assertRaises(config.ParseError, msg=text):
                config.parse_builtin(text)

    def test_duplicate_term_is_error(self):
        with self.assertRaises(config.ParseError):
            config.parse_builtin('l:\n  "AI": a\n  "AI": b\n')

    def test_get(self):
        self.write('voice:\n  lexicon:\n    "AI": ây ai\n')
        self.assertEqual(json.loads(self.cli("get", "voice.lexicon")[1]), {"AI": "ây ai"})
        self.write("")
        self.assertEqual(json.loads(self.cli("get", "voice.lexicon")[1]), {})

    def bad(self, text, *fragments):
        self.write(text)
        code, _, err = self.cli("validate")
        self.assertEqual(code, 2, err)
        for f in fragments:
            self.assertIn(f, err)

    def test_invalid_values(self):
        self.bad('voice:\n  lexicon:\n    "AI": ""\n', "must not be empty")
        self.bad('voice:\n  lexicon:\n    "AI":\n', "voice.lexicon['AI']")
        self.bad('voice:\n  lexicon:\n    "AI": 5\n', "must be text")
        self.bad('voice:\n  lexicon:\n    "%s": x\n' % ("a" * 61), "term is longer than 60")
        self.bad('voice:\n  lexicon:\n    "AI": "%s"\n' % ("a" * 61), "spoken spelling is longer")
        self.bad("voice:\n  lexicon: [a]\n", "must be a map")
        self.bad("voice:\n  lexicon: x\n", "must be a map")
        self.write('voice:\n  lexicon:\n    "%s": "%s"\n' % ("a" * 60, "b" * 60))
        self.assertEqual(self.cli("validate")[0], 0)

    def test_free_form_keys_do_not_trip_unknown_key(self):
        self.write('voice:\n  lexicon: {"engine": "x", "bogus": "y"}\n')
        self.assertEqual(self.cli("validate")[0], 0)
        self.bad("voice:\n  speed: 2\n", "voice.speed: unknown key")


class ApplyLexicon(Workspace):
    LEX = ('voice:\n  lexicon:\n    "AI": ây ai\n    "AI Video Trends": ây ai vi-đi-ô tren\n'
           '    "YouTube": diu-tíu\n    "C++": xi cộng cộng\n')

    def conv(self, text, lex=None):
        self.write(self.LEX if lex is None else lex)
        code, out, err = self.cli("apply-lexicon", "--text", text)
        self.assertEqual(code, 0, err)
        return out

    def test_longest_first(self):
        self.assertEqual(self.conv("AI Video Trends and AI"), "ây ai vi-đi-ô tren and ây ai")

    def test_whole_word_only(self):
        self.assertEqual(self.conv("AIM and trAIn, NAI AIs"), "AIM and trAIn, NAI AIs")

    def test_case_sensitive(self):
        self.assertEqual(self.conv("ai Ai youtube"), "ai Ai youtube")

    def test_adjacent_punctuation(self):
        self.assertEqual(self.conv('"AI," (YouTube). AI?'), '"ây ai," (diu-tíu). ây ai?')
        self.assertEqual(self.conv("in C++, yes"), "in xi cộng cộng, yes")

    def test_vietnamese_neighbours(self):
        self.assertEqual(self.conv("của AI và"), "của ây ai và")
        self.assertEqual(self.conv("AIđ đAI"), "AIđ đAI")  # diacritic letters are word chars
        self.assertEqual(self.conv("AIế"), "AIế")
        self.assertEqual(self.conv("AI" + "é"), "AI" + "é")  # decomposed accent

    def test_no_resubstitution(self):
        lex = 'voice:\n  lexicon:\n    "A": B\n    "B": C\n'
        self.assertEqual(self.conv("A B", lex), "B C")
        self.assertEqual(self.conv("AI", 'voice:\n  lexicon: {"AI": "AI AI"}\n'), "AI AI")

    def test_empty_lexicon_is_identity(self):
        text = "AI  YouTube\n\ttext é\n"
        self.assertEqual(self.conv(text, ""), text)

    def test_json_counts(self):
        self.write(self.LEX)
        code, out, _ = self.cli("apply-lexicon", "--json", "--text", "AI, AI and YouTube AI Video Trends")
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(res["text"], "ây ai, ây ai and diu-tíu ây ai vi-đi-ô tren")
        self.assertEqual(res["applied"], [
            {"term": "AI Video Trends", "spoken": "ây ai vi-đi-ô tren", "count": 1},
            {"term": "YouTube", "spoken": "diu-tíu", "count": 1},
            {"term": "AI", "spoken": "ây ai", "count": 2}])

    def test_file_and_stdin(self):
        self.write(self.LEX)
        src = os.path.join(self.dir, "narr.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("Xin chào AI\n")
        self.assertEqual(self.cli("apply-lexicon", "--file", src)[1], "Xin chào ây ai\n")
        old = sys.stdin
        sys.stdin = io.StringIO("YouTube\n")
        try:
            self.assertEqual(self.cli("apply-lexicon")[1], "diu-tíu\n")
        finally:
            sys.stdin = old

    def test_errors(self):
        self.write(self.LEX)
        self.assertEqual(self.cli("apply-lexicon", "--file", os.path.join(self.dir, "none.txt"))[0], 2)
        self.assertEqual(self.cli("apply-lexicon", "--text", "a", "--file", "b")[0], 2)
        self.write("voice:\n  lexicon:\n    AI: ''\n")
        self.assertEqual(self.cli("apply-lexicon", "--text", "AI")[0], 2)


class VoiceProps(Workspace):
    def bad(self, text, *fragments):
        self.write(text)
        code, _, err = self.cli("validate")
        self.assertEqual(code, 2, err)
        for f in fragments:
            self.assertIn(f, err)

    def test_defaults_and_valid(self):
        self.write("")
        v = config.load_config(self.path)["voice"]
        self.assertEqual((v["rate"], v["pitch"]), ("+0%", "+0Hz"))
        self.write('voice:\n  engine: recorded\n  rate: "-30%"\n  pitch: "+50Hz"\n')
        v = config.load_config(self.path)["voice"]
        self.assertEqual((v["engine"], v["rate"], v["pitch"]), ("recorded", "-30%", "+50Hz"))
        self.write('voice:\n  rate: "+30%"\n  pitch: "-50Hz"\n')
        self.assertEqual(self.cli("validate")[0], 0)
        for e in ("edge", "kokoro", "elevenlabs", "recorded"):
            self.write("voice:\n  engine: %s\n" % e)
            self.assertEqual(self.cli("validate")[0], 0, e)

    def test_bad_patterns(self):
        for text in ('rate: "10%"', 'rate: "+10"', 'rate: "+100%"', 'rate: fast', 'rate: "+5 %"',
                     'rate: 10'):
            self.bad("voice:\n  %s\n" % text, "voice.rate")
        for text in ('pitch: "5Hz"', 'pitch: "+5"', 'pitch: "+1000Hz"', 'pitch: high',
                     'pitch: "+5hz"'):
            self.bad("voice:\n  %s\n" % text, "voice.pitch")
        self.bad("voice:\n  rate: null\n", "must not be null")

    def test_out_of_range(self):
        self.bad('voice:\n  rate: "+31%"\n', "voice.rate: must be between -30 and +30")
        self.bad('voice:\n  rate: "-31%"\n', "voice.rate")
        self.bad('voice:\n  pitch: "+51Hz"\n', "voice.pitch: must be between -50 and +50")
        self.bad('voice:\n  pitch: "-51Hz"\n', "voice.pitch")


class SourceLanguage(Workspace):
    def test_default_null_and_valid(self):
        self.write("")
        self.assertIsNone(config.load_config(self.path)["language"])
        self.assertIsNone(json.loads(self.cli("get", "language")[1]))
        self.write("language: pt-BR\n")
        self.assertEqual(config.load_config(self.path)["language"], "pt-BR")
        self.write('language: "no"\n')
        self.assertEqual(config.load_config(self.path)["language"], "no")

    def test_invalid(self):
        for text in ("language: english language\n", "language: e\n", "language: 5\n", 'language: ""\n'):
            self.write(text)
            code, _, err = self.cli("validate")
            self.assertEqual(code, 2, text)
            self.assertIn("language", err)

    def test_template_has_language_and_recommended_voice(self):
        with open(config.TEMPLATE, encoding="utf-8") as f:
            text = f.read()
        self.assertIsNone(config.parse_builtin(text)["language"])
        self.assertLess(text.index("vi-VN-NamMinhNeural"), text.index("vi-VN-HoaiMyNeural"))
        self.assertIsNone(config.defaults()["voice"]["name"])


class Get(Workspace):
    def test_get_paths(self):
        self.write("voice:\n  engine: elevenlabs\n")
        self.assertEqual(json.loads(self.cli("get", "voice.engine")[1]), "elevenlabs")
        self.assertEqual(json.loads(self.cli("get", "targets.lufs")[1]), -14)
        self.assertEqual(json.loads(self.cli("get", "captions")[1]),
                         {"burn_in": False, "layout": "overlay", "max_chars": 42})
        self.assertEqual(json.loads(self.cli("get", "formats")[1]), ["16:9"])
        self.assertIsNone(json.loads(self.cli("get", "platform")[1]))
        self.assertEqual(json.loads(self.cli("get")[1])["voice"]["engine"], "elevenlabs")

    def test_get_unknown(self):
        self.write("")
        code, _, err = self.cli("get", "voice.nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown path", err)


class DiffMapping(Workspace):
    def diff(self, before, after):
        self.write(before)
        self.assertEqual(self.cli("apply")[0], 0)
        self.write(after)
        code, out, err = self.cli("diff", "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def keys(self, res):
        return [r["key"] for r in res["rerun"]]

    def test_no_snapshot(self):
        self.write("")
        res = json.loads(self.cli("diff", "--json")[1])
        self.assertFalse(res["baseline"])
        self.assertEqual(res["rerun"], [])
        self.assertIn("first run", self.cli("diff")[1])

    def test_no_change(self):
        res = self.diff("length_s: 60\n", "length_s: 60  # same\n")
        self.assertEqual(res["changed"], [])
        self.assertIn("no changes", self.cli("diff")[1])

    def test_defaults_equal_explicit(self):
        res = self.diff("", "voice:\n  engine: edge\ntargets:\n  lufs: -14\n")
        self.assertEqual(res["changed"], [])

    def test_voice_engine(self):
        res = self.diff("", "voice:\n  engine: kokoro\n")
        self.assertEqual(res["changed"][0]["path"], "voice.engine")
        self.assertEqual(self.keys(res), ["voice", "timeline", "motion", "captions", "mix",
                                          "checks", "delivery"])
        self.assertEqual(res["pre"], [])

    def test_voice_language_reopens_narration(self):
        res = self.diff("", "voice:\n  language: vi\n")
        self.assertEqual(res["pre"], ["scriptwriter"])
        self.assertEqual(res["gates"], ["G2"])
        self.assertEqual(self.keys(res)[0], "voice")

    def test_motion(self):
        res = self.diff("", "motion:\n  level: cinematic\n")
        self.assertEqual(self.keys(res), ["motion", "checks", "delivery"])

    def test_formats(self):
        res = self.diff("", 'formats: ["16:9", "9:16"]\n')
        self.assertEqual(self.keys(res), ["motion", "captions", "checks", "delivery"])

    def test_captions(self):
        res = self.diff("", "captions:\n  max_chars: 36\n")
        self.assertEqual(self.keys(res), ["captions", "checks", "delivery"])
        res = self.diff("", "captions:\n  layout: band\n")
        self.assertEqual(self.keys(res), ["captions", "checks", "delivery"])

    def test_mix_fields(self):
        for text in ("music:\n  style: calm\n", "music:\n  duck_db: -24\n",
                     "targets:\n  lufs: -16\n", "targets:\n  true_peak: -2\n"):
            res = self.diff("", text)
            self.assertEqual(self.keys(res), ["mix", "checks", "delivery"], text)

    def test_privacy(self):
        res = self.diff("", 'privacy:\n  blur: ["email"]\n  real_data: true\n')
        self.assertEqual(self.keys(res), ["blur", "checks", "delivery"])
        self.assertEqual(len(res["changed"]), 2)

    def test_drift(self):
        res = self.diff("", "targets:\n  max_drift_ms: 40\n")
        self.assertEqual(self.keys(res), ["timeline", "motion", "captions", "mix", "checks", "delivery"])

    def test_caption_offset(self):
        res = self.diff("", "targets:\n  caption_offset_ms: 100\n")
        self.assertEqual(self.keys(res), ["captions", "checks", "delivery"])

    def test_platform_is_whole_rerecord(self):
        res = self.diff("platform: web\n", "platform: android\n")
        self.assertEqual(self.keys(res), project.RUN_ORDER)
        self.assertEqual(res["pre"], ["app-scout", "storyboarder", "scriptwriter"])
        self.assertEqual(res["gates"], ["G2"])

    def test_length_asks_user(self):
        res = self.diff("length_s: 60\n", "length_s: 90\n")
        self.assertTrue(res["needs_user"])
        self.assertEqual(res["pre"], ["storyboarder"])
        self.assertEqual(res["gates"], ["G2"])
        self.assertEqual(self.keys(res), ["timeline", "motion", "captions", "mix", "checks", "delivery"])
        self.assertNotIn("voice", self.keys(res))
        self.assertNotIn("events", self.keys(res))
        self.assertTrue(any("word budget" in n and "narration changes" in n for n in res["notes"]))

    def test_voice_and_events_only_from_expected_fields(self):
        cases = {
            "platform: android\n": (True, True),
            "voice:\n  engine: kokoro\n": (True, False),
            "voice:\n  name: Aria\n": (True, False),
            "voice:\n  language: vi\n": (True, False),
            "length_s: 40\n": (False, False),
            "formats: [\"9:16\"]\n": (False, False),
            "motion:\n  level: basic\n": (False, False),
            "music:\n  style: calm\n": (False, False),
            "captions:\n  burn_in: true\n": (False, False),
            "targets:\n  lufs: -16\n": (False, False),
            "targets:\n  max_drift_ms: 40\n": (False, False),
            "targets:\n  caption_offset_ms: 100\n": (False, False),
            "privacy:\n  real_data: true\n": (False, False),
            "install:\n  approved: [mix]\n": (False, False),
        }
        for text, (voice, events) in cases.items():
            res = self.diff("", text)
            keys = self.keys(res)
            self.assertEqual("voice" in keys, voice, text)
            self.assertEqual("events" in keys, events, text)

    def test_lexicon_add_change_remove(self):
        base = 'voice:\n  lexicon: {"AI": "ây ai", "Old": "o"}\n'
        res = self.diff("", base)
        self.assertEqual(res["lexicon"]["added"], {"AI": "ây ai", "Old": "o"})
        self.assertEqual(self.keys(res), ["voice", "timeline", "motion", "captions", "mix",
                                          "checks", "delivery"])
        self.assertEqual((res["pre"], res["gates"], res["needs_user"]), ([], [], False))
        self.assertNotIn("events", self.keys(res))
        res = self.diff(base, 'voice:\n  lexicon: {"AI": "ay eye", "New": "n"}\n')
        lex = res["lexicon"]
        self.assertEqual(lex["added"], {"New": "n"})
        self.assertEqual(lex["changed"], {"AI": {"old": "ây ai", "new": "ay eye"}})
        self.assertEqual(lex["removed"], {"Old": "o"})
        self.assertEqual(self.keys(res)[0], "voice")
        self.assertEqual(res["pre"], [])
        text = self.cli("diff")[1]
        self.assertIn('lexicon + "New" -> "n"', text)
        self.assertIn('lexicon ~ "AI": "ây ai" -> "ay eye"', text)
        self.assertIn('lexicon - "Old" (was "o")', text)
        res = self.diff(base, "")
        self.assertEqual(res["lexicon"]["removed"], {"AI": "ây ai", "Old": "o"})
        self.assertEqual(self.keys(res)[0], "voice")

    def test_lexicon_unchanged_no_rerun(self):
        res = self.diff('voice:\n  lexicon: {"AI": "x"}\n', 'voice:\n  lexicon:\n    "AI": x\n')
        self.assertEqual(res["changed"], [])
        self.assertNotIn("lexicon", res)

    def test_diff_reruns_voice(self):
        for text in ('voice:\n  rate: "-10%"\n', 'voice:\n  pitch: "+5Hz"\n',
                     "voice:\n  engine: recorded\n"):
            res = self.diff("", text)
            self.assertEqual(self.keys(res), ["voice", "timeline", "motion", "captions", "mix",
                                           "checks", "delivery"], text)
            self.assertEqual((res["pre"], res["gates"]), ([], []), text)
        res = self.diff("voice:\n  engine: recorded\n", "voice:\n  engine: edge\n")
        self.assertEqual(self.keys(res)[0], "voice")

    def test_language_reopens_script_and_localization(self):
        res = self.diff("", "language: vi\n")
        self.assertEqual(res["pre"], ["scriptwriter", "localizer"])
        self.assertEqual(res["gates"], ["G2"])
        self.assertTrue(res["needs_user"])
        self.assertEqual(self.keys(res), ["voice", "timeline", "motion", "captions", "mix",
                                          "checks", "delivery"])
        self.assertEqual(res["localization"], {"source": "vi", "target": "en", "needed": True})
        self.assertTrue(any(n.startswith("localization:") and "localizer translates" in n
                            for n in res["notes"]))
        self.assertIn("re-run first: scriptwriter, localizer (reopens G2)", self.cli("diff")[1])

    def test_language_change_between_values(self):
        res = self.diff("language: en\nvoice:\n  language: vi\n", "language: de\nvoice:\n  language: vi\n")
        self.assertEqual(res["pre"], ["scriptwriter", "localizer"])
        self.assertTrue(res["needs_user"])

    def test_language_set_to_effective_value_is_noop(self):
        res = self.diff("voice:\n  language: vi\n", "language: vi\nvoice:\n  language: vi\n")
        self.assertEqual(len(res["changed"]), 1)
        self.assertEqual((res["pre"], res["rerun"], res["needs_user"]), ([], [], False))
        res = self.diff("language: vi\nvoice:\n  language: vi\n", "voice:\n  language: vi\n")
        self.assertEqual((res["pre"], res["rerun"]), ([], []))

    def test_voice_language_with_source_language_uses_localizer(self):
        res = self.diff("language: en\n", "language: en\nvoice:\n  language: vi\n")
        self.assertEqual(res["pre"], ["localizer"])
        self.assertEqual(res["gates"], ["G2"])
        self.assertTrue(res["needs_user"])
        self.assertEqual(self.keys(res)[0], "voice")
        self.assertEqual(res["localization"], {"source": "en", "target": "vi", "needed": True})

    def test_voice_language_without_source_language_uses_scriptwriter(self):
        res = self.diff("", "voice:\n  language: vi\n")
        self.assertEqual(res["pre"], ["scriptwriter"])
        self.assertEqual(res["gates"], ["G2"])
        self.assertTrue(res["needs_user"])
        self.assertEqual(res["localization"]["needed"], False)
        self.assertTrue(any("none needed" in n for n in res["notes"]))

    def test_voice_language_back_to_source_uses_scriptwriter(self):
        res = self.diff("language: en\nvoice:\n  language: vi\n", "language: en\nvoice:\n  language: en\n")
        self.assertEqual(res["pre"], ["scriptwriter"])

    def test_burn_in_only_reruns_render(self):
        res = self.diff("", "captions:\n  burn_in: true\n")
        self.assertEqual(self.keys(res), ["checks", "delivery"])
        self.assertEqual(res["pre"], [])
        self.assertFalse(res["needs_user"])
        self.assertEqual(self.keys(self.diff("", "captions:\n  max_chars: 30\n")),
                         ["captions", "checks", "delivery"])

    def test_install_only(self):
        res = self.diff("", "install:\n  approved: [mix]\n")
        self.assertEqual(res["rerun"], [])
        self.assertEqual(len(res["changed"]), 1)

    def test_multiple_changes_run_order_and_owners(self):
        res = self.diff("", "music:\n  style: calm\nprivacy:\n  real_data: true\n")
        self.assertEqual(self.keys(res), ["blur", "mix", "checks", "delivery"])
        self.assertEqual(res["rerun"][0]["owner"], project.OWNERS["blur"])

    def test_every_schema_field_has_a_rule(self):
        for path in config.flatten(config.defaults()):
            config.lookup_rule(path)

    def test_diff_text_output(self):
        self.write("")
        self.cli("apply")
        self.write("motion:\n  level: basic\n")
        code, out, _ = self.cli("diff")
        self.assertEqual(code, 0)
        self.assertIn('motion.level: null -> "basic"', out)
        self.assertIn("motion (motion-designer)", out)

    def test_invalid_file_blocks_diff_and_apply(self):
        self.write("motion:\n  level: wild\n")
        self.assertEqual(self.cli("diff")[0], 2)
        self.assertEqual(self.cli("apply")[0], 2)
        self.assertFalse(os.path.exists(config.snapshot_path(self.path)))

    def test_apply_snapshot_then_clean_diff(self):
        self.write("length_s: 60\n")
        code, _, _ = self.cli("apply")
        self.assertEqual(code, 0)
        with open(config.snapshot_path(self.path), encoding="utf-8") as f:
            snap = json.load(f)
        self.assertEqual(snap["config"]["length_s"], 60)
        self.assertIn("no changes", self.cli("diff")[1])

    def test_corrupt_snapshot(self):
        self.write("")
        with open(config.snapshot_path(self.path), "w", encoding="utf-8") as f:
            f.write("{nope")
        code, _, err = self.cli("diff")
        self.assertEqual(code, 2)
        self.assertIn("unreadable", err)


if __name__ == "__main__":
    unittest.main()
