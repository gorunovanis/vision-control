import math
import time

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    HandLandmarksConnections,
    RunningMode,
)
from mediapipe.tasks.python.vision.drawing_utils import DrawingSpec, draw_landmarks

from model_store import ensure_models

HAND_TRIGGERS = [
    ("fist", "Кулак"),
    ("palm", "Открытая ладонь"),
    ("point", "Указательный палец"),
    ("peace", "Победа (V)"),
    ("three", "Три пальца"),
    ("four", "Четыре пальца"),
    ("pinch", "Пинч (щипок)"),
    ("ok", "Жест OK"),
    ("thumbs_up", "Лайк"),
    ("thumbs_down", "Дизлайк"),
    ("rock", "Рок"),
    ("call", "«Позвонить»"),
    ("swipe_left", "Свайп влево"),
    ("swipe_right", "Свайп вправо"),
    ("swipe_up", "Свайп вверх"),
    ("swipe_down", "Свайп вниз"),
]


class HandDetector:
    def __init__(self):
        paths = ensure_models()
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(paths["hand_landmarker.task"])),
            running_mode=RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.landmarker = HandLandmarker.create_from_options(options)
        self.prev_gesture = "none"
        self.wrist_hist = []
        self.pinch_latched = False
        self.finger_xy = None
        self.debug = {}
        self._ts = 0

    def detect(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        self._ts += 33
        result = self.landmarker.detect_for_video(mp_image, self._ts)

        gesture = "none"
        swipe = None
        self.finger_xy = None
        handedness = ""

        if result.hand_landmarks:
            lm = result.hand_landmarks[0]
            if result.handedness:
                handedness = result.handedness[0][0].category_name
            gesture = self._classify(lm, handedness)
            swipe = self._swipe(lm)
            idx = lm[8]
            h, w = frame.shape[:2]
            self.finger_xy = (idx.x * w, idx.y * h)
            draw_landmarks(
                frame,
                lm,
                HandLandmarksConnections.HAND_CONNECTIONS,
                DrawingSpec(color=(80, 255, 210), thickness=2, circle_radius=3),
                DrawingSpec(color=(40, 160, 255), thickness=2),
            )
        else:
            self.wrist_hist.clear()
            self.prev_gesture = "none"
            self.pinch_latched = False

        fired = []
        if swipe:
            fired.append(swipe)
        if gesture == "pinch":
            if not self.pinch_latched:
                fired.append("pinch")
                self.pinch_latched = True
        else:
            self.pinch_latched = False
            if gesture != "none" and gesture != self.prev_gesture:
                fired.append(gesture)
        self.prev_gesture = gesture

        self.debug = {
            "gesture": gesture,
            "hand": handedness or "—",
            "swipe": swipe or "—",
            "pinch": self.pinch_latched,
        }
        self._hud(frame)
        return fired, gesture, frame

    def _fingers(self, lm, handedness):
        if handedness == "Right":
            thumb = lm[4].x < lm[3].x
        else:
            thumb = lm[4].x > lm[3].x
        index = lm[8].y < lm[6].y
        middle = lm[12].y < lm[10].y
        ring = lm[16].y < lm[14].y
        pinky = lm[20].y < lm[18].y
        return [thumb, index, middle, ring, pinky]

    def _hand_size(self, lm):
        return math.hypot(lm[0].x - lm[9].x, lm[0].y - lm[9].y) or 0.15

    def _classify(self, lm, handedness):
        f = self._fingers(lm, handedness)
        size = self._hand_size(lm)
        pinch_dist = math.hypot(lm[4].x - lm[8].x, lm[4].y - lm[8].y)
        pinched = pinch_dist < size * 0.45

        if pinched and f[2] and f[3] and f[4]:
            return "ok"
        if pinched:
            return "pinch"

        pattern = tuple(f)
        mapping = {
            (False, False, False, False, False): "fist",
            (False, True, False, False, False): "point",
            (False, True, True, False, False): "peace",
            (False, True, True, True, False): "three",
            (False, True, True, True, True): "four",
            (True, True, True, True, True): "palm",
            (True, False, False, False, True): "call",
            (False, True, False, False, True): "rock",
        }
        if pattern == (True, False, False, False, False):
            if lm[4].y > lm[2].y + 0.04:
                return "thumbs_down"
            return "thumbs_up"
        return mapping.get(pattern, "none")

    def _swipe(self, lm):
        now = time.time()
        self.wrist_hist.append((lm[0].x, lm[0].y, now))
        self.wrist_hist = [p for p in self.wrist_hist if now - p[2] < 0.28]
        if len(self.wrist_hist) < 4:
            return None
        x0, y0, t0 = self.wrist_hist[0]
        x1, y1, t1 = self.wrist_hist[-1]
        dt = max(t1 - t0, 1e-3)
        dx, dy = x1 - x0, y1 - y0
        if math.hypot(dx, dy) / dt < 1.15:
            return None
        self.wrist_hist.clear()
        if abs(dx) > abs(dy):
            return "swipe_left" if dx < 0 else "swipe_right"
        return "swipe_up" if dy < 0 else "swipe_down"

    def _hud(self, frame):
        lines = [
            f"HAND: {self.debug.get('hand', '—')}",
            f"GESTURE: {self.debug.get('gesture', 'none')}",
            f"SWIPE: {self.debug.get('swipe', '—')}",
        ]
        y = 28
        for line in lines:
            cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80, 255, 210), 2, cv2.LINE_AA)
            y += 26

    def close(self):
        self.landmarker.close()
