import math

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker,
    FaceLandmarkerOptions,
    FaceLandmarksConnections,
    RunningMode,
)
from mediapipe.tasks.python.vision.drawing_utils import DrawingSpec, draw_landmarks

from actions import screen_size
from model_store import ensure_models

LEFT_EAR = [33, 160, 158, 133, 153, 144]
RIGHT_EAR = [362, 385, 387, 263, 373, 380]
LEFT_IRIS = 468
RIGHT_IRIS = 473
LEFT_INNER, LEFT_OUTER = 133, 33
RIGHT_INNER, RIGHT_OUTER = 362, 263

EYE_TRIGGERS = [
    ("blink_left", "Моргание левым глазом"),
    ("blink_right", "Моргание правым глазом"),
    ("blink_both", "Моргание обоими"),
    ("wink_left", "Подмигивание слева"),
    ("wink_right", "Подмигивание справа"),
    ("look_left", "Взгляд влево"),
    ("look_right", "Взгляд вправо"),
    ("look_up", "Взгляд вверх"),
    ("look_down", "Взгляд вниз"),
    ("gaze", "Взгляд (курсор)"),
]


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _ear(lm, idx):
    p1, p2, p3, p4, p5, p6 = (lm[i] for i in idx)
    return (_dist(p2, p6) + _dist(p3, p5)) / (2.0 * _dist(p1, p4) + 1e-6)


