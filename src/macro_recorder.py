"""
鼠标宏录制与回放模块
支持全局录制鼠标：点击、弹起、拖拽移动，保存为宏文件，并可加载回放
"""
import json
import time
from datetime import datetime

try:
    from pynput import mouse
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


class MacroRecorder:
    """鼠标宏录制器 - 全局捕获鼠标事件（点击、弹起、拖拽移动）"""

    def __init__(self):
        self.events = []
        self._recording = False
        self._start_time = 0
        self._listener = None
        self._click_callback = None

        # 拖拽跟踪
        self._button_pressed = False
        self._last_move_time = 0
        self._move_sample_interval = 0.05  # 50ms 采样一次拖拽移动

    @property
    def is_recording(self):
        return self._recording

    @property
    def event_count(self):
        return len(self.events)

    def set_click_callback(self, callback):
        """设置录制回调 callback(x, y, event_type, event_count)
        event_type: "press" | "release" | "drag"
        """
        self._click_callback = callback

    def start(self):
        """开始录制（全局鼠标钩子）"""
        if not HAS_PYNPUT:
            raise ImportError("pynput 未安装，请运行: pip install pynput")
        if self._recording:
            return False

        self.events.clear()
        self._recording = True
        self._start_time = time.time()
        self._button_pressed = False
        self._last_move_time = 0

        def on_click(x, y, button, pressed):
            if not self._recording:
                return False
            elapsed = round(time.time() - self._start_time, 3)
            self._button_pressed = pressed
            event_type = "press" if pressed else "release"
            self.events.append({
                "type": event_type,
                "x": x,
                "y": y,
                "button": str(button),
                "timestamp": elapsed,
            })
            if self._click_callback:
                self._click_callback(x, y, event_type, len(self.events))
            return True

        def on_move(x, y):
            if not self._recording or not self._button_pressed:
                return
            now = time.time()
            if now - self._last_move_time >= self._move_sample_interval:
                elapsed = round(now - self._start_time, 3)
                self.events.append({
                    "type": "drag",
                    "x": x,
                    "y": y,
                    "timestamp": elapsed,
                })
                self._last_move_time = now
                if self._click_callback:
                    self._click_callback(x, y, "drag", len(self.events))

        self._listener = mouse.Listener(on_click=on_click, on_move=on_move)
        self._listener.start()
        return True

    def stop(self):
        """停止录制"""
        if not self._recording:
            return
        self._recording = False
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._button_pressed = False

    def save(self, filepath, name=""):
        """保存宏文件（保存所有事件）"""
        data = {
            "name": name or "未命名宏",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_count": len(self.events),
            "events": self.events,
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return len(self.events)

    def load(self, filepath):
        """加载宏文件"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.events = data.get("events", [])
        return data.get("name", "未命名宏"), len(self.events)

    def clear(self):
        """清除所有事件"""
        self.events.clear()

    def remove_event(self, index):
        """删除指定索引的事件"""
        if 0 <= index < len(self.events):
            self.events.pop(index)
            return True
        return False

    def get_summary(self):
        """获取录制摘要"""
        if not self.events:
            return "无录制事件"
        press_count = sum(1 for e in self.events if e.get("type") == "press")
        release_count = sum(1 for e in self.events if e.get("type") == "release")
        drag_count = sum(1 for e in self.events if e.get("type") == "drag")
        duration = self.events[-1]["timestamp"] - self.events[0]["timestamp"]
        parts = []
        if press_count:
            parts.append(f"{press_count} 次点击")
        if drag_count:
            parts.append(f"{drag_count} 次拖拽")
        return f"{', '.join(parts)}, 总时长 {duration:.1f}s"

    def get_total_duration(self):
        """获取录制总时长"""
        if len(self.events) < 2:
            return 0
        return self.events[-1]["timestamp"] - self.events[0]["timestamp"]
