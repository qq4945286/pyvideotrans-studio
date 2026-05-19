# -*- coding: utf-8 -*-
"""
单轨时间线 — QPainter 渲染
"""

import os
import copy
import math
import uuid
import tempfile
import subprocess
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRectF, QRect, QPoint, QPointF, QThread
from PySide6.QtGui import QPolygonF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QSlider,
    QLabel,
    QScrollBar,
    QFrame,
    QMenu,
    QDialog,
    QPushButton,
    QComboBox,
)

from .models import TimelineClip, SubtitleEntry
from . import pvt_bridge
from .. import oplog

# ── SRT 解析 ──


def _parse_srt(text: str) -> list:
    """解析 SRT 格式文本 → list[SubtitleEntry]"""
    import re

    entries = []
    blocks = text.strip().replace("\r\n", "\n").split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue
        m = re.match(
            r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)",
            lines[1],
        )
        if not m:
            continue

        def _ts(h, m, s, ms):
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        g = [int(x) for x in m.groups()]
        start = _ts(g[0], g[1], g[2], g[3])
        end = _ts(g[4], g[5], g[6], g[7])
        text_content = "\n".join(lines[2:])
        entries.append(SubtitleEntry(index=idx, start=start, end=end, text=text_content))
    return entries


# ── 辅助 ──


def _probe_duration(path: str) -> float:
    try:
        info = pvt_bridge.probe(path)
        return info.get("duration_secs", 0.0)
    except Exception:
        return 0.0


# ── 缩略图提取 ──


def extract_thumbnail_blocking(
    source_path: str, position_sec: float, thumb_w: int = 160, thumb_h: int = 90
) -> bytes | None:
    """用 ffmpeg 在指定位置抽取一帧缩略图，返回 JPEG 字节"""
    import subprocess
    import os

    if not os.path.exists(source_path):
        return None
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(position_sec),
                "-i",
                source_path,
                "-vframes",
                "1",
                "-s",
                f"{thumb_w}x{thumb_h}",
                "-f",
                "mjpeg",
                "-q:v",
                "5",
                "-",
            ],
            capture_output=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode == 0 and proc.stdout:
            return bytes(proc.stdout)
    except Exception:
        pass
    return None


class ThumbnailWorker(QThread):
    """后台提取缩略图"""

    thumbnail_ready = Signal(str, float, object)  # source_path, position, QImage | None

    def __init__(self, source_path: str, position_sec: float, thumb_w: int = 160, thumb_h: int = 90):
        super().__init__()
        self._source_path = source_path
        self._position = position_sec
        self._tw = thumb_w
        self._th = thumb_h
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        data = extract_thumbnail_blocking(self._source_path, self._position, self._tw, self._th)
        if self._cancelled:
            return
        if data:
            img = QImage()
            img.loadFromData(data, "JPEG")
            if not img.isNull():
                self.thumbnail_ready.emit(self._source_path, self._position, img)
                return
        self.thumbnail_ready.emit(self._source_path, self._position, None)


# ── 波形提取 ──


