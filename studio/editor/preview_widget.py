# -*- coding: utf-8 -*-
"""
视频预览播放器 — 基于 ffmpeg 帧提取
"""

import os
import subprocess
import threading
import tempfile

from PySide6.QtCore import Qt, QTimer, Signal, QThread
from studio.editor.gpu_accel import hwaccel_args
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QSlider,
    QWidget,
)

from . import pvt_bridge

# ── 探测工具 ──


def _probe_duration(path: str) -> float:
    try:
        info = pvt_bridge.probe(path)
        return info.get("duration_secs", 0.0)
    except Exception:
        return 0.0


def _probe_fps(path: str) -> float:
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=r_frame_rate",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        val = r.stdout.strip()
        if "/" in val:
            num, den = val.split("/")
            return float(num) / float(den)
        return float(val) if val else 24.0
    except Exception:
        return 24.0


def _probe_resolution(path: str):
    try:
        info = pvt_bridge.probe(path)
        return info.get("width", 0), info.get("height", 0)
    except Exception:
        return 0, 0


# ── 帧提取线程 ──


class FrameExtractor(QThread):
    """后台线程：seek 单帧 + 播放流读取"""

    frame_ready = Signal(object)  # QImage
    duration_ready = Signal(float)
    position_changed = Signal(float)
    error_occurred = Signal(str)
    play_finished = Signal()
    play_started = Signal()

    MODE_IDLE = 0
    MODE_SEEK = 1
    MODE_PLAY = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = None
        self._running = False
        self._mode = self.MODE_IDLE
        self._seek_pos = 0.0
        self._play_start_pos = 0.0
        self._play_speed = 1.0
        self._fps = 24.0
        self._duration = 0.0
        self._w = 0
        self._h = 0
        self._ffproc = None
        self._request_mode = self.MODE_IDLE
        self._request_seek = None
        self._skip_to_pos = None

    def load(self, path):
        self.stop()
        self.wait(500)
        self._path = path
        self._mode = self.MODE_IDLE
        self._running = True
        self.start()

    def seek_to(self, seconds):
        self._seek_pos = max(0.0, seconds)
        self._request_mode = self.MODE_SEEK
        self._request_seek = self._seek_pos

    def start_play(self, from_pos: float = None):
        if from_pos is not None:
            self._play_start_pos = from_pos
        self._request_mode = self.MODE_PLAY

    def stop_play(self):
        if self._mode == self.MODE_PLAY or self._request_mode == self.MODE_PLAY:
            self._request_mode = self.MODE_IDLE

    def skip_to(self, pos: float):
        """播放中跳帧：无缝跳到目标位置，不触发 play_finished"""
        self._skip_to_pos = max(0.0, pos)

    def terminate(self):
        if self._ffproc:
            try:
                self._ffproc.kill()
                self._ffproc.wait(1)
            except Exception:
                pass
            self._ffproc = None

    def stop(self):
        self.terminate()
        self._running = False
        self._request_mode = self.MODE_IDLE
        self._request_seek = None
        self._skip_to_pos = None

    @property
    def duration(self):
        return self._duration

    @property
    def fps(self):
        return self._fps

    @property
    def play_speed(self):
        return self._play_speed

    @play_speed.setter
    def play_speed(self, val: float):
        self._play_speed = max(0.5, min(val, 5.0))

    def _open_video(self):
        self._duration = _probe_duration(self._path)
        self._fps = _probe_fps(self._path)
        self._w, self._h = _probe_resolution(self._path)
        self.duration_ready.emit(self._duration)

    def _extract_frame_at(self, sec: float):
        try:
            w, h = self._w, self._h
            if w <= 0 or h <= 0:
                w, h = 640, 360
            dst_w = min(w, 640)
            dst_h = int(h * dst_w / w)
            cmd = ["ffmpeg"]
            hw = hwaccel_args()
            if hw:
                cmd.extend(hw)
            cmd.extend(
                [
                    "-ss",
                    str(sec),
                    "-i",
                    self._path,
                    "-vframes",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-s",
                    f"{dst_w}x{dst_h}",
                    "-y",
                    "-",
                ]
            )
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            if not r.stdout:
                return None
            img = QImage(r.stdout, dst_w, dst_h, QImage.Format.Format_RGB888)
            return img.copy()
        except Exception:
            return None

    def _play_stream(self):
        w, h = self._w, self._h
        if w <= 0 or h <= 0:
            w, h = 640, 360
        dst_w = min(w, 640)
        dst_h = int(h * dst_w / w)
        frame_bytes = dst_w * dst_h * 3

        def _spawn_ffmpeg(start_pos: float):
            cmd = ["ffmpeg"]
            hw = hwaccel_args()
            if hw:
                cmd.extend(hw)
            cmd.extend(
                [
                    "-ss",
                    str(start_pos),
                    "-i",
                    self._path,
                    "-vframes",
                    str(int(self._duration * self._fps)),
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-s",
                    f"{dst_w}x{dst_h}",
                    "-threads",
                    "1",
                    "-",
                ]
            )
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=frame_bytes * 4,
            )
            self._ffproc = p
            return p

        try:
            proc = _spawn_ffmpeg(self._play_start_pos)
        except Exception as e:
            self.error_occurred.emit(str(e))
            return

        frame_idx = 0
        pos = self._play_start_pos
        self._mode = self.MODE_PLAY
        self._request_mode = self.MODE_PLAY
        self.play_started.emit()
        _interrupted = False

        while self._running and self._mode == self.MODE_PLAY:
            if self._skip_to_pos is not None:
                skip = self._skip_to_pos
                self._skip_to_pos = None
                proc.kill()
                proc.wait(1)
                self._ffproc = None
                self._play_start_pos = skip
                pos = skip
                frame_idx = 0
                try:
                    proc = _spawn_ffmpeg(skip)
                except Exception:
                    break
                continue

            if self._request_mode == self.MODE_IDLE:
                self._ffproc = None
                self._mode = self.MODE_IDLE
                _interrupted = True
                break

            if self._request_mode == self.MODE_SEEK:
                proc.kill()
                proc.wait(1)
                self._ffproc = None
                self._mode = self.MODE_IDLE
                self._request_mode = self.MODE_IDLE
                self._handle_seek()
                return

            data = proc.stdout.read(frame_bytes)
            if not data or len(data) < frame_bytes:
                break

            img = QImage(data, dst_w, dst_h, QImage.Format.Format_RGB888)
            if not img.isNull():
                self.frame_ready.emit(img.copy())

            pos = self._play_start_pos + frame_idx / self._fps
            self.position_changed.emit(pos)
            frame_idx += 1
            self.msleep(max(1, int(1000 / (self._fps * self._play_speed))))

        proc.kill()
        proc.wait(1)
        self._ffproc = None
        self._mode = self.MODE_IDLE
        if not _interrupted and self._running and self._request_mode == self.MODE_PLAY:
            self.play_finished.emit()
            self._request_mode = self.MODE_IDLE

    def _handle_seek(self):
        self._mode = self.MODE_SEEK
        img = self._extract_frame_at(self._seek_pos)
        if img and not img.isNull():
            self.frame_ready.emit(img)
        self.position_changed.emit(self._seek_pos)
        self._mode = self.MODE_IDLE

    def run(self):
        if not self._path or not os.path.exists(self._path):
            self.error_occurred.emit("文件不存在")
            return
        self._open_video()
        if self._duration <= 0:
            self.error_occurred.emit("无法获取视频时长")
            return
        img = self._extract_frame_at(0)
        if img and not img.isNull():
            self.frame_ready.emit(img)
        while self._running:
            mode = self._request_mode
            if mode == self.MODE_SEEK:
                self._request_mode = self.MODE_IDLE
                self._mode = self.MODE_SEEK
                img = self._extract_frame_at(self._request_seek or self._seek_pos)
                if img and not img.isNull():
                    self.frame_ready.emit(img)
                self.position_changed.emit(self._request_seek or self._seek_pos)
                self._mode = self.MODE_IDLE
            elif mode == self.MODE_PLAY:
                self._request_mode = self.MODE_IDLE
                self._play_stream()
            else:
                self.msleep(50)


