"""Tests for scripts/mobile_driver.py with a fake process runner (no device needed).
Run: python -m unittest discover -s scripts/tests -v"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mobile_driver as md  # noqa: E402

DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node index="0" text="" resource-id="" class="android.widget.FrameLayout" content-desc="" clickable="false" bounds="[0,0][1080,2400]">
 <node index="0" text="New invoice" resource-id="com.example.app:id/new_invoice" class="android.widget.Button" content-desc="Create invoice" clickable="true" bounds="[40,1150][1040,1270]" />
 <node index="1" text="" resource-id="com.example.app:id/pwd" class="android.widget.EditText" content-desc="" clickable="true" password="true" bounds="[40,1300][1040,1400]" />
 <node index="2" text="" resource-id="" class="android.widget.ImageButton" content-desc="" clickable="true" bounds="[900,100][1000,200]" />
 <node index="3" text="gone" resource-id="" class="android.view.View" content-desc="" clickable="false" bounds="[0,0][0,0]" />
</node></hierarchy>"""

AXE = [{"type": "Application", "AXLabel": "Example", "frame": {"x": 0, "y": 0, "width": 393, "height": 852},
        "children": [
            {"type": "Button", "AXLabel": "New invoice", "AXUniqueId": "new_invoice",
             "AXFrame": "{{20, 500}, {353, 44}}", "children": []},
            {"type": "SecureTextField", "AXLabel": "Password", "frame": {"x": 20, "y": 560, "width": 353, "height": 44}},
        ]}]


class FakeRunner:
    """Records commands; answers by the first matching substring of the joined command."""

    def __init__(self, answers=None, rc=0):
        self.calls, self.answers, self.rc = [], answers or {}, rc

    def __call__(self, cmd, timeout=30, binary=False):
        self.calls.append(list(cmd))
        joined = " ".join(cmd)
        out = next((v for k, v in self.answers.items() if k in joined), b"" if binary else "")
        return subprocess.CompletedProcess(cmd, self.rc, out, "boom" if self.rc else "")


class ParseAndroid(unittest.TestCase):
    def test_parse_drops_zero_size_and_reads_fields(self):
        els = md.parse_uiautomator("UI hierchary dumped\n" + DUMP)
        self.assertEqual(len(els), 4)
        b = els[1]
        self.assertEqual((b.short_id, b.label, b.text, b.cls), ("new_invoice", "Create invoice", "New invoice", "Button"))
        self.assertEqual(b.rect, (40, 1150, 1000, 120))
        self.assertEqual(b.center, (540, 1210))
        self.assertEqual(b.bbox, [40, 1150, 1000, 120])
        self.assertTrue(els[2].password)

    def test_no_hierarchy_is_environment(self):
        with self.assertRaises(md.EnvError):
            md.parse_uiautomator("ERROR: null root node")

    def test_escape(self):
        self.assertEqual(md.escape_input_text("a b&c"), "a%sb\\&c")
        with self.assertRaises(md.StepError):
            md.escape_input_text("Xin chào")
        with self.assertRaises(md.StepError):  # Android would type "Hello  world"
            md.escape_input_text("Hello %s world")
        self.assertEqual(md.escape_input_text("50% off"), "50%%soff")


