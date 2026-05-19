# -*- coding: utf-8 -*-
"""
文字生视频输入面板 — 文字输入 + 素材源选择 + 分镜面板 + 操作按钮
"""

import os
import math
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize, QRect, QPoint
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QPlainTextEdit,
    QCheckBox,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QFileDialog,
    QSplitter,
    QFrame,
    QMessageBox,
    QSpacerItem,
    QSizePolicy,
    QLayout,
    QLayoutItem,
)

from videotrans.text_to_video.engine import TextToVideoEngine, TextToVideoConfig
from videotrans.text_to_video.llm_service import StoryboardShot
from videotrans.configure import config as cfg
from .storyboard_panel import StoryboardPanel

_HOVER_MAP = {"#3a8cff": "#5b9dff", "#555": "#777", "#ff6b3a": "#ff835a"}


# ── 自适应流式布局 ────────────────────────────────────────────────
class FlowLayout(QLayout):
    """自适应流式布局：子控件水平排列，超出宽度自动换行"""

    def __init__(self, parent=None, margin=0, spacing_h=8, spacing_v=6):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing_h = spacing_h
        self._spacing_v = spacing_v
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        try:
            while self._items:
                item = self._items.pop()
                w = item.widget()
                if w is not None:
                    try:
                        w.setParent(None)
                    except RuntimeError:
                        pass
                del item
        except Exception:
            pass

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, w):
        super().addWidget(w)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, dry=False):
        margins = self.contentsMargins()
        x = rect.x() + margins.left()
        y = rect.y() + margins.top()
        line_h = 0
        usable_w = rect.width() - margins.left() - margins.right()

        for item in self._items:
            widget = item.widget()
            if widget:
                hint = widget.sizeHint().expandedTo(widget.minimumSize())
            else:
                hint = item.sizeHint()
            w = min(hint.width(), usable_w)
            h = hint.height()
            if x + w > rect.x() + margins.left() + usable_w and line_h > 0:
                x = rect.x() + margins.left()
                y += line_h + self._spacing_v
                line_h = 0
            if not dry:
                if widget:
                    widget.setGeometry(QRect(x, y, w, h))
                else:
                    item.setGeometry(QRect(x, y, w, h))
            x += w + self._spacing_h
            line_h = max(line_h, h)

        return y + line_h - rect.y() + margins.bottom()


