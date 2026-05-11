"""
百炼英雄脚本助手 v2.0
改进的UI界面 + 鼠标宏录制与回放功能
"""
import sys
import os
import time
import threading

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QFrame, QSizePolicy,
    QLabel, QScrollArea, QGroupBox, QFileDialog,
    QListWidget, QListWidgetItem, QMessageBox, QSlider,
    QMenu, QAction, QCheckBox, QComboBox,
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

from src.style_conf import *
from src.macro_recorder import MacroRecorder


# ============================================================
# MacroPlayer - 基于 QTimer，完全在主线程运行
# ============================================================
class MacroPlayer:
    """定时器驱动的宏播放器，无线程安全问题"""

    def __init__(self):
        self.events = []
        self._index = 0
        self._start_time = 0
        self._speed = 1.0
        self._playing = False
        self._callback = None

        # 循环播放
        self._loop_enabled = False
        self._loop_interval = 3
        self._looping = False

        # 步进定时器 - 每 30ms 检查一次是否该执行下个事件
        self._step_timer = QTimer()
        self._step_timer.setTimerType(Qt.PreciseTimer)
        self._step_timer.timeout.connect(self._tick)

        # 倒计时定时器
        self._countdown_val = 0
        self._cd_timer = QTimer()
        self._cd_timer.timeout.connect(self._tick_countdown)

    @property
    def is_playing(self):
        return self._playing

    def set_callback(self, callback):
        """callback(status, data)"""
        self._callback = callback

    @property
    def is_looping(self):
        return self._looping

    def set_loop(self, enabled, interval=3):
        """设置循环播放"""
        self._loop_enabled = enabled
        self._loop_interval = max(0, interval)

    def play(self, events, speed=1.0):
        """开始播放，返回 True 表示启动成功"""
        if self._playing:
            return False
        self.events = list(events)
        self._index = 0
        self._speed = speed
        self._playing = True

        if not events:
            self._emit("error", "没有可播放的事件")
            self._playing = False
            return True

        self._countdown_val = 3
        self._emit("countdown", 3)
        self._cd_timer.start(1000)
        return True

    def _tick_countdown(self):
        self._countdown_val -= 1
        if self._countdown_val > 0:
            if self._looping:
                self._emit("loop_countdown", self._countdown_val)
            else:
                self._emit("countdown", self._countdown_val)
        else:
            self._cd_timer.stop()
            if self._looping:
                self._looping = False
            self._index = 0
            self._start_time = time.time()
            self._step_timer.start(30)
            self._emit("started", len(self.events))

    def _tick(self):
        if self._index >= len(self.events):
            import pyautogui
            pyautogui.mouseUp()
            self._step_timer.stop()
            self._playing = False
            if self._loop_enabled and self.events:
                self._looping = True
                self._countdown_val = self._loop_interval
                self._emit("loop_countdown", self._countdown_val)
                self._cd_timer.start(1000)
            else:
                self._emit("finished", None)
            return

        elapsed = time.time() - self._start_time
        event_time = self.events[self._index]["timestamp"] / self._speed

        if elapsed >= event_time:
            event = self.events[self._index]
            try:
                import pyautogui
                et = event.get("type", "press")
                x, y = event["x"], event["y"]

                if et == "press":
                    # 鼠标按下（单击/拖拽起点）
                    pyautogui.mouseDown(x, y)
                elif et == "release":
                    # 鼠标弹起
                    pyautogui.mouseUp(x, y)
                elif et == "drag":
                    # 拖拽中间移动点
                    pyautogui.moveTo(x, y, duration=0.02)
                else:
                    # 向下兼容旧格式
                    pyautogui.mouseDown(x, y)
                    pyautogui.mouseUp(x, y)
            except Exception as e:
                self._step_timer.stop()
                self._playing = False
                self._emit("error", str(e))
                return
            self._index += 1
            self._emit("progress", (self._index, len(self.events)))

    def stop(self):
        self._step_timer.stop()
        self._cd_timer.stop()
        self._playing = False
        self._looping = False
        self._emit("stopped", None)

    def _emit(self, status, data):
        if self._callback:
            self._callback(status, data)