class EyeTracker:
    def __init__(self, blink_threshold=0.19):
        paths = ensure_models()
        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(paths["face_landmarker.task"])),
            running_mode=RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=True,
        )
        self.landmarker = FaceLandmarker.create_from_options(options)
        self.blink_threshold = blink_threshold
        self.left_closed = False
        self.right_closed = False
        self.gaze_dir = "center"
        self.smooth = None
        self.gaze_screen = None
        self.debug = {}
        self._look_latched = None
        self._ts = 0

    def track(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        self._ts += 33
        result = self.landmarker.detect_for_video(mp_image, self._ts)

        events = []
        left_ear = right_ear = 0.0
        blink_l = blink_r = 0.0

        if result.face_landmarks:
            lm = result.face_landmarks[0]
            left_ear = _ear(lm, LEFT_EAR)
            right_ear = _ear(lm, RIGHT_EAR)
            blink_l, blink_r = self._blend_blinks(result)

            thr = self.blink_threshold
            left_now = (blink_l > 0.45) if blink_l else left_ear < thr
            right_now = (blink_r > 0.45) if blink_r else right_ear < thr

            if left_now and right_now and not (self.left_closed and self.right_closed):
                events.append("blink_both")
            else:
                if left_now and not self.left_closed and not right_now:
                    events.append("blink_left")
                    events.append("wink_left")
                if right_now and not self.right_closed and not left_now:
                    events.append("blink_right")
                    events.append("wink_right")

            self.left_closed = left_now
            self.right_closed = right_now

            gx, gy, nx, ny = self._gaze(lm)
            if self.smooth is None:
                self.smooth = [nx, ny]
            else:
                self.smooth[0] = self.smooth[0] * 0.72 + nx * 0.28
                self.smooth[1] = self.smooth[1] * 0.72 + ny * 0.28

            sx, sy = screen_size()
            self.gaze_screen = (
                int(np.clip(self.smooth[0], 0, 1) * (sx - 1)),
                int(np.clip(self.smooth[1], 0, 1) * (sy - 1)),
            )
            events.append("gaze")

            direction = self._direction(self.smooth[0], self.smooth[1])
            if direction != "center" and direction != self._look_latched:
                events.append(direction)
            self._look_latched = None if direction == "center" else direction
            self.gaze_dir = direction
            self._draw(frame, lm)
        else:
            self.left_closed = self.right_closed = False
            self.smooth = None
            self.gaze_screen = None
            self._look_latched = None

        self.debug = {
            "left_ear": left_ear,
            "right_ear": right_ear,
            "left_closed": self.left_closed,
            "right_closed": self.right_closed,
            "gaze": self.gaze_dir,
            "screen": self.gaze_screen,
            "blink_l": blink_l,
            "blink_r": blink_r,
        }
        self._hud(frame, left_ear, right_ear)
        return events, self.gaze_screen, frame

    def _blend_blinks(self, result):
        left = right = 0.0
        if not result.face_blendshapes:
            return left, right
        for item in result.face_blendshapes[0]:
            name = item.category_name
            if name == "eyeBlinkLeft":
                left = item.score
            elif name == "eyeBlinkRight":
                right = item.score
        return left, right

    def _gaze(self, lm):
        def axis(iris_i, inner, outer, top, bottom):
            if iris_i >= len(lm):
                iris = type("P", (), {"x": (inner.x + outer.x) / 2, "y": (top.y + bottom.y) / 2})
            else:
                iris = lm[iris_i]
            span_x = (outer.x - inner.x) or 1e-6
            span_y = (bottom.y - top.y) or 1e-6
            return (iris.x - inner.x) / span_x, (iris.y - top.y) / span_y

        lx, ly = axis(LEFT_IRIS, lm[LEFT_INNER], lm[LEFT_OUTER], lm[159], lm[145])
        rx, ry = axis(RIGHT_IRIS, lm[RIGHT_INNER], lm[RIGHT_OUTER], lm[386], lm[374])
        nx = 1.0 - (lx + rx) / 2
        ny = (ly + ry) / 2
        nx = (nx - 0.35) / 0.30
        ny = (ny - 0.35) / 0.30
        return 0, 0, nx, ny

    def _direction(self, nx, ny):
        if nx < 0.28:
            return "look_left"
        if nx > 0.72:
            return "look_right"
        if ny < 0.28:
            return "look_up"
        if ny > 0.72:
            return "look_down"
        return "center"

    def _draw(self, frame, lm):
        draw_landmarks(
            frame,
            lm,
            FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION,
            DrawingSpec(color=(60, 50, 80), thickness=1, circle_radius=1),
            DrawingSpec(color=(70, 60, 90), thickness=1),
        )
        draw_landmarks(
            frame,
            lm,
            FaceLandmarksConnections.FACE_LANDMARKS_LEFT_IRIS,
            DrawingSpec(color=(0, 255, 180), thickness=2, circle_radius=3),
            DrawingSpec(color=(0, 255, 180), thickness=2),
        )
        draw_landmarks(
            frame,
            lm,
            FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_IRIS,
            DrawingSpec(color=(255, 160, 40), thickness=2, circle_radius=3),
            DrawingSpec(color=(255, 160, 40), thickness=2),
        )
        h, w = frame.shape[:2]
        if self.gaze_screen:
            sx, sy = screen_size()
            px = int(self.gaze_screen[0] / sx * w)
            py = int(self.gaze_screen[1] / sy * h)
            cv2.drawMarker(frame, (px, py), (0, 80, 255), cv2.MARKER_CROSS, 28, 2)
            cv2.circle(frame, (px, py), 16, (0, 80, 255), 2)

        cv2.putText(
            frame,
            "L-BLINK" if self.left_closed else "L-OPEN",
            (12, h - 48),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 90, 255) if self.left_closed else (80, 255, 160),
            2,
        )
        cv2.putText(
            frame,
            "R-BLINK" if self.right_closed else "R-OPEN",
            (12, h - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 90, 255) if self.right_closed else (80, 255, 160),
            2,
        )

    def _hud(self, frame, left_ear, right_ear):
        lines = [
            f"L-EAR: {left_ear:.2f}  R-EAR: {right_ear:.2f}",
            f"GAZE: {self.gaze_dir}",
        ]
        if self.gaze_screen:
            lines.append(f"SCREEN: {self.gaze_screen[0]}, {self.gaze_screen[1]}")
        y = 28
        for line in lines:
            cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (180, 140, 255), 2, cv2.LINE_AA)
            y += 26

    def close(self):
        self.landmarker.close()
