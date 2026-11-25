import json
from pathlib import Path

from eye_tracker import EYE_TRIGGERS
from hand_detector import HAND_TRIGGERS

STORE = Path(__file__).with_name("bindings.json")

DEFAULTS = {
    "hand": {key: "none" for key, _ in HAND_TRIGGERS},
    "eye": {key: "none" for key, _ in EYE_TRIGGERS},
}
DEFAULTS["hand"]["pinch"] = "left_click"
DEFAULTS["hand"]["point"] = "move_cursor"
DEFAULTS["hand"]["palm"] = "right_click"
DEFAULTS["eye"]["blink_left"] = "left_click"
DEFAULTS["eye"]["wink_left"] = "left_click"
DEFAULTS["eye"]["blink_right"] = "right_click"
DEFAULTS["eye"]["wink_right"] = "right_click"
DEFAULTS["eye"]["gaze"] = "move_cursor"


class Bindings:
    def __init__(self):
        self.data = {
            "hand": dict(DEFAULTS["hand"]),
            "eye": dict(DEFAULTS["eye"]),
        }
        self.load()

    def load(self):
        if not STORE.exists():
            self.save()
            return
        try:
            raw = json.loads(STORE.read_text(encoding="utf-8"))
            for section in ("hand", "eye"):
                self.data[section].update(raw.get(section, {}))
        except (OSError, json.JSONDecodeError):
            pass

    def save(self):
        STORE.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, section, trigger):
        return self.data.get(section, {}).get(trigger, "none")

    def set(self, section, trigger, action):
        self.data.setdefault(section, {})[trigger] = action
        self.save()