# ============================================================
# Macro Panel - 宏管理右侧面板
# ============================================================
class MacroPanel(QWidget):
    """鼠标宏录制与回放控制面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.recorder = MacroRecorder()
        self.player = MacroPlayer()

        self.current_filepath = None
        self.current_macro_name = "未保存"

        # 录制倒计时
        self._rec_cd = 0
        self._rec_cd_timer = QTimer()
        self._rec_cd_timer.timeout.connect(self._on_rec_cd_tick)

        # 录制时定时刷新显示
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_stats)

        # pynput 录制回调（从 pynput 线程来，用 QTimer 刷新列表）
        self.recorder.set_click_callback(self._on_recorder_click)

        # 播放器回调（完全在主线程，直接调用）
        self.player.set_callback(self._on_player_status)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # === 标题 ===
        title = QLabel("鼠标宏管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2C3E50;"
                            "padding-bottom: 10px; border-bottom: 2px solid #BDC3C7;")
        layout.addWidget(title)

        # === 文件区域 ===
        fg = QFrame()
        fg.setStyleSheet("QFrame { background: white; border-radius: 8px; }")
        fl = QVBoxLayout(fg)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(8)

        self.file_label = QLabel("当前宏文件: 未保存")
        self.file_label.setStyleSheet("font-size: 13px; color: #555;")
        fl.addWidget(self.file_label)

        fb = QHBoxLayout()
        fb.setSpacing(10)
        self.load_btn = QPushButton("📂 加载宏")
        self.save_btn = QPushButton("💾 保存宏")
        for btn in (self.load_btn, self.save_btn):
            btn.setFixedHeight(36)
            btn.setCursor(Qt.PointingHandCursor)
        self.load_btn.setStyleSheet(
            "QPushButton { font-size: 13px; background: #3498DB; color: white;"
            " border-radius: 6px; padding: 0 22px; font-weight: bold; }"
            "QPushButton:hover { background: #2980B9; }"
        )
        self.save_btn.setStyleSheet(
            "QPushButton { font-size: 13px; background: #2ECC71; color: white;"
            " border-radius: 6px; padding: 0 22px; font-weight: bold; }"
            "QPushButton:hover { background: #27AE60; }"
            "QPushButton:disabled { background: #BDC3C7; }"
        )
        self.save_btn.setEnabled(False)
        self.load_btn.clicked.connect(self._on_load)
        self.save_btn.clicked.connect(self._on_save)
        fb.addWidget(self.load_btn)
        fb.addWidget(self.save_btn)
        fb.addStretch()
        fl.addLayout(fb)
        layout.addWidget(fg)

        # === 控制按钮区域 ===
        cg = QFrame()
        cg.setStyleSheet("QFrame { background: white; border-radius: 8px; }")
        cl = QVBoxLayout(cg)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(10)

        bb = QHBoxLayout()
        bb.setSpacing(12)
        self.record_btn = QPushButton("● 开始录制")
        self.stop_btn = QPushButton("■ 停止")
        self.play_btn = QPushButton("▶ 播放宏")

        for btn, bg in ((self.record_btn, "#E74C3C"),
                         (self.stop_btn, "#7F8C8D"),
                         (self.play_btn, "#2ECC71")):
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 14px; background: {bg}; color: white;"
                f" border-radius: 6px; padding: 0 28px; font-weight: bold; min-height: 42px; }}"
                f"QPushButton:hover {{ background: {self._dark(bg)}; }}"
                f"QPushButton:disabled {{ background: #BDC3C7; }}"
            )
            btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.play_btn.setEnabled(False)

        self.record_btn.clicked.connect(self._on_record)
        self.stop_btn.clicked.connect(self._on_stop)
        self.play_btn.clicked.connect(self._on_play)

        bb.addWidget(self.record_btn)
        bb.addWidget(self.stop_btn)
        bb.addWidget(self.play_btn)
        bb.addStretch()
        cl.addLayout(bb)

        # 速度滑块
        sx = QHBoxLayout()
        sx.setSpacing(10)
        sx.addWidget(self._label("速度:", "13px", "#555"))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(5, 30)
        self.speed_slider.setValue(10)
        self.speed_slider.setFixedWidth(160)
        self.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.speed_slider.setTickInterval(5)
        self.speed_val = QLabel("1.0x")
        self.speed_val.setStyleSheet("font-size: 13px; color: #2C3E50; font-weight: bold; min-width: 40px;")
        self.speed_slider.valueChanged.connect(lambda v: self.speed_val.setText(f"{v/10:.1f}x"))
        sx.addWidget(self.speed_slider)
        sx.addWidget(self.speed_val)
        sx.addStretch()
        cl.addLayout(sx)

        # 循环播放控制
        lx = QHBoxLayout()
        lx.setSpacing(10)
        self.loop_cb = QCheckBox("循环播放")
        self.loop_cb.setStyleSheet(
            "QCheckBox { font-size: 13px; color: #2C3E50; font-weight: bold; spacing: 6px; }"
        )
        self.loop_interval_label = QLabel("间隔:")
        self.loop_interval_label.setStyleSheet("font-size: 13px; color: #555;")
        self.loop_interval_combo = QComboBox()
        self.loop_interval_combo.addItems(
            ["0秒", "1秒", "2秒", "3秒", "5秒", "10秒", "30秒", "60秒"]
        )
        self.loop_interval_combo.setCurrentIndex(3)  # 默认 3秒
        self.loop_interval_combo.setFixedWidth(100)
        self.loop_interval_combo.setStyleSheet(
            "QComboBox { font-size: 13px; padding: 4px 8px; border: 1px solid #BDC3C7;"
            " border-radius: 4px; background: white; }"
        )
        lx.addWidget(self.loop_cb)
        lx.addWidget(self.loop_interval_label)
        lx.addWidget(self.loop_interval_combo)
        lx.addStretch()
        cl.addLayout(lx)

        layout.addWidget(cg)

        # === 状态显示 ===
        sg = QFrame()
        sg.setStyleSheet("QFrame { background: white; border-radius: 8px; }")
        sl2 = QVBoxLayout(sg)
        sl2.setContentsMargins(16, 10, 16, 10)
        sl2.setSpacing(4)

        sr1 = QHBoxLayout()
        self.dot = QLabel()
        self.dot.setFixedSize(14, 14)
        self.status_text = QLabel("● 空闲")
        self.status_text.setStyleSheet("font-size: 14px; color: #2C3E50; font-weight: bold;")
        sr1.addWidget(self.dot)
        sr1.addWidget(self.status_text)
        sr1.addStretch()

        sr2 = QHBoxLayout()
        self.event_label = QLabel("录制事件: 0")
        self.event_label.setStyleSheet("font-size: 13px; color: #7F8C8D;")
        self.dur_label = QLabel("总时长: 0.0s")
        self.dur_label.setStyleSheet("font-size: 13px; color: #7F8C8D;")
        sr2.addWidget(self.event_label)
        sr2.addWidget(QLabel("|"))
        sr2.addWidget(self.dur_label)
        sr2.addStretch()

        sl2.addLayout(sr1)
        sl2.addLayout(sr2)
        layout.addWidget(sg)

        # === 事件列表 ===
        lh = QLabel("录制事件列表")
        lh.setStyleSheet("font-size: 14px; font-weight: bold; color: #2C3E50; padding-top: 4px;")
        layout.addWidget(lh)

        self.event_list = QListWidget()
        self.event_list.setStyleSheet(
            "QListWidget { background: white; border: 1px solid #BDC3C7; border-radius: 6px;"
            " padding: 4px; font-size: 12px; color: #2C3E50; }"
            "QListWidget::item { padding: 5px 10px; border-bottom: 1px solid #ECF0F1; }"
            "QListWidget::item:hover { background: #F5F7FA; }"
            "QListWidget::item:alternate { background: #FAFBFC; }"
        )
        self.event_list.setAlternatingRowColors(True)
        self.event_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.event_list.customContextMenuRequested.connect(self._on_list_context)
        layout.addWidget(self.event_list, 1)

        hint = QLabel("提示: 点击「开始录制」后全局捕获鼠标点击，右键可删除事件")
        hint.setStyleSheet("font-size: 11px; color: #95A5A6;")
        layout.addWidget(hint)

        self._set_dot("idle")

    @staticmethod
    def _dark(hex_c):
        r = max(0, int(hex_c[1:3], 16) - 24)
        g = max(0, int(hex_c[3:5], 16) - 24)
        b = max(0, int(hex_c[5:7], 16) - 24)
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _label(text, size, color):
        lb = QLabel(text)
        lb.setStyleSheet(f"font-size: {size}; color: {color}; font-weight: bold;")
        return lb

    # ---- 状态指示 ----
    def _set_dot(self, state):
        if state == "idle":
            self.dot.setStyleSheet("background: #2ECC71; border-radius: 7px;")
            self.status_text.setText("● 空闲")
        elif state == "recording":
            self.dot.setStyleSheet("background: #E74C3C; border-radius: 7px;")
            self.status_text.setText("● 录制中...")
        elif state == "playing":
            self.dot.setStyleSheet("background: #3498DB; border-radius: 7px;")
            self.status_text.setText("▶ 播放中...")
        elif state == "countdown":
            self.dot.setStyleSheet("background: #F39C12; border-radius: 7px;")

    # ---- 录制 ----
    def _on_record(self):
        if self.recorder.is_recording or self.player.is_playing:
            return
        self._rec_cd = 3
        self.record_btn.setText("● 3...")
        self.record_btn.setEnabled(False)
        self._rec_cd_timer.start(1000)

    def _on_rec_cd_tick(self):
        self._rec_cd -= 1
        if self._rec_cd > 0:
            self.record_btn.setText(f"● {self._rec_cd}...")
        else:
            self._rec_cd_timer.stop()
            self._begin_recording()

    def _begin_recording(self):
        try:
            self.recorder.start()
        except ImportError as e:
            QMessageBox.warning(self, "缺少依赖", str(e))
            self.record_btn.setText("● 开始录制")
            self.record_btn.setEnabled(True)
            return
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            self.record_btn.setText("● 开始录制")
            self.record_btn.setEnabled(True)
            return

        self.event_list.clear()
        self.record_btn.setText("● 录制中...")
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.play_btn.setEnabled(False)
        self.load_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self._set_dot("recording")
        self._refresh_timer.start(200)
        self._msg("🔴 宏录制已开始，请操作游戏...")

    def _on_stop(self):
        if self.recorder.is_recording:
            self.recorder.stop()
            self._refresh_timer.stop()
            self._refresh_stats()
            self._rebuild_event_list()
            n = len(self.recorder.events)
            self.record_btn.setText("● 开始录制")
            self.record_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.play_btn.setEnabled(n > 0)
            self.load_btn.setEnabled(True)
            self.save_btn.setEnabled(n > 0)
            self._set_dot("idle")
            self._msg(f"⏹️ 录制停止，共 {n} 个事件")

        if self.player.is_playing or self.player.is_looping:
            self.player.stop()

    def _on_recorder_click(self, x, y, event_type, count):
        """pynput 线程回调 - 在主线程刷新列表"""
        QTimer.singleShot(0, lambda: self._add_event_item(x, y, event_type, count))

    def _add_event_item(self, x, y, event_type, count):
        icons = {"press": "⇩", "release": "⇧", "drag": "✦"}
        icon = icons.get(event_type, "•")
        label = {"press": "按下", "release": "弹起", "drag": "拖拽"}.get(event_type, event_type)
        self.event_list.addItem(QListWidgetItem(f"#{count:03d} {icon} {label} ({x}, {y})"))
        self.event_list.scrollToBottom()

    def _refresh_stats(self):
        n = len(self.recorder.events)
        press_n = sum(1 for e in self.recorder.events if e.get("type") == "press")
        drag_n = sum(1 for e in self.recorder.events if e.get("type") == "drag")
        parts = []
        if press_n:
            parts.append(f"{press_n} 次点击")
        if drag_n:
            parts.append(f"{drag_n} 次拖拽")
        self.event_label.setText(f"录制事件: {'，'.join(parts) if parts else '0'}" if n else "录制事件: 0")
        d = self.recorder.get_total_duration()
        self.dur_label.setText(f"总时长: {d:.1f}s")

    def _rebuild_event_list(self):
        self.event_list.clear()
        icons = {"press": "⇩", "release": "⇧", "drag": "✦"}
        labels_map = {"press": "按下", "release": "弹起", "drag": "拖拽"}
        for i, e in enumerate(self.recorder.events, 1):
            et = e.get("type", "press")
            icon = icons.get(et, "•")
            label = labels_map.get(et, et)
            btn = str(e.get("button", "left")).replace("Button.", "")
            detail = f"  [{btn}]" if et != "drag" else "     "
            self.event_list.addItem(
                QListWidgetItem(f"#{i:03d} {icon} {label}{detail} ({e['x']}, {e['y']})  {e['timestamp']:.1f}s")
            )

    # ---- 播放 ----
    def _on_play(self):
        if self.player.is_playing or self.player.is_looping:
            self.player.stop()
            return
        if self.recorder.is_recording:
            return
        evts = self.recorder.events
        if not evts:
            QMessageBox.information(self, "提示", "没有可播放的事件，请先录制或加载宏文件")
            return
        speed = self.speed_slider.value() / 10.0
        # 应用循环播放设置
        loop_enabled = self.loop_cb.isChecked()
        interval_text = self.loop_interval_combo.currentText().replace("秒", "")
        loop_interval = int(interval_text) if interval_text else 3
        self.player.set_loop(loop_enabled, loop_interval)
        self.player.play(evts, speed=speed)

    def _on_player_status(self, status, data):
        """播放器回调（主线程直接调用）"""
        if status == "countdown":
            self.play_btn.setText(f"⏳ {data}s...")
            self.play_btn.setEnabled(False)
            self._set_dot("countdown")
            self.status_text.setText(f"⏳ 即将开始 ({data}s)...")
            self._msg(f"⏳ {data} 秒后开始播放...")
        elif status == "loop_countdown":
            self.play_btn.setText("■ 停止循环")
            self.play_btn.setEnabled(True)
            self._set_dot("countdown")
            self.status_text.setText(f"🔄 下次循环 ({data}s)...")
            self._msg(f"🔄 {data} 秒后开始下一次循环...")
        elif status == "started":
            self.play_btn.setText("■ 停止播放")
            self.play_btn.setEnabled(True)
            self.record_btn.setEnabled(False)
            self.load_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self._set_dot("playing")
            self._msg(f"▶️ 播放中 ({data} 个事件)")
        elif status == "progress":
            cur, tot = data
            self.status_text.setText(f"▶ 播放中... {cur}/{tot}")
            self.event_label.setText(f"播放进度: {cur}/{tot}")
        elif status in ("finished", "stopped"):
            self._reset_play_ui()
            self._msg("✅ 宏播放完成" if status == "finished" else "⏹️ 宏播放已停止")
        elif status == "error":
            self._reset_play_ui()
            QMessageBox.warning(self, "播放错误", str(data))
            self._msg(f"❌ {data}")

    def _reset_play_ui(self):
        n = len(self.recorder.events)
        self.play_btn.setText("▶ 播放宏")
        self.play_btn.setEnabled(n > 0)
        self.record_btn.setEnabled(True)
        self.load_btn.setEnabled(True)
        self.save_btn.setEnabled(n > 0)
        self.stop_btn.setEnabled(False)
        self._set_dot("idle")
        self._refresh_stats()

    # ---- 文件操作 ----
    def _on_save(self):
        if not self.recorder.events:
            QMessageBox.information(self, "提示", "没有录制事件")
            return
        fp, _ = QFileDialog.getSaveFileName(
            self, "保存宏文件",
            self.current_filepath or os.path.expanduser("~/Desktop/百炼宏.json"),
            "宏文件 (*.json)"
        )
        if not fp:
            return
        try:
            name = os.path.splitext(os.path.basename(fp))[0]
            n = self.recorder.save(fp, name=name)
            self.current_filepath = fp
            self.current_macro_name = name
            self.file_label.setText(f"当前宏文件: {os.path.basename(fp)}")
            self._msg(f"💾 已保存 ({n} 个事件)")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _on_load(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "加载宏文件",
            os.path.expanduser("~/Desktop/"),
            "宏文件 (*.json)"
        )
        if not fp:
            return
        try:
            name, n = self.recorder.load(fp)
            self.current_filepath = fp
            self.current_macro_name = name
            self.file_label.setText(f"当前宏文件: {os.path.basename(fp)} ({n} 个事件)")
            self._rebuild_event_list()
            self.play_btn.setEnabled(n > 0)
            self.save_btn.setEnabled(n > 0)
            self._refresh_stats()
            self._msg(f"📂 已加载: {name}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))

    # ---- 事件列表右键 ----
    def _on_list_context(self, pos):
        item = self.event_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        a1 = QAction("删除该事件", self)
        a1.triggered.connect(lambda: self._del_event(item))
        menu.addAction(a1)
        a2 = QAction("清空所有事件", self)
        a2.triggered.connect(self._clear_events)
        menu.addAction(a2)
        menu.exec_(self.event_list.mapToGlobal(pos))

    def _del_event(self, item):
        row = self.event_list.row(item)
        if self.recorder.remove_event(row):
            self._rebuild_event_list()
            self._refresh_stats()
            n = len(self.recorder.events)
            self.play_btn.setEnabled(n > 0)
            self.save_btn.setEnabled(n > 0)

    def _clear_events(self):
        self.recorder.clear()
        self.event_list.clear()
        self._refresh_stats()
        self.play_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

    def _msg(self, text):
        if self.parent_window:
            self.parent_window.show_status_message(text)


# ============================================================
# 二级按钮控件
# ============================================================
class SubButtonWidget(QWidget):
    """功能任务卡片 - 含开始/停止控制和状态显示"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(15)

        self.func_btn = QPushButton(title)
        self.func_btn.setFixedHeight(50)
        self.func_btn.setCursor(Qt.PointingHandCursor)
        self.func_btn.setStyleSheet(func_btn_style)

        self.ctrl_btn = QPushButton("开始")
        self.ctrl_btn.setFixedSize(90, 40)
        self.ctrl_btn.setCursor(Qt.PointingHandCursor)
        self.ctrl_btn.setStyleSheet(ctrl_btn_style)

        self.status_label = QLabel("待命")
        self.status_label.setFixedSize(90, 40)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(status_label_style)

        layout.addWidget(self.func_btn, 70)
        layout.addWidget(self.ctrl_btn, 15)
        layout.addWidget(self.status_label, 15)

        self.ctrl_btn.clicked.connect(self._on_ctrl_click)
        self.is_running = False
        self._stop_event = None
        self._task_thread = None

    def _on_ctrl_click(self):
        if self.parent_window:
            rt = self.parent_window.current_running_task
            if rt is not None and rt is not self:
                self.parent_window.show_status_message("已有任务正在运行")
                return
        if self.is_running:
            self.stop_task()
        else:
            self.start_task()

    def start_task(self):
        if self.parent_window:
            self.parent_window.set_current_running_task(self)
        self.is_running = True
        self.ctrl_btn.setText("停止")
        self.ctrl_btn.setStyleSheet(ctrl_btn_style2)
        self.status_label.setText("运行中")
        self.status_label.setStyleSheet(status_label_style2)
        self.func_btn.setEnabled(False)
        self._msg(f"任务 '{self.func_btn.text()}' 已开始")

        # 启动后台线程执行自动化任务
        self._stop_event = threading.Event()
        self._task_thread = threading.Thread(target=self._run_task, daemon=True)
        self._task_thread.start()

    def stop_task(self):
        self.is_running = False
        if self.parent_window:
            self.parent_window.clear_current_running_task()
        if self._stop_event:
            self._stop_event.set()
        self.ctrl_btn.setText("开始")
        self.ctrl_btn.setStyleSheet(ctrl_btn_style)
        self.status_label.setText("完成")
        self.status_label.setStyleSheet(
            "QLabel { font-size: 13px; background: #27AE60; color: white;"
            " border-radius: 5px; font-weight: bold; }"
        )
        self.func_btn.setEnabled(True)
        self._msg(f"任务 '{self.func_btn.text()}' 已停止")
        QTimer.singleShot(3000, self._reset_status)

    def _run_task(self):
        """在后台线程中执行自动化任务"""
        from src.bailian import DailyTask, DrawCard, AutoFight

        title = self.func_btn.text()
        if title == "未命名":
            return

        try:
            if title == "每日领取":
                DailyTask(self._stop_event).rush_all()
            elif title == "自动PK":
                DailyTask(self._stop_event).click_battle()
            elif title == "自动抽卡":
                DrawCard(self._stop_event).run()
            elif title == "木头":
                AutoFight(self._stop_event).rush_wood()
            elif title == "蓝矿":
                self._msg("蓝矿功能尚未实现")
            elif title in ("1-1", "2-2"):
                self._msg(f"关卡 {title} 功能尚未实现")
            else:
                self._msg(f"任务 '{title}' 尚未实现")
        except Exception as e:
            import traceback
            traceback.print_exc()

        # 任务结束，切回主线程更新UI
        QTimer.singleShot(0, self._on_task_finished)

    def _on_task_finished(self):
        """任务线程结束后更新UI（主线程执行）"""
        if self.is_running:
            self.stop_task()

    def _reset_status(self):
        if not self.is_running:
            self.status_label.setText("待命")
            self.status_label.setStyleSheet(status_label_style)

    def _msg(self, text):
        if self.parent_window:
            self.parent_window.show_status_message(text)


