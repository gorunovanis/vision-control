import threading
import time
from collections import deque

import cv2
import customtkinter as ctk
from PIL import Image

from actions import ACTION_LABELS, ACTIONS, CONTINUOUS, ActionEngine, screen_size
from bindings import Bindings
from eye_tracker import EYE_TRIGGERS, EyeTracker
from hand_detector import HAND_TRIGGERS, HandDetector

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACTION_NAMES = [label for _, label in ACTIONS]
LABEL_TO_ID = {label: key for key, label in ACTIONS}
HAND_LABELS = {k: v for k, v in HAND_TRIGGERS}
EYE_LABELS = {k: v for k, v in EYE_TRIGGERS}


class CameraLoop(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.stop_flag = threading.Event()

    def run(self):
        cap = None
        last_index = -1
        while not self.stop_flag.is_set():
            if not self.app.running:
                if cap is not None:
                    cap.release()
                    cap = None
                    last_index = -1
                time.sleep(0.05)
                continue
            index = self.app.camera_index
            if cap is None or index != last_index:
                if cap is not None:
                    cap.release()
                cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cap.set(cv2.CAP_PROP_FPS, 30)
                last_index = index
            ok, frame = cap.read()
            if not ok:
                self.app.last_error = "Камера недоступна"
                time.sleep(0.2)
                continue
            frame = cv2.flip(frame, 1)
            try:
                self.app.process_frame(frame)
            except Exception as exc:
                self.app.last_error = str(exc)
                time.sleep(0.05)
        if cap is not None:
            cap.release()


class GazeOverlay(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry("36x36+0+0")
        self.configure(fg_color="#050508")
        try:
            self.attributes("-transparentcolor", "#050508")
        except Exception:
            self.attributes("-alpha", 0.55)
        self.canvas = ctk.CTkCanvas(self, width=36, height=36, bg="#050508", highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_oval(6, 6, 30, 30, outline="#ff5a3c", width=3)
        self.canvas.create_line(18, 4, 18, 32, fill="#ff5a3c", width=2)
        self.canvas.create_line(4, 18, 32, 18, fill="#ff5a3c", width=2)
        self.withdraw()
        self.after(80, self._click_through)

    def _click_through(self):
        try:
            from ctypes import windll

            hwnd = windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            style = windll.user32.GetWindowLongW(hwnd, -20)
            windll.user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x80)
        except Exception:
            pass

    def follow(self, xy, visible):
        if not visible or xy is None:
            self.withdraw()
            return
        self.deiconify()
        self.geometry(f"36x36+{xy[0] - 18}+{xy[1] - 18}")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("GestureCam")
        self.geometry("1280x820")
        self.minsize(1100, 720)
        self.configure(fg_color="#0c1018")

        self.bindings = Bindings()
        self.engine = ActionEngine()
        self.hand = None
        self.eyes = None
        self.running = False
        self.camera_index = 0
        self.mode = "hand"
        self.actions_on = True
        self.last_error = ""
        self.frame_lock = threading.Lock()
        self.preview = None
        self.debug_text = "ожидание камеры"
        self.event_log = deque(maxlen=14)
        self.fps = 0
        self._last_tick = time.time()
        self._frames = 0
        self._photo = None
        self.last_action = "—"

        self._build()
        self.overlay = GazeOverlay(self)
        self.loop = CameraLoop(self)
        self.loop.start()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(16, self.refresh_ui)

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="#121826", corner_radius=0, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header,
            text="GESTURECAM",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#7af0d0",
        ).pack(side="left", padx=22)
        ctk.CTkLabel(
            header,
            text="рука · взгляд · действия без кода",
            font=ctk.CTkFont(size=13),
            text_color="#8b97ad",
        ).pack(side="left", padx=8)

        self.cam_var = ctk.StringVar(value="Камера 0")
        ctk.CTkOptionMenu(
            header,
            values=[f"Камера {i}" for i in range(4)],
            variable=self.cam_var,
            command=self._set_camera,
            width=120,
            fg_color="#1c2740",
        ).pack(side="right", padx=12, pady=18)
        self.go_btn = ctk.CTkButton(
            header,
            text="Старт",
            width=110,
            fg_color="#1ee0b0",
            hover_color="#14b892",
            text_color="#041510",
            command=self.toggle_cam,
        )
        self.go_btn.pack(side="right", padx=8)
        self.act_btn = ctk.CTkButton(
            header,
            text="Действия: вкл",
            width=140,
            fg_color="#2a3550",
            command=self.toggle_actions,
        )
        self.act_btn.pack(side="right", padx=8)

        self.tabs = ctk.CTkTabview(
            self,
            fg_color="#0c1018",
            segmented_button_fg_color="#121826",
            segmented_button_selected_color="#1ee0b0",
            segmented_button_selected_hover_color="#14b892",
            segmented_button_unselected_color="#1a2233",
            segmented_button_unselected_hover_color="#243044",
        )
        self.tabs.pack(fill="both", expand=True, padx=16, pady=12)
        self.tabs.add("Рука")
        self.tabs.add("Глаза")

        self.hand_video, self.hand_debug, self.hand_binds = self._tab_body(
            self.tabs.tab("Рука"),
            "Отладка руки",
            HAND_TRIGGERS,
            "hand",
        )
        self.eye_video, self.eye_debug, self.eye_binds = self._tab_body(
            self.tabs.tab("Глаза"),
            "Отладка взгляда",
            EYE_TRIGGERS,
            "eye",
        )

        self.status = ctk.CTkLabel(self, text="камера выключена", text_color="#8b97ad", anchor="w")
        self.status.pack(fill="x", padx=22, pady=(0, 10))

    def _tab_body(self, parent, debug_title, triggers, section):
        parent.grid_columnconfigure(0, weight=3)
        parent.grid_columnconfigure(1, weight=2)
        parent.grid_rowconfigure(0, weight=3)
        parent.grid_rowconfigure(1, weight=2)

        video = ctk.CTkLabel(
            parent,
            text="окно камеры",
            fg_color="#101722",
            corner_radius=16,
            text_color="#5c6a82",
        )
        video.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))

        debug = ctk.CTkTextbox(
            parent,
            fg_color="#101722",
            text_color="#c9d6ea",
            font=ctk.CTkFont(family="Consolas", size=14),
            corner_radius=16,
        )
        debug.grid(row=0, column=1, sticky="nsew", pady=(0, 10))
        debug.insert("1.0", f"{debug_title}\nожидание…")
        debug.configure(state="disabled")

        bind_box = ctk.CTkScrollableFrame(parent, fg_color="#101722", corner_radius=16, label_text="Триггер → действие")
        bind_box.grid(row=1, column=0, columnspan=2, sticky="nsew")
        menus = {}
        for i, (key, title) in enumerate(triggers):
            row = ctk.CTkFrame(bind_box, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=4)
            ctk.CTkLabel(row, text=title, width=240, anchor="w").pack(side="left")
            current = ACTION_LABELS.get(self.bindings.get(section, key), "Ничего")
            var = ctk.StringVar(value=current)
            menu = ctk.CTkOptionMenu(
                row,
                values=ACTION_NAMES,
                variable=var,
                width=320,
                fg_color="#1c2740",
                button_color="#1ee0b0",
                button_hover_color="#14b892",
                command=lambda label, s=section, t=key: self._on_bind(s, t, label),
            )
            menu.pack(side="left", padx=8)
            menus[key] = (var, menu)
        return video, debug, menus

    def _on_bind(self, section, trigger, label):
        self.bindings.set(section, trigger, LABEL_TO_ID.get(label, "none"))
        self._log(f"связка: {trigger} → {label}")

    def _set_camera(self, value):
        self.camera_index = int(value.split()[-1])

    def _on_tab(self):
        name = self.tabs.get()
        self.mode = "eye" if name == "Глаза" else "hand"

    def toggle_cam(self):
        self.running = not self.running
        self.go_btn.configure(text="Стоп" if self.running else "Старт")
        if self.running and self.hand is None:
            try:
                self.hand = HandDetector()
                self.eyes = EyeTracker()
            except Exception as exc:
                self.running = False
                self.go_btn.configure(text="Старт")
                self.last_error = f"Модели: {exc}"

    def toggle_actions(self):
        self.actions_on = not self.actions_on
        self.act_btn.configure(
            text="Действия: вкл" if self.actions_on else "Действия: выкл",
            fg_color="#1ee0b0" if self.actions_on else "#2a3550",
            text_color="#041510" if self.actions_on else "#e8eef8",
        )

    def process_frame(self, frame):
        h, w = frame.shape[:2]
        sx, sy = screen_size()
        fired = []
        gesture = "none"
        gaze = None
        if self.mode == "hand":
            if self.hand is None:
                return
            fired, gesture, vis = self.hand.detect(frame)
            debug = dict(self.hand.debug)
            if self.hand.finger_xy:
                fx, fy = self.hand.finger_xy
                screen_xy = (int(fx / w * sx), int(fy / h * sy))
            else:
                screen_xy = None
            ctx = {"screen_xy": screen_xy}
            self._fire("hand", fired, ctx, hold_trigger=gesture)
            text = self._hand_debug(debug, fired, screen_xy)
        else:
            if self.eyes is None:
                return
            events, gaze, vis = self.eyes.track(frame)
            debug = dict(self.eyes.debug)
            oneshot = [e for e in events if e != "gaze"]
            ctx = {"screen_xy": gaze}
            if "gaze" in events:
                self._fire("eye", ["gaze"], ctx, continuous_only=True)
            self._fire("eye", oneshot, ctx)
            text = self._eye_debug(debug, oneshot, gaze)
            vis = self._draw_gaze_panel(vis, gaze)

        self._frames += 1
        now = time.time()
        if now - self._last_tick >= 1:
            self.fps = self._frames
            self._frames = 0
            self._last_tick = now

        with self.frame_lock:
            self.preview = vis
            self.debug_text = text

    def _fire(self, section, triggers, ctx, hold_trigger=None, continuous_only=False):
        if not self.actions_on:
            return
        seen = []
        if hold_trigger and hold_trigger != "none":
            action = self.bindings.get(section, hold_trigger)
            if action in CONTINUOUS:
                self.engine.run(action, ctx)
                seen.append(hold_trigger)
        for trigger in triggers:
            action = self.bindings.get(section, trigger)
            if action == "none":
                continue
            if continuous_only and action not in CONTINUOUS:
                continue
            if not continuous_only and action in CONTINUOUS and trigger == hold_trigger:
                continue
            self.engine.run(action, ctx)
            self.last_action = ACTION_LABELS.get(action, action)
            self._log(f"{section}:{trigger} → {self.last_action}")

    def _log(self, line):
        stamp = time.strftime("%H:%M:%S")
        self.event_log.appendleft(f"{stamp}  {line}")

    def _hand_debug(self, debug, fired, xy):
        lines = [
            "=== ОТЛАДКА РУКИ ===",
            f"FPS: {self.fps}",
            f"Камера: {self.camera_index}",
            f"Рука: {debug.get('hand', '—')}",
            f"Жест: {debug.get('gesture', 'none')}",
            f"Свайп: {debug.get('swipe', '—')}",
            f"Пинч зажат: {debug.get('pinch')}",
            f"Палец → экран: {xy}",
            f"Сработало: {', '.join(fired) if fired else '—'}",
            f"Последнее действие: {self.last_action}",
            f"Действия: {'вкл' if self.actions_on else 'выкл'}",
            f"Ошибка: {self.last_error or 'нет'}",
            "",
            "лог:",
            *self.event_log,
        ]
        return "\n".join(lines)

    def _eye_debug(self, debug, fired, gaze):
        lines = [
            "=== ОТЛАДКА ВЗГЛЯДА ===",
            f"FPS: {self.fps}",
            f"Камера: {self.camera_index}",
            f"Левый EAR: {debug.get('left_ear', 0):.3f}",
            f"Правый EAR: {debug.get('right_ear', 0):.3f}",
            f"Левый blink: {debug.get('blink_l', 0):.2f}",
            f"Правый blink: {debug.get('blink_r', 0):.2f}",
            f"Левый закрыт: {debug.get('left_closed')}",
            f"Правый закрыт: {debug.get('right_closed')}",
            f"Направление: {debug.get('gaze')}",
            f"Куда смотрите: {gaze}",
            f"Сработало: {', '.join(fired) if fired else '—'}",
            f"По умолчанию: левый глаз = ЛКМ, правый = ПКМ",
            f"Последнее действие: {self.last_action}",
            f"Действия: {'вкл' if self.actions_on else 'выкл'}",
            f"Ошибка: {self.last_error or 'нет'}",
            "",
            "лог:",
            *self.event_log,
        ]
        return "\n".join(lines)

    def _draw_gaze_panel(self, frame, gaze):
        h, w = frame.shape[:2]
        panel_h = 90
        cv2.rectangle(frame, (0, h - panel_h), (w, h), (16, 18, 28), -1)
        sx, sy = screen_size()
        if gaze:
            px = int(gaze[0] / max(sx, 1) * (w - 20)) + 10
            py = h - panel_h + int(gaze[1] / max(sy, 1) * (panel_h - 20)) + 10
            cv2.circle(frame, (px, py), 8, (60, 90, 255), -1)
            cv2.putText(
                frame,
                f"LOOK {gaze[0]},{gaze[1]}",
                (12, h - panel_h - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (80, 180, 255),
                2,
            )
        return frame

    def refresh_ui(self):
        with self.frame_lock:
            frame = self.preview
            text = self.debug_text
        if frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            img.thumbnail((860, 520))
            photo = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._photo = photo
            target = self.eye_video if self.mode == "eye" else self.hand_video
            target.configure(image=photo, text="")
        box = self.eye_debug if self.mode == "eye" else self.hand_debug
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")
        self.status.configure(
            text=f"{'рука' if self.mode == 'hand' else 'глаза'}  |  {self.fps} fps  |  {self.last_action}"
        )
        gaze = None if self.eyes is None else self.eyes.gaze_screen
        self.overlay.follow(gaze, self.mode == "eye" and self.running)
        self.after(16, self.refresh_ui)

    def on_close(self):
        self.running = False
        self.loop.stop_flag.set()
        if self.hand:
            self.hand.close()
        if self.eyes:
            self.eyes.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