# ── 预览控件 ──


class _FitView(QGraphicsView):
    """自动 fitInView 的预览视图，窗口缩放时画面等比例缩放"""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_pixmap_item") and self._pixmap_item.pixmap().isNull() is False:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        if hasattr(self, "_reposition_callback") and self._reposition_callback:
            self._reposition_callback()


class PreviewWidget(QWidget):
    """视频预览控件"""

    play_state_changed = Signal(bool)
    position_changed = Signal(float)
    duration_changed = Signal(float)
    frame_step_requested = Signal(float)  # 逐帧步进
    play_finished = Signal()
    audio_ready = Signal()
    timeline_link_changed = Signal(bool)  # 时间线联动开关切换
    play_requested = Signal()  # 播放按钮点击 → MainWindow 统一调度

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PreviewWidget")
        self.setStyleSheet("background-color: #0d0d0f;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._current_path = None
        self._audio_source = ""  # 音频提取用源（代理模式下用原始文件）
        self._playing = False
        self._duration = 0.0
        self._position = 0.0
        self._audio_temp = None
        self._audio_proc = None
        self._extract_gen = 0
        self._audio_schedule = []  # [(start, end, audio_path, muted), ...]
        self._video_schedule = []  # [(start, end, video_path), ...]
        self._schedule_idx = -1
        self._video_size = (0.0, 0.0)  # (width, height) 用于字幕定位
        self._active_duration = 0.0  # 选中素材时长（timeline 时间），0 表示用 _duration
        self._source_offset = 0.0  # 选中素材在源文件中的偏移
        self._speed = 1.0  # 当前素材播放速度
        self._muted = False  # 静音状态
        self._clip_relative = False  # 是否处于素材相对模式（选中素材时）
        self._still_frame = False  # 特效预览静态帧标志

        # 场景
        self._scene = QGraphicsScene(self)
        self._view = _FitView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._view.setStyleSheet("background: transparent; border: none;")
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._view._pixmap_item = self._pixmap_item
        self._view._reposition_callback = self._reposition_subtitle_overlay

        # 字幕叠加 QLabel（viewport 子控件，自动裁剪超出区域）
        self._sub_overlay = QLabel(self._view.viewport())
        self._sub_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_overlay.setWordWrap(True)
        self._sub_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._sub_overlay.setStyleSheet("background: transparent;")
        self._sub_overlay.hide()

        # 提取器
        self._extractor = FrameExtractor(self)
        self._extractor.frame_ready.connect(self._on_frame)
        self._extractor.duration_ready.connect(self._on_duration)
        self._extractor.position_changed.connect(self._on_position_changed)
        self._extractor.error_occurred.connect(self._on_error)
        self._extractor.play_finished.connect(self._on_play_finished)
        self._extractor.play_finished.connect(self.play_finished.emit)
        self._extractor.play_started.connect(self._on_play_started)
        self.audio_ready.connect(self._on_audio_ready)

        self._setup_ui()
        self._show_placeholder()

        # 播放/暂停按钮同步
        self.play_state_changed.connect(self._on_play_state_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 视频区域
        self._view.setMinimumHeight(200)
        self._view.setLayout(None)  # 确保没有布局冲突
        layout.addWidget(self._view, 1)

        # 播放控制条
        # 控制栏
        controls = QWidget()
        controls.setStyleSheet("background-color: #1a1a1e;")
        ctrl_outer = QVBoxLayout(controls)
        ctrl_outer.setContentsMargins(12, 4, 12, 4)
        ctrl_outer.setSpacing(2)

        # 时间线联动开关（仅 t2v 模式可见，默认关闭=独立预览）
        self._timeline_link_cb = QCheckBox("时间线联动")
        self._timeline_link_cb.setChecked(False)
        self._timeline_linked = False
        self._timeline_link_cb.setToolTip("勾选后预览响应时间线；不勾选时仅显示文字生视频素材画面")
        self._timeline_link_cb.setStyleSheet("color: #aaa; font-size: 13px; spacing: 6px;")
        self._timeline_link_cb.toggled.connect(self._on_timeline_link_toggled)
        self._timeline_link_cb.hide()
        ctrl_outer.addWidget(self._timeline_link_cb)

        # 主控制行
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        self._time_label = QLabel("00:00.0 / 00:00.0")
        self._time_label.setStyleSheet("color: #888; font-size: 11px; font-family: monospace;")
        ctrl.addWidget(self._time_label)

        ctrl.addSpacing(4)

        self._btn_play = QPushButton("▶")
        self._btn_play.setFixedSize(40, 32)
        self._btn_play.setToolTip("播放 (空格)")
        self._btn_play.setStyleSheet(
            "QPushButton { background-color:#3a8cff; color:#fff; border:none; border-radius:6px; font-size:16px; font-weight:bold; } "
            "QPushButton:hover { background-color:#5b9dff; }"
        )
        self._btn_play.clicked.connect(self._on_play_btn)
        ctrl.addWidget(self._btn_play)

        self._btn_pause = QPushButton("⏸")
        self._btn_pause.setFixedSize(40, 32)
        self._btn_pause.setToolTip("暂停 (空格)")
        self._btn_pause.setStyleSheet(
            "QPushButton { background-color:#3a8cff; color:#fff; border:none; border-radius:6px; font-size:16px; font-weight:bold; } "
            "QPushButton:hover { background-color:#5b9dff; }"
        )
        self._btn_pause.clicked.connect(self.pause)
        self._btn_pause.setVisible(False)
        ctrl.addWidget(self._btn_pause)

        ctrl.addSpacing(4)

        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.setStyleSheet(self._slider_style())
        self._seek_slider.sliderPressed.connect(self._on_seek_start)
        self._seek_slider.sliderReleased.connect(self._on_seek_end)
        self._seek_slider.sliderMoved.connect(self._on_seek)
        ctrl.addWidget(self._seek_slider, 1)

        ctrl_outer.addLayout(ctrl)
        layout.addWidget(controls)

    def _slider_style(self) -> str:
        return (
            "QSlider::groove:horizontal { background: #2a2a32; height: 4px; border-radius: 2px; } "
            "QSlider::handle:horizontal { background: #3a8cff; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; } "
            "QSlider::sub-page:horizontal { background: #3a8cff; border-radius: 2px; }"
        )

    def _show_placeholder(self):
        pm = QPixmap(320, 200)
        pm.fill(QColor("#0d0d0f"))
        p = QPainter(pm)
        p.setPen(QColor("#444"))
        p.setFont(QFont("sans-serif", 14))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "预览")
        p.end()
        self._pixmap_item.setPixmap(pm)

    def _format_time(self, sec: float) -> str:
        m = int(sec // 60)
        s = int(sec % 60)
        ms = int((sec % 1) * 10)
        return f"{m}:{s:02d}.{ms}"

    def _update_time_display(self):
        eff = self._get_effective_duration()
        self._time_label.setText(f"{self._format_time(self._position)} / {self._format_time(eff)}")

    # ── 公共 API ──

    def load(self, path: str, audio_source: str = ""):
        self._stop_audio()
        self._audio_schedule.clear()  # 选中单个素材时清空多轨排期
        self._video_schedule.clear()
        self._current_path = path
        self._audio_source = audio_source or path
        self._playing = False
        self._position = 0.0
        self._duration = 0.0
        self._extractor.stop()
        self._extractor.wait(500)
        self._extractor.load(path)
        self._extract_gen += 1
        self._extract_audio_async()
        self.play_state_changed.emit(False)

        self._update_time_display()

    def play(self):
        if not self._current_path or self._duration <= 0:
            return
        eff = self._get_effective_duration()
        if self._position >= eff:
            self._position = 0.0
        self._playing = True
        self._extractor.start_play(self._source_offset + self._position * self._speed)
        if self._audio_schedule:
            self._check_schedule()
        else:
            self._try_start_audio()
        self.play_state_changed.emit(True)

    def _try_start_audio(self):
        if not self._playing:
            return
        if self._audio_temp and os.path.exists(self._audio_temp):
            self._start_audio()
            return
        QTimer.singleShot(800, self._try_start_audio)

    def pause(self):
        self._playing = False
        self._extractor.stop_play()
        self._stop_audio()
        self.play_state_changed.emit(False)

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play_requested.emit()

    def _on_play_btn(self):
        if self._playing:
            self.pause()
        else:
            self.play_requested.emit()

    @property
    def timeline_linked(self) -> bool:
        """时间线联动开关状态 — t2v 模式下可关闭以独立预览"""
        return self._timeline_linked

    def set_timeline_link_visible(self, visible: bool):
        """显示/隐藏时间线联动开关（仅 t2v 模式显示，默认关闭=独立预览）"""
        self._timeline_link_cb.setVisible(visible)
        if visible:
            self._timeline_linked = False
            self._timeline_link_cb.setChecked(False)
        else:
            self._timeline_linked = True
            self._timeline_link_cb.setChecked(True)

    def _on_timeline_link_toggled(self, checked: bool):
        self._timeline_linked = checked
        self.timeline_link_changed.emit(checked)

    def show_still_frame(self, pixmap):
        """显示静态帧（特效预览用），阻止视频帧更新"""
        self._still_frame = True
        self._pixmap_item.setPixmap(pixmap)
        self._view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def clear_still_frame(self):
        """清除静态帧，恢复视频预览"""
        self._still_frame = False
        return self._playing

    def is_playing(self):
        return self._playing

    def seek(self, seconds: float):
        """跳转到 timeline 相对位置 seconds（不含 source_offset，含 speed 补偿）"""
        eff = self._get_effective_duration()
        self._position = max(0.0, min(seconds, eff))
        abs_pos = self._source_offset + self._position * self._speed  # 转成源绝对位置
        if self._playing:
            self._stop_audio()
            self._extractor.skip_to(abs_pos)
            self._start_audio()
        else:
            self._extractor.seek_to(abs_pos)
        self.position_changed.emit(self._position)  # 发射 timeline 相对位置
        self._update_time_display()
        self._update_seek_slider()

    def step_forward(self):
        """前进一帧"""
        if self._duration <= 0:
            return
        dt = 1.0 / max(self._extractor.fps, 24.0)
        self.pause()
        self.seek(self._position + dt)

    def step_backward(self):
        """后退一帧"""
        if self._duration <= 0:
            return
        dt = 1.0 / max(self._extractor.fps, 24.0)
        self.pause()
        self.seek(self._position - dt)

    def _reposition_subtitle_overlay(self):
        """根据视频帧在 viewport 中的实际区域定位字幕（底部居中，不超出视频画面）"""
        vp = self._view.viewport()
        vw = vp.width()
        vh = vp.height()
        if vw <= 0 or vh <= 0:
            return
        # 计算视频帧在 viewport 坐标中的实际矩形（fitInView + KeepAspectRatio 会产生黑边）
        pix = self._pixmap_item.pixmap()
        video_rect = self._view.viewport().rect()
        if not pix.isNull():
            scene_rect = self._pixmap_item.sceneBoundingRect()
            video_rect = self._view.mapFromScene(scene_rect).boundingRect()
        # 字幕宽度 ≤ 视频帧宽的 80%，不超过 viewport
        max_w = min(int(video_rect.width() * 0.8), int(vw * 0.92))
        # 字幕区域必须在视频帧内
        video_bottom = video_rect.bottom()
        video_top = video_rect.top()
        margin = max(8, int(video_rect.height() * 0.03))
        max_h = max(video_rect.height() // 4, video_bottom - video_top - margin * 2)
        self._sub_overlay.setFixedWidth(max_w)
        self._sub_overlay.setMaximumHeight(max_h)
        self._sub_overlay.adjustSize()
        oh = min(self._sub_overlay.height(), max_h)
        # 底部居中，距视频帧底部 margin 像素
        x = video_rect.left() + (video_rect.width() - max_w) // 2
        y = video_bottom - oh - margin
        # 确保不超出 viewport
        x = max(0, min(x, vw - max_w))
        y = max(video_top, min(y, vh - oh))
        self._sub_overlay.move(x, y)

    def set_subtitle(self, text: str, font_size: int = 18):
        if not text:
            self._sub_overlay.hide()
            return
        # 用 QLabel 显示，CSS text-shadow 实现 1px 描边，保持文字清晰
        self._sub_overlay.setText(
            f'<p style="color:white; font-size:{font_size}px; font-weight:bold; '
            "text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, "
            "-1px 1px 0 #000, 1px 1px 0 #000; "
            "background: rgba(0,0,0,0.05); border-radius:4px; "
            'text-align:center; margin:0; padding:4px 14px;">'
            f"{text}</p>"
        )
        self._reposition_subtitle_overlay()
        self._sub_overlay.show()

    @property
    def current_path(self):
        return self._current_path

    @property
    def duration(self):
        return self._duration

    @property
    def position(self):
        return self._position

    @property
    def fps(self):
        return self._extractor.fps

    @property
    def play_speed(self):
        return self._extractor.play_speed

    @play_speed.setter
    def play_speed(self, val: float):
        self._extractor.play_speed = val

    def set_mode(self, mode: str):
        """兼容旧 API — 切换剪辑/翻译模式"""
        pass

    # ── 兼容方法（翻译管线集成） ──

    def set_clip_ranges(self, ranges: list):
        """设置有效播放范围（兼容旧 API）"""
        pass

    def refresh_audio(self):
        """刷新音频（旧 API 兼容）"""
        if self._current_path:
            self._extract_gen += 1
            self._extract_audio_async()

    def update_subtitle_style(self, font_size: int, bold: bool):
        """兼容旧 API — 字幕样式已移除"""
        pass

    def set_active_duration(self, dur: float, speed: float = 1.0):
        """设置有效时长（选中素材时用 clip.duration，取消选中时传 0）
        dur — timeline 时长；speed — 播放速度倍率
        """
        self._active_duration = max(0.0, dur)
        self._speed = max(0.1, speed) if dur > 0 else 1.0
        # 变速后素材时长可能缩短，裁剪 _position 防止溢出
        eff = self._get_effective_duration()
        if self._position > eff:
            self._position = eff
        self._update_seek_slider()

    def set_source_offset(self, offset: float):
        """设置素材在源文件中的偏移（分割素材 source_start）"""
        self._source_offset = max(0.0, offset)
        self._clip_relative = offset > 0

    def set_muted(self, muted: bool):
        """设置静音状态，停止当前音频"""
        self._muted = muted
        if muted:
            self._stop_audio()

    def _get_effective_duration(self) -> float:
        return self._active_duration if self._active_duration > 0 else self._duration

    def clear_preview(self):
        self._extractor.terminate()
        self.cleanup()
        self._current_path = None
        self._audio_source = ""
        self._position = 0.0
        self._duration = 0.0
        self._extractor._skip_to_pos = None
        self._sub_overlay.hide()
        self._show_placeholder()

    def cleanup(self):
        self._stop_audio()
        self._cleanup_audio_temp()
        self._extractor.terminate()
        self._extractor.stop()
        self._extractor.wait(3000)

    # ── 内部 ──

    def _on_frame(self, img: QImage):
        if self._still_frame:
            return
        if img.isNull():
            return
        pm = QPixmap.fromImage(img)
        self._pixmap_item.setPixmap(pm)
        self._view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._video_size = (img.width(), img.height())
        if self._sub_overlay and self._sub_overlay.isVisible():
            self._reposition_subtitle_overlay()

    def _on_duration(self, sec: float):
        self._duration = sec
        self.duration_changed.emit(sec)
        self._update_time_display()
        self._update_seek_slider()

    def _on_position_changed(self, pos: float):
        """FrameExtractor 报告绝对源位置 → 转成 timeline 相对位置（含 speed 补偿）"""
        self._position = max(0.0, (pos - self._source_offset) / self._speed)
        self.position_changed.emit(self._position)  # 发射 timeline 相对位置
        self._check_schedule()  # 帧同步检查排期表，切换音频
        self._update_time_display()
        self._update_seek_slider()

    def _on_error(self, msg: str):
        self._show_placeholder()

    def _on_play_finished(self):
        self._playing = False
        self._stop_audio()
        self.play_state_changed.emit(False)
        self._update_time_display()
        self._update_seek_slider()

    def _on_play_state_changed(self, playing: bool):
        """同步播放/暂停按钮可见性"""
        self._btn_play.setVisible(not playing)
        self._btn_pause.setVisible(playing)

    def _on_play_started(self):
        self._playing = True
        self.play_state_changed.emit(True)

        if self._audio_temp and os.path.exists(self._audio_temp):
            self._start_audio()

    def _update_seek_slider(self):
        eff = self._get_effective_duration()
        if eff > 0:
            self._seek_slider.blockSignals(True)
            self._seek_slider.setValue(int((self._position / eff) * 1000))
            self._seek_slider.blockSignals(False)

    def _on_seek_start(self):
        if self._playing:
            self._extractor.stop_play()
            self._stop_audio()

    def _on_seek_end(self):
        eff = self._get_effective_duration()
        val = self._seek_slider.value() / 1000.0 * eff
        self.seek(val)

    def _on_seek(self, val: int):
        eff = self._get_effective_duration()
        pos = val / 1000.0 * eff
        self._position = pos
        self._extractor.seek_to(self._source_offset + pos)
        self.position_changed.emit(pos)  # 立即同步到时间线
        self._update_time_display()

    # ── 音频 ──

    def _extract_audio(self, video_path: str) -> str:
        try:
            fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="pv_audio_")
            os.close(fd)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    video_path,
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-b:a",
                    "128k",
                    tmp,
                ],
                capture_output=True,
                timeout=300,
            )
            return tmp if os.path.exists(tmp) and os.path.getsize(tmp) > 1000 else None
        except Exception:
            return None

    def _extract_audio_async(self):
        gen = self._extract_gen
        audio_src = self._audio_source

        def _do():
            tmp = self._extract_audio(audio_src)
            if tmp and gen == self._extract_gen:
                self._audio_temp = tmp
                self.audio_ready.emit()

        threading.Thread(target=_do, daemon=True).start()

    def _on_audio_ready(self):
        # 有排期表时音频由 _check_schedule 控制，不从提取的临时文件自动播放
        if self._playing and self._audio_temp and os.path.exists(self._audio_temp) and not self._audio_schedule:
            self._start_audio()

    def _start_audio(self):
        if self._muted:
            return
        # 有排期表时音频由 _check_schedule 切换，不从提取的临时文件播放
        if self._audio_schedule:
            return
        self._stop_audio()
        if not self._audio_temp or not os.path.exists(self._audio_temp):
            return
        try:
            self._audio_proc = subprocess.Popen(
                [
                    "ffplay",
                    "-nodisp",
                    "-autoexit",
                    "-ss",
                    str(self._source_offset + self._position * self._speed),
                    "-i",
                    self._audio_temp,
                    "-loglevel",
                    "quiet",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            self._audio_proc = None

    def _stop_audio(self):
        if self._audio_proc:
            try:
                self._audio_proc.kill()
                self._audio_proc.wait(1)
            except Exception:
                pass
            self._audio_proc = None

    def set_multi_track_schedule(self, audio_schedule: list, video_schedule: list = None):
        """设置多轨排期表。audio: [(start, end, audio_path, muted), ...]; video: [(start, end, video_path), ...]"""
        self._audio_schedule = sorted(audio_schedule, key=lambda x: x[0])
        self._video_schedule = sorted(video_schedule or [], key=lambda x: x[0])
        self._schedule_idx = -1

    def _find_schedule_at(self, pos: float) -> int:
        """返回播放头位置对应的排期索引，-1 表示无匹配"""
        for i, (start, end, _, _) in enumerate(self._audio_schedule):
            if start <= pos < end:
                return i
        return -1

    def _check_schedule(self):
        """帧同步检查：播放头跨过音源/视频源边界时切换"""
        if not self._playing or not self._audio_schedule:
            return
        pos = self._source_offset + self._position * self._speed

        # ── 音频切换 ──
        idx = self._find_schedule_at(pos)
        if idx != self._schedule_idx:
            self._schedule_idx = idx
            self._stop_audio()
            if idx >= 0 and not self._muted:
                _, _, audio_path, entry_muted = self._audio_schedule[idx]
                if not entry_muted and audio_path and os.path.exists(audio_path):
                    try:
                        offset = pos - self._audio_schedule[idx][0]
                        self._audio_proc = subprocess.Popen(
                            [
                                "ffplay",
                                "-nodisp",
                                "-autoexit",
                                "-ss",
                                str(max(0.0, offset)),
                                "-i",
                                audio_path,
                                "-loglevel",
                                "quiet",
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    except Exception:
                        self._audio_proc = None

        # ── 视频源切换 ──
        for v_start, v_end, v_path in self._video_schedule:
            if v_start <= pos < v_end and v_path != self._current_path:
                if os.path.exists(v_path):
                    self._extractor.stop()
                    self._extractor.wait(300)
                    self._extractor.load(v_path)
                    self._current_path = v_path
                break

    def _cleanup_audio_temp(self):
        if self._audio_temp and os.path.exists(self._audio_temp):
            try:
                os.unlink(self._audio_temp)
            except Exception:
                pass
        self._audio_temp = None

    def mouseDoubleClickEvent(self, event):
        self.toggle_play()
        super().mouseDoubleClickEvent(event)