# ============================================================
# 主窗口
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("百炼英雄脚本助手 v2.0")
        self.setGeometry(100, 100, 750, 720)
        self.setMinimumSize(660, 600)

        self.current_running_task = None
        self.all_sub_widgets = []
        self.macro_panel = None

        self._build_central()
        self._build_sidebar()
        self._build_right_panel()
        self._build_statusbar()

        self.sub_buttons_config = {
            "日常": ["每日领取", "自动PK", "自动抽卡"],
            "资源": ["木头", "蓝矿"],
            "刷图": ["1-1", "2-2"],
        }

        self.show_sub_buttons("日常")

    # ---- 构建 UI ----
    def _build_central(self):
        main = QWidget()
        main.setStyleSheet("background: #ECF0F1;")
        self.main_layout = QVBoxLayout(main)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.content_h = QHBoxLayout()
        self.content_h.setContentsMargins(10, 10, 10, 10)
        self.content_h.setSpacing(12)
        self.main_layout.addLayout(self.content_h, 1)
        self.setCentralWidget(main)

    def _build_sidebar(self):
        side = QFrame()
        side.setFixedWidth(150)
        side.setStyleSheet("QFrame { background: #1a1a2e; border-radius: 10px; }")
        vl = QVBoxLayout(side)
        vl.setContentsMargins(10, 20, 10, 20)
        vl.setSpacing(10)

        title = QLabel("功能菜单")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ECF0F1;"
                            "padding: 6px; border-bottom: 1px solid #34495E;")
        vl.addWidget(title)
        vl.addSpacing(6)

        categories = [("日常", "#3498DB"), ("资源", "#E67E22"), ("刷图", "#9B59B6")]
        self.main_btns = {}
        for text, color in categories:
            btn = QPushButton(text)
            btn.setFixedHeight(50)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 14px; font-weight: bold;"
                f" background: {color}; color: white; border-radius: 8px; }}"
                f"QPushButton:hover {{ background: {self._dark(color)}; }}"
            )
            btn.clicked.connect(lambda checked, t=text: self.show_sub_buttons(t))
            vl.addWidget(btn)
            self.main_btns[text] = btn

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #34495E;")
        vl.addWidget(sep)

        macro_btn = QPushButton("🎬 宏管理")
        macro_btn.setFixedHeight(50)
        macro_btn.setCursor(Qt.PointingHandCursor)
        macro_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold;"
            " background: #E74C3C; color: white; border-radius: 8px; }"
            "QPushButton:hover { background: #C0392B; }"
        )
        macro_btn.clicked.connect(self.show_macro_panel)
        vl.addWidget(macro_btn)

        vl.addStretch()
        self.content_h.addWidget(side)

    @staticmethod
    def _dark(hex_c):
        r = max(0, int(hex_c[1:3], 16) - 24)
        g = max(0, int(hex_c[3:5], 16) - 24)
        b = max(0, int(hex_c[5:7], 16) - 24)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _build_right_panel(self):
        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self.right_content = QWidget()
        self.right_content.setStyleSheet("background: transparent;")
        self.right_layout = QVBoxLayout(self.right_content)
        self.right_layout.setContentsMargins(15, 15, 15, 15)
        self.right_layout.setSpacing(15)

        self.right_title = QLabel("请选择功能")
        self.right_title.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #2C3E50;"
            "padding-bottom: 10px; border-bottom: 2px solid #BDC3C7;"
        )
        self.right_layout.addWidget(self.right_title)

        self.placeholder = QLabel("请从左侧菜单中选择功能")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("font-size: 15px; color: #95A5A6; padding: 60px;")
        self.placeholder.hide()
        self.right_layout.addWidget(self.placeholder)
        self.right_layout.addStretch()

        self.right_scroll.setWidget(self.right_content)
        self.content_h.addWidget(self.right_scroll, 1)

    def _build_statusbar(self):
        sf = QFrame()
        sf.setFixedHeight(36)
        sf.setStyleSheet("background: #1a1a2e;")
        sl = QHBoxLayout(sf)
        sl.setContentsMargins(15, 6, 15, 6)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("font-size: 13px; color: #ECF0F1; font-weight: bold;")
        sl.addWidget(self.status_label)

        self.task_dot = QLabel()
        self.task_dot.setFixedSize(12, 12)
        self.task_dot.setStyleSheet("background: #2ECC71; border-radius: 6px;")
        sl.addWidget(self.task_dot)
        sl.addStretch()

        self.main_layout.addWidget(sf)

    # ---- 面板切换 ----
    def clear_right_frame(self):
        while self.right_layout.count() > 1:
            item = self.right_layout.takeAt(1)
            if item.widget():
                w = item.widget()
                if w in self.all_sub_widgets:
                    self.all_sub_widgets.remove(w)
                w.deleteLater()

    def show_sub_buttons(self, category):
        self.clear_right_frame()
        self.right_title.setText(f"{category}功能")

        items = self.sub_buttons_config.get(category, [])
        grp = QGroupBox(f"{category}功能")
        grp.setStyleSheet(
            "QGroupBox { font-size: 15px; font-weight: bold; color: #2C3E50;"
            " border: 1px solid #BDC3C7; border-radius: 10px; margin-top: 12px;"
            " padding-top: 15px; background: white; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 15px; padding: 0 8px; }"
        )
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(12, 22, 12, 12)
        gl.setSpacing(8)

        for title in items:
            w = SubButtonWidget(title, self)
            gl.addWidget(w)
            self.all_sub_widgets.append(w)

        self.right_layout.addWidget(grp)
        self.right_layout.addStretch()
        self.show_status_message(f"已切换到 '{category}'")

    def show_macro_panel(self):
        self.clear_right_frame()
        self.right_title.setText("宏管理")
        self.macro_panel = MacroPanel(self)
        self.right_layout.addWidget(self.macro_panel, 1)
        self.show_status_message("已切换到宏管理")

    # ---- 任务管理 ----
    def is_any_task_running(self):
        return self.current_running_task is not None

    def set_current_running_task(self, task):
        self.current_running_task = task
        self.task_dot.setStyleSheet("background: #E74C3C; border-radius: 6px;")
        for w in self.all_sub_widgets:
            if w != task:
                w.ctrl_btn.setEnabled(False)

    def clear_current_running_task(self):
        self.current_running_task = None
        self.task_dot.setStyleSheet("background: #2ECC71; border-radius: 6px;")
        for w in self.all_sub_widgets:
            w.ctrl_btn.setEnabled(True)

    def show_status_message(self, message):
        self.status_label.setText(message)


# ============================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 9))
    app.setStyleSheet(
        "QToolTip { background: #2C3E50; color: white; border: none;"
        " padding: 4px 10px; border-radius: 4px; font-size: 12px; }"
        "QScrollBar:vertical { background: #ECF0F1; width: 8px; border-radius: 4px; }"
        "QScrollBar::handle:vertical { background: #BDC3C7; border-radius: 4px; min-height: 30px; }"
        "QScrollBar::handle:vertical:hover { background: #95A5A6; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
    )

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