class AndroidActions(unittest.TestCase):
    def driver(self, **kw):
        r = FakeRunner({"uiautomator dump": "UI hierchary dumped to: x", "exec-out cat": DUMP,
                        "wm size": "Physical size: 1080x2400\nOverride size: 720x1600"}, **kw)
        return md.AndroidDriver("emulator-5554", r), r

    def test_find_by_short_id_label_text(self):
        d, _ = self.driver()
        self.assertEqual(d.find(id="new_invoice").label, "Create invoice")
        self.assertEqual(d.find(id="com.example.app:id/new_invoice").text, "New invoice")
        self.assertEqual(d.find(label="Create invoice").short_id, "new_invoice")
        self.assertEqual(d.find(text="invoice", contains=True).short_id, "new_invoice")

    def test_missing_is_step_error(self):
        d, _ = self.driver()
        with self.assertRaises(md.StepError):
            d.find(id="nope", timeout_ms=0)
        self.assertFalse(d.exists(id="nope"))

    def test_tap_type_key_swipe_commands(self):
        d, r = self.driver()
        d.tap(d.find(id="new_invoice"))
        d.type("hi there")
        d.key("back")
        d.swipe(1, 2, 3, 4, 250)
        shell = [c[-1] for c in r.calls if c[:4] == ["adb", "-s", "emulator-5554", "shell"]]
        self.assertIn("input tap 540 1210", shell)
        self.assertIn("input text hi%sthere", shell)
        self.assertIn("input keyevent KEYCODE_BACK", shell)
        self.assertIn("input swipe 1 2 3 4 250", shell)
        with self.assertRaises(md.StepError):
            d.key("rm -rf")

    def test_size_prefers_override(self):
        d, _ = self.driver()
        self.assertEqual(d.size(), (720, 1600))

    def test_launch_validates_ids(self):
        d, r = self.driver()
        d.launch("com.example.app", ".MainActivity")
        self.assertIn("am start -W -n com.example.app/.MainActivity", r.calls[-1][-1])
        with self.assertRaises(md.StepError):
            d.launch("com.x; reboot")

    def test_adb_failure_is_environment(self):
        d, _ = self.driver(rc=1)
        with self.assertRaises(md.EnvError) as cm:
            d.tap((1, 1))
        self.assertEqual(cm.exception.error_class, "environment")

    def test_dump_error_retries_then_environment(self):
        r = FakeRunner({"uiautomator dump": "ERROR: could not get idle state."})
        d = md.AndroidDriver(None, r)
        md.time.sleep, orig = (lambda s: None), md.time.sleep
        try:
            with self.assertRaises(md.EnvError):
                d.snapshot()
        finally:
            md.time.sleep = orig
        self.assertEqual(sum("uiautomator dump" in " ".join(c) for c in r.calls), 3)
        self.assertEqual(r.calls[0][:2], ["adb", "shell"])  # no -s without a device


class IOS(unittest.TestCase):
    def driver(self):
        booted = json.dumps({"devices": {"iOS-18": [{"udid": "ABC", "state": "Booted"}]}})
        r = FakeRunner({"simctl list": booted, "describe-ui": json.dumps(AXE)})
        return md.IOSDriver(None, r), r

    def test_parse_axe_nested_and_axframe(self):
        els = md.parse_axe(AXE)
        self.assertEqual([e.cls for e in els], ["Application", "Button", "SecureTextField"])
        self.assertEqual(els[1].rect, (20, 500, 353, 44))
        self.assertTrue(els[2].password)
        self.assertIsNone(els[1].clickable)

    def test_find_tap_uses_booted_udid(self):
        d, r = self.driver()
        d.tap(d.find(id="new_invoice"))
        self.assertEqual(r.calls[-1], ["axe", "tap", "-x", "196", "-y", "522", "--udid", "ABC"])
        self.assertEqual(d.size(), (393, 852))
        d.key("home")
        self.assertEqual(r.calls[-1][:3], ["axe", "button", "home"])

    def _stop_with(self, rc, stderr):
        booted = json.dumps({"devices": {"iOS-18": [{"udid": "ABC", "state": "Booted"}]}})

        def run(cmd, timeout=30, binary=False):
            if "terminate" in cmd:
                return subprocess.CompletedProcess(cmd, rc, "", stderr)
            return subprocess.CompletedProcess(cmd, 0, booted, "")
        return md.IOSDriver(None, run)

    def test_stop_tolerates_app_not_running(self):
        # simctl exits nonzero when there is nothing to terminate (fresh boot); prepare() calls stop() before launch().
        d = self._stop_with(3, "An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=3):\n"
                               "Simulator device failed to terminate com.example.app.\nfound nothing to terminate")
        d.stop("com.example.app")

    def test_stop_keeps_other_errors(self):
        d = self._stop_with(149, "Invalid device: ABC")
        with self.assertRaises(md.EnvError):
            d.stop("com.example.app")

    def test_no_booted_simulator(self):
        d = md.IOSDriver(None, FakeRunner({"simctl list": json.dumps({"devices": {}})}))
        with self.assertRaises(md.EnvError):
            d.udid()


class Describe(unittest.TestCase):
    def test_unnamed_clickable_flagged(self):
        els = md.parse_uiautomator(DUMP)
        self.assertIn("UNNAMED", md.describe(els[3], 3))
        self.assertIn('id="com.example.app:id/new_invoice"', md.describe(els[1], 1))

    def test_connect_rejects_platform(self):
        with self.assertRaises(ValueError):
            md.connect("web")


if __name__ == "__main__":
    unittest.main()
