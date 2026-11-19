import json, sys, time
TAIL_MS = 400                         # keep scene alive after VO ends
class Ctx:
    def __init__(self, scene, target, vo_ms, scale=1.0, origin=(0, 0), dry=False):
        self.scene, self.target, self.vo_ms = scene, target, vo_ms
        self.scale, self.origin, self.dry = scale, origin, dry
        self._t0, self._virt = time.monotonic(), 0
    def now(self):                    # ms since scene start (virtual clock in dry-run)
        return max(int((time.monotonic() - self._t0) * 1000), self._virt)
    def _bbox(self, b):
        if b is None: return None
        ox, oy = self.origin
        return [round((b[0]-ox)*self.scale), round((b[1]-oy)*self.scale),
                round(b[2]*self.scale), round(b[3]*self.scale)]
    def mark(self, type, bbox=None, label=""):
        print(json.dumps({"t": self.now(), "scene": self.scene, "type": type,
                          "bbox": self._bbox(bbox), "label": label}), flush=True)
    def sensitive(self, bbox, label): self.mark("sensitive", bbox, label)
    def sensitive_end(self, label):   self.mark("sensitive", None, label)
    def hold_until(self, ms):         # the ONLY way to wait; never bare sleep()
        if self.dry: self._virt = max(self._virt, ms); return
        left = ms - self.now()
        if left > 0: time.sleep(left / 1000)
    def start(self): self._t0 = time.monotonic(); self.mark("scene_start")
    def end(self):
        self.hold_until(self.vo_ms + TAIL_MS); self.mark("scene_end")