class TextToVideoPanel(QWidget):
    """文字生视频面板 — 嵌入主窗口左侧"""

    shots_changed = Signal(list)
    narration_ready = Signal(str)
    video_ready = Signal(str)
    open_settings = Signal()
    sources_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = TextToVideoEngine(self)
        self._config = TextToVideoConfig()
        self._shots: list[StoryboardShot] = []

        self._setup_ui()
        self._connect_signals()
        self._sync_config_from_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 垂直分割器：输入文字 / 素材来源+按钮（分镜脚本已移至右侧面板）──
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.setHandleWidth(3)
        v_splitter.setStyleSheet("""
            QSplitter::handle { background-color: #2a2a30; }
            QSplitter::handle:hover { background-color: #3a8cff; }
        """)

        # ── 输入区域 ──
        input_group = QGroupBox("输入文字")
        input_group.setStyleSheet(self._group_style())
        ig_layout = QVBoxLayout(input_group)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText(
            "在这里输入文字，AI 将自动生成分镜脚本...\n\n例如：夏日海边的美好时光，阳光洒在金色沙滩上..."
        )
        self._text_edit.setMinimumHeight(80)
        self._text_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e22; color: #e0e0e0;
                border: 1px solid #2a2a30; border-radius: 6px; padding: 10px; font-size: 13px;
            }
            QPlainTextEdit:focus { border-color: #3a8cff; }
        """)
        ig_layout.addWidget(self._text_edit)
        v_splitter.addWidget(input_group)

        # ── 素材源 + 按钮（合并在一个 widget 中） ──
        mid_widget = QWidget()
        mid_layout = QVBoxLayout(mid_widget)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(6)

        src_group = QGroupBox("素材来源")
        src_group.setStyleSheet(self._group_style())
        sg_layout = FlowLayout(src_group, margin=10, spacing_h=12, spacing_v=6)

        chk_style = """
            QCheckBox {
                color: #cccccc; font-size: 13px; spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                background-color: #2a2a30; border: 1px solid #3a3a42; border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #3a8cff; border-color: #3a8cff;
            }
            QCheckBox::indicator:hover {
                border-color: #5b9dff;
            }
        """

        small_btn_style = """
            QPushButton {
                background-color: #333; color: #ccc; border: none;
                border-radius: 4px; padding: 4px 8px; font-size: 11px;
            }
            QPushButton:hover { background-color: #555; }
        """

        self._chk_local = QCheckBox("本地素材")
        self._chk_local.setChecked(True)
        self._chk_local.setStyleSheet(chk_style)
        self._chk_local.toggled.connect(self._emit_sources_changed)
        sg_layout.addWidget(self._chk_local)

        self._chk_pexels = QCheckBox("Pexels 在线")
        self._chk_pexels.setStyleSheet(chk_style)
        self._chk_pexels.toggled.connect(self._emit_sources_changed)
        sg_layout.addWidget(self._chk_pexels)

        self._chk_pixabay = QCheckBox("Pixabay 在线")
        self._chk_pixabay.setStyleSheet(chk_style)
        self._chk_pixabay.toggled.connect(self._emit_sources_changed)
        sg_layout.addWidget(self._chk_pixabay)

        self._chk_comfyui = QCheckBox("ComfyUI 本地")
        self._chk_comfyui.setStyleSheet(chk_style)
        self._chk_comfyui.toggled.connect(self._emit_sources_changed)
        sg_layout.addWidget(self._chk_comfyui)

        self._btn_local_dir = QPushButton("本地目录...")
        self._btn_local_dir.setToolTip("选择本地素材搜索目录")
        self._btn_local_dir.clicked.connect(self.add_local_dir)
        self._btn_local_dir.setStyleSheet(small_btn_style)
        sg_layout.addWidget(self._btn_local_dir)

        self._btn_api_settings = QPushButton("⚙ API设置")
        self._btn_api_settings.setToolTip("配置 Pexels / Pixabay / ComfyUI 的 API Key 和服务地址")
        self._btn_api_settings.clicked.connect(self._on_open_settings)
        self._btn_api_settings.setStyleSheet(small_btn_style)
        sg_layout.addWidget(self._btn_api_settings)

        mid_layout.addWidget(src_group)

        # ── 操作按钮（自适应排列） ──
        btn_layout = FlowLayout(margin=0, spacing_h=6, spacing_v=6)

        self._btn_generate = QPushButton("① 生成分镜")
        self._btn_generate.setToolTip("通过 AI 分析文字，自动生成分镜脚本")
        self._btn_generate.setMinimumSize(160, 36)
        self._btn_generate.setStyleSheet(self._btn_style("#3a8cff"))
        self._btn_generate.clicked.connect(self._on_generate_storyboard)
        btn_layout.addWidget(self._btn_generate)

        self._btn_search = QPushButton("② 搜索素材")
        self._btn_search.setToolTip("为每个分镜搜索匹配的素材")
        self._btn_search.setMinimumSize(160, 36)
        self._btn_search.setStyleSheet(self._btn_style("#555"))
        self._btn_search.setEnabled(False)
        self._btn_search.clicked.connect(self._on_search_materials)
        btn_layout.addWidget(self._btn_search)

        self._btn_narrate = QPushButton("③ 生成配音")
        self._btn_narrate.setToolTip("通过 Edge-TTS 生成旁白配音")
        self._btn_narrate.setMinimumSize(160, 36)
        self._btn_narrate.setStyleSheet(self._btn_style("#555"))
        self._btn_narrate.setEnabled(False)
        self._btn_narrate.clicked.connect(self._on_generate_narration)
        btn_layout.addWidget(self._btn_narrate)

        self._btn_compose = QPushButton("④ 合成视频")
        self._btn_compose.setToolTip("合成为最终视频")
        self._btn_compose.setMinimumSize(160, 36)
        self._btn_compose.setStyleSheet(self._btn_style("#ff6b3a"))
        self._btn_compose.setEnabled(False)
        self._btn_compose.clicked.connect(self._on_compose)
        btn_layout.addWidget(self._btn_compose)

        mid_layout.addLayout(btn_layout)
        v_splitter.addWidget(mid_widget)

        # ── 分镜面板（创建但不加入左侧布局，由 main_window 放入右侧面板）──
        self._storyboard = StoryboardPanel()
        self._storyboard.shot_edited.connect(self._on_shot_updated)
        self._storyboard.shot_deleted.connect(self._on_shot_deleted)

        # 设置初始比例：输入 40% / 素材+按钮 60%
        v_splitter.setStretchFactor(0, 2)
        v_splitter.setStretchFactor(1, 3)

        layout.addWidget(v_splitter, 1)

        # ── 进度条 ──
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(6)
        self._progress.setStyleSheet("""
            QProgressBar { background-color: #222226; border: none; border-radius: 3px; }
            QProgressBar::chunk { background-color: #3a8cff; border-radius: 3px; }
        """)
        layout.addWidget(self._progress)

        # ── 状态 ──
        self._status_label = QLabel("就绪 — 输入文字后点击「生成分镜」")
        self._status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._status_label)

    def _connect_signals(self):
        self._engine.progress.connect(self._on_progress)
        self._engine.shots_ready.connect(self._on_shots_ready)
        self._engine.shot_material_ready.connect(self._on_shot_material_ready)
        self._engine.narration_ready.connect(self._on_narration_ready)
        self._engine.finished.connect(self._on_finished)
        self._engine.error.connect(self._on_error)

    def _emit_sources_changed(self):
        """素材源勾选变化时通知外部同步"""
        self.sources_changed.emit(
            {
                "use_local": self._chk_local.isChecked(),
                "use_pexels": self._chk_pexels.isChecked(),
                "use_pixabay": self._chk_pixabay.isChecked(),
                "use_comfyui": self._chk_comfyui.isChecked(),
            }
        )

    # ── 配置同步 ──
    def _sync_config_from_settings(self):
        self._config.pexels_api_key = cfg.params.get("pexels_api_key", "")
        self._config.pixabay_api_key = cfg.params.get("pixabay_api_key", "")
        self._config.comfyui_url = cfg.params.get("comfyui_url", "http://127.0.0.1:8188")
        self._config.comfyui_workflow = cfg.params.get("comfyui_workflow", "")
        # 恢复本地素材目录
        saved_dirs = cfg.params.get("t2v_local_dirs", [])
        if isinstance(saved_dirs, str):
            import json

            try:
                saved_dirs = json.loads(saved_dirs)
            except (json.JSONDecodeError, TypeError):
                saved_dirs = []
        self._config.local_dirs = list(saved_dirs) if saved_dirs else []

    def refresh_config(self):
        self._sync_config_from_settings()
        self._emit_sources_changed()

    # ── 按钮事件 ──
    def _on_open_settings(self):
        from .settings_dialog import TextToVideoSettingsDialog

        dlg = TextToVideoSettingsDialog(self)
        if dlg.exec():
            self._sync_config_from_settings()
            self._status_label.setText("设置已更新")
        self.open_settings.emit()

    def _on_generate_storyboard(self):
        text = self._text_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请先输入文字内容")
            return
        self._sync_config_from_settings()
        self._btn_generate.setEnabled(False)
        self._engine.generate_storyboard(text)

    def _on_search_materials(self):
        if not self._shots:
            return
        self._sync_config_from_settings()
        self._config.use_local = self._chk_local.isChecked()
        self._config.use_pexels = self._chk_pexels.isChecked()
        self._config.use_pixabay = self._chk_pixabay.isChecked()
        self._config.use_comfyui = self._chk_comfyui.isChecked()

        # 校验：勾选了在线源但没有 API Key
        missing_keys = []
        if self._config.use_pexels and not self._config.pexels_api_key:
            missing_keys.append("Pexels")
        if self._config.use_pixabay and not self._config.pixabay_api_key:
            missing_keys.append("Pixabay")
        if missing_keys:
            QMessageBox.warning(
                self,
                "缺少 API Key",
                f"已勾选 {'、'.join(missing_keys)} 在线素材源，但未配置 API Key。\n"
                "请点击右上角齿轮图标 →「API 密钥」标签页填写。",
            )
            return

        # 校验：至少有一个可用的素材源
        has_source = (
            self._config.use_local
            or (self._config.use_pexels and self._config.pexels_api_key)
            or (self._config.use_pixabay and self._config.pixabay_api_key)
            or self._config.use_comfyui
        )
        if not has_source:
            QMessageBox.warning(
                self,
                "没有可用素材源",
                "请至少启用一个素材源：\n"
                "• 本地素材 — 指定包含图片/视频的文件夹\n"
                "• Pexels / Pixabay — 需在设置中填写 API Key\n"
                "• ComfyUI — 需本地运行并配置服务地址",
            )
            return

        self._btn_search.setEnabled(False)
        self._acquisition_done_count = 0
        self._engine.acquire_materials(self._shots)

    def _on_generate_narration(self):
        text = self._text_edit.toPlainText().strip()
        if not text:
            return
        self._btn_narrate.setEnabled(False)
        tts_engine = cfg.params.get("t2v_tts_engine", "edgetts")
        voice = cfg.params.get("tts_voice", "zh-CN-YunjianNeural")
        speed = float(cfg.params.get("tts_speed", 1.2))
        # CosyVoice 模式使用配置的音色
        if tts_engine == "cosyvoice":
            voice = cfg.params.get("t2v_cosyvoice_role", "clone")
        self._engine.generate_narration(text, voice, speed, tts_engine=tts_engine)

    def _on_compose(self):
        self._sync_config_from_settings()
        self._config.input_text = self._text_edit.toPlainText().strip()
        self._config.shots = self._shots
        self._config.use_local = self._chk_local.isChecked()
        self._config.use_pexels = self._chk_pexels.isChecked()
        self._config.use_pixabay = self._chk_pixabay.isChecked()
        self._config.use_comfyui = self._chk_comfyui.isChecked()

        orient = cfg.params.get("orientation", "landscape")
        self._config.orientation = orient
        res_str = cfg.params.get("t2v_resolution", "1920x1080")
        try:
            w_str, h_str = res_str.split("x")
            self._config.resolution = (int(w_str), int(h_str))
        except Exception:
            self._config.resolution = (1920, 1080)
        self._config.fps = int(cfg.params.get("fps", 30))
        self._config.subtitle_enabled = cfg.params.get("subtitle_enabled", True)

        self._btn_compose.setEnabled(False)
        self._engine.compose_video(self._config)

    # ── 引擎回调 ──
    def _on_progress(self, message: str, pct: int):
        self._status_label.setText(message)
        self._progress.setVisible(True)
        self._progress.setValue(pct)

    def _on_shots_ready(self, shots: list):
        self._shots = shots
        self._storyboard.set_shots(shots)
        self._btn_generate.setEnabled(True)
        self._btn_search.setEnabled(True)
        self.shots_changed.emit(shots)
        self._progress.setValue(100)
        self._status_label.setText(f"已生成 {len(shots)} 个分镜镜头，合成后自动加入素材库")

    def _on_shot_material_ready(self, index: int):
        for i, shot in enumerate(self._shots):
            if shot.index == index:
                self._storyboard.update_shot(i, shot)
                break
        self._acquisition_done_count = getattr(self, "_acquisition_done_count", 0) + 1
        if self._acquisition_done_count >= len(self._shots):
            self._on_acquisition_done()

    def _on_shot_updated(self, index: int, shot: StoryboardShot):
        """storyboard 面板编辑后同步数据，不再回写避免递归"""
        if 0 <= index < len(self._shots):
            self._shots[index] = shot

    def _on_shot_deleted(self, index: int):
        if 0 <= index < len(self._shots):
            self._shots.pop(index)
            for i, s in enumerate(self._shots):
                s.index = i + 1
            self._storyboard.set_shots(self._shots)
            self.shots_changed.emit(self._shots)

    def _on_acquisition_done(self):
        self._btn_search.setEnabled(True)
        self._btn_narrate.setEnabled(True)
        self._status_label.setText("素材获取完成 — 可生成配音或直接合成")

    def _on_narration_ready(self, path: str):
        self._btn_narrate.setEnabled(True)
        self._btn_compose.setEnabled(True)
        self.narration_ready.emit(path)
        self._status_label.setText(f"配音就绪: {os.path.basename(path)}")

    def _on_finished(self, path: str):
        self._btn_compose.setEnabled(True)
        self._status_label.setText(f"视频合成完成: {os.path.basename(path)}")
        self.video_ready.emit(path)

    def _on_error(self, message: str):
        self._btn_generate.setEnabled(True)
        self._btn_search.setEnabled(True)
        self._btn_narrate.setEnabled(True)
        self._btn_compose.setEnabled(True)
        self._status_label.setText(f"错误: {message}")
        self._progress.setVisible(False)
        QMessageBox.critical(self, "错误", message)

    # ── 公开接口 ──
    @property
    def storyboard(self):
        """分镜面板组件，由 main_window 放入右侧面板"""
        return self._storyboard

    def get_shots(self) -> list:
        return self._shots

    def get_sources_config(self) -> dict:
        return {
            "use_local": self._chk_local.isChecked(),
            "use_pexels": self._chk_pexels.isChecked(),
            "use_pixabay": self._chk_pixabay.isChecked(),
            "use_comfyui": self._chk_comfyui.isChecked(),
        }

    def set_local_dirs(self, dirs: list[str]):
        self._config.local_dirs = dirs

    def add_local_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择本地素材目录")
        if d:
            if d not in self._config.local_dirs:
                self._config.local_dirs.append(d)
                self._persist_local_dirs()
            dirs_text = ", ".join(os.path.basename(d) for d in self._config.local_dirs[-3:])
            more = f" +{len(self._config.local_dirs) - 3}" if len(self._config.local_dirs) > 3 else ""
            self._status_label.setText(f"本地素材目录 ({len(self._config.local_dirs)}): {dirs_text}{more}")

    def _persist_local_dirs(self):
        """持久化本地素材目录列表"""
        cfg.params["t2v_local_dirs"] = self._config.local_dirs
        cfg.params.save()

    # ── 样式 ──
    def _group_style(self) -> str:
        return """
            QGroupBox {
                color: #aaaaaa; font-size: 12px; font-weight: bold;
                border: 1px solid #2a2a30; border-radius: 6px;
                margin-top: 8px; padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
            }
        """

    def _btn_style(self, color: str) -> str:
        hover = _HOVER_MAP.get(color, color)
        return f"""
            QPushButton {{
                background-color: {color}; color: #ffffff;
                border: none; border-radius: 6px;
                padding: 10px 16px; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:disabled {{ background-color: #333; color: #666; }}
        """