def extract_audio_peaks_blocking(audio_path: str, num_peaks: int = 2000) -> list[float]:
    import struct
    import math
    import subprocess

    try:
        cmd = ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "8000", "-f", "f32le", "-hide_banner", "pipe:1"]
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
        raw = proc.stdout
        if not raw or len(raw) < 4:
            return []
        sample_count = len(raw) // 4
        max_samp = 1000000
        dc = min(sample_count, max_samp)
        samples = struct.unpack(f"{dc}f", raw[: dc * 4])
        chunk = max(1, len(samples) // num_peaks)
        peaks = []
        for i in range(0, len(samples), chunk):
            seg = samples[i : i + chunk]
            if not seg:
                continue
            rms = math.sqrt(sum(s * s for s in seg) / len(seg))
            peaks.append(min(1.0, rms * 3.0))
        return peaks
    except Exception:
        return []


class WaveformWorker(QThread):
    waveform_ready = Signal(str, object)  # source_path, list[float]

    def __init__(self, source_path, num_peaks=2000):
        super().__init__()
        self._source_path = source_path
        self._num_peaks = num_peaks
        self._cancelled = False

    @property
    def source_path(self):
        return self._source_path

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        peaks = extract_audio_peaks_blocking(self._source_path, self._num_peaks)
        if not self._cancelled:
            self.waveform_ready.emit(self._source_path, peaks or [])


# ── Clip 属性编辑对话框 ──


class ProxyDialog(QDialog):
    """代理设置对话框 — 选中素材生成低分辨率代理文件"""

    def __init__(self, clip_label: str, source_resolution: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"代理设置 — {clip_label}")
        self.setFixedSize(380, 320)
        self.setStyleSheet("""
            QDialog { background:#1e1e22; color:#d0d0d0; }
            QLabel { color:#aaa; font-size:12px; }
            QComboBox { background:#2a2a32; color:#d0d0d0; border:1px solid #3a3a42;
                border-radius:4px; padding:4px 8px; font-size:12px; }
            QComboBox::drop-down { border:none; }
            QComboBox QAbstractItemView { background:#2a2a32; color:#d0d0d0;
                selection-background-color:#3a8cff44; }
            QPushButton { background:#2a2a32; color:#d0d0d0; border:1px solid #3a3a42;
                border-radius:4px; padding:6px 16px; font-size:12px; }
            QPushButton:hover { border-color:#3a8cff; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        layout.addWidget(QLabel("输出分辨率"))
        self.res_combo = QComboBox()
        self.res_combo.addItems(["原始分辨率", "1/2 (50%)", "1/4 (25%)", "960×540", "640×360"])
        self.res_combo.setCurrentIndex(1)
        layout.addWidget(self.res_combo)

        layout.addWidget(QLabel("编码格式"))
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["H.264 (推荐)", "ProRes Proxy"])
        layout.addWidget(self.codec_combo)

        layout.addWidget(QLabel("帧率"))
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["原始帧率", "1/2 帧率"])
        layout.addWidget(self.fps_combo)

        note = QLabel("代理仅用于剪辑预览，导出和翻译始终使用原素材。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(note)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("生成代理")
        btn_ok.setStyleSheet("QPushButton { background:#3a8cff; color:#fff; border-radius:4px; padding:6px 20px; }")
        btn_ok.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def get_settings(self) -> dict:
        return {
            "resolution": self.res_combo.currentIndex(),
            "codec": self.codec_combo.currentIndex(),
            "fps": self.fps_combo.currentIndex(),
        }


# ═══════════════════════════════════════════════════════════════
# 时间线控件
# ═══════════════════════════════════════════════════════════════


class TimelineWidget(QFrame):
    """单轨时间线 — QPainter 渲染"""

    clip_selected = Signal(object)  # TimelineClip | None
    clip_changed = Signal(object)  # clip 被编辑
    clips_changed = Signal()  # 整体变化（增删改）
    seek_requested = Signal(float)  # 跳转到时间点
    clip_double_clicked = Signal(object)  # TimelineClip
    subtitle_edit_requested = Signal(object, int)  # SubtitleEntry, index
    subtitle_selected = Signal(object)  # SubtitleEntry | None
    dub_requested = Signal(list)  # list[SubtitleEntry] — 右键菜单请求配音
    dub_local_requested = Signal(list)  # list[SubtitleEntry] — 右键菜单请求本地字幕配音
    resolution_mismatch = Signal(object, int, int)  # clip, project_w, project_h — 分辨率不匹配通知

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(120)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        # ── 数据 ──
        self._clips: list[TimelineClip] = []
        self._selected: Optional[TimelineClip] = None
        self._multi_selected: list[TimelineClip] = []
        self._range_anchor: Optional[TimelineClip] = None  # Shift 范围选择锚点
        self._duration = 30.0  # 时间线总长（秒）
        self._position = 0.0  # 播放头位置
        self._pixels_per_sec = 2.0  # 缩放，默认 1%

        # ── 控件 ──

        self._clip_color_bg = QColor("#1a2a3a")
        self._clip_color_selected = QColor("#1a4a6a")
        self._clip_border = QColor("#4a7acc")
        self._clip_border_sel = QColor("#FF8C00")

        # ── 拖拽 ──
        self._dragging = False
        self._drag_start_x = 0
        self._drag_orig_start = 0.0
        self._trimming = None  # "left" | "right" | None
        self._trim_clip = None
        self._trim_orig_start = 0.0
        self._trim_orig_dur = 0.0
        self._trim_orig_source_start = 0.0
        self._trim_orig_x = 0

        # ── 波形缓存 ──
        self._waveform_cache: dict[str, list[float]] = {}
        self._waveform_pending: set[str] = set()
        self._thumbnail_cache: dict[tuple[str, float], QImage] = {}  # (source_path, position) -> QImage
        self._thumbnail_pending: set[tuple[str, float]] = set()
        self._waveform_workers: list[WaveformWorker] = []

        # ── 吸附 ──
        self._snap_enabled = True

        # ── 撤销/重做 ──
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._undo_max = 200
        self._undo_group: Optional[dict] = None  # 组合操作（如拖拽+松手=一次撤销）

        # ── 字幕 ──
        self._subtitle_entries: list[SubtitleEntry] = []
        self._subtitle_font_size: int = 18
        self._selected_subtitle: Optional[SubtitleEntry] = None
        self._multi_selected_subs: set = set()  # Ctrl/Shift 多选字幕集合
        self._drag_sub = False
        self._drag_sub_orig_start = 0.0
        self._drag_sub_orig_end = 0.0
        self._drag_sub_orig_mx = 0

        # ── 滚动 ──
        self._scroll_offset = 0

        # ── 项目基准分辨率 ──
        self._project_width: int = 0
        self._project_height: int = 0

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 留白区域（轨道绘制在 paintEvent 中）
        layout.addStretch(1)

        # 底部控件栏（滚动条）
        self._bottom_bar = QWidget()
        bottom = self._bottom_bar
        bottom.setStyleSheet("background: #16161a;")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(8, 2, 8, 2)
        bl.setSpacing(6)

        # 滑块控制缩放，Shift+滚轮快速缩放

        # 缩放滑块
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(4)
        zl = QLabel("缩放")
        zl.setStyleSheet("color: #666; font-size: 10px;")
        zoom_row.addWidget(zl)
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(1, 100)
        self._zoom_slider.setValue(int(self._pixels_per_sec))
        self._zoom_slider.setFixedWidth(80)
        self._zoom_slider.setFixedHeight(16)
        self._zoom_slider.setStyleSheet(
            "QSlider::groove:horizontal { background:#2a2a32; height:4px; border-radius:2px; } "
            "QSlider::handle:horizontal { background:#3a8cff; width:10px; height:10px; "
            "margin:-3px 0; border-radius:5px; } "
            "QSlider::sub-page:horizontal { background:#3a8cff; border-radius:2px; }"
        )
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        zoom_row.addWidget(self._zoom_slider)
        self._zoom_val = QLabel(f"{int(self._pixels_per_sec)}%")
        self._zoom_val.setStyleSheet("color: #666; font-size: 10px; min-width: 24px;")
        zoom_row.addWidget(self._zoom_val)
        bl.addLayout(zoom_row)

        # 滚动条
        self._scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self._scrollbar.setStyleSheet(
            "QScrollBar:horizontal { background: #1e1e22; height: 14px; } "
            "QScrollBar::handle:horizontal { background: #3a3a42; min-width: 30px; border-radius: 4px; margin: 2px 0; } "
            "QScrollBar::add-line, QScrollBar::sub-line { width: 0; }"
        )
        self._scrollbar.valueChanged.connect(self._on_scroll)
        bl.addWidget(self._scrollbar, 1)

        layout.addWidget(bottom)

    # ── 公共 API ──

    def set_clips(self, clips: list[TimelineClip]):
        self._clips = list(clips)
        self._selected = None
        self._update_duration()
        self._ensure_waveforms()
        self._sync_zoom_slider()
        self._update_scrollbar()
        self.update()

    def add_clip(self, clip: TimelineClip):
        self._clips.append(clip)
        if clip.end > self._duration:
            self._duration = clip.end
        self._check_and_set_resolution(clip)
        self._ensure_waveform_for(clip)
        self._sync_zoom_slider()
        self._update_scrollbar()
        self._push_undo({"type": "add", "data": {"clip": clip.snapshot(), "index": len(self._clips) - 1}})
        self.clips_changed.emit()
        self.update()

    def remove_clip(self, clip: TimelineClip):
        if clip in self._clips:
            idx = self._clips.index(clip)
            gid = clip.link_group
            self._clips.remove(clip)
            self._push_undo({"type": "delete", "data": {"clip": clip.snapshot(), "index": idx}})
            # 清理多选和锚点
            if clip in self._multi_selected:
                self._multi_selected.remove(clip)
            if self._range_anchor is clip:
                self._range_anchor = None
            if self._selected is clip:
                self._selected = None
                self.clip_selected.emit(None)
            # 清除同一链接组内其他素材的 link_group（删除配对素材后链接自动取消）
            if gid:
                for c in self._clips:
                    if c.link_group == gid:
                        c.link_group = ""
            # 不填补空档，素材保持在原位
            self._update_duration()
            self._sync_zoom_slider()
            self._update_scrollbar()
            self.clips_changed.emit()
            self.update()

    def remove_selected(self):
        if self._selected:
            self.remove_clip(self._selected)

    def _delete_multi_selected(self):
        """批量删除多选的素材"""
        saved = []
        removed_gids = set()
        for c in list(self._multi_selected):
            if not c.locked and c in self._clips:
                idx = self._clips.index(c)
                saved.append((c.snapshot(), idx))
                if c.link_group:
                    removed_gids.add(c.link_group)
                self._clips.remove(c)
        # 按 index 倒序压入撤销栈（保持恢复顺序一致）
        for clip_copy, idx in reversed(saved):
            self._push_undo({"type": "delete", "data": {"clip": clip_copy, "index": idx}})
        # 清除被删除素材留下的 link_group
        for gid in removed_gids:
            for c in self._clips:
                if c.link_group == gid:
                    c.link_group = ""
        self._multi_selected.clear()
        self._selected = None
        self._range_anchor = None
        self.clip_selected.emit(None)
        self._update_duration()
        self._sync_zoom_slider()
        self._update_scrollbar()
        self.clips_changed.emit()
        self.update()
        oplog.operation("批量删除素材")

    def _toggle_mute_clip(self, clip: TimelineClip):
        """切换素材静音状态"""
        clip.muted = not clip.muted
        self.update()
        oplog.operation(f"静音: {'开' if clip.muted else '关'} {clip.label}")

    def split_at_playhead(self):
        """在播放头位置分割选中的素材"""
        if not self._selected or self._selected.locked:
            return
        clip = self._selected
        split_pos = self._position
        if split_pos <= clip.start + 0.1 or split_pos >= clip.end - 0.1:
            return  # 太靠近边缘

        dur1 = split_pos - clip.start
        dur2 = clip.end - split_pos
        if dur1 < 0.1 or dur2 < 0.1:
            return

        old_duration = clip.duration

        # 为分割后的新素材生成顺序命名：03.mp4 → 03_01.mp4
        label2 = self._next_split_label(clip.label)

        clip2 = TimelineClip(
            source_path=clip.source_path,
            source_start=clip.source_start + (split_pos - clip.start) * clip.speed,
            start=split_pos,
            duration=dur2,
            source_duration=clip.source_duration,
            label=label2,
            speed=clip.speed,
            muted=clip.muted,
            track_type=clip.track_type,
            link_group=clip.link_group,
            display_scale=clip.display_scale,
            proxy_path=clip.proxy_path,
            target_width=clip.target_width,
            target_height=clip.target_height,
            effects=list(clip.effects),
            locked=clip.locked,
            position_fixed=clip.position_fixed,
        )
        clip.duration = dur1

        idx = self._clips.index(clip)
        self._clips.insert(idx + 1, clip2)
        self._push_undo({"type": "split", "data": {"clip": clip, "old_duration": old_duration, "clip2": clip2}})
        self._selected = clip
        self._update_duration()
        self._sync_zoom_slider()
        self._update_scrollbar()
        self.clips_changed.emit()
        self.update()
        oplog.operation("分割素材")

    def _next_split_label(self, current_label: str) -> str:
        """生成分割素材的顺序编号，如 03.mp4 → 03_01.mp4, 03_01.mp4 → 03_02.mp4"""
        import re

        if "." in current_label:
            base, ext = current_label.rsplit(".", 1)
            ext = "." + ext
        else:
            base = current_label
            ext = ""
        # 去掉已有的 _NN 后缀，得到纯 basename
        pure_base = re.sub(r"_\d+$", "", base)
        # 扫描已有 clips 找最大序号
        max_n = 0
        pattern = re.compile(rf"^{re.escape(pure_base)}_(\d+){re.escape(ext)}$")
        for c in self._clips:
            m = pattern.match(c.label)
            if m:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
        return f"{pure_base}_{max_n + 1:02d}{ext}"

    def select_clip_at(self, pos_sec: float) -> Optional[TimelineClip]:
        """选中在指定时间点的 clip"""
        for c in self._clips:
            if c.start <= pos_sec <= c.end:
                self._selected = c
                self.clip_selected.emit(c)
                self.update()
                return c
        self._selected = None
        self.clip_selected.emit(None)
        self.update()
        return None

    # ── 缩放 / 滚动 ──

    _ZOOM_MAX_PPS = 200.0

    def _get_min_pps(self) -> float:
        """计算能让所有内容（素材+字幕）完整显示的最小 pps"""
        if not self._clips and not self._subtitle_entries:
            return 2.0
        view_w = max(self.width(), 100)
        clip_end = max((c.start + c.duration * c.display_scale for c in self._clips), default=0.0)
        sub_end = max((e.end for e in self._subtitle_entries), default=0.0)
        total_visual_dur = max(clip_end, sub_end)
        if total_visual_dur <= 0:
            return 2.0
        return max(0.5, view_w / total_visual_dur * 0.95)

    def _zoom_val_to_pps(self, val: int) -> float:
        """滑块值 1-100 → pps，最小值=适配全部素材"""
        min_pps = self._get_min_pps()
        ratio = max(0.0, min(1.0, (val - 1) / 99.0))
        return min_pps + ratio * (self._ZOOM_MAX_PPS - min_pps)

    def _pps_to_zoom_val(self, pps: float) -> int:
        """pps → 滑块值 1-100"""
        min_pps = self._get_min_pps()
        if self._ZOOM_MAX_PPS <= min_pps:
            return 50
        ratio = (pps - min_pps) / (self._ZOOM_MAX_PPS - min_pps)
        return max(1, min(100, int(ratio * 100 + 0.5)))

    def set_zoom(self, px_per_sec: float):
        min_pps = self._get_min_pps()
        self._pixels_per_sec = max(min_pps, min(px_per_sec, self._ZOOM_MAX_PPS))
        self._scroll_offset = 0
        self._scrollbar.setValue(0)
        self._sync_zoom_slider()
        self._update_scrollbar()
        self.update()

    def _on_zoom_slider(self, val: int):
        """缩放滑块回调 — 最小值=全部素材可见，最大值=最大缩放"""
        self._pixels_per_sec = self._zoom_val_to_pps(val)
        pct = int(self._pixels_per_sec / 2)
        self._zoom_val.setText(f"{pct}%")
        self._scroll_offset = 0
        self._scrollbar.setValue(0)
        self._update_scrollbar()
        self.update()

    def _sync_zoom_slider(self):
        """同步滑块位置到当前缩放值"""
        val = self._pps_to_zoom_val(self._pixels_per_sec)
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(val)
        self._zoom_slider.blockSignals(False)
        pct = int(self._pixels_per_sec / 2)
        self._zoom_val.setText(f"{pct}%")

    def set_position(self, sec: float):
        self._position = max(0.0, min(sec, self._duration))
        self._ensure_playhead_visible()
        self.update()

    def set_duration(self, sec: float):
        self._duration = max(sec, 30.0)
        self._update_scrollbar()
        self.update()

    @property
    def clips(self):
        return list(self._clips)

    @property
    def selected_clip(self):
        return self._selected

    @property
    def position(self):
        return self._position

    @property
    def pixels_per_sec(self):
        return self._pixels_per_sec

    def zoom_in(self):
        self.set_zoom(self._pixels_per_sec * 1.3)

    def zoom_out(self):
        self.set_zoom(self._pixels_per_sec / 1.3)

    def _zoom_to_fit(self):
        """自适应缩放：让所有内容（素材+字幕）完整显示在可视区内"""
        if not self._clips and not self._subtitle_entries:
            return
        view_w = max(self.width(), 200)
        clip_end = max((c.start + c.duration * c.display_scale for c in self._clips), default=0.0)
        sub_end = max((e.end for e in self._subtitle_entries), default=0.0)
        total_visual_dur = max(clip_end, sub_end)
        if total_visual_dur <= 0:
            return
        px = max(0.5, min(view_w / total_visual_dur, self._ZOOM_MAX_PPS))
        self._pixels_per_sec = px
        self._scroll_offset = 0
        self._scrollbar.setValue(0)
        self._update_scrollbar()
        self._sync_zoom_slider()
        self.update()

    # ── 字幕 ──

    def load_subtitles(self, srt_path: str):
        """加载 SRT 文件到时间线"""
        try:
            with open(srt_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return
        self._subtitle_entries = _parse_srt(text)
        if not self._subtitle_entries:
            return
        # 更新时间线总长
        last_end = max(e.end for e in self._subtitle_entries)
        if last_end > self._duration:
            self._duration = last_end + 10
        self._update_scrollbar()
        self.update()
        oplog.operation("加载字幕", srt_path)

    def clear_subtitles(self):
        self._subtitle_entries.clear()
        self._set_selected_subtitle(None)
        self._multi_selected_subs.clear()
        self.update()
        # 通知父窗口清除预览字幕
        try:
            pw = self.parent()
            while pw:
                if hasattr(pw, "_preview_widget"):
                    pw._preview_widget.set_subtitle("")
                    break
                pw = pw.parent()
        except Exception:
            pass

    def set_subtitle_font_size(self, size: int):
        self._subtitle_font_size = max(8, min(size, 72))
        self.update()

    # ── 其他属性 ──

    @property
    def is_empty(self) -> bool:
        return len(self._clips) == 0

    def clear_all(self):
        self._clips.clear()
        self._selected = None
        self._multi_selected.clear()
        self._range_anchor = None
        self._project_width = 0
        self._project_height = 0
        self.clip_selected.emit(None)
        self._sync_zoom_slider()
        self.clips_changed.emit()
        self.update()

    def set_snap(self, enabled: bool):
        self._snap_enabled = enabled

    def load_video(self, path: str, duration: float):
        """加载视频到时间线（兼容旧 API）"""
        self.clear_all()
        if path and duration > 0:
            clip = TimelineClip(source_path=path, start=0, duration=duration, label=os.path.basename(path))
            self._clips.append(clip)
            self._check_and_set_resolution(clip)
            self._duration = max(duration + 10, 30)
            self._sync_zoom_slider()
            self._update_scrollbar()
            self.update()

    def add_audio_clip(self, path: str, label: str = "", duration: float = 0):
        """添加音频 clip（兼容旧 API）"""
        dur = duration if duration > 0 else _probe_duration(path)
        clip = TimelineClip(source_path=path, start=0, duration=dur or 10, label=label or os.path.basename(path))
        self._clips.append(clip)
        self._check_and_set_resolution(clip)
        if clip.end > self._duration:
            self._duration = clip.end + 10
        self._sync_zoom_slider()
        self._update_scrollbar()
        self.clips_changed.emit()
        self.update()

    def add_bgm_clip(self, path: str, label: str = "", duration: float = 0):
        """添加 BGM clip（兼容旧 API）"""
        self.add_audio_clip(path, label, duration)

    def append_clip(self, path: str, label: str = ""):
        """在时间线尾部追加素材"""
        dur = _probe_duration(path)
        start = max((c.end for c in self._clips), default=0.0)
        clip = TimelineClip(
            source_path=path,
            start=start,
            duration=dur or 10,
            source_duration=dur,
            label=label or os.path.basename(path),
        )
        self._clips.append(clip)
        if clip.end > self._duration:
            self._duration = clip.end + 10
        self._check_and_set_resolution(clip)
        self._ensure_waveform_for(clip)
        self._sync_zoom_slider()
        self._update_scrollbar()
        self.clips_changed.emit()
        self.update()

    def get_video_ranges(self) -> list:
        """返回有效视频播放范围（兼容旧 API）"""
        return [(c.start, c.end) for c in self._clips if c.source_path]

    # ── 轨道兼容 ──

    class _TrackShim:
        """兼容旧 API 的轨道对象"""

        def __init__(self, clips_ref):
            self._clips = clips_ref

        def update(self):
            pass

        def add_clip(self, clip):
            self._clips.append(clip)

        def set_clips(self, clips):
            self._clips.clear()
            self._clips.extend(clips)

        def clear_selection(self):
            pass

        @property
        def track_volume(self):
            return 1.0

        @track_volume.setter
        def track_volume(self, v):
            pass

        @property
        def track_muted(self):
            return False

        @track_muted.setter
        def track_muted(self, v):
            pass

    @property
    def video_track(self):
        return self._TrackShim(self._clips)

    @property
    def audio_track(self):
        return self._TrackShim(self._clips)

    @property
    def bgm_track(self):
        return self._TrackShim([])

    @property
    def subtitle_track(self):
        return self._TrackShim([])

    # ── 波形 ──

    def _ensure_waveforms(self):
        for c in self._clips:
            self._ensure_waveform_for(c)

    def _ensure_waveform_for(self, clip: TimelineClip):
        if (
            not clip.source_path
            or clip.source_path in self._waveform_cache
            or clip.source_path in self._waveform_pending
        ):
            return
        self._waveform_pending.add(clip.source_path)
        num = max(200, min(5000, int(clip.duration * self._pixels_per_sec / 2)))
        w = WaveformWorker(clip.source_path, num)
        w.waveform_ready.connect(self._on_waveform_ready)
        # 保留引用防止 GC
        self._waveform_workers.append(w)
        w.finished.connect(lambda: self._waveform_workers.remove(w) if w in self._waveform_workers else None)
        w.start()

    def _on_waveform_ready(self, source_path, peaks):
        self._waveform_pending.discard(source_path)
        self._waveform_cache[source_path] = peaks or []
        self.update()

    def _get_thumb_positions(self, clip: TimelineClip) -> list[float]:
        """返回素材内应抽取缩略图的源时间位置列表"""
        cw = int(clip.duration * self._pixels_per_sec * clip.display_scale)
        n = max(1, min(8, cw // 80))
        if n == 1:
            return [clip.source_start]
        step = clip.duration / (n - 1)
        return [clip.source_start + i * step for i in range(n)]

    def _ensure_thumbnail_for(self, clip: TimelineClip):
        """为视频轨素材提取缩略图（仅选中素材，多帧平铺）"""
        if not clip.source_path or getattr(clip, "track_type", "") != "video":
            return
        positions = self._get_thumb_positions(clip)
        for pos in positions:
            key = (clip.source_path, pos)
            if key in self._thumbnail_cache or key in self._thumbnail_pending:
                continue
            self._thumbnail_pending.add(key)
            w = ThumbnailWorker(clip.source_path, pos)
            w.thumbnail_ready.connect(self._on_thumbnail_ready)
            self._waveform_workers.append(w)
            w.finished.connect(lambda _w=w: self._waveform_workers.remove(_w) if _w in self._waveform_workers else None)
            w.start()

    def _on_thumbnail_ready(self, source_path, position, img):
        key = (source_path, position)
        self._thumbnail_pending.discard(key)
        if img is not None:
            self._thumbnail_cache[key] = img
        self.update()

    # ── 坐标转换 ──

    def _sec_to_x(self, sec: float) -> int:
        return int(sec * self._pixels_per_sec - self._scroll_offset)

    def _x_to_sec(self, x: int) -> float:
        return (x + self._scroll_offset) / self._pixels_per_sec

    def _clip_at_pos(self, x: int, track: str = "") -> Optional[TimelineClip]:
        """track: ''=任意, 'video', 'audio'"""
        so = self._scroll_offset
        for c, vx, vw in self._get_visual_layout():
            cx = vx - so
            if cx <= x <= cx + vw:
                if not track:
                    return c
                ct = getattr(c, "track_type", "") or "audio"
                if ct == track:
                    return c
        return None

    def _clip_edge_at(self, x: int, track: str = "") -> tuple[Optional[TimelineClip], Optional[str]]:
        threshold = 8
        so = self._scroll_offset
        for c in self._clips:
            if track:
                ct = getattr(c, "track_type", "") or "audio"
                if ct != track:
                    continue
            lx = self._sec_to_x(c.start)
            # 实际宽度 = 原始 * display_scale，所以右边缘也需要调整
            cw = int(c.duration * self._pixels_per_sec * c.display_scale)
            rx = lx + cw
            if abs(x - lx) <= threshold:
                return c, "left"
            if abs(x - rx) <= threshold:
                return c, "right"
        return None, None

    def _probe_resolution(self, path: str) -> tuple[int, int]:
        """探测视频文件分辨率，返回 (width, height)"""
        try:
            info = pvt_bridge.probe(path)
            return info.get("width", 0), info.get("height", 0)
        except Exception:
            return 0, 0

    def _check_and_set_resolution(self, clip: TimelineClip):
        """检测素材分辨率，首个素材设为基准，后续不匹配则标记转换"""
        if not clip.source_path:
            return
        w, h = self._probe_resolution(clip.source_path)
        if w <= 0 or h <= 0:
            return
        # 首个视频素材设为项目基准分辨率
        if self._project_width == 0 and self._project_height == 0:
            self._project_width = w
            self._project_height = h
            return
        # 后续素材比对基准
        if w != self._project_width or h != self._project_height:
            clip.target_width = self._project_width
            clip.target_height = self._project_height
            self.resolution_mismatch.emit(clip, self._project_width, self._project_height)

    def _update_duration(self):
        clip_end = max((c.end for c in self._clips), default=0.0)
        sub_end = max((e.end for e in self._subtitle_entries), default=0.0)
        max_end = max(clip_end, sub_end)
        self._duration = max(max_end + 10.0, 30.0)

    def _visual_total_width(self) -> int:
        """计算所有内容（含 display_scale）的视觉总宽度（像素）"""
        clip_end = max((c.start + c.duration * c.display_scale for c in self._clips), default=0.0)
        sub_end = max((e.end for e in self._subtitle_entries), default=0.0)
        visual_dur = max(clip_end, sub_end, self._duration)
        return int(visual_dur * self._pixels_per_sec)

    def _update_scrollbar(self):
        total_w = self._visual_total_width()
        view_w = max(self.width(), 1)
        self._scrollbar.setRange(0, max(total_w, 1))
        self._scrollbar.setPageStep(view_w)
        self._scrollbar.setSingleStep(int(self._pixels_per_sec))

    def _ensure_playhead_visible(self):
        px = self._sec_to_x(self._position)
        view_w = self.width()
        if px < 50:
            self._scrollbar.setValue(max(0, self._scrollbar.value() - int(view_w * 0.3)))
        elif px > view_w - 50:
            self._scrollbar.setValue(min(self._scrollbar.maximum(), self._scrollbar.value() + int(view_w * 0.3)))

    def _adjust_scroll_to_drag(self, x: int):
        """拖拽时自动滚动视图边缘"""
        margin = 40
        step = int(self._pixels_per_sec * 2)
        if x < margin:
            self._scrollbar.setValue(max(0, self._scrollbar.value() - step))
        elif x > self.width() - margin:
            self._scrollbar.setValue(min(self._scrollbar.maximum(), self._scrollbar.value() + step))

    def _on_scroll(self, val: int):
        view_w = max(self.width(), 1)
        total_w = self._visual_total_width()
        self._scroll_offset = min(val, max(0, total_w - view_w))
        self.update()

    # ── 吸附 ──

    def _snap_sec(self, sec: float, dragging_clip: TimelineClip = None) -> float:
        """将时间吸附到最近的吸附点，返回吸附后的值"""
        if not self._snap_enabled:
            return sec
        threshold = 6.0 / self._pixels_per_sec
        best = sec
        best_dist = threshold

        # 吸附到播放头
        d = abs(sec - self._position)
        if d < best_dist:
            best_dist = d
            best = self._position

        # 吸附到 clip 边缘
        for c in self._clips:
            if c is dragging_clip:
                continue
            for pt in (c.start, c.end):
                d = abs(sec - pt)
                if d < best_dist:
                    best_dist = d
                    best = pt
        # 吸附到字幕边缘
        for e in self._subtitle_entries:
            for pt in (e.start, e.end):
                d = abs(sec - pt)
                if d < best_dist:
                    best_dist = d
                    best = pt
        return best

    def _snap_end(self, sec: float, dragging_clip: TimelineClip = None) -> float:
        """将结束时间吸附"""
        if not self._snap_enabled:
            return sec
        threshold = 6.0 / self._pixels_per_sec
        best = sec
        best_dist = threshold
        for c in self._clips:
            if c is dragging_clip:
                continue
            for pt in (c.start, c.end):
                d = abs(sec - pt)
                if d < best_dist:
                    best_dist = d
                    best = pt
        return best

    # ── 撤销/重做 ──

    def _push_undo(self, record: dict):
        """压入撤销栈（上限 200），有新操作时清空重做栈"""
        self._undo_stack.append(record)
        if len(self._undo_stack) > self._undo_max:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self):
        """执行撤销"""
        if not self._undo_stack:
            return
        record = self._undo_stack.pop()
        self._redo_stack.append(copy.deepcopy(record))
        if len(self._redo_stack) > self._undo_max:
            self._redo_stack.pop(0)

        t = record["type"]
        data = record["data"]

        if t == "add":
            # 取消添加：按 index 移除
            target = data["clip"]
            idx = data.get("index", 0)
            if idx < len(self._clips) and self._clips[idx] is target:
                self._clips.pop(idx)
            elif target in self._clips:
                self._clips.remove(target)
            if self._selected is target:
                self._selected = None
                self.clip_selected.emit(None)
            self._update_duration()
            self._sync_zoom_slider()
            self._update_scrollbar()
            self.clips_changed.emit()
            self.update()

        elif t == "delete":
            # 恢复被删除的 clip
            clip = data["clip"]
            idx = data["index"]
            self._clips.insert(min(idx, len(self._clips)), clip)
            self._selected = None
            self.clip_selected.emit(None)
            self._update_duration()
            self._sync_zoom_slider()
            self._update_scrollbar()
            self.clips_changed.emit()
            self.update()

        elif t == "split":
            # 恢复分割：移除 clip2，恢复 clip 时长
            clip = data["clip"]
            old_dur = data["old_duration"]
            clip2 = data.get("clip2")
            if clip2 and clip2 in self._clips:
                self._clips.remove(clip2)
            clip.duration = old_dur
            self._selected = None
            self._update_duration()
            self._sync_zoom_slider()
            self._update_scrollbar()
            self.clips_changed.emit()
            self.update()

        elif t == "move":
            data["clip"].start = data["old_start"]
            self._ensure_clip_visible(data["clip"])
            self.clips_changed.emit()
            self.update()

        elif t == "trim":
            clip = data["clip"]
            clip.start = data["old_start"]
            clip.duration = data["old_duration"]
            clip.source_start = data.get("old_source_start", 0.0)
            self._ensure_clip_visible(clip)
            self.clips_changed.emit()
            self.update()

        elif t == "subtitle_split":
            # 恢复分割前的完整素材列表
            current_snapshots = [c.snapshot() for c in self._clips]
            self._clips = data["original_clips"]
            # 将当前状态压入重做栈
            self._redo_stack.append(
                {
                    "type": "subtitle_split",
                    "data": {"original_clips": current_snapshots, "subtitle_count": data.get("subtitle_count", 0)},
                }
            )
            self._selected = None
            self.clip_selected.emit(None)
            self._update_duration()
            self._sync_zoom_slider()
            self._update_scrollbar()
            self.clips_changed.emit()
            self.update()

    def redo(self):
        """执行重做"""
        if not self._redo_stack:
            return
        record = self._redo_stack.pop()
        self._undo_stack.append(copy.deepcopy(record))

        t = record["type"]
        data = record["data"]

        if t == "add":
            # 重新添加 clip
            clip = data["clip"]
            idx = data.get("index", 0)
            if clip not in self._clips:
                self._clips.insert(min(idx, len(self._clips)), clip)
                self._update_duration()
                self._sync_zoom_slider()
                self._update_scrollbar()
                self.clips_changed.emit()
                self.update()

        elif t == "delete":
            # 重新删除
            clip = data["clip"]
            if clip in self._clips:
                self._clips.remove(clip)
                if self._selected is clip:
                    self._selected = None
                    self.clip_selected.emit(None)
                self._update_duration()
                self._sync_zoom_slider()
                self._update_scrollbar()
                self.clips_changed.emit()
                self.update()

        elif t == "split":
            # 重新分割：找到 clip 并缩短，插入 clip2
            clip = data["clip"]
            clip2 = data.get("clip2")
            if clip2 and clip2 not in self._clips and clip in self._clips:
                split_pos = clip2.start
                clip.duration = split_pos - clip.start
                self._clips.insert(self._clips.index(clip) + 1, clip2)
                self._update_duration()
                self._sync_zoom_slider()
                self._update_scrollbar()
                self.clips_changed.emit()
                self.update()

        elif t == "move":
            data["clip"].start = data["new_start"]
            self._ensure_clip_visible(data["clip"])
            self.clips_changed.emit()
            self.update()

        elif t == "trim":
            clip = data["clip"]
            new_start = clip.start
            new_dur = clip.duration
            new_source_start = clip.source_start
            clip.start = data["old_start"]
            clip.duration = data["old_duration"]
            clip.source_start = data.get("old_source_start", 0.0)
            record["data"] = {
                "clip": clip,
                "old_start": new_start,
                "old_duration": new_dur,
                "old_source_start": new_source_start,
            }
            if self._undo_stack:
                self._undo_stack[-1] = record
            self._ensure_clip_visible(clip)
            self.clips_changed.emit()
            self.update()

        elif t == "subtitle_split":
            # 重新分割：应用之前保存的原始状态 → 当前状态
            current_snapshots = [c.snapshot() for c in self._clips]
            self._clips = data["original_clips"]
            data["original_clips"] = current_snapshots
            self._selected = None
            self.clip_selected.emit(None)
            self._update_duration()
            self._sync_zoom_slider()
            self._update_scrollbar()
            self.clips_changed.emit()
            self.update()

    def _ensure_clip_visible(self, clip: TimelineClip):
        """滚动时间线确保素材在可视区内"""
        clip_x = int(clip.start * self._pixels_per_sec)
        clip_end_x = int((clip.start + clip.duration * clip.display_scale) * self._pixels_per_sec)
        view_w = self.width()
        if clip_x < self._scroll_offset or clip_end_x > self._scroll_offset + view_w:
            target_offset = max(0, clip_x - view_w // 3)
            self._scrollbar.setValue(target_offset)

    # ── 视觉布局 ──

    def _get_visual_layout(self) -> list[tuple[TimelineClip, int, int]]:
        """返回 [(clip, visual_x, visual_width), ...]，按 start 排序，考虑 display_scale"""
        sorted_clips = sorted(self._clips, key=lambda c: c.start)
        result = []
        for c in sorted_clips:
            vx = int(c.start * self._pixels_per_sec)
            vw = int(c.duration * self._pixels_per_sec * c.display_scale)
            result.append((c, vx, vw))
        return result

    # ══════════════════════════════════════════════════════════
    # 事件处理
    # ══════════════════════════════════════════════════════════

    def _get_track_h(self) -> int:
        """返回可用轨道总高度"""
        track_h = (
            self._bottom_bar.y() if self._bottom_bar.isVisible() and self._bottom_bar.y() > 0 else self.height() - 28
        )
        if track_h <= 0:
            track_h = max(100, self.height() - 28)
        return track_h

    def _get_track_heights(self) -> tuple[int, int, int]:
        """返回 (sub_h, video_h, audio_h) — 20% / 40% / 40%"""
        track_h = self._get_track_h()
        has_sub = bool(self._subtitle_entries)
        has_video = any(getattr(c, "track_type", "") == "video" for c in self._clips)
        sub_h = max(20, int(track_h * 0.20)) if has_sub else 0
        video_h = max(36, int(track_h * 0.40)) if has_video else 0
        audio_h = max(40, track_h - sub_h - video_h)
        return sub_h, video_h, audio_h

    def _is_in_subtitle_zone(self, y: int) -> bool:
        """判断 y 坐标是否在字幕轨区域内"""
        if not self._subtitle_entries:
            return False
        sub_h, _, _ = self._get_track_heights()
        return y < sub_h

    def _get_track_for_y(self, y: int) -> str:
        """根据 y 坐标返回所在轨道: 'subtitle' | 'video' | 'audio' | ''"""
        sub_h, video_h, _ = self._get_track_heights()
        if self._subtitle_entries and y < sub_h:
            return "subtitle"
        video_y = sub_h + 2
        has_video = any(getattr(c, "track_type", "") == "video" for c in self._clips)
        if has_video and video_y <= y < video_y + video_h:
            return "video"
        return "audio"

    def mousePressEvent(self, event):
        x = int(event.position().x())
        y = int(event.position().y())

        # 底部控件栏区域（滚动条、缩放滑块）不拦截，让子控件处理
        track_h = self._get_track_h()
        if y >= track_h:
            super().mousePressEvent(event)
            return

        self.setFocus()

        track = self._get_track_for_y(y)
        clip = self._clip_at_pos(x, track if track in ("video", "audio") else "")
        mods = event.modifiers()
        in_sub_zone = track == "subtitle"
        sec = max(0.0, self._x_to_sec(x))

        if event.button() == Qt.MouseButton.LeftButton:
            # ── 字幕区域优先 ──
            if in_sub_zone:
                hit = self._subtitle_at_sec(sec)
                if hit:
                    # ── Alt+Click: 全选所有字幕 ──
                    if mods & Qt.KeyboardModifier.AltModifier:
                        self._multi_selected_subs = set(self._subtitle_entries)
                        self._set_selected_subtitle(hit[1])
                        self._selected = None
                        self._multi_selected.clear()
                        self.clip_selected.emit(None)
                        self._drag_sub = False
                        self._dragging = False
                        self.update()
                        return

                    # ── Shift+Click: 连续区间选择 ──
                    if mods & Qt.KeyboardModifier.ShiftModifier:
                        anchor = self._selected_subtitle
                        if anchor is None or anchor not in self._subtitle_entries:
                            anchor = hit[1]
                        try:
                            idx_a = self._subtitle_entries.index(anchor)
                            idx_b = hit[0]  # hit[0] 是 index
                        except ValueError:
                            idx_a = idx_b = 0
                        start_idx, end_idx = min(idx_a, idx_b), max(idx_a, idx_b)
                        self._multi_selected_subs = set(self._subtitle_entries[start_idx : end_idx + 1])
                        self._set_selected_subtitle(hit[1])
                        self._selected = None
                        self._multi_selected.clear()
                        self.clip_selected.emit(None)
                        self._drag_sub = False
                        self._dragging = False
                        self.update()
                        return

                    # ── Ctrl+Click: 切换单个字幕选中状态 ──
                    if mods & Qt.KeyboardModifier.ControlModifier:
                        if hit[1] in self._multi_selected_subs:
                            self._multi_selected_subs.discard(hit[1])
                        else:
                            self._multi_selected_subs.add(hit[1])
                        if self._multi_selected_subs:
                            self._set_selected_subtitle(hit[1])
                        self._selected = None
                        self._multi_selected.clear()
                        self.clip_selected.emit(None)
                        self._drag_sub = False
                        self._dragging = False
                        self.update()
                        return

                    # ── 普通点击: 单选 + 可拖拽 ──
                    self._set_selected_subtitle(hit[1])
                    self._multi_selected_subs.clear()
                    self._selected = None
                    self._multi_selected.clear()
                    self.clip_selected.emit(None)
                    self._drag_sub = True
                    self._drag_sub_orig_start = hit[1].start
                    self._drag_sub_orig_end = hit[1].end
                    self._drag_sub_orig_mx = x
                    self.update()
                    return

                # ── 点击字幕轨空白区域: 清空所有选中 ──
                self._set_selected_subtitle(None)
                self._multi_selected_subs.clear()
                self._selected = None
                self._multi_selected.clear()
                self.clip_selected.emit(None)
                self._dragging = False
                self.update()
                return

            # ── 素材区域 ──
            trim_c, trim_edge = self._clip_edge_at(x, track if track in ("video", "audio") else "")
            if trim_c and trim_edge and not trim_c.locked:
                self._multi_selected = [trim_c]
                self._selected = trim_c
                self._set_selected_subtitle(None)
                self.clip_selected.emit(trim_c)
                self._trimming = trim_edge
                self._trim_clip = trim_c
                self._trim_orig_start = trim_c.start
                self._trim_orig_dur = trim_c.duration
                self._trim_orig_source_start = trim_c.source_start
                self._trim_orig_x = x
                self._ensure_clip_visible(trim_c)
                self.update()
                return

            if clip:
                self._set_selected_subtitle(None)
                if clip.locked:
                    self.update()
                    return
                if clip.position_fixed:
                    self._multi_selected = [clip]
                    self._selected = clip
                    self._range_anchor = clip
                    self.clip_selected.emit(clip)
                    self._ensure_clip_visible(clip)
                    self.update()
                    return

                # ── Ctrl+Click: 切换单个素材多选状态 ──
                if mods & Qt.KeyboardModifier.ControlModifier:
                    if clip in self._multi_selected:
                        self._multi_selected.remove(clip)
                    else:
                        self._multi_selected.append(clip)
                    self._range_anchor = clip
                    self._dragging = False
                    self.update()
                    return

                # ── Shift+Click: 范围选择（锚点 → 点击素材） ──
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    if self._range_anchor is None or self._range_anchor not in self._clips:
                        self._range_anchor = clip
                    sorted_clips = sorted(self._clips, key=lambda c: c.start)
                    try:
                        idx_a = sorted_clips.index(self._range_anchor)
                        idx_b = sorted_clips.index(clip)
                    except ValueError:
                        idx_a = idx_b = 0
                    start_idx, end_idx = min(idx_a, idx_b), max(idx_a, idx_b)
                    self._multi_selected = sorted_clips[start_idx : end_idx + 1]
                    self._selected = clip
                    self.clip_selected.emit(clip)
                    self._ensure_clip_visible(clip)
                    self._dragging = False
                    self.update()
                    return

                # ── 普通点击: 单选 + 可拖拽 ──
                self._multi_selected = [clip]
                self._selected = clip
                self._range_anchor = clip
                self.clip_selected.emit(clip)
                self._ensure_clip_visible(clip)
                self._dragging = True
                self._drag_start_x = x
                self._drag_orig_start = clip.start
                self.update()
            else:
                self._multi_selected.clear()
                self._selected = None
                self._set_selected_subtitle(None)
                self._range_anchor = None
                self.clip_selected.emit(None)
                self._dragging = False
                self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            if in_sub_zone:
                sub_hit = self._subtitle_at_sec(sec)
                if sub_hit:
                    self._set_selected_subtitle(sub_hit[1])
                    self._show_subtitle_context_menu(sub_hit[1], sub_hit[0], event.globalPosition().toPoint())
                    self.update()
                    return
            if clip:
                self._selected = clip
                self.clip_selected.emit(clip)
                self._show_context_menu(clip, event.globalPosition().toPoint())
                self.update()

    def mouseMoveEvent(self, event):
        x = int(event.position().x())
        y = int(event.position().y())
        buttons = event.buttons()

        # ── 悬停状态 ──
        if not buttons:
            track = self._get_track_for_y(y)
            trim_c, trim_edge = self._clip_edge_at(x, track if track in ("video", "audio") else "")
            self.setCursor(Qt.CursorShape.SizeHorCursor if trim_edge else Qt.CursorShape.ArrowCursor)
            return

        # ── 边缘裁剪 ──
        if buttons & Qt.MouseButton.LeftButton and self._trimming and self._trim_clip:
            dx = x - self._trim_orig_x
            delta = dx / self._pixels_per_sec
            min_dur = 0.1

            if self._trimming == "left":
                new_start = max(0.0, self._trim_orig_start + delta)
                new_start = min(new_start, self._trim_orig_start + self._trim_orig_dur - min_dur)
                new_start = self._snap_sec(new_start, self._trim_clip)
                new_start = min(new_start, self._trim_orig_start + self._trim_orig_dur - min_dur)
                orig_end = self._trim_orig_start + self._trim_orig_dur
                self._trim_clip.source_start = max(
                    0.0, self._trim_orig_source_start + (new_start - self._trim_orig_start) * self._trim_clip.speed
                )
                self._trim_clip.start = new_start
                self._trim_clip.duration = max(min_dur, orig_end - new_start)
            else:  # right
                new_end = self._trim_orig_start + self._trim_orig_dur + delta
                new_end = self._snap_end(new_end, self._trim_clip)
                new_end = max(self._trim_orig_start + min_dur, new_end)
                self._trim_clip.duration = max(min_dur, new_end - self._trim_orig_start)

            self.clip_changed.emit(self._trim_clip)
            self._adjust_scroll_to_drag(x)
            self.update()
            return

        # ── 拖拽移动 ──
        if self._dragging and self._selected and buttons & Qt.MouseButton.LeftButton:
            dx = x - self._drag_start_x
            delta = dx / self._pixels_per_sec
            new_start = max(0.0, self._drag_orig_start + delta)
            new_start = self._snap_sec(new_start, self._selected)
            # 尾部吸附：拖拽素材的 end 吸附到后续素材的 start
            end_threshold = 6.0 / self._pixels_per_sec
            end_pos = new_start + self._selected.duration
            for c in self._clips:
                if c is self._selected:
                    continue
                if abs(end_pos - c.start) < end_threshold:
                    new_start = c.start - self._selected.duration
                    break
            shift = new_start - self._selected.start
            self._selected.start = new_start
            if self._selected.link_group:
                for c in self._clips:
                    if c is not self._selected and c.link_group == self._selected.link_group:
                        c.start = max(0.0, c.start + shift)
            self.clip_changed.emit(self._selected)
            self._adjust_scroll_to_drag(x)
            self.update()
            return

        # ── 拖拽字幕（带吸附） ──
        if self._drag_sub and self._selected_subtitle and buttons & Qt.MouseButton.LeftButton:
            dx = x - self._drag_sub_orig_mx
            delta = dx / self._pixels_per_sec
            dur = self._selected_subtitle.duration
            new_start = max(0.0, self._drag_sub_orig_start + delta)
            new_start = self._snap_sec(new_start)
            self._selected_subtitle.start = new_start
            self._selected_subtitle.end = new_start + dur
            self.update()
            return

        # 鼠标拖动不再影响播放指针

    def mouseReleaseEvent(self, event):
        # 裁剪完成
        if self._trimming and self._trim_clip:
            c = self._trim_clip
            self._push_undo(
                {
                    "type": "trim",
                    "data": {
                        "clip": c,
                        "old_start": self._trim_orig_start,
                        "old_duration": self._trim_orig_dur,
                        "old_source_start": self._trim_orig_source_start,
                    },
                }
            )
            self._trimming = None
            self._trim_clip = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.clips_changed.emit()
            return

        # 字幕拖拽完成
        if self._drag_sub and self._selected_subtitle:
            self._drag_sub = False
            self.update()
            return

        # 拖拽完成
        if self._dragging and self._selected:
            if abs(self._selected.start - self._drag_orig_start) > 0.05:
                new_start = self._selected.start
                self._selected.start = self._drag_orig_start  # 临时回退以便记录旧值
                self._push_undo(
                    {
                        "type": "move",
                        "data": {"clip": self._selected, "old_start": self._drag_orig_start, "new_start": new_start},
                    }
                )
                self._selected.start = new_start
                self.clips_changed.emit()
        self._dragging = False

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            x = int(event.position().x())
            y = int(event.position().y())
            sec = max(0.0, self._x_to_sec(x))
            track = self._get_track_for_y(y)
            if track != "subtitle":
                clip = self._clip_at_pos(x, track if track in ("video", "audio") else "")
                if clip:
                    self.clip_double_clicked.emit(clip)
                    return
            if self._subtitle_entries:
                hit = self._subtitle_at_sec(sec)
                if hit:
                    self._set_selected_subtitle(hit[1])
                    self.subtitle_edit_requested.emit(hit[1], hit[0])
                    return
            self.update()

    def wheelEvent(self, event):
        """Shift+滚轮：缩放时间线"""
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self._selected_subtitle:
                if self._multi_selected_subs:
                    self._delete_multi_selected_subs()
                else:
                    self._delete_subtitle(self._selected_subtitle)
                return
            # 多选时批量删除
            if len(self._multi_selected) > 1:
                self._delete_multi_selected()
                return
            if self._selected and not self._selected.locked:
                self.remove_selected()
        elif event.key() == Qt.Key_S and not event.modifiers():
            self.split_at_playhead()
        elif event.key() in (Qt.Key_Equal, Qt.Key_Plus):
            self.zoom_in()
        elif event.key() == Qt.Key_Minus:
            self.zoom_out()
        elif event.key() == Qt.Key_Home:
            self._zoom_to_fit()
        elif event.key() == Qt.Key_Right:
            w = self.window()
            if hasattr(w, "_step_forward"):
                w._step_forward()
        elif event.key() == Qt.Key_Left:
            w = self.window()
            if hasattr(w, "_step_backward"):
                w._step_backward()
        else:
            super().keyPressEvent(event)

    # ── 右键菜单 ──

    def _show_subtitle_context_menu(self, entry, idx, global_pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #222226; color: #d0d0d0; border: 1px solid #3a3a42; padding: 4px; } "
            "QMenu::item { padding: 6px 24px; border-radius: 3px; } "
            "QMenu::item:selected { background: #3a8cff44; } "
            "QMenu::separator { height: 1px; background: #3a3a42; margin: 4px 8px; }"
        )
        act_edit = menu.addAction(f"编辑字幕 #{entry.index}")
        act_edit.triggered.connect(lambda: self.subtitle_edit_requested.emit(entry, idx))

        if self._multi_selected_subs and len(self._multi_selected_subs) > 1:
            act_del_multi = menu.addAction(f"删除 {len(self._multi_selected_subs)} 条选中字幕")
            act_del_multi.triggered.connect(self._delete_multi_selected_subs)
        act_del = menu.addAction("删除字幕")
        act_del.triggered.connect(lambda: self._delete_subtitle(entry))

        menu.addSeparator()
        if self._multi_selected_subs and len(self._multi_selected_subs) > 1:
            act_split = menu.addAction(f"按字幕切割 ({len(self._multi_selected_subs)} 条)")
            act_split.triggered.connect(lambda: self._split_clips_by_subtitles(list(self._multi_selected_subs)))
        else:
            act_split = menu.addAction("按字幕分割")
            act_split.triggered.connect(lambda: self._split_clips_by_subtitles([entry]))

        menu.addSeparator()
        if self._multi_selected_subs and len(self._multi_selected_subs) > 1:
            subs = list(self._multi_selected_subs)
            act_dub = menu.addAction(f"配音 ({len(subs)} 条字幕)")
            act_dub.triggered.connect(lambda: self.dub_requested.emit(subs))
            act_dub_local = menu.addAction(f"字幕配音 ({len(subs)} 条)")
            act_dub_local.triggered.connect(lambda: self.dub_local_requested.emit(subs))
        else:
            act_dub = menu.addAction("配音")
            act_dub.triggered.connect(lambda: self.dub_requested.emit([entry]))
            act_dub_local = menu.addAction("字幕配音")
            act_dub_local.triggered.connect(lambda: self.dub_local_requested.emit([entry]))
        menu.exec(global_pos)

    def _delete_subtitle(self, entry):
        if entry in self._subtitle_entries:
            self._subtitle_entries.remove(entry)
            self._multi_selected_subs.discard(entry)
            if self._selected_subtitle is entry:
                self._set_selected_subtitle(None)
            self.clips_changed.emit()
            self.update()
            oplog.operation("删除字幕")

    def _delete_multi_selected_subs(self):
        """批量删除多选字幕"""
        if not self._multi_selected_subs:
            return
        count = len(self._multi_selected_subs)
        for entry in list(self._multi_selected_subs):
            if entry in self._subtitle_entries:
                self._subtitle_entries.remove(entry)
        self._multi_selected_subs.clear()
        if self._selected_subtitle not in self._subtitle_entries:
            self._set_selected_subtitle(None)
        self.clips_changed.emit()
        self.update()
        oplog.operation(f"批量删除 {count} 条字幕")

    def _split_clips_by_subtitles(self, entries: list[SubtitleEntry]):
        """按字幕时间戳批量切割素材"""
        if not entries or not self._clips:
            return

        # 收集所有切割点（去重排序）
        split_points = sorted(set(p for e in entries for p in (e.start, e.end)))

        # 保存原始状态用于撤销
        original_snapshots = [c.snapshot() for c in self._clips]

        # 从右到左处理切割点，避免索引偏移
        for pt in reversed(split_points):
            for clip in list(self._clips):
                if clip.locked:
                    continue
                if not (clip.start + 0.05 < pt < clip.end - 0.05):
                    continue

                dur1 = pt - clip.start
                dur2 = clip.end - pt
                if dur1 < 0.05 or dur2 < 0.05:
                    continue

                label2 = self._next_split_label(clip.label)
                clip2 = TimelineClip(
                    source_path=clip.source_path,
                    source_start=clip.source_start + dur1 * clip.speed,
                    start=pt,
                    duration=dur2,
                    source_duration=clip.source_duration,
                    label=label2,
                    speed=clip.speed,
                    muted=clip.muted,
                    track_type=clip.track_type,
                    link_group=clip.link_group,
                    display_scale=clip.display_scale,
                    proxy_path=clip.proxy_path,
                    target_width=clip.target_width,
                    target_height=clip.target_height,
                    effects=list(clip.effects),
                    locked=clip.locked,
                    position_fixed=clip.position_fixed,
                )
                clip.duration = dur1
                idx = self._clips.index(clip)
                self._clips.insert(idx + 1, clip2)

        self._push_undo(
            {
                "type": "subtitle_split",
                "data": {
                    "original_clips": original_snapshots,
                    "subtitle_count": len(entries),
                },
            }
        )

        self._selected = None
        self.clip_selected.emit(None)
        self._update_duration()
        self._sync_zoom_slider()
        self._update_scrollbar()
        self.clips_changed.emit()
        self.update()
        oplog.operation(f"按字幕分割素材 ({len(entries)} 条字幕)")

    def _show_context_menu(self, clip: TimelineClip, global_pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #222226; color: #d0d0d0; border: 1px solid #3a3a42; padding: 4px; } "
            "QMenu::item { padding: 6px 24px; border-radius: 3px; } "
            "QMenu::item:selected { background: #3a8cff44; } "
            "QMenu::separator { height: 1px; background: #3a3a42; margin: 4px 8px; }"
        )

        if not clip.locked:
            act_split = menu.addAction("在此分割 (S)")
            act_split.triggered.connect(self.split_at_playhead)

            act_delete = menu.addAction("删除 (Delete)")
            if len(self._multi_selected) > 1:
                act_delete.triggered.connect(self._delete_multi_selected)
            else:
                act_delete.triggered.connect(lambda: self.remove_clip(clip))

            act_speed = menu.addAction("变速")
            act_speed.triggered.connect(lambda: self._cycle_speed(clip))

            act_mute = menu.addAction("取消静音" if clip.muted else "静音")
            act_mute.triggered.connect(lambda: self._toggle_mute_clip(clip))

            menu.addSeparator()
            # 分离音视频（仅普通素材）
            if not clip.track_type:
                act_separate = menu.addAction("分离音视频")
                act_separate.triggered.connect(lambda: self._separate_av(clip))
            # 合并音视频（已分离的素材）
            if clip.track_type and clip.link_group:
                act_merge_av = menu.addAction("合并音视频")
                act_merge_av.triggered.connect(lambda: self._merge_av(clip))

        menu.addSeparator()
        if not clip.locked and len(self._multi_selected) > 1:
            act_merge = menu.addAction("合并素材")
            act_merge.triggered.connect(self._merge_selected)
        if clip.merge_parts:
            act_unmerge = menu.addAction("取消合并")
            act_unmerge.triggered.connect(lambda: self._unmerge_clip(clip))
        if clip.link_group:
            act_unlink = menu.addAction("取消链接")
            act_unlink.triggered.connect(lambda: self._unlink_clip(clip))
        elif not clip.locked and len(self._multi_selected) > 1:
            act_link = menu.addAction("链接素材")
            act_link.triggered.connect(self._link_selected)

        menu.exec(global_pos)

    def _merge_selected(self):
        """合并选中的素材为一个（仅相邻素材）"""
        if len(self._multi_selected) < 2:
            return
        sorted_clips = sorted(self._multi_selected, key=lambda c: c.start)
        first = sorted_clips[0]
        last = sorted_clips[-1]
        first.duration = last.end - first.start
        first.merge_parts = [
            {"source_path": c.source_path, "source_start": c.source_start, "duration": c.duration} for c in sorted_clips
        ]
        for c in sorted_clips[1:]:
            self._clips.remove(c)
        self._multi_selected = [first]
        self._selected = first
        self._update_duration()
        self._sync_zoom_slider()
        self.clips_changed.emit()
        self.update()

    def _unmerge_clip(self, clip: TimelineClip):
        """取消合并 — 还原为合并前的各段"""
        if not clip.merge_parts:
            return
        idx = self._clips.index(clip)
        base = clip.start
        cumulative = base
        new_clips = []
        for part in clip.merge_parts:
            nc = TimelineClip(
                source_path=part["source_path"],
                source_start=part.get("source_start", 0.0),
                start=cumulative,
                duration=part["duration"],
                label=os.path.basename(part["source_path"]),
            )
            cumulative += part["duration"]
            new_clips.append(nc)
        self._clips[idx : idx + 1] = new_clips
        self._multi_selected = new_clips
        self._selected = new_clips[0]
        self._update_duration()
        self._sync_zoom_slider()
        self.clips_changed.emit()
        self.update()

    def _link_selected(self):
        """链接选中素材成组"""
        if len(self._multi_selected) < 2:
            return
        import uuid

        gid = uuid.uuid4().hex[:8]
        for c in self._multi_selected:
            c.link_group = gid
        self.update()

    def _unlink_clip(self, clip: TimelineClip):
        """取消素材链接"""
        clip.link_group = ""
        self.update()

    def _separate_av(self, clip: TimelineClip):
        """分离音视频 — 创建视频轨和音频轨两个链接素材"""
        if clip.track_type:
            return
        import uuid

        gid = uuid.uuid4().hex[:8]
        idx = self._clips.index(clip)
        video_clip = TimelineClip(
            source_path=clip.source_path,
            source_start=clip.source_start,
            start=clip.start,
            duration=clip.duration,
            source_duration=clip.source_duration,
            label=f"{clip.label} [视频]",
            link_group=gid,
            track_type="video",
            speed=clip.speed,
            display_scale=clip.display_scale,
            muted=True,
        )
        audio_clip = TimelineClip(
            source_path=clip.source_path,
            source_start=clip.source_start,
            start=clip.start,
            duration=clip.duration,
            source_duration=clip.source_duration,
            label=f"{clip.label} [音频]",
            link_group=gid,
            track_type="audio",
            speed=clip.speed,
        )
        self._clips[idx : idx + 1] = [video_clip, audio_clip]
        self._multi_selected = [video_clip, audio_clip]
        self._selected = video_clip
        self.clip_selected.emit(video_clip)
        self.clips_changed.emit()
        self.update()
        oplog.operation("分离音视频", clip.label)

    def _merge_av(self, clip: TimelineClip):
        """合并分离的音视频素材为普通素材"""
        gid = clip.link_group
        if not gid:
            return
        group = [c for c in self._clips if c.link_group == gid]
        if len(group) < 2:
            return
        audio_clip = next((c for c in group if getattr(c, "track_type", "") == "audio"), None)
        video_clip = next((c for c in group if getattr(c, "track_type", "") == "video"), None)
        if not audio_clip or not video_clip:
            return
        merged = TimelineClip(
            source_path=video_clip.source_path,
            source_start=video_clip.source_start,
            start=video_clip.start,
            duration=video_clip.duration,
            source_duration=video_clip.source_duration,
            label=video_clip.label.replace(" [视频]", ""),
            speed=video_clip.speed,
            display_scale=video_clip.display_scale,
        )
        idx_a = self._clips.index(audio_clip)
        idx_v = self._clips.index(video_clip)
        min_idx = min(idx_a, idx_v)
        self._clips.remove(audio_clip)
        self._clips.remove(video_clip)
        self._clips.insert(min_idx, merged)
        self._multi_selected = [merged]
        self._selected = merged
        self._range_anchor = merged
        self.clip_selected.emit(merged)
        self.clips_changed.emit()
        self.update()
        oplog.operation("合并音视频", merged.label)

    def generate_proxy(self, clip: TimelineClip, settings: dict) -> str:
        """生成代理文件, 返回代理路径"""
        proxy_dir = os.path.join(tempfile.gettempdir(), "pvt_proxy")
        os.makedirs(proxy_dir, exist_ok=True)

        res_idx = settings.get("resolution", 1)
        codec_idx = settings.get("codec", 0)
        fps_idx = settings.get("fps", 0)

        # 构建 filter
        filters = []
        if res_idx == 1:
            filters.append("scale=iw/2:ih/2")
        elif res_idx == 2:
            filters.append("scale=iw/4:ih/4")
        elif res_idx == 3:
            filters.append("scale=960:540")
        elif res_idx == 4:
            filters.append("scale=640:360")
        if fps_idx == 1:
            filters.append("fps=source_fps/2")

        vf = ",".join(filters) if filters else None

        if codec_idx == 1:
            codec_name, ext, codec_opts = "prores_ks", "mov", ["-profile:v", "0"]
        else:
            codec_name, ext, codec_opts = "libx264", "mp4", ["-preset", "ultrafast", "-crf", "28"]

        uid = uuid.uuid4().hex[:8]
        proxy_path = os.path.join(proxy_dir, f"proxy_{uid}.{ext}")

        cmd = ["ffmpeg", "-y", "-i", clip.source_path]
        if vf:
            cmd += ["-filter:v", vf]
        cmd += ["-c:v", codec_name, *codec_opts, "-g", "1", "-c:a", "aac", "-b:a", "128k", proxy_path]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0 and os.path.getsize(proxy_path) > 1000:
                clip.proxy_path = proxy_path
                self.clips_changed.emit()
                self.update()
                return proxy_path
            oplog.operation("代理生成失败", f"ffmpeg: {result.stderr[:200] if result.stderr else 'unknown'}")
            try:
                os.remove(proxy_path)
            except Exception:
                pass
            return ""
        except subprocess.TimeoutExpired:
            oplog.operation("代理生成超时")
            try:
                os.remove(proxy_path)
            except Exception:
                pass
            return ""
        except Exception as e:
            oplog.operation("代理生成异常", str(e))
            return ""

    def _set_selected_subtitle(self, entry):
        """设置选中字幕并出射信号"""
        self._selected_subtitle = entry
        self.subtitle_selected.emit(entry)

    @property
    def selected_subtitle(self) -> Optional[SubtitleEntry]:
        """当前选中的字幕条目（只读）"""
        return self._selected_subtitle

    def _subtitle_at_sec(self, sec: float) -> Optional[tuple[int, SubtitleEntry]]:
        """返回 (index, entry) 或 None"""
        for i, e in enumerate(self._subtitle_entries):
            if e.start <= sec <= e.end:
                return i, e
        return None

    def _set_lock(self, clip: TimelineClip, locked: bool | None = None, position_fixed: bool | None = None):
        """设置锁定/固定状态"""
        if locked is not None:
            clip.locked = locked
        if position_fixed is not None:
            clip.position_fixed = position_fixed
        if not clip.locked and not clip.position_fixed:
            # 全部解锁时重新允许选中拖拽
            pass
        self.update()

    # ── 变速 ──

    def _cycle_speed(self, clip):
        """循环变速：1x → 2x → 4x → 6x → 8x → 10x → 1x"""
        speeds = [1.0, 2.0, 4.0, 6.0, 8.0, 10.0]
        current = clip.speed
        # 找到当前速度在循环中的下一个
        try:
            idx = speeds.index(current)
            new_speed = speeds[(idx + 1) % len(speeds)]
        except ValueError:
            new_speed = 2.0
        old_speed = clip.speed
        clip.duration = max(0.1, clip.duration * old_speed / new_speed)
        clip.speed = new_speed
        oplog.operation("变速", f"{clip.label[:20]} → {new_speed:.1f}x")
        self._update_duration()
        self.clip_changed.emit(clip)
        self.clips_changed.emit()
        self.update()

    # ── 拖放导入 ──

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        if not e.mimeData().hasUrls():
            return
        exts = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".mp3", ".wav", ".aac", ".m4a"}
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if not path or not os.path.isfile(path):
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext not in exts:
                continue
            start_sec = max(0.0, self._x_to_sec(int(e.position().x())))
            duration = 10.0
            try:
                info = pvt_bridge.probe(path)
                dur = info.get("duration_secs", 0.0)
                if dur:
                    duration = dur
            except Exception:
                pass
            clip = TimelineClip(
                source_path=path,
                start=start_sec,
                duration=duration,
                source_duration=duration,
                label=os.path.basename(path),
            )
            self.add_clip(clip)  # add_clip 内部会调用 _check_and_set_resolution
        e.acceptProposedAction()

    # ── 绘制 ──

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        # 背景
        p.fillRect(0, 0, w, h, QColor("#1a1a1e"))

        # 轨道高度（20% 字幕 / 40% 视频 / 40% 音频）
        track_h = self._get_track_h()
        has_sub = bool(self._subtitle_entries)
        has_video_track = any(getattr(c, "track_type", "") == "video" for c in self._clips)
        sub_h, video_h, audio_h = self._get_track_heights()

        p.fillRect(0, 0, w, track_h, QColor("#121216"))

        # 裁剪轨道绘制区域，防止内容溢出到底部控制栏
        p.setClipRect(QRectF(0, 0, w, track_h))

        # ── 字幕轨（波形图上方） ──
        if has_sub:
            p.fillRect(0, 0, w, sub_h, QColor("#0d1a2a"))
            sub_font = QFont("sans-serif", 11)
            p.setFont(sub_font)

            for entry in self._subtitle_entries:
                sx = int(entry.start * self._pixels_per_sec - self._scroll_offset)
                sw = max(2, int(entry.duration * self._pixels_per_sec))
                if sx + sw < 0 or sx > w:
                    continue
                is_sub_sel = entry is self._selected_subtitle or entry in self._multi_selected_subs
                # 边框：选中橙色，未选中白色
                bc = "#FF8C00" if is_sub_sel else "#FFFFFF"
                p.setPen(QPen(QColor(bc), 2 if is_sub_sel else 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(sx + 1, 1, sw - 2, sub_h - 2), 3, 3)
                # 索引号 + 字幕文字（固定字号，不随全局字号变化）
                display_text = f"#{entry.index} {entry.text.replace(chr(10), '  ')}"
                p.setPen(QColor("#FFFFFF"))
                p.setFont(QFont("sans-serif", 9))
                fm = p.fontMetrics()
                elided = fm.elidedText(display_text, Qt.TextElideMode.ElideRight, sw - 8)
                p.drawText(
                    QRect(sx + 4, 2, sw - 8, sub_h - 4),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    elided,
                )

        # ── 视频轨（字幕下方，仅分离素材可见） ──
        video_y = sub_h + 2
        if has_video_track:
            p.fillRect(0, video_y, w, video_h, QColor("#0d1a1a"))
            p.setPen(QColor("#555"))
            p.setFont(QFont("sans-serif", 8))
            p.drawText(QRectF(4, video_y, 60, 14), Qt.AlignmentFlag.AlignLeft, "视频轨")

            for clip, x, cw in self._get_visual_layout():
                if getattr(clip, "track_type", "") != "video":
                    continue
                x = x - self._scroll_offset
                if x + cw < 0 or x > w:
                    continue
                is_sel = clip is self._selected
                bg = QColor("#1a3a1a") if not is_sel else QColor("#2a5a2a")
                border = self._clip_border_sel if is_sel else QColor("#3a6a3a")
                p.setPen(QPen(border, 1 if not is_sel else 2))
                p.setBrush(QBrush(bg))
                clip_rect = QRectF(x, video_y + 16, cw, video_h - 18)
                p.drawRoundedRect(clip_rect, 4, 4)

                # 缩略图：已缓存则始终绘制，仅选中时触发新提取
                positions = self._get_thumb_positions(clip)
                thumbs = [self._thumbnail_cache.get((clip.source_path, p)) for p in positions]
                cached = [t for t in thumbs if t is not None]
                if cached and len(cached) == len(positions):
                    n = len(cached)
                    tile_w = (clip_rect.width() - 4) / n
                    th = clip_rect.adjusted(2, 2, -2, -2)
                    for i, img in enumerate(cached):
                        p.drawImage(QRectF(th.x() + i * tile_w, th.y(), tile_w, th.height()), img)
                elif is_sel:
                    self._ensure_thumbnail_for(clip)

                # 多选边框
                if clip in self._multi_selected and len(self._multi_selected) > 1:
                    p.setPen(QPen(QColor("#FF8C00"), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(clip_rect, 4, 4)
                # 链接指示器
                if clip.link_group:
                    p.setPen(QPen(QColor("#FFD700"), 1.5))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    chain_x = x + cw - 16
                    chain_y = video_y + 20
                    p.drawEllipse(QPointF(chain_x, chain_y), 3, 3)
                    p.drawEllipse(QPointF(chain_x + 6, chain_y + 2), 3, 3)
                    p.drawLine(QPointF(int(chain_x + 3), int(chain_y) + 1), QPointF(int(chain_x + 3), int(chain_y) + 3))
                # 标签（未选中时显示文字）
                if not is_sel:
                    p.setPen(QColor("#6a6"))
                    p.setFont(QFont("sans-serif", 8))
                    label = getattr(clip, "label", "") or "视频"
                    txt_rect = QRectF(x + 4, video_y + 18, cw - 8, video_h - 22)
                    elided = p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, cw - 8)
                    p.drawText(txt_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        # ── 素材轨（视频轨下方） ──
        clip_y = video_y + video_h + (2 if has_video_track else 0)

        if not self._clips and not has_sub:
            p.setPen(QColor("#444"))
            p.setFont(QFont("sans-serif", 10))
            p.drawText(QRect(0, 0, w, track_h), Qt.AlignmentFlag.AlignCenter, "拖入素材开始剪辑")
            p.end()
            return

        for clip, x, cw in self._get_visual_layout():
            # 视频轨素材不在主轨渲染
            if getattr(clip, "track_type", "") == "video":
                continue
            x = x - self._scroll_offset
            if x + cw < 0 or x > w:
                continue
            is_sel = clip is self._selected

            cy = clip_y
            ch = audio_h

            # clip 主体
            bg = self._clip_color_selected if is_sel else self._clip_color_bg
            border = self._clip_border_sel if is_sel else self._clip_border
            p.setPen(QPen(border, 1 if not is_sel else 2))
            p.setBrush(QBrush(bg))
            p.drawRoundedRect(QRectF(x, cy, cw, ch), 4, 4)

            # 多选橙色边框
            if clip in self._multi_selected and len(self._multi_selected) > 1:
                p.setPen(QPen(QColor("#FF8C00"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(x, cy, cw, ch), 4, 4)

            # ── 链接指示器（金色链扣） ──
            if clip.link_group:
                linked = [c for c in self._clips if c.link_group == clip.link_group]
                chain_color = QColor("#FFD700")
                p.setPen(QPen(chain_color, 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                cx_icon = x + cw - 16
                cy_icon = cy + 8
                p.drawEllipse(QPointF(cx_icon, cy_icon), 3, 3)
                p.drawEllipse(QPointF(cx_icon + 6, cy_icon + 2), 3, 3)
                p.drawLine(QPointF(int(cx_icon + 3), int(cy_icon) + 1), QPointF(int(cx_icon + 3), int(cy_icon) + 3))
                # 链接数量
                p.setPen(QColor("#FFD700"))
                p.setFont(QFont("sans-serif", 8))
                p.drawText(QRectF(x + cw - 36, cy + 14, 32, 12), Qt.AlignmentFlag.AlignRight, f"×{len(linked)}")

            # ── 静音标记 ──
            if getattr(clip, "muted", False):
                p.setPen(QPen(QColor("#cc4444"), 1.5))
                p.setFont(QFont("sans-serif", 9))
                mute_rect = QRectF(x + 4, cy + ch - 30, 36, 14)
                p.drawText(mute_rect, Qt.AlignmentFlag.AlignLeft, "🔇")

            # ── FX 特效标记 ──
            if getattr(clip, "effects", None):
                p.setPen(QPen(QColor("#88aaff"), 1))
                p.setFont(QFont("sans-serif", 7, QFont.Bold))
                fx_rect = QRectF(x + cw - 32, cy + 2, 28, 12)
                p.fillRect(fx_rect.adjusted(-1, -1, 1, 1), QColor("#1a1a30"))
                p.drawText(fx_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, "FX")

            # 波形（底层）
            if clip.source_path in self._waveform_cache:
                peaks = self._waveform_cache[clip.source_path]
                step_px = 2
                num_bars = max(1, cw // step_px)
                p.setPen(QPen(QColor("#66BB6A"), 1))
                cx = x
                bar_h = max(12, ch - 8)  # 上下预留 4px 间隙
                bar_y = cy + (ch - bar_h) // 2
                for bi in range(num_bars):
                    if cx > w:
                        break
                    idx = min(int(bi * len(peaks) / num_bars), len(peaks) - 1)
                    amp = peaks[idx] if peaks else 0
                    bh = max(1, int(bar_h * amp))
                    cy2 = bar_y + (bar_h - bh) // 2
                    p.drawLine(int(cx), cy2, int(cx), cy2 + bh)
                    cx += step_px
            else:
                # 延迟加载波形
                if clip.source_path not in self._waveform_pending:
                    self._ensure_waveform_for(clip)

            # 标签
            label = clip.label or os.path.basename(clip.source_path)
            p.setPen(QColor("#cccccc"))
            p.setFont(QFont("sans-serif", 9))
            txt_rect = QRect(x + 6, cy + 2, cw - 12, 16)
            elided = p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, cw - 12)
            p.drawText(txt_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, elided)

            # 时长
            dur_text = f"{clip.duration:.1f}s"
            p.setPen(QColor("#888"))
            p.setFont(QFont("sans-serif", 8))
            p.drawText(
                QRect(x + 6, cy + ch - 16, cw - 12, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                dur_text,
            )

        # 播放头（贯穿字幕轨+素材轨）
        head_x = self._sec_to_x(self._position)
        if 0 <= head_x <= w:
            # 轨道区竖线
            p.setPen(QPen(QColor("#3a8cff"), 2))
            p.drawLine(head_x, 0, head_x, track_h)

        p.end()
