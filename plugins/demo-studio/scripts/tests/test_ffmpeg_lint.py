"""ffmpeg -nostdin lint for agent/skill Markdown. Run: python -m unittest discover -s scripts/tests -v"""
import os
import re
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.dirname(SCRIPTS)
LIVE_CAPTURE = re.compile(r"-f (gdigrab|avfoundation|x11grab|dshow)\b")


class FfmpegNostdinLint(unittest.TestCase):
    """Every `ffmpeg ` command in agents/ and skills/ must carry -nostdin (and -y when it writes a file)."""

    def test_all_ffmpeg_commands_have_nostdin(self):
        bad = []
        for sub in ("agents", "skills"):
            for root, _, names in os.walk(os.path.join(PLUGIN, sub)):
                for n in names:
                    if not n.endswith(".md"):
                        continue
                    path = os.path.join(root, n)
                    text = open(path, encoding="utf-8").read()
                    for m in re.finditer(r"(?<![\w-])ffmpeg (-[^\n`]*)", text):
                        rest = m.group(1)
                        if LIVE_CAPTURE.search(rest) and "-list_devices" not in rest:
                            continue  # live recorder: stopped with `q` on stdin, -nostdin would break the stop
                        if "-nostdin" not in rest:
                            line = text.count("\n", 0, m.start()) + 1
                            bad.append(f"{os.path.relpath(path, PLUGIN)}:{line}: ffmpeg {rest[:50]}")
        self.assertEqual(bad, [], "ffmpeg without -nostdin:\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
