# -*- coding: utf-8 -*-
"""
导出设置对话框 — 支持视频/GIF/MP3
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QCheckBox,
    QDialogButtonBox,
    QGroupBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
)

from .engine import ExportOptions


def _default_filename(fmt: str, src_path: str) -> str:
    """根据格式生成默认文件名"""
    name = os.path.splitext(os.path.basename(src_path))[0] if src_path else "export"
    ext = fmt if fmt in ("gif", "mp3") else "mp4"
    return f"{name}_export.{ext}"


class ExportDialog(QDialog):
    """导出参数设置"""

    def __init__(self, parent=None, duration=0, source_path=""):
        super().__init__(parent)
        self.setWindowTitle("导出设置")
        self.setMinimumWidth(460)
        self.setStyleSheet(self._load_style())
        self._source_path = source_path
        self._duration = duration
        self._gif_fps = 10
        self._gif_scale = 480
        self._mp3_bitrate = "192k"
        self._setup_ui()

    def _load_style(self) -> str:
        return """
            QDialog { background-color: #1e1e22; color: #e0e0e0; }
            QLabel { color: #cccccc; font-size: 13px; }
            QGroupBox { font-size: 12px; color: #aaa; border: 1px solid #2a2a30;
                border-radius: 6px; margin-top: 12px; padding-top: 16px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QComboBox, QSpinBox, QLineEdit { background: #2a2a32; color: #d0d0d0;
                border: 1px solid #3a3a42; border-radius: 4px; padding: 4px 8px;
                font-size: 13px; min-width: 100px; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView { background: #222226; color: #d0d0d0;
                border: 1px solid #3a3a42; selection-background-color: #3a8cff44; }
            QCheckBox { color: #ccc; font-size: 13px; spacing: 6px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px;
                border: 1px solid #3a3a42; background: #2a2a32; }
            QCheckBox::indicator:checked { background: #3a8cff; border-color: #3a8cff; }
            QPushButton { background: #2a2a32; color: #d0d0d0;
                border: 1px solid #3a3a42; border-radius: 4px; padding: 6px 20px; font-size: 13px; }
            QPushButton:hover { background: #3a3a44; }
            QPushButton#accent { background: #3a8cff; color: #fff; border: none; }
            QPushButton#accent:hover { background: #4a9cff; }
        """

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("导出设置")
        title.setStyleSheet("font-size:15px; font-weight:bold; color:#e0e0e0;")
        layout.addWidget(title)
        if self._duration > 0:
            info = QLabel(f"素材时长: {self._duration:.1f}s")
            info.setStyleSheet("color:#888; font-size:11px;")
            layout.addWidget(info)

        # ── 封装格式 ──
        self._format_combo = QComboBox()
        self._format_combo.addItems(["MP4", "MOV", "MKV", "AVI", "GIF", "MP3"])
        self._format_combo.currentTextChanged.connect(self._on_format_changed)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("导出格式:"))
        fmt_row.addWidget(self._format_combo)
        fmt_row.addStretch()
        layout.addLayout(fmt_row)

        # ── 视频参数 ──
        self._video_group = QGroupBox("视频参数")
        vf = QFormLayout(self._video_group)
        vf.setSpacing(8)

        self._codec_combo = QComboBox()
        self._codec_combo.addItems(["H.264 (x264)", "H.265 (x265)", "VP9 (libvpx)"])
        vf.addRow("视频编码:", self._codec_combo)

        self._quality_combo = QComboBox()
        self._quality_combo.addItems(["高 (小体积)", "中 (平衡)", "低 (高质量)"])
        self._quality_combo.setCurrentIndex(1)
        vf.addRow("质量预设:", self._quality_combo)

        self._resolution_combo = QComboBox()
        self._resolution_combo.addItems(["原始分辨率", "1920x1080", "1280x720", "854x480"])
        vf.addRow("分辨率:", self._resolution_combo)

        layout.addWidget(self._video_group)

        # ── GIF 参数 ──
        self._gif_group = QGroupBox("GIF 参数")
        gf = QFormLayout(self._gif_group)
        gf.setSpacing(8)

        self._gif_fps_spin = QSpinBox()
        self._gif_fps_spin.setRange(1, 30)
        self._gif_fps_spin.setValue(10)
        self._gif_fps_spin.setSuffix(" fps")
        gf.addRow("帧率:", self._gif_fps_spin)

        self._gif_scale_spin = QSpinBox()
        self._gif_scale_spin.setRange(100, 1920)
        self._gif_scale_spin.setValue(480)
        self._gif_scale_spin.setSuffix(" px (宽)")
        gf.addRow("缩放:", self._gif_scale_spin)

        layout.addWidget(self._gif_group)

        # ── 音频参数 ──
        self._audio_group = QGroupBox("音频参数")
        af = QFormLayout(self._audio_group)
        af.setSpacing(8)

        self._acodec_combo = QComboBox()
        self._acodec_combo.addItems(["AAC", "MP3", "复制原始音频"])
        af.addRow("音频编码:", self._acodec_combo)

        layout.addWidget(self._audio_group)

        # ── MP3 参数 ──
        self._mp3_group = QGroupBox("MP3 参数")
        mf = QFormLayout(self._mp3_group)
        mf.setSpacing(8)

        self._mp3_bitrate_combo = QComboBox()
        self._mp3_bitrate_combo.addItems(["128k", "192k", "256k", "320k"])
        self._mp3_bitrate_combo.setCurrentText("192k")
        mf.addRow("比特率:", self._mp3_bitrate_combo)

        layout.addWidget(self._mp3_group)

        # ── 其他 ──
        self._gpu_check = QCheckBox("启用 GPU 硬件加速")
        self._gpu_check.setChecked(True)
        layout.addWidget(self._gpu_check)

        layout.addStretch()

        # ── 按钮 ──
        btns = QDialogButtonBox()
        btn_cancel = btns.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        btn_cancel.clicked.connect(self.reject)
        btn_ok = btns.addButton("开始导出", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_ok.setObjectName("accent")
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btns)

        self._on_format_changed(self._format_combo.currentText())

    def _on_format_changed(self, fmt: str):
        """格式切换时显示/隐藏对应参数"""
        is_video = fmt in ("MP4", "MOV", "MKV", "AVI")
        is_gif = fmt == "GIF"
        is_mp3 = fmt == "MP3"
        self._video_group.setVisible(is_video)
        self._audio_group.setVisible(is_video)
        self._gif_group.setVisible(is_gif)
        self._mp3_group.setVisible(is_mp3)
        self._gpu_check.setVisible(is_video)

    @property
    def format(self) -> str:
        t = self._format_combo.currentText()
        if t == "GIF":
            return "gif"
        if t == "MP3":
            return "mp3"
        return {"MP4": "mp4", "MOV": "mov", "MKV": "mkv", "AVI": "avi"}.get(t, "mp4")

    @property
    def video_codec(self) -> str:
        return {"H.264 (x264)": "h264", "H.265 (x265)": "hevc", "VP9 (libvpx)": "vp9"}.get(
            self._codec_combo.currentText(), "h264"
        )

    @property
    def quality(self) -> str:
        return {"高 (小体积)": "low", "中 (平衡)": "medium", "低 (高质量)": "high"}.get(
            self._quality_combo.currentText(), "medium"
        )

    @property
    def resolution(self) -> str:
        return {"原始分辨率": "original", "1920x1080": "1920:1080", "1280x720": "1280:720", "854x480": "854:480"}.get(
            self._resolution_combo.currentText(), "original"
        )

    @property
    def audio_codec(self) -> str:
        return {"AAC": "aac", "MP3": "mp3", "复制原始音频": "copy"}.get(self._acodec_combo.currentText(), "aac")

    @property
    def use_gpu(self) -> bool:
        return self._gpu_check.isChecked()

    @property
    def gif_fps(self) -> int:
        return self._gif_fps_spin.value()

    @property
    def gif_scale(self) -> int:
        return self._gif_scale_spin.value()

    @property
    def mp3_bitrate(self) -> str:
        return self._mp3_bitrate_combo.currentText()

    @property
    def output_path(self) -> str:
        """弹出保存文件对话框，返回路径"""
        fmt = self.format
        default = _default_filename(fmt, self._source_path)
        filters = {
            "mp4": "视频文件 (*.mp4)",
            "mov": "MOV 文件 (*.mov)",
            "mkv": "MKV 文件 (*.mkv)",
            "avi": "AVI 文件 (*.avi)",
            "gif": "GIF 图像 (*.gif)",
            "mp3": "MP3 音频 (*.mp3)",
        }
        selected_filter = filters.get(fmt, "所有文件 (*.*)")
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, "导出到", default, selected_filter)
        return path

    @property
    def export_options(self) -> ExportOptions:
        return ExportOptions(
            format=self.format,
            video_codec=self.video_codec,
            quality=self.quality,
            resolution=self.resolution,
            audio_codec=self.audio_codec,
            use_gpu=self.use_gpu,
        )
