import os
import subprocess
import time
from ctypes import Structure, byref, c_long, windll
from datetime import datetime
from pathlib import Path

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
WHEEL_DELTA = 120
KEYEVENTF_KEYUP = 0x0002
VK = {
    "volume_mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "media_next": 0xB0,
    "media_prev": 0xB1,
    "media_stop": 0xB2,
    "media_play": 0xB3,
    "back": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "esc": 0x1B,
    "space": 0x20,
    "pgup": 0x21,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "print": 0x2C,
    "ins": 0x2D,
    "del": 0x2E,
    "win": 0x5B,
    "f5": 0x74,
    "f11": 0x7A,
}

user32 = windll.user32


class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


ACTIONS = [
    ("none", "Ничего"),
    ("left_click", "Мышь: ЛКМ"),
    ("right_click", "Мышь: ПКМ"),
    ("double_click", "Мышь: двойной клик"),
    ("middle_click", "Мышь: колесо (клик)"),
    ("move_cursor", "Мышь: вести курсор"),
    ("drag_hold", "Мышь: зажать ЛКМ"),
    ("drag_release", "Мышь: отпустить ЛКМ"),
    ("scroll_up", "Скролл вверх"),
    ("scroll_down", "Скролл вниз"),
    ("scroll_left", "Скролл влево"),
    ("scroll_right", "Скролл вправо"),
    ("volume_up", "Громкость +"),
    ("volume_down", "Громкость −"),
    ("volume_mute", "Без звука"),
    ("media_play", "Плей / пауза"),
    ("media_next", "Следующий трек"),
    ("media_prev", "Предыдущий трек"),
    ("media_stop", "Стоп"),
    ("copy", "Копировать"),
    ("paste", "Вставить"),
    ("cut", "Вырезать"),
    ("undo", "Отменить"),
    ("redo", "Повторить"),
    ("select_all", "Выделить всё"),
    ("save", "Сохранить"),
    ("new_tab", "Новая вкладка"),
    ("close_tab", "Закрыть вкладку"),
    ("refresh", "Обновить"),
    ("zoom_in", "Масштаб +"),
    ("zoom_out", "Масштаб −"),
    ("enter", "Enter"),
    ("esc", "Escape"),
    ("space", "Пробел"),
    ("backspace", "Backspace"),
    ("delete", "Delete"),
    ("tab_key", "Tab"),
    ("arrow_left", "Стрелка влево"),
    ("arrow_right", "Стрелка вправо"),
    ("arrow_up", "Стрелка вверх"),
    ("arrow_down", "Стрелка вниз"),
    ("page_up", "Page Up"),
    ("page_down", "Page Down"),
    ("home", "Home"),
    ("end", "End"),
    ("alt_tab", "Alt+Tab"),
    ("alt_f4", "Закрыть окно"),
    ("win", "Клавиша Win"),
    ("win_d", "Показать рабочий стол"),
    ("win_e", "Проводник"),
    ("win_l", "Заблокировать ПК"),
    ("win_tab", "Просмотр задач"),
    ("task_manager", "Диспетчер задач"),
    ("screenshot", "Скриншот в буфер"),
    ("screenshot_file", "Скриншот в файл"),
    ("fullscreen", "F11"),
    ("minimize", "Свернуть окно"),
    ("maximize", "Развернуть окно"),
    ("switch_desktop_left", "Рабочий стол ←"),
    ("switch_desktop_right", "Рабочий стол →"),
    ("open_browser", "Открыть браузер"),
    ("open_notepad", "Блокнот"),
    ("open_calc", "Калькулятор"),
    ("open_settings", "Параметры Windows"),
    ("empty_recycle", "Очистить корзину"),
]

CONTINUOUS = {"move_cursor", "drag_hold"}
ACTION_LABELS = {key: label for key, label in ACTIONS}


def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def cursor_pos():
    pt = POINT()
    user32.GetCursorPos(byref(pt))
    return pt.x, pt.y


def move_abs(x, y):
    sx, sy = screen_size()
    x = max(0, min(int(x), sx - 1))
    y = max(0, min(int(y), sy - 1))
    user32.SetCursorPos(x, y)


def _mouse(flags, data=0):
    user32.mouse_event(flags, 0, 0, data & 0xFFFFFFFF, 0)


def _key(vk, up=False):
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)


def tap(vk):
    _key(vk, False)
    _key(vk, True)


def combo(*keys):
    for k in keys:
        _key(k, False)
    for k in reversed(keys):
        _key(k, True)


def left_down():
    _mouse(MOUSEEVENTF_LEFTDOWN)


def left_up():
    _mouse(MOUSEEVENTF_LEFTUP)


class ActionEngine:
    def __init__(self):
        self._drag = False
        self.last_message = "ожидание"
        self.shots = Path.home() / "Pictures" / "GestureCam"
        self.shots.mkdir(parents=True, exist_ok=True)

    def run(self, action_id, context=None):
        context = context or {}
        if not action_id or action_id == "none":
            return
        fn = getattr(self, f"do_{action_id}", None)
        if fn is None:
            self.last_message = f"нет действия: {action_id}"
            return
        fn(context)
        self.last_message = ACTION_LABELS.get(action_id, action_id)

    def do_left_click(self, _):
        left_down()
        left_up()

    def do_right_click(self, _):
        _mouse(MOUSEEVENTF_RIGHTDOWN)
        _mouse(MOUSEEVENTF_RIGHTUP)

    def do_double_click(self, ctx):
        self.do_left_click(ctx)
        time.sleep(0.05)
        self.do_left_click(ctx)

    def do_middle_click(self, _):
        _mouse(MOUSEEVENTF_MIDDLEDOWN)
        _mouse(MOUSEEVENTF_MIDDLEUP)

    def do_move_cursor(self, ctx):
        pos = ctx.get("screen_xy")
        if pos:
            move_abs(*pos)

    def do_drag_hold(self, ctx):
        pos = ctx.get("screen_xy")
        if pos:
            move_abs(*pos)
        if not self._drag:
            left_down()
            self._drag = True

    def do_drag_release(self, _):
        if self._drag:
            left_up()
            self._drag = False
        else:
            left_up()

    def do_scroll_up(self, _):
        _mouse(MOUSEEVENTF_WHEEL, WHEEL_DELTA * 3)

    def do_scroll_down(self, _):
        _mouse(MOUSEEVENTF_WHEEL, (-WHEEL_DELTA * 3) & 0xFFFFFFFF)

    def do_scroll_left(self, _):
        _mouse(MOUSEEVENTF_HWHEEL, (-WHEEL_DELTA * 3) & 0xFFFFFFFF)

    def do_scroll_right(self, _):
        _mouse(MOUSEEVENTF_HWHEEL, WHEEL_DELTA * 3)

    def do_volume_up(self, _):
        tap(VK["volume_up"])

    def do_volume_down(self, _):
        tap(VK["volume_down"])

    def do_volume_mute(self, _):
        tap(VK["volume_mute"])

    def do_media_play(self, _):
        tap(VK["media_play"])

    def do_media_next(self, _):
        tap(VK["media_next"])

    def do_media_prev(self, _):
        tap(VK["media_prev"])

    def do_media_stop(self, _):
        tap(VK["media_stop"])

    def do_copy(self, _):
        combo(VK["ctrl"], ord("C"))

    def do_paste(self, _):
        combo(VK["ctrl"], ord("V"))

    def do_cut(self, _):
        combo(VK["ctrl"], ord("X"))

    def do_undo(self, _):
        combo(VK["ctrl"], ord("Z"))

    def do_redo(self, _):
        combo(VK["ctrl"], ord("Y"))

    def do_select_all(self, _):
        combo(VK["ctrl"], ord("A"))

    def do_save(self, _):
        combo(VK["ctrl"], ord("S"))

    def do_new_tab(self, _):
        combo(VK["ctrl"], ord("T"))

    def do_close_tab(self, _):
        combo(VK["ctrl"], ord("W"))

    def do_refresh(self, _):
        tap(VK["f5"])

    def do_zoom_in(self, _):
        combo(VK["ctrl"], 0xBB)

    def do_zoom_out(self, _):
        combo(VK["ctrl"], 0xBD)

    def do_enter(self, _):
        tap(VK["enter"])

    def do_esc(self, _):
        tap(VK["esc"])

    def do_space(self, _):
        tap(VK["space"])

    def do_backspace(self, _):
        tap(VK["back"])

    def do_delete(self, _):
        tap(VK["del"])

    def do_tab_key(self, _):
        tap(VK["tab"])

    def do_arrow_left(self, _):
        tap(VK["left"])

    def do_arrow_right(self, _):
        tap(VK["right"])

    def do_arrow_up(self, _):
        tap(VK["up"])

    def do_arrow_down(self, _):
        tap(VK["down"])

    def do_page_up(self, _):
        tap(VK["pgup"])

    def do_page_down(self, _):
        tap(VK["pgdn"])

    def do_home(self, _):
        tap(VK["home"])

    def do_end(self, _):
        tap(VK["end"])

    def do_alt_tab(self, _):
        combo(VK["alt"], VK["tab"])

    def do_alt_f4(self, _):
        combo(VK["alt"], 0x73)

    def do_win(self, _):
        tap(VK["win"])

    def do_win_d(self, _):
        combo(VK["win"], ord("D"))

    def do_win_e(self, _):
        combo(VK["win"], ord("E"))

    def do_win_l(self, _):
        combo(VK["win"], ord("L"))

    def do_win_tab(self, _):
        combo(VK["win"], VK["tab"])

    def do_task_manager(self, _):
        combo(VK["ctrl"], VK["shift"], VK["esc"])

    def do_screenshot(self, _):
        combo(VK["win"], VK["shift"], ord("S"))

    def do_screenshot_file(self, _):
        from PIL import ImageGrab

        img = ImageGrab.grab()
        name = self.shots / f"shot_{datetime.now():%Y%m%d_%H%M%S}.png"
        img.save(name)

    def do_fullscreen(self, _):
        tap(VK["f11"])

    def do_minimize(self, _):
        hwnd = user32.GetForegroundWindow()
        user32.ShowWindow(hwnd, 6)

    def do_maximize(self, _):
        hwnd = user32.GetForegroundWindow()
        user32.ShowWindow(hwnd, 3)

    def do_switch_desktop_left(self, _):
        combo(VK["ctrl"], VK["win"], VK["left"])

    def do_switch_desktop_right(self, _):
        combo(VK["ctrl"], VK["win"], VK["right"])

    def do_open_browser(self, _):
        os.startfile("https://www.google.com")

    def do_open_notepad(self, _):
        subprocess.Popen(["notepad.exe"])

    def do_open_calc(self, _):
        subprocess.Popen(["calc.exe"])

    def do_open_settings(self, _):
        subprocess.Popen(["cmd", "/c", "start", "ms-settings:"], shell=False)

    def do_empty_recycle(self, _):
        windll.shell32.SHEmptyRecycleBinW(None, None, 0x0001 | 0x0002 | 0x0004)
