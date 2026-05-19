# -*- coding: utf-8 -*-
"""
剪映风格主窗口 — pyvideotrans Studio
"""

import os
import sys
import time
import traceback
import threading
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSettings, QSize, QUrl, QMimeData, QRect
from PySide6.QtGui import QIcon, QAction, QShortcut, QKeySequence, QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QMenu,
    QStatusBar,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStyle,
    QFrame,
    QApplication,
    QSizePolicy,
    QMessageBox,
    QPlainTextEdit,
    QLineEdit,
    QTextEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from videotrans import VERSION
from videotrans.configure import config as cfg
from videotrans.configure.config import tr, ROOT_DIR, TEMP_DIR, logger
from studio.editor import PreviewWidget
from studio.editor import TimelineWidget
from studio.editor import ClipEngine, ClipSegment, ExportOptions
from studio.editor import pvt_bridge
from studio.text_to_video import TextToVideoPanel
from studio.text_to_video import MediaBrowser
from studio.text_to_video.material_timeline import MaterialTimeline, _material_to_dict, _dict_to_material
from . import oplog

# ── 暗色样式表 ──────────────────────────────────────────────
STYLESHEET = """
/* 全局 */
QMainWindow, QWidget {
    background-color: #1a1a1e;
    color: #e0e0e0;
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
    font-size: 13px;
}

/* 工具提示 */
QToolTip {
    background-color: #2a2a32;
    color: #ffffff;
    border: 1px solid #3a3a44;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 12px;
}

/* 顶部工具栏 */
#topToolbar {
    background-color: #1e1e22;
    border-bottom: 1px solid #2a2a30;
    padding: 4px 8px;
    min-height: 48px;
}
#topToolbar QToolButton {
    background-color: transparent;
    color: #cccccc;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
    margin: 0 2px;
}
#topToolbar QToolButton:hover {
    background-color: #2a2a32;
    color: #ffffff;
}
#topToolbar QToolButton:checked {
    background-color: #3a8cff;
    color: #ffffff;
}
#topToolbar QToolButton:pressed {
    background-color: #2a7aee;
}

/* 面板标题 */
.panel-title {
    font-size: 12px;
    color: #888888;
    padding: 4px 8px;
    background-color: #222226;
    border-bottom: 1px solid #2a2a30;
}

/* 列表控件 */
QListWidget {
    background-color: #1a1a1e;
    border: none;
    outline: none;
    color: #d0d0d0;
    font-size: 12px;
}
QListWidget::item {
    padding: 6px 8px;
    border-radius: 4px;
    margin: 1px 4px;
    background: transparent;
}
QListWidget::item:hover {
    background-color: #2a2a32;
}
QListWidget::item:selected {
    background: transparent;
    color: #ffffff;
}

/* 分割器 */
QSplitter::handle {
    background-color: #2a2a30;
    width: 1px;
    height: 1px;
}

/* 按钮 */
QPushButton {
    background-color: #2a2a32;
    color: #d0d0d0;
    border: 1px solid #3a3a42;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #3a3a44;
    border-color: #4a4a54;
}
QPushButton:pressed {
    background-color: #2a2a2e;
}
QPushButton#accentBtn {
    background-color: #3a8cff;
    color: #ffffff;
    border: none;
    font-weight: bold;
}
QPushButton#accentBtn:hover {
    background-color: #4a9cff;
}

/* 标签 */
QLabel {
    color: #cccccc;
    background-color: transparent;
}

/* 预览区域占位 */
#previewWidget {
    background-color: #0d0d0f;
    border: 1px solid #2a2a30;
    border-radius: 4px;
}

/* 底部时间线区域 */
#timelineWidget {
    background-color: #1a1a1e;
    border-top: 1px solid #2a2a30;
}

/* 滚动条 */
QScrollBar:vertical {
    background-color: #1a1a1e;
    width: 8px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #3a3a44;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #4a4a54;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background-color: #1a1a1e;
    height: 8px;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: #3a3a44;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #4a4a54;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* 状态栏 */
QStatusBar {
    background-color: #1e1e22;
    border-top: 1px solid #2a2a30;
    color: #888888;
    font-size: 12px;
}
"""


# ── 字幕编辑对话框 ──────────────────────────────────────────
class SubtitleEditDialog(QDialog):
    """暂停管线，让用户修改字幕。未操作时 20 秒自动继续，一旦开始编辑则等待手动点击"""

    def __init__(self, parent, title, text, file_path):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 420)
        self._file_path = file_path
        self._countdown = 20
        self._interacted = False  # 用户是否编辑过字幕

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 提示 + 倒计时
        self._hint = QLabel(f"请修改{title}，20 秒后自动继续")
        self._hint.setStyleSheet("color: #ff9900; font-size: 12px;")
        layout.addWidget(self._hint)

        self._countdown_label = QLabel("20 秒")
        self._countdown_label.setStyleSheet("color: #ff9900; font-size: 11px;")
        layout.addWidget(self._countdown_label)

        # 字幕文本编辑框
        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlainText(text)
        self._text_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e24; color: #e0e0e0;
                border: 1px solid #3a3a42; border-radius: 4px;
                font-size: 13px; padding: 8px;
            }
        """)
        # 检测用户编辑行为
        self._text_edit.textChanged.connect(self._on_text_changed)
        # 启用输入法（fcitx5 等 Linux 输入法支持）
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self._text_edit.setAttribute(Qt.WA_InputMethodEnabled, True)
        self._text_edit.setFocusPolicy(Qt.StrongFocus)
        layout.addWidget(self._text_edit, 1)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._next_btn = QPushButton("下一步 (20s)")
        self._next_btn.setFixedHeight(32)
        self._next_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a8cff; color: white;
                border: none; border-radius: 4px;
                padding: 6px 28px; font-size: 13px;
            }
            QPushButton:hover { background-color: #5a9cff; }
        """)
        self._next_btn.clicked.connect(self._on_next)
        btn_layout.addWidget(self._next_btn)
        layout.addLayout(btn_layout)

        # 倒计时
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        # 确保文本框获得焦点，输入法才能正常工作
        self._text_edit.setFocus()

    def _on_text_changed(self):
        """用户开始编辑字幕 → 取消倒计时自动关闭，改为等待手动点击"""
        if not self._interacted:
            self._interacted = True
            self._timer.stop()
            self._hint.setText("请修改完成后点击「下一步」继续")
            self._countdown_label.setText("")
            self._next_btn.setText("下一步")

    def _tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._timer.stop()
            self.accept()
        else:
            self._next_btn.setText(f"下一步 ({self._countdown}s)")
            self._countdown_label.setText(f"{self._countdown} 秒")

    def _on_next(self):
        self._timer.stop()
        self.accept()

    def save(self):
        """将编辑后的文本写回字幕文件"""
        if self._file_path:
            try:
                Path(self._file_path).write_text(self._text_edit.toPlainText(), encoding="utf-8")
            except Exception as e:
                print(f"保存字幕失败: {e}")


# ── 媒体列表项控件 ──────────────────────────────────────────


class _MediaItemWidget(QWidget):
    """hover 显示添加/删除按钮，点击选中项，自适应换行高度"""

    def mousePressEvent(self, event):
        lw = self._list_widget
        for i in range(lw.count()):
            if lw.itemWidget(lw.item(i)) is self:
                lw.setCurrentItem(lw.item(i))
                break
        super().mousePressEvent(event)

    def enterEvent(self, event):
        if hasattr(self, "_btn_add"):
            self.setStyleSheet("background: rgba(58, 140, 255, 0.18); border-radius: 4px;")
            self._btn_add.show()
            self._btn_del.show()
            QTimer.singleShot(0, self._sync_size)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if hasattr(self, "_btn_add"):
            QTimer.singleShot(80, lambda: self._hide_if_not_under_mouse())
        super().leaveEvent(event)

    def _hide_if_not_under_mouse(self):
        try:
            if not self.underMouse() and hasattr(self, "_btn_add"):
                self._btn_add.hide()
                self._btn_del.hide()
                self.setStyleSheet("background: transparent;")
                self._sync_size()
        except RuntimeError:
            pass

    def _sync_size(self):
        if not hasattr(self, "_label") or not hasattr(self, "_list_widget"):
            return
        lw = self._list_widget
        sh = self.sizeHint()
        for i in range(lw.count()):
            item = lw.item(i)
            if item and lw.itemWidget(item) is self:
                item.setSizeHint(QSize(sh.width(), sh.height()))
                if self._btn_del and self._btn_del.isVisible():
                    btn_h = self._btn_del.height()
                    if btn_h > 0:
                        icon_sz = max(16, min(32, btn_h - 6))
                        self._btn_del.setIconSize(QSize(icon_sz, icon_sz))
                break

    @staticmethod
    def _btn_render_width(btn) -> int:
        if not btn.isVisible():
            return 0
        return max(btn.sizeHint().width(), btn.minimumSize().width())

    def sizeHint(self):
        if not hasattr(self, "_label"):
            return QSize(200, 24)
        list_w = self._list_widget.viewport().width()
        if list_w <= 0:
            list_w = 160
        l, _, r, _ = self.layout().getContentsMargins()
        spacing = self.layout().spacing()
        avail = list_w - l - r
        if self._btn_add and self._btn_add.isVisible():
            avail -= self._btn_render_width(self._btn_add) + spacing
        if self._btn_del and self._btn_del.isVisible():
            avail -= self._btn_render_width(self._btn_del) + spacing
        fm = self._label.fontMetrics()
        flags = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft)
        br = fm.boundingRect(
            QRect(0, 0, max(avail, 40), 99999),
            flags,
            self._label.text(),
        )
        return QSize(list_w, max(28, br.height() + 8))


# ── 主窗口 ────────────────────────────────────────────────


class StudioMainWindow(QMainWindow):
    """剪映风格主窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StudioMainWindow")
        oplog.start()
        self._oplog("启动程序")

        # 全局异常钩子 — 崩溃前写入日志，便于排查
        self._orig_excepthook = sys.excepthook

        def _studio_excepthook(typ, val, tb):
            msg = "".join(traceback.format_exception(typ, val, tb))
            log_path = f"{TEMP_DIR}/studio_crash.log"
            try:
                with open(log_path, "a") as f:
                    f.write(f"\n===== CRASH at {__import__('datetime').datetime.now()} =====\n{msg}\n")
            except Exception:
                pass
            # 仍调用原钩子
            if self._orig_excepthook:
                self._orig_excepthook(typ, val, tb)

        sys.excepthook = _studio_excepthook

        # 关联 .desktop 文件，让任务栏显示自定义图标
        QGuiApplication.setDesktopFileName("pyvideotrans-studio")

        # 状态
        self._current_mode = "clip"  # "clip" | "translate"
        self._media_files = []
        self._current_video = None
        self._time_editing = False  # 时间输入标志
        self._project_path: str = ""  # 当前项目文件路径
        self._last_import_dir = ""  # 导入文件对话框最后目录

        # 字幕样式（全局默认）
        self._subtitle_font_size = 20
        self._subtitle_font_bold = True

        # 剪辑引擎
        self._engine = ClipEngine(self)
        self._engine.progress_changed.connect(self._on_engine_progress)
        self._engine.status_message.connect(self._on_engine_status)
        self._engine.operation_finished.connect(self._on_engine_finished)

        self._init_window()
        self._init_top_toolbar()
        self._init_central_area()
        self._init_status_bar()
        self._init_shortcuts()

        # 加载设置
        self._load_settings()

    # ── 窗口初始化 ──

    def _init_window(self):
        self.setWindowTitle(f"pyvideotrans Studio {VERSION}")
        self.setMinimumSize(1024, 600)

        # 使用预生成的 PNG 作为窗口图标
        # PNG 由 logo_icon.svg 预先渲染生成
        icon_path = os.path.join(ROOT_DIR, "studio/logo_icon_64.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setStyleSheet(STYLESHEET)

    # ── 顶部工具栏 ──

    def _init_top_toolbar(self):
        tb = QToolBar(self)
        tb.setObjectName("topToolbar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        # Logo
        logo = QLabel("  pyvideotrans Studio  ")
        logo.setStyleSheet("font-size:16px; font-weight:bold; color:#3a8cff; padding:0 8px;")
        tb.addWidget(logo)
        tb.addSeparator()

        # ── 文件菜单 ──
        self.btn_file_menu = QToolButton()
        self.btn_file_menu.setText("  文件  ")
        self.btn_file_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_file_menu.setToolTip("项目文件操作")
        file_menu = QMenu(self)
        file_menu.setStyleSheet("""
            QMenu {
                background-color: #222226;
                border: 1px solid #3a3a42;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
                color: #cccccc;
                font-size: 13px;
            }
            QMenu::item:hover {
                background-color: #2a2a32;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #2a2a30;
                margin: 4px 8px;
            }
        """)
        act_open = QAction("  打开项目  ", self)
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self._on_open_project)
        file_menu.addAction(act_open)
        act_save = QAction("  保存  ", self)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self._on_save_project)
        file_menu.addAction(act_save)
        act_save_as = QAction("  另存为...  ", self)
        act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_save_as.triggered.connect(self._on_save_project_as)
        file_menu.addAction(act_save_as)
        file_menu.addSeparator()
        act_exit = QAction("  退出  ", self)
        act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)
        self.btn_file_menu.setMenu(file_menu)
        tb.addWidget(self.btn_file_menu)
        tb.addSeparator()

        # ── 模式切换 ──
        self.btn_clip_mode = QToolButton()
        self.btn_clip_mode.setText("  剪辑  ")
        self.btn_clip_mode.setCheckable(True)
        self.btn_clip_mode.setChecked(True)
        self.btn_clip_mode.setToolTip("轻量剪辑模式 — 裁剪/分割/合并")
        self.btn_clip_mode.clicked.connect(lambda: self._switch_mode("clip"))

        self.btn_trans_mode = QToolButton()
        self.btn_trans_mode.setText("  翻译配音  ")
        self.btn_trans_mode.setCheckable(True)
        self.btn_trans_mode.setChecked(False)
        self.btn_trans_mode.setToolTip("视频翻译 + 配音模式（核心功能）")
        self.btn_trans_mode.clicked.connect(lambda: self._switch_mode("translate"))

        tb.addWidget(self.btn_clip_mode)
        tb.addWidget(self.btn_trans_mode)
        tb.addSeparator()

        # ── 导出/高级 ──
        self.btn_dubbing_adv = QToolButton()
        self.btn_dubbing_adv.setText("  配音高级设置  ")
        self.btn_dubbing_adv.setToolTip("配音模块高级参数设置")
        self.btn_dubbing_adv.clicked.connect(self._on_dubbing_advanced)
        tb.addWidget(self.btn_dubbing_adv)

        self.btn_export = QToolButton()
        self.btn_export.setText("  导出  ")
        self.btn_export.setObjectName("accentBtn")
        self.btn_export.setToolTip("导出处理结果")
        self.btn_export.clicked.connect(self._on_export_clip)
        tb.addWidget(self.btn_export)

        tb.addSeparator()

        self.btn_settings = QToolButton()
        self.btn_settings.setText("  设置  ")
        self.btn_settings.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        settings_menu = QMenu(self)
        settings_menu.setStyleSheet("""
            QMenu {
                background-color: #222226;
                border: 1px solid #3a3a42;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
                color: #cccccc;
                font-size: 13px;
            }
            QMenu::item:hover {
                background-color: #2a2a32;
                color: #ffffff;
            }
            QMenu::item:selected {
                background-color: #3a8cff44;
                color: #3a8cff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #2a2a30;
                margin: 4px 8px;
            }
        """)
        menu_categories = [
            ("common", "通用设置"),
            ("whisper", "语音识别"),
            ("trans", "翻译设置"),
            ("dubbing", "配音设置"),
            ("justify", "字幕对齐"),
            ("video", "视频输出"),
            ("prompt_init", "Whisper提示词"),
        ]
        for cat_key, cat_label in menu_categories:
            act = QAction(cat_label, self)
            act.triggered.connect(lambda checked=False, k=cat_key: self._on_settings_category(k))
            settings_menu.addAction(act)
        self.btn_settings.setMenu(settings_menu)
        tb.addWidget(self.btn_settings)

        tb.addSeparator()

        # ── 文字生视频入口 ──
        self.btn_t2v_mode = QToolButton()
        self.btn_t2v_mode.setText("  文字生视频  ")
        self.btn_t2v_mode.setCheckable(True)
        self.btn_t2v_mode.setChecked(False)
        self.btn_t2v_mode.setToolTip("AI 文字转视频 — 自动生成分镜素材并合成")
        self.btn_t2v_mode.clicked.connect(lambda: self._switch_mode("text_to_video"))
        tb.addWidget(self.btn_t2v_mode)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self._mode_label = QLabel()
        self._mode_label.setStyleSheet("color:#888888; font-size:12px; padding:0 8px;")
        tb.addWidget(self._mode_label)
        self._update_mode_label()

    # ── 中央区域 ──

    def _init_central_area(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 主水平分割器 ──
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(1)

        # 左面板
        self._left_panel = self._create_left_panel()
        self.main_splitter.addWidget(self._left_panel)

        # ── 中央区域（含预览+时间线垂直分割） ──
        self._center_col = QWidget()
        center_col_layout = QVBoxLayout(self._center_col)
        center_col_layout.setContentsMargins(0, 0, 0, 0)
        center_col_layout.setSpacing(0)

        # 垂直分割器：预览(上) / 时间线(下)
        self._preview_timeline_splitter = QSplitter(Qt.Orientation.Vertical)
        self._preview_timeline_splitter.setHandleWidth(3)
        self._preview_timeline_splitter.setStyleSheet("""
            QSplitter::handle { background-color: #2a2a30; }
            QSplitter::handle:hover { background-color: #3a8cff; }
        """)

        # 剪辑模式中心（预览 + 底部区域：播放条/素材时间线，整体可拖拽分割）
        clip_center = QWidget()
        clip_layout = QVBoxLayout(clip_center)
        clip_layout.setContentsMargins(4, 4, 4, 0)
        clip_layout.setSpacing(0)

        self._preview_widget = self._create_preview_widget()

        # 底部区域：播放栏 + 素材时间线
        bottom_area = QWidget()
        bottom_layout = QVBoxLayout(bottom_area)
        bottom_layout.setContentsMargins(0, 4, 0, 0)
        bottom_layout.setSpacing(4)
        self._playback_bar = self._create_playback_bar()
        bottom_layout.addWidget(self._playback_bar)
        # 素材时间线（T2V 模式可见）
        self._t2v_material_timeline = MaterialTimeline()
        self._t2v_material_timeline.material_selected.connect(self._on_t2v_material_selected)
        self._t2v_material_timeline.effects_requested.connect(self._on_t2v_material_fx)
        self._t2v_material_timeline.hide()
        bottom_layout.addWidget(self._t2v_material_timeline, 1)

        # 预览与底部区域垂直分割
        center_splitter = QSplitter(Qt.Orientation.Vertical)
        center_splitter.setHandleWidth(0)
        center_splitter.addWidget(self._preview_widget)
        center_splitter.addWidget(bottom_area)
        # 默认：预览占 70%，底部占 30%
        center_splitter.setStretchFactor(0, 7)
        center_splitter.setStretchFactor(1, 3)
        clip_layout.addWidget(center_splitter, 1)
        self._preview_timeline_splitter.addWidget(clip_center)

        # 翻译模式中心 => TranslatePanel（完整参数面板）
        from studio.translate_panel import TranslatePanel

        self.translate_panel = TranslatePanel()
        self.translate_panel.start_requested.connect(self._on_translate_start)
        self.translate_panel.stop_requested.connect(self._on_translate_stop)

        # 底部时间线
        self._timeline_widget = self._create_timeline_widget()
        self._preview_timeline_splitter.addWidget(self._timeline_widget)

        # 默认分配 65% 给预览，35% 给时间线
        self._preview_timeline_splitter.setStretchFactor(0, 3)
        self._preview_timeline_splitter.setStretchFactor(1, 2)

        center_col_layout.addWidget(self._preview_timeline_splitter, 1)
        self._center_col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # QStackedWidget 默认按最大子控件确定 sizeHint — 改为按当前控件
        class _CurrentSizeStack(QStackedWidget):
            def sizeHint(self):
                w = self.currentWidget()
                return w.sizeHint() if w else super().sizeHint()

            def minimumSizeHint(self):
                w = self.currentWidget()
                return w.minimumSizeHint() if w else super().minimumSizeHint()

        self._center_stack = _CurrentSizeStack()
        self._center_stack.addWidget(self._center_col)  # index 0
        self._center_stack.addWidget(self.translate_panel)  # index 1
        self.main_splitter.addWidget(self._center_stack)

        # 右面板（仅剪辑模式显示）
        self._right_panel = self._create_right_panel()
        self.main_splitter.addWidget(self._right_panel)

        self.main_splitter.setSizes([220, 640, 220])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)

        main_layout.addWidget(self.main_splitter, 1)

    # ── 左侧媒体面板 ──

    def _create_left_panel(self):
        panel = QWidget()
        panel.setObjectName("leftPanel")
        panel.setMinimumWidth(160)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._left_title = QLabel("  媒体素材")
        self._left_title.setFixedHeight(32)
        self._left_title.setStyleSheet("background-color:#222226; font-size:12px; color:#888888; padding-left:8px;")
        layout.addWidget(self._left_title)

        import_btn = QPushButton("  + 导入素材  ")
        self._import_btn = import_btn
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a8cff; color: #fff; border: none;
                border-radius: 4px; padding: 8px; margin: 8px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #4a9cff; }
        """)
        import_btn.clicked.connect(self._on_import_media)
        layout.addWidget(import_btn)

        # ── 左侧内容堆栈：媒体列表(0) / 字幕视图(1) ──
        self._left_stack = QStackedWidget()

        # Page 0: 可拖拽导入的列表
        class DropList(QListWidget):
            def __init__(self, parent_win):
                super().__init__()
                self._parent_win = parent_win
                self.setAcceptDrops(True)
                self.setDragEnabled(True)
                self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                self.customContextMenuRequested.connect(self._show_context_menu)

            def dragEnterEvent(self, e):
                if e.mimeData().hasUrls():
                    e.acceptProposedAction()

            def dragMoveEvent(self, e):
                if e.mimeData().hasUrls():
                    e.acceptProposedAction()

            def dropEvent(self, e):
                exts = {
                    ".mp4",
                    ".mov",
                    ".avi",
                    ".mkv",
                    ".webm",
                    ".wmv",
                    ".flv",
                    ".mp3",
                    ".wav",
                    ".aac",
                    ".m4a",
                    ".ogg",
                    ".srt",
                }
                paths = []
                for url in e.mimeData().urls():
                    path = url.toLocalFile()
                    if path and os.path.isfile(path) and os.path.splitext(path)[1].lower() in exts:
                        paths.append(path)
                if paths:
                    self._parent_win._add_media_files(paths)
                e.acceptProposedAction()

            def mimeData(self, items):
                md = QMimeData()
                urls = []
                for item in items:
                    path = item.data(Qt.ItemDataRole.UserRole)
                    if path:
                        urls.append(QUrl.fromLocalFile(path))
                if urls:
                    md.setUrls(urls)
                return md

            def _show_context_menu(self, pos):
                item = self.itemAt(pos)
                if not item:
                    return
                path = item.data(Qt.ItemDataRole.UserRole)
                if not path:
                    return
                menu = QMenu(self)
                menu.setStyleSheet("""
                    QMenu {
                        background-color: #222226;
                        border: 1px solid #3a3a42;
                        border-radius: 6px;
                        padding: 4px;
                    }
                    QMenu::item {
                        padding: 6px 20px;
                        border-radius: 4px;
                        color: #cccccc;
                        font-size: 13px;
                    }
                    QMenu::item:hover {
                        background-color: #2a2a32;
                        color: #ffffff;
                    }
                """)
                # addAction 内部创建 QAction，避免引用回收问题
                ext = os.path.splitext(path)[1].lower()
                audio_exts = {".mp3", ".wav", ".aac", ".m4a", ".ogg"}
                is_audio = ext in audio_exts
                menu.addAction("加载到时间轴", lambda p=path: self._parent_win._on_load_to_timeline(p))
                menu.addSeparator()
                menu.addAction("删除", lambda p=path: self._parent_win._on_delete_media(p))
                menu.addAction("替换素材", lambda p=path: self._parent_win._on_replace_media(p))
                menu.exec(self.mapToGlobal(pos))

            def resizeEvent(self, event):
                """列表宽度变化时更新所有 item 高度以适应换行文本"""
                super().resizeEvent(event)
                for i in range(self.count()):
                    item = self.item(i)
                    w = self.itemWidget(item)
                    if w:
                        item.setSizeHint(w.sizeHint())

        self.media_list = DropList(self)
        self.media_list.setAlternatingRowColors(False)
        self.media_list.setSpacing(2)
        self.media_list.viewport().setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.media_list.itemDoubleClicked.connect(self._on_media_selected)
        self.media_list.currentItemChanged.connect(self._on_media_current_changed)
        self._left_stack.addWidget(self.media_list)  # index 0

        # 不再将字幕视图放在左侧（移至右侧面板），但保留 left_stack 结构
        # 空白占位页，避免 index 1 越界
        placeholder = QWidget()
        self._left_stack.addWidget(placeholder)  # index 1

        # 文字生视频面板
        self._t2v_panel = TextToVideoPanel()
        self._t2v_panel.video_ready.connect(self._on_t2v_video_ready)
        self._t2v_panel.sources_changed.connect(self._on_t2v_sources_changed)
        self._left_stack.addWidget(self._t2v_panel)  # index 2

        layout.addWidget(self._left_stack, 1)

        return panel

    def _create_subtitle_view(self):
        """翻译模式左侧——字幕显示视图（并列式）"""
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)

        # 左侧：原文字幕
        src_widget = QWidget()
        src_layout = QVBoxLayout(src_widget)
        src_layout.setContentsMargins(0, 0, 2, 0)
        src_layout.setSpacing(4)

        src_header = QHBoxLayout()
        src_label = QLabel("原文字幕")
        src_label.setStyleSheet("color:#3a8cff; font-size:12px; font-weight:bold;")
        src_header.addWidget(src_label)
        src_header.addStretch()
        self._src_import_btn = QPushButton("📂 导入")
        self._src_import_btn.setFixedHeight(22)
        self._src_import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a2a3a; color: #6ab4ff;
                border: 1px solid #2a3a4a; border-radius: 3px;
                font-size: 11px; padding: 0 8px;
            }
            QPushButton:hover { background-color: #2a3a5a; }
        """)
        self._src_import_btn.clicked.connect(self._on_import_src_sub)
        src_header.addWidget(self._src_import_btn)
        src_layout.addLayout(src_header)

        self._src_sub_edit = QPlainTextEdit()
        self._src_sub_edit.setReadOnly(True)
        self._src_sub_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0d0d0f; color: #e0e0e0;
                border: 1px solid #2a2a30; border-radius: 4px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px; padding: 4px;
            }
        """)
        src_layout.addWidget(self._src_sub_edit, 1)
        splitter.addWidget(src_widget)

        # 右侧：翻译字幕
        tgt_widget = QWidget()
        tgt_layout = QVBoxLayout(tgt_widget)
        tgt_layout.setContentsMargins(2, 0, 0, 0)
        tgt_layout.setSpacing(4)

        tgt_header = QHBoxLayout()
        tgt_label = QLabel("翻译字幕")
        tgt_label.setStyleSheet("color:#8bc34a; font-size:12px; font-weight:bold;")
        tgt_header.addWidget(tgt_label)
        tgt_header.addStretch()
        self._tgt_import_btn = QPushButton("📂 导入")
        self._tgt_import_btn.setFixedHeight(22)
        self._tgt_import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a2a1a; color: #8bc34a;
                border: 1px solid #2a3a2a; border-radius: 3px;
                font-size: 11px; padding: 0 8px;
            }
            QPushButton:hover { background-color: #2a4a2a; }
        """)
        self._tgt_import_btn.clicked.connect(self._on_import_tgt_sub)
        tgt_header.addWidget(self._tgt_import_btn)
        tgt_layout.addLayout(tgt_header)

        self._tgt_sub_edit = QPlainTextEdit()
        self._tgt_sub_edit.setReadOnly(True)
        self._tgt_sub_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0d0d0f; color: #e0e0e0;
                border: 1px solid #2a2a30; border-radius: 4px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px; padding: 4px;
            }
        """)
        tgt_layout.addWidget(self._tgt_sub_edit, 1)
        splitter.addWidget(tgt_widget)

        splitter.setSizes([300, 300])
        layout.addWidget(splitter, 1)

        return view

    # ── 预览播放器 ──

    def _create_preview_widget(self):
        preview = PreviewWidget()
        preview.setObjectName("previewWidget")

        # 预览信号 → 主窗口
        preview.play_state_changed.connect(self._on_play_state)
        preview.position_changed.connect(self._on_position_changed)
        preview.duration_changed.connect(self._on_duration_changed)
        preview.play_finished.connect(self._on_play_finished)
        preview.timeline_link_changed.connect(self._on_timeline_link_changed)
        preview.play_requested.connect(self._on_play_pause)

        return preview

    def _create_playback_bar(self):
        bar = QWidget()
        bar.setMinimumHeight(36)
        bar.setStyleSheet("background-color: #222226; border-radius: 4px;")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # 跳转到开头
        self.btn_go_start = QPushButton(" ⏮ ")
        self.btn_go_start.setFixedSize(36, 28)
        self.btn_go_start.setToolTip("跳转到视频开头")
        self.btn_go_start.setStyleSheet(
            "background-color:#2a2a32; color:#ccc; border:1px solid #3a3a42; border-radius:4px; font-size:14px;"
        )
        self.btn_go_start.clicked.connect(self._on_go_start)
        layout.addWidget(self.btn_go_start)

        # 播放
        self.btn_play = QPushButton(" ▶ ")
        self.btn_play.setFixedSize(36, 28)
        self.btn_play.setToolTip("播放视频")
        self.btn_play.setStyleSheet(
            "background-color:#3a8cff; color:#fff; border:none; border-radius:4px; font-size:14px;"
        )
        self.btn_play.clicked.connect(self._on_play)
        layout.addWidget(self.btn_play)

        # 暂停
        self.btn_pause = QPushButton(" ⏸ ")
        self.btn_pause.setFixedSize(36, 28)
        self.btn_pause.setToolTip("暂停视频")
        self.btn_pause.setStyleSheet(
            "background-color:#2a2a32; color:#ccc; border:1px solid #3a3a42; border-radius:4px; font-size:14px;"
        )
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_pause.setVisible(False)
        layout.addWidget(self.btn_pause)

        # 跳转到结尾
        self.btn_go_end = QPushButton(" ⏭ ")
        self.btn_go_end.setFixedSize(36, 28)
        self.btn_go_end.setToolTip("跳转到视频结尾")
        self.btn_go_end.setStyleSheet(
            "background-color:#2a2a32; color:#ccc; border:1px solid #3a3a42; border-radius:4px; font-size:14px;"
        )
        self.btn_go_end.clicked.connect(self._on_go_end)
        layout.addWidget(self.btn_go_end)

        # 时间标签（点击弹出对话框输入时间跳转）
        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet(
            "background-color:#2a2a32; color:#ccc; border:1px solid #3a3a42; border-radius:4px; font-size:12px; padding:2px 10px;"
        )
        self.lbl_time.setToolTip("点击输入时间跳转")
        self.lbl_time.mousePressEvent = lambda e: self._on_time_label_click()
        layout.addWidget(self.lbl_time)

        # 后退一帧
        self.btn_prev_frame = QPushButton(" 上一帧 ")
        self.btn_prev_frame.setFixedSize(72, 28)
        self.btn_prev_frame.setToolTip("后退一帧 (←)")
        self.btn_prev_frame.setStyleSheet(
            "background-color:#2a2a32; color:#ccc; border:1px solid #3a3a42; border-radius:4px; font-size:12px;"
        )
        self.btn_prev_frame.clicked.connect(self._on_prev_frame)
        layout.addWidget(self.btn_prev_frame)

        # 前进一帧
        self.btn_next_frame = QPushButton(" 下一帧 ")
        self.btn_next_frame.setFixedSize(72, 28)
        self.btn_next_frame.setToolTip("前进一帧 (→)")
        self.btn_next_frame.setStyleSheet(
            "background-color:#2a2a32; color:#ccc; border:1px solid #3a3a42; border-radius:4px; font-size:12px;"
        )
        self.btn_next_frame.clicked.connect(self._on_next_frame)
        layout.addWidget(self.btn_next_frame)

        # 速度控制（三个独立按钮）
        btn_ss = "background-color:#2a4a2a; color:#8c8; border:1px solid #3a5a3a; border-radius:4px; font-size:12px;"

        self.btn_slow = QPushButton("慢速")
        self.btn_slow.setFixedSize(68, 28)
        self.btn_slow.setToolTip("慢速播放")
        self.btn_slow.setStyleSheet(btn_ss)
        slow_menu = QMenu(self)
        for v in [0.5, 1.0, 1.5, 2.0]:
            action = slow_menu.addAction(f"×{v:.1f}")
            action.triggered.connect(lambda checked, s=v, lbl=f"×{v:.1f}": self._set_speed(s, lbl))
        self.btn_slow.setMenu(slow_menu)
        layout.addWidget(self.btn_slow)

        self.btn_normal = QPushButton("正常")
        self.btn_normal.setFixedSize(56, 28)
        self.btn_normal.setToolTip("正常速度 1×")
        self.btn_normal.setStyleSheet(btn_ss)
        self.btn_normal.clicked.connect(lambda: self._set_speed(1.0, "正常"))
        layout.addWidget(self.btn_normal)

        self.btn_fast = QPushButton("加速")
        self.btn_fast.setFixedSize(68, 28)
        self.btn_fast.setToolTip("加速播放")
        self.btn_fast.setStyleSheet(btn_ss)
        fast_menu = QMenu(self)
        for v in [1.5, 2.5, 3.0, 4.0, 5.0]:
            action = fast_menu.addAction(f"×{v:.1f}")
            action.triggered.connect(lambda checked, s=v, lbl=f"×{v:.1f}": self._set_speed(s, lbl))
        self.btn_fast.setMenu(fast_menu)
        layout.addWidget(self.btn_fast)

        # 特效入口（T2V 模式：当前选中素材；剪辑模式：当前选中片段）
        self.btn_fx = QPushButton(" 特效 ")
        self.btn_fx.setFixedSize(60, 28)
        self.btn_fx.setToolTip("为当前素材/片段添加视频特效")
        self.btn_fx.setStyleSheet(
            "background-color:#3a2a1a; color:#ff9800; border:1px solid #5a3a2a; border-radius:4px; font-size:12px;"
        )
        self.btn_fx.clicked.connect(self._on_fx_click)
        layout.addWidget(self.btn_fx)

        # ── 剪辑专用编辑工具 ──
        self._clip_tools = []

        self.btn_split = QPushButton(" 分割 ")
        self.btn_split.setFixedSize(60, 28)
        self.btn_split.setToolTip("在当前位置分割素材 (S)")
        self.btn_split.setStyleSheet(
            "background-color:#5a3a2a; color:#f90; border:1px solid #6a4a3a; border-radius:4px; font-size:14px;"
        )
        self.btn_split.clicked.connect(self._on_split_click)
        layout.addWidget(self.btn_split)
        self._clip_tools.append(self.btn_split)

        self.btn_lock = QPushButton(" 锁 ")
        self.btn_lock.setFixedSize(52, 28)
        self.btn_lock.setToolTip("锁定素材 — 固定位置或完全锁定")
        self.btn_lock.setStyleSheet(
            "background-color:#3a2a3a; color:#c8c; border:1px solid #5a3a5a; border-radius:4px; font-size:12px;"
        )
        self.btn_lock.clicked.connect(self._on_lock_clip)
        layout.addWidget(self.btn_lock)
        self._clip_tools.append(self.btn_lock)

        self._snap_btn = QPushButton(" 吸附 ")
        self._snap_btn.setCheckable(True)
        self._snap_btn.setChecked(True)
        self._snap_btn.setFixedSize(56, 28)
        self._snap_btn.setToolTip("拖拽素材时吸附到边缘和指针")
        self._snap_btn.setStyleSheet(
            "QPushButton { background:#2a2a32; color:#aaa; border:1px solid #3a3a42; "
            "border-radius:4px; font-size:12px; } "
            "QPushButton:checked { background:#3a8cff; color:#fff; border-color:#3a8cff; }"
        )
        self._snap_btn.toggled.connect(self._on_toggle_snap)
        layout.addWidget(self._snap_btn)
        self._clip_tools.append(self._snap_btn)

        self._mute_btn = QPushButton(" 静音 ")
        self._mute_btn.setCheckable(True)
        self._mute_btn.setFixedSize(56, 28)
        self._mute_btn.setToolTip("静音选中素材")
        self._mute_btn.setStyleSheet(
            "QPushButton { background:#2a2a32; color:#aaa; border:1px solid #3a3a42; "
            "border-radius:4px; font-size:12px; } "
            "QPushButton:checked { background:#cc4444; color:#fff; border-color:#cc4444; }"
        )
        self._mute_btn.toggled.connect(self._on_toggle_mute)
        layout.addWidget(self._mute_btn)
        self._clip_tools.append(self._mute_btn)

        self._proxy_btn = QPushButton(" 代理 ")
        self._proxy_btn.setFixedSize(56, 28)
        self._proxy_btn.setToolTip("为选中素材生成低分辨率代理，提升剪辑流畅度")
        self._proxy_btn.setStyleSheet(
            "QPushButton { background:#2a2a32; color:#aaa; border:1px solid #3a3a42; "
            "border-radius:4px; font-size:12px; } "
            "QPushButton:hover { border-color:#3a8cff; color:#3a8cff; }"
        )
        self._proxy_btn.clicked.connect(self._on_proxy)
        layout.addWidget(self._proxy_btn)
        self._clip_tools.append(self._proxy_btn)

        self._fx_btn = QPushButton(" 特效 ")
        self._fx_btn.setFixedSize(56, 28)
        self._fx_btn.setToolTip("为选中素材添加视频特效（滤镜链）")
        self._fx_btn.setStyleSheet(
            "QPushButton { background:#2a2a3a; color:#8af; border:1px solid #3a5a6a; "
            "border-radius:4px; font-size:12px; } "
            "QPushButton:hover { border-color:#5a9cff; color:#5a9cff; } "
            "QPushButton:disabled { background:#1a1a22; color:#444; border-color:#2a2a32; }"
        )
        self._fx_btn.clicked.connect(self._on_fx_click)
        layout.addWidget(self._fx_btn)
        self._clip_tools.append(self._fx_btn)

        layout.addStretch()

        return bar

    # ── 右侧参数面板 ──

    def _create_right_panel(self):
        panel = QWidget()
        panel.setObjectName("rightPanel")
        panel.setMinimumWidth(180)
        panel.setMinimumHeight(100)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 模式切换堆栈 ──
        self._param_stack = QStackedWidget()

        # ── 剪辑模式面板 ──
        clip_panel = QWidget()
        clip_layout = QVBoxLayout(clip_panel)
        clip_layout.setContentsMargins(4, 4, 4, 4)
        clip_layout.setSpacing(4)

        prop_title = QLabel("属性")
        prop_title.setStyleSheet("font-size:12px; color:#888888; padding:4px 0;")
        clip_layout.addWidget(prop_title)

        # 属性面板（表单式）
        self._prop_scroll = QScrollArea()
        self._prop_scroll.setWidgetResizable(True)
        self._prop_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._prop_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._prop_widget = QWidget()
        self._prop_widget.setStyleSheet("background: transparent;")
        self._prop_layout = QVBoxLayout(self._prop_widget)
        self._prop_layout.setContentsMargins(0, 0, 0, 0)
        self._prop_layout.setSpacing(1)
        self._prop_labels: dict[str, QLabel] = {}

        # 初始化属性行
        for key, label_text in [
            ("filename", "文件名"),
            ("path", "路径"),
            ("type", "类型"),
            ("timeline_start", "时间线起始"),
            ("timeline_end", "时间线结束"),
            ("duration", "时长"),
            ("source_offset", "源偏移"),
            ("speed", "速度"),
            ("muted", "静音"),
            ("locked", "锁定"),
            ("resolution_orig", "原始分辨率"),
            ("resolution_target", "目标分辨率"),
            ("effects", "特效"),
        ]:
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 2, 6, 2)
            row_layout.setSpacing(8)

            key_label = QLabel(label_text)
            key_label.setFixedWidth(72)
            key_label.setStyleSheet("color: #777; font-size: 11px; background: transparent;")
            row_layout.addWidget(key_label)

            val_label = QLabel("—")
            val_label.setStyleSheet("color: #d0d0d0; font-size: 11px; background: transparent;")
            val_label.setWordWrap(True)
            row_layout.addWidget(val_label, 1)

            self._prop_layout.addWidget(row)
            self._prop_labels[key] = val_label

        self._prop_layout.addStretch()
        self._prop_scroll.setWidget(self._prop_widget)
        self._prop_scroll.hide()  # 未选中素材时隐藏
        clip_layout.addWidget(self._prop_scroll, 1)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self.btn_export_clip = QPushButton("导出合并")
        self.btn_export_clip.setFixedHeight(26)
        self.btn_export_clip.setStyleSheet(
            "background-color:#2a2a32; color:#ccc; border:1px solid #3a3a42; border-radius:4px; padding:0 8px; font-size:11px;"
        )
        self.btn_export_clip.clicked.connect(self._on_export_clip)
        btn_row.addWidget(self.btn_export_clip)

        clip_layout.addLayout(btn_row)

        # ── 发送给翻译配音 ──
        self.btn_to_trans = QPushButton("  🎤 发送给翻译配音  ")
        self.btn_to_trans.setFixedHeight(30)
        self.btn_to_trans.setStyleSheet("""
            QPushButton {
                background-color: #2a4a3a; color: #8bc34a;
                border: 1px solid #3a5a3a; border-radius: 4px;
                padding: 0 8px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3a5a4a; }
        """)
        self.btn_to_trans.setToolTip("将当前视频发送到翻译配音模式进行处理")
        self.btn_to_trans.clicked.connect(self._on_send_to_translate)
        clip_layout.addWidget(self.btn_to_trans)

        self._param_stack.addWidget(clip_panel)  # index 0

        # Page 1: 翻译模式右侧字幕视图
        self._translate_sub_view = self._create_subtitle_view()
        self._param_stack.addWidget(self._translate_sub_view)  # index 1

        # 文字生视频：素材浏览器 + 分镜脚本（垂直分割）
        t2v_right = QWidget()
        t2v_right_layout = QVBoxLayout(t2v_right)
        t2v_right_layout.setContentsMargins(0, 0, 0, 0)
        t2v_right_layout.setSpacing(0)

        t2v_splitter = QSplitter(Qt.Orientation.Vertical)
        t2v_splitter.setHandleWidth(3)
        t2v_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #2a2a30; } " "QSplitter::handle:hover { background-color: #3a8cff; }"
        )

        # 素材浏览器
        self._t2v_media_browser = MediaBrowser()
        t2v_splitter.addWidget(self._t2v_media_browser)

        # 分镜脚本（从 t2v_panel 取出，放入右侧面板，组件自带标题）
        t2v_splitter.addWidget(self._t2v_panel.storyboard)
        t2v_splitter.setStretchFactor(0, 2)
        t2v_splitter.setStretchFactor(1, 3)

        t2v_right_layout.addWidget(t2v_splitter, 1)
        self._param_stack.addWidget(t2v_right)  # index 2

        self._param_stack.setCurrentIndex(0)  # 默认剪辑模式

        layout.addWidget(self._param_stack, 1)

        return panel

    # ── 底部时间线 ──

    def _create_timeline_widget(self):
        tl = TimelineWidget()
        tl.setObjectName("timelineWidget")
        tl.seek_requested.connect(self._on_timeline_seek)
        tl.clips_changed.connect(self._on_timeline_clips_changed)
        tl.subtitle_edit_requested.connect(self._on_timeline_subtitle_edit)
        tl.clip_selected.connect(self._on_timeline_clip_selected)
        tl.clip_changed.connect(self._on_timeline_clip_changed)
        tl.subtitle_selected.connect(self._on_timeline_subtitle_selected)
        tl.resolution_mismatch.connect(self._on_resolution_mismatch)
        tl.dub_requested.connect(self._on_timeline_dub_requested)
        tl.dub_local_requested.connect(self._on_timeline_dub_local_requested)
        return tl

    # ── 状态栏 ──

    def _init_status_bar(self):
        sb = QStatusBar()
        sb.setFixedHeight(28)
        self.setStatusBar(sb)

        self._status_label = QLabel("就绪")
        self._pipeline_step = ""  # 当前管线执行步骤名称
        self._pipeline_pct = 0  # 当前进度百分比
        # 字幕编辑暂停/恢复同步原语
        self._subtitle_edit_file = None
        self._subtitle_edit_pending = False
        self._subtitle_dialog_open = False
        self._subtitle_resume = threading.Event()
        sb.addWidget(self._status_label)

        self._status_gpu = QLabel("")
        self._status_gpu.setStyleSheet("color:#888888;")
        sb.addPermanentWidget(self._status_gpu)

    # ── 快捷键 ──

    def _init_shortcuts(self):
        sc = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(self._on_play_pause)

        # ← → 逐帧
        self._prev_frame_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        self._prev_frame_shortcut.activated.connect(self._on_prev_frame)

        self._next_frame_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        self._next_frame_shortcut.activated.connect(self._on_next_frame)

        # ? 快捷键面板
        self._shortcuts_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Slash), self)
        self._shortcuts_shortcut.activated.connect(self._show_shortcuts)

        # Home → 时间线适应
        self._home_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Home), self)
        self._home_shortcut.activated.connect(self._on_timeline_zoom_fit)

        # Ctrl+Z → 撤销
        self._undo_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_Z), self)
        self._undo_shortcut.activated.connect(self._on_undo)

        # Ctrl+Shift+Z → 重做
        self._redo_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Modifier.SHIFT | Qt.Key.Key_Z), self)
        self._redo_shortcut.activated.connect(self._on_redo)

        # Ctrl+S → 保存项目
        self._save_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_S), self)
        self._save_shortcut.activated.connect(self._on_save_project)

        # Ctrl+Shift+S → 另存为
        self._save_as_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Modifier.SHIFT | Qt.Key.Key_S), self)
        self._save_as_shortcut.activated.connect(self._on_save_project_as)

        # Ctrl+O → 打开项目
        self._open_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_O), self)
        self._open_shortcut.activated.connect(self._on_open_project)

        # Ctrl+E → 导出
        self._export_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_E), self)
        self._export_shortcut.activated.connect(self._on_export_clip)

    # ── 快捷键面板 ──

    def _show_shortcuts(self):
        """按 ? 显示快捷键列表"""
        dlg = QDialog(self)
        dlg.setWindowTitle("快捷键")
        dlg.setMinimumSize(480, 420)
        dlg.setStyleSheet("""
            QDialog { background-color: #1e1e22; color: #e0e0e0; }
            QTableWidget {
                background-color: #1a1a1e; color: #d0d0d0;
                border: 1px solid #2a2a30; gridline-color: #2a2a30;
                font-size: 13px;
            }
            QTableWidget::item { padding: 6px 12px; }
            QHeaderView::section {
                background-color: #222226; color: #888888;
                border: 1px solid #2a2a30; padding: 6px;
                font-size: 12px; font-weight: bold;
            }
        """)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("快捷键参考")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff; padding-bottom: 8px;")
        layout.addWidget(title)

        shortcuts_data = [
            ("空格", "播放 / 暂停"),
            ("←", "后退一帧"),
            ("→", "前进一帧"),
            ("Delete / Backspace", "删除选中素材"),
            ("S", "分割素材"),
            ("Ctrl+S", "保存项目"),
            ("Ctrl+Shift+S", "另存为"),
            ("Ctrl+O", "打开项目"),
            ("Ctrl+Q", "退出"),
            ("? / /", "显示本面板"),
        ]

        table = QTableWidget(len(shortcuts_data), 2)
        table.setHorizontalHeaderLabels(["按键", "功能"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        for row, (key, desc) in enumerate(shortcuts_data):
            table.setItem(row, 0, QTableWidgetItem(f"  {key}  "))
            table.setItem(row, 1, QTableWidgetItem(desc))

        table.setStyleSheet("""
            QTableWidget { background-color: #1a1a1e; color: #d0d0d0;
                border: 1px solid #2a2a30; font-size: 13px; }
            QTableWidget::item { padding: 6px 12px; }
        """)
        layout.addWidget(table, 1)

        btn = QPushButton("关闭")
        btn.setObjectName("accentBtn")
        btn.setFixedWidth(100)
        btn.clicked.connect(dlg.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

        dlg.exec()

    # ── 模式切换 ──

    def _switch_mode(self, mode):
        self._current_mode = mode
        is_clip = mode == "clip"
        is_trans = mode == "translate"
        is_t2v = mode == "text_to_video"

        self.btn_clip_mode.setChecked(is_clip)
        self.btn_trans_mode.setChecked(is_trans)
        self.btn_t2v_mode.setChecked(is_t2v)

        # 先断开所有 T2V 信号，避免重复连接累积
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for sig, slot in [
                (self._t2v_panel.storyboard.shot_selected, self._on_t2v_shot_selected),
                (self._t2v_media_browser.material_selected, self._on_t2v_browser_material_selected),
                (self._t2v_media_browser.material_double_clicked, self._on_t2v_browser_material_double_clicked),
            ]:
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass

        if is_t2v:
            # 文字生视频布局：左侧=输入面板，中央=预览+播放条+素材时间线，右侧=分镜脚本+素材浏览器
            self._preview_widget.set_timeline_link_visible(True)
            self._param_stack.setCurrentIndex(2)
            self._center_stack.setCurrentIndex(0)
            self._left_stack.setCurrentIndex(2)
            self._left_title.setText("  文字生视频")
            self._import_btn.hide()
            self._right_panel.show()
            self._timeline_widget.hide()
            self._playback_bar.show()
            self._t2v_material_timeline.show()
            self._set_clip_tools_visible(False)
            # 塌缩垂直分割器时间线区域 → 预览+播放条+素材时间线占满中心
            total_h = sum(self._preview_timeline_splitter.sizes())
            if total_h > 0:
                self._preview_timeline_splitter.setSizes([total_h, 0])
            self.main_splitter.setStretchFactor(0, 1)
            self.main_splitter.setStretchFactor(1, 2)
            self.main_splitter.setStretchFactor(2, 1)
            self._t2v_media_browser.set_sources(self._t2v_panel.get_sources_config())
            # 连接分镜选中 → 素材时间线
            self._t2v_panel.storyboard.shot_selected.connect(self._on_t2v_shot_selected)
            # 连接素材浏览器卡片点击
            self._t2v_media_browser.material_selected.connect(self._on_t2v_browser_material_selected)
            self._t2v_media_browser.material_double_clicked.connect(self._on_t2v_browser_material_double_clicked)
        elif is_clip:
            # 剪辑布局：左侧=媒体列表，中央=预览+播放条，右侧=片段列表
            self._preview_widget.set_timeline_link_visible(False)
            self._param_stack.setCurrentIndex(0)
            self._center_stack.setCurrentIndex(0)
            self._left_stack.setCurrentIndex(0)
            self._left_title.setText("  媒体素材")
            self._import_btn.show()
            self._right_panel.show()
            self._playback_bar.show()
            self._t2v_material_timeline.hide()
            self._timeline_widget.show()
            self._set_clip_tools_visible(True)
            # 恢复垂直分割器比例：预览 60% / 时间线 40%
            total_h = sum(self._preview_timeline_splitter.sizes()) or 1
            self._preview_timeline_splitter.setSizes([total_h * 3 // 5, total_h * 2 // 5])
            self.main_splitter.setStretchFactor(0, 0)
            self.main_splitter.setStretchFactor(1, 1)
            self.main_splitter.setStretchFactor(2, 0)
        else:
            # 翻译布局：左侧=媒体列表，中央=翻译参数面板，右侧=字幕视图
            self._param_stack.setCurrentIndex(1)
            self._center_stack.setCurrentIndex(1)
            self._left_stack.setCurrentIndex(0)
            self._left_title.setText("  媒体素材")
            self._import_btn.show()
            self._timeline_widget.hide()
            self._playback_bar.hide()
            self._t2v_material_timeline.hide()
            self._set_clip_tools_visible(False)
            self._preview_widget.set_timeline_link_visible(False)
            self.main_splitter.setStretchFactor(0, 0)
            self.main_splitter.setStretchFactor(1, 1)
            self.main_splitter.setStretchFactor(2, 0)

        self._update_mode_label()
        self._preview_widget.set_mode(mode)

    def _set_clip_tools_visible(self, visible: bool):
        """显示/隐藏剪辑专用工具按钮（分割/锁/吸附/静音/代理）"""
        for btn in getattr(self, "_clip_tools", []):
            btn.setVisible(visible)

    def _update_mode_label(self):
        names = {"clip": "剪辑模式", "translate": "翻译配音模式", "text_to_video": "文字生视频模式"}
        self._mode_label.setText(f"  {names.get(self._current_mode, '')}  ")

    def _on_timeline_link_changed(self, linked: bool):
        """时间线联动开关切换 → 勾选时同步预览到时间线当前位置"""
        if not linked:
            return
        sel = self._timeline_widget._selected
        if sel:
            # 有选中素材 → 加载素材视频 + 跳转到素材开头
            vid_path = sel.proxy_path or sel.source_path
            if vid_path and os.path.exists(vid_path):
                self._load_video(vid_path, sel.source_path if sel.proxy_path else "")
            self._preview_widget.set_active_duration(sel.duration, sel.speed)
            self._preview_widget.set_source_offset(sel.source_start)
            QTimer.singleShot(80, lambda: self._preview_widget.seek(0.0))
        elif self._preview_widget.current_path:
            # 无选中素材但预览有内容 → 跳转到时间线当前位置
            self._preview_widget.set_active_duration(0.0)
            self._preview_widget.set_source_offset(0.0)
            tpos = self._timeline_widget.position
            self._preview_widget.seek(tpos)

    def _on_send_to_translate(self):
        """剪辑模式 → 发送给翻译配音"""
        if not self._preview_widget.current_path:
            self._status_label.setText("请先加载视频素材")
            return
        self._switch_mode("translate")
        self._status_label.setText("已切换到翻译配音模式")

    def _on_t2v_video_ready(self, path: str):
        """文字生视频合成完成后，加入素材库并加载预览"""
        if os.path.exists(path) and path not in self._media_paths:
            self._add_media_files([path])
        if os.path.exists(path):
            self._load_video(path)
            self._status_label.setText(f"已生成视频并加入素材库: {os.path.basename(path)}")

    def _on_t2v_sources_changed(self, sources: dict):
        """左侧素材源勾选变化 → 同步右侧素材浏览器"""
        self._t2v_media_browser.set_sources(sources)

    def _on_t2v_shot_selected(self, index: int, shot):
        """分镜卡片被选中 → 素材时间线显示该镜头的素材"""
        materials = []
        for m in getattr(shot, "materials", []) or []:
            if isinstance(m, dict):
                materials.append(_dict_to_material(m))
        self._t2v_material_timeline.set_materials(materials)
        self._status_label.setText(f"选中镜头 {index + 1}: {shot.text[:30]}...")
        # 加载首选素材到预览
        if shot.material_path and os.path.exists(shot.material_path):
            self._load_video(shot.material_path)

    def _on_t2v_material_selected(self, index: int, material):
        """素材时间线中某个素材被点击 → 预览"""
        if material.local_path and os.path.exists(material.local_path):
            self._load_video(material.local_path)
            self._status_label.setText(f"预览素材 {index + 1}: [{material.source}]")
        else:
            self._status_label.setText(f"素材 {index + 1} [{material.source}] 尚未下载到本地，请先执行「搜索素材」")

    def _on_t2v_browser_material_selected(self, material):
        """媒体浏览器中素材卡片被点击 → 预览"""
        if material.local_path and os.path.exists(material.local_path):
            self._load_video(material.local_path)
            self._status_label.setText(f"预览: [{material.source}] {material.description or ''}")
        else:
            self._status_label.setText(f"[{material.source}] 素材未缓存本地")

    def _on_t2v_browser_material_double_clicked(self, material):
        """媒体浏览器中素材卡片被双击 → 替换当前选中镜头首选素材"""
        sel_idx = self._t2v_material_timeline.get_selected_index()
        shots = self._t2v_panel.get_shots()
        sel_shot_idx = -1
        # 找到当前在素材时间线中显示的镜头（即有素材被选中的镜头）
        for i, shot in enumerate(shots):
            if sel_idx >= 0 and shot.materials and sel_idx < len(shot.materials):
                sel_shot_idx = i
                break
        if sel_shot_idx < 0:
            self._status_label.setText("请先在素材时间线中选中一个镜头")
            return
        shot = shots[sel_shot_idx]
        shot.material_path = material.local_path or material.url
        shot.material_source = material.source
        # 将浏览器素材插入到 shot.materials 首位
        mat_dict = {
            "source": material.source,
            "url": material.url,
            "preview_url": material.preview_url,
            "description": material.description,
            "author": material.author,
            "width": material.width,
            "height": material.height,
            "duration": material.duration,
            "media_type": material.media_type,
            "local_path": material.local_path,
            "effects": [],
        }
        if shot.materials:
            shot.materials.insert(0, mat_dict)
        else:
            shot.materials = [mat_dict]
        # 刷新素材时间线
        materials = [_dict_to_material(m) for m in shot.materials]
        self._t2v_material_timeline.set_materials(materials)
        self._t2v_material_timeline.select_material(0)
        if material.local_path and os.path.exists(material.local_path):
            self._load_video(material.local_path)
        self._status_label.setText(f"已替换镜头素材: [{material.source}] {material.description or ''}")

    def _on_t2v_material_fx(self, index: int, material):
        """素材特效按钮被点击 → 打开特效对话框，实时预览"""
        from studio.editor.effects_dialog import EffectsDialog

        # 加载素材到预览并暂停
        if material.local_path and os.path.exists(material.local_path):
            self._load_video(material.local_path)
            self._preview_widget.pause()

        # 预览回调：实时更新特效效果
        def _preview_fx(effects: list):
            if not material.local_path or not os.path.exists(material.local_path):
                return
            try:
                from studio.editor.effects import build_ffmpeg_filter_chain

                chain = build_ffmpeg_filter_chain(effects)
                if not chain:
                    # 无特效 → 显示原始帧
                    pix = (
                        self._preview_widget._extractor._extract_frame_at(0.0)
                        if hasattr(self._preview_widget, "_extractor")
                        else None
                    )
                    if pix is None:
                        pix = self._preview_widget._pixmap_item.pixmap()
                    if pix:
                        self._preview_widget.show_still_frame(pix)
                    return
                # 有特效 → ffmpeg 提取单帧应用滤镜
                import os

                tmpdir = tempfile.mkdtemp(prefix="fx_preview_")
                out_frame = os.path.join(tmpdir, "frame.png")
                # 视频用 -ss 0.5 取帧避免黑场
                is_video = material.media_type == "video" and material.duration > 0
                cmd = ["ffmpeg", "-y"]
                if is_video:
                    cmd += ["-ss", "0.5"]
                cmd += ["-i", material.local_path]
                if not is_video:
                    cmd += ["-t", "1"]
                cmd += [
                    "-vframes",
                    "1",
                    "-vf",
                    chain,
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-s",
                    "480x270",
                    out_frame.replace(".png", ".raw"),
                ]
                subprocess.run(cmd, capture_output=True, timeout=15)
                raw = out_frame.replace(".png", ".raw")
                if os.path.exists(raw) and os.path.getsize(raw) > 0:
                    from PySide6.QtGui import QImage, QPixmap

                    img = QImage(raw, 480, 270, QImage.Format.Format_RGB888)
                    pix = QPixmap.fromImage(img)
                    self._preview_widget.show_still_frame(pix)
                elif os.path.exists(out_frame):
                    pix = QPixmap(out_frame)
                    if not pix.isNull():
                        self._preview_widget.show_still_frame(pix)
                import shutil

                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

        label = f"素材 {index + 1} [{material.source}]"
        dlg = EffectsDialog(label, material.effects, self, preview_callback=_preview_fx)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_effects = dlg.get_effects()
            self._t2v_material_timeline.update_material_effects(index, new_effects)
            # 同步更新到 input_panel 的 shots 数据
            shots = self._t2v_panel.get_shots()
            if shots:
                sel_idx = self._t2v_material_timeline.get_selected_index()
                # 找到当前选中的 shot 并更新其 materials
                for shot in shots:
                    if shot.materials and index < len(shot.materials):
                        shot.materials[index]["effects"] = [
                            {"effect_id": e.effect_id, "params": e.params, "enabled": e.enabled} for e in new_effects
                        ]
            self._status_label.setText(f"已为素材 {index + 1} 添加 {len(new_effects)} 个特效")
        self._preview_widget.clear_still_frame()

    def _on_play_state(self, playing: bool):
        self.btn_play.setVisible(not playing)
        self.btn_pause.setVisible(playing)

    def _on_position_changed(self, pos: float):
        """预览位置更新 → 同步到时间线和播放条"""
        # pos 是素材相对位置（含 source_offset 转换）
        sel = self._timeline_widget._selected
        if sel:
            timeline_pos = sel.start + pos
        else:
            timeline_pos = pos
        self._timeline_widget.set_position(timeline_pos)
        self._update_time_display(timeline_pos)
        # 查找当前时间对应的字幕
        sub_text = ""
        for e in self._timeline_widget._subtitle_entries:
            if e.start <= timeline_pos <= e.end:
                sub_text = e.text
                break
        self._preview_widget.set_subtitle(sub_text, self._timeline_widget._subtitle_font_size)
        # 只播放选中素材的范围
        if self._preview_widget.is_playing():
            if sel and pos >= sel.duration:
                self._preview_widget.pause()
                return
            # 跳过已删除素材的空档
            clips = sorted(self._timeline_widget._clips, key=lambda c: c.start)
            in_clip = any(c.start <= timeline_pos < c.end for c in clips)
            if not in_clip and clips:
                next_start = None
                for c in clips:
                    if c.start > timeline_pos:
                        next_start = c.start
                        break
                if next_start is not None:
                    self._preview_widget.seek(next_start)

    def _on_duration_changed(self, dur: float):
        """视频时长变化 → 更新时间线标尺"""
        if self._timeline_widget._clips:
            # 已有素材时，时间线长度由素材决定，不受预览视频时长影响
            self._timeline_widget._update_duration()
        else:
            self._timeline_widget.set_duration(dur)
        # 如果标记了等待加载到时间轴，则创建素材
        if getattr(self, "_pending_timeline_load", False):
            path = self._current_video or ""
            if path:
                self._timeline_widget.load_video(path, dur)
            self._pending_timeline_load = False

    def _on_timeline_clips_changed(self):
        """时间线素材变化 → 同步预览的有效播放范围 + 刷新音频"""
        ranges = self._timeline_widget.get_video_ranges()
        self._preview_widget.set_clip_ranges(ranges)
        self._preview_widget.refresh_audio()

    def _on_timeline_seek(self, sec: float):
        """时间线 seek → 预览跳转（全局绝对位置）"""
        if not self._preview_widget.timeline_linked:
            return
        self._preview_widget.seek(sec)

    def _on_timeline_zoom_fit(self):
        """Home → 时间线适应全部素材"""
        self._timeline_widget._zoom_to_fit()

    def _on_timeline_clip_selected(self, clip):
        """选中素材 → 跳转到素材开头 + 更新时间显示 + 刷新属性面板"""
        # 如果有选中的字幕，素材取消选中时不覆盖字幕属性
        if clip is None and self._timeline_widget.selected_subtitle:
            pass
        else:
            self._update_property_panel(clip)
        if not self._preview_widget.timeline_linked:
            return
        if clip is None:
            self._preview_widget.set_active_duration(0.0)
            self._preview_widget.set_source_offset(0.0)
            self._mute_btn.blockSignals(True)
            self._mute_btn.setChecked(False)
            self._mute_btn.blockSignals(False)
            self._preview_widget.set_muted(False)
            self._fx_btn.setEnabled(False)
            return
        vid_path = clip.proxy_path or clip.source_path
        if vid_path and os.path.exists(vid_path) and vid_path != self._current_video:
            self._load_video(vid_path, clip.source_path if clip.proxy_path else "")
        self._preview_widget.set_active_duration(clip.duration, clip.speed)
        self._preview_widget.set_source_offset(clip.source_start)
        self._timeline_widget.set_position(clip.start)
        QTimer.singleShot(80, lambda: self._preview_widget.seek(0.0))
        self._update_time_display(clip.start)
        self._mute_btn.blockSignals(True)
        self._mute_btn.setChecked(clip.muted if clip else False)
        self._mute_btn.blockSignals(False)
        self._preview_widget.set_muted(bool(clip and clip.muted))
        self._fx_btn.setEnabled(clip is not None and not clip.locked)

    def _on_timeline_subtitle_selected(self, entry):
        """字幕选中 → 刷新属性面板"""
        self._update_property_panel(entry)
        if entry is not None:
            # 清空素材预览状态（不触发 _update_property_panel 避免闪烁）
            self._preview_widget.set_active_duration(0.0)
            self._preview_widget.set_source_offset(0.0)
            self._mute_btn.blockSignals(True)
            self._mute_btn.setChecked(False)
            self._mute_btn.blockSignals(False)
            self._preview_widget.set_muted(False)
            self._fx_btn.setEnabled(False)

    def _on_timeline_dub_requested(self, entries):
        """字幕右键 → 配音：弹出引擎/音色选择对话框，确认后调用 TTS"""
        if not entries:
            return
        from videotrans.tts import TTS_NAME_LIST
        import videotrans.tts as tts_mod
        from videotrans import translator as translator_mod
        from videotrans.util import tools as vt_tools

        out_dir = self.translate_panel._output_dir_edit.text().strip()
        if not out_dir:
            out_dir = os.path.join(os.path.expanduser("~"), "pyvideotrans_output")

        target_lang_text = self.translate_panel.target_language.currentText().strip()
        if target_lang_text in ("", "-"):
            target_lang_text = "Chinese"
        target_code = translator_mod.get_code(show_text=target_lang_text) or "zh"

        # ── 配音设置对话框 ──
        dlg = QDialog(self)
        dlg.setWindowTitle(f"配音设置 — {len(entries)} 条字幕")
        dlg.setFixedSize(400, 240)
        dlg.setStyleSheet("""
            QDialog { background: #1e1e24; }
            QLabel { color: #aaa; font-size: 12px; }
            QComboBox { background: #2a2a32; color: #d0d0d0; border: 1px solid #3a3a42;
                border-radius: 4px; padding: 4px 8px; font-size: 12px; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background: #2a2a32; color: #d0d0d0;
                selection-background-color: #3a8cff44; }
            QPushButton { background: #2a2a32; color: #d0d0d0; border: 1px solid #3a3a42;
                border-radius: 4px; padding: 6px 16px; font-size: 12px; }
            QPushButton:hover { border-color: #3a8cff; }
        """)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # 输出目录
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录:"))
        out_label = QLabel(out_dir)
        out_label.setStyleSheet("color: #888;")
        out_label.setWordWrap(True)
        out_row.addWidget(out_label, 1)
        layout.addLayout(out_row)

        # 配音引擎
        eng_row = QHBoxLayout()
        eng_row.addWidget(QLabel("配音引擎:"))
        engine_combo = QComboBox()
        engine_combo.addItems(TTS_NAME_LIST)
        engine_combo.setCurrentIndex(self.translate_panel.tts_type.currentIndex())
        eng_row.addWidget(engine_combo, 1)
        layout.addLayout(eng_row)

        # 音色
        role_row = QHBoxLayout()
        role_row.addWidget(QLabel("音色:"))
        role_combo = QComboBox()
        role_combo.setEditable(True)
        role_combo.setCurrentText(self.translate_panel.voice_role.currentText())
        role_row.addWidget(role_combo, 1)
        layout.addLayout(role_row)

        def _load_roles(tts_idx):
            """根据 TTS 引擎和语言加载音色列表"""
            lang_prefix = target_code.split("-")[0]
            try:
                if tts_idx == tts_mod.EDGE_TTS:
                    rl = vt_tools.get_edge_rolelist()
                elif tts_idx == tts_mod.KOKORO_TTS:
                    rl = vt_tools.get_kokoro_rolelist()
                elif tts_idx == tts_mod.MINIMAXI_TTS:
                    rl = vt_tools.get_minimaxi_rolelist()
                elif tts_idx == tts_mod.AI302_TTS:
                    rl = vt_tools.get_302ai()
                elif tts_idx == tts_mod.DOUBAO_TTS:
                    rl = vt_tools.get_doubao_rolelist()
                elif tts_idx == tts_mod.DOUBAO2_TTS:
                    rl = vt_tools.get_doubao2_rolelist()
                elif tts_idx == tts_mod.PIPER_TTS:
                    rl = vt_tools.get_piper_role()
                elif tts_idx == tts_mod.VITSCNEN_TTS:
                    rl = vt_tools.get_vits_role()
                elif tts_idx == tts_mod.AZURE_TTS:
                    rl = vt_tools.get_azure_rolelist()
                elif tts_idx == tts_mod.FreeAzure:
                    rl = vt_tools.get_azure_rolelist()
                else:
                    rl = None
            except Exception:
                rl = None

            if rl and lang_prefix in rl:
                role_combo.clear()
                items = list(rl[lang_prefix].keys()) if isinstance(rl[lang_prefix], dict) else rl[lang_prefix]
                role_combo.addItems(items)
            elif rl is not None:
                # 有 rolelist 但没匹配语言 → 保留当前输入，同时给个 "No" 提示
                role_combo.clear()
                role_combo.addItem("No")
            # rl is None → 引擎不支持预定义音色列表（如 OpenAI TTS、CosyVoice 等），
            # 不清空，保留初始 setCurrentText 的值，用户可自由输入

        engine_combo.currentIndexChanged.connect(_load_roles)
        _load_roles(engine_combo.currentIndex())

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dlg.reject)
        btn_ok = QPushButton("开始配音")
        btn_ok.setStyleSheet("QPushButton { background:#3a8cff; color:#fff; border-radius:4px; padding:6px 20px; }")
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        if not dlg.exec():
            return

        tts_type_idx = engine_combo.currentIndex()
        voice_role = role_combo.currentText().strip()
        srty_dir = os.path.join(out_dir, "srty")
        os.makedirs(srty_dir, exist_ok=True)

        # 构建 queue_tts
        queue = []
        for entry in entries:
            filename = os.path.join(srty_dir, f"{entry.index}.wav")
            queue.append(
                {
                    "text": entry.text.strip(),
                    "line": entry.index,
                    "start_time": entry.start,
                    "end_time": entry.end,
                    "startraw": "",
                    "endraw": "",
                    "ref_text": "",
                    "start_time_source": entry.start,
                    "end_time_source": entry.end,
                    "role": voice_role,
                    "rate": "+0%",
                    "volume": "+0%",
                    "pitch": "+0Hz",
                    "tts_type": tts_type_idx,
                    "filename": filename,
                }
            )

        if not queue:
            return

        self.translate_panel.log(f"开始配音 {len(queue)} 条字幕 → {srty_dir}")

        def _run_tts():
            try:
                tts_mod.run(
                    queue_tts=queue,
                    language=target_code,
                    tts_type=tts_type_idx,
                )
                self.translate_panel.log(f"配音完成，{len(queue)} 条字幕已保存到 {srty_dir}")
            except Exception as e:
                self.translate_panel.log(f"配音失败: {e}")

        threading.Thread(target=_run_tts, daemon=True).start()

    def _on_timeline_dub_local_requested(self, entries):
        """字幕右键 → 字幕配音：选择本地已生成的配音文件目录，自动匹配到音频轨"""
        if not entries:
            return
        import re
        from studio.editor.models import TimelineClip

        # 选择配音文件目录
        dir_path = QFileDialog.getExistingDirectory(self, "选择字幕配音文件目录")
        if not dir_path:
            return

        # 扫描目录中的音频文件，提取序号
        audio_files = {}
        for fname in os.listdir(dir_path):
            full = os.path.join(dir_path, fname)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".opus"):
                continue
            # 从文件名提取序号: "1.wav" → 1, "dub-005.mp3" → 5
            m = re.match(r"(\d+)", os.path.splitext(fname)[0])
            if m:
                idx = int(m.group(1))
                if idx not in audio_files:
                    audio_files[idx] = full

        if not audio_files:
            QMessageBox.warning(self, "提示", f"在所选目录中未找到音频文件 (1.wav, 2.mp3 等)")
            return

        # 按字幕序号匹配，创建音频轨素材
        new_clips = []
        matched = 0
        for entry in sorted(entries, key=lambda e: e.start):
            audio_path = audio_files.get(entry.index)
            if not audio_path:
                continue
            dur = entry.duration
            # 用 ffprobe 探测实际音频时长
            try:
                import subprocess

                r = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "quiet",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        audio_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if r.returncode == 0 and r.stdout.strip():
                    dur = float(r.stdout.strip())
            except Exception:
                pass

            clip = TimelineClip(
                source_path=audio_path,
                start=entry.start,
                duration=dur,
                source_duration=dur,
                label=f"配音 #{entry.index}",
                track_type="audio",
            )
            self._timeline_widget._clips.append(clip)
            new_clips.append(clip)
            matched += 1

        if not new_clips:
            QMessageBox.warning(self, "提示", "未匹配到任何字幕对应的配音文件")
            return

        # 按时序排列素材
        self._timeline_widget._clips.sort(key=lambda c: c.start)
        self._timeline_widget._update_duration()
        self._timeline_widget.clips_changed.emit()
        self._timeline_widget.update()
        self._status_label.setText(f"已添加 {matched} 条本地配音到音频轨")

    def _update_property_panel(self, obj):
        """更新右侧属性面板：TimelineClip（视频/音频）或 SubtitleEntry（字幕）"""
        if obj is None:
            self._prop_scroll.hide()
            return
        self._prop_scroll.show()

        from studio.editor.models import SubtitleEntry

        def _fmt(sec):
            m = int(sec // 60)
            s = int(sec % 60)
            ms = int((sec % 1) * 10)
            return f"{m}:{s:02d}.{ms}"

        if isinstance(obj, SubtitleEntry):
            entry = obj
            self._prop_labels["filename"].setText(f"字幕 #{entry.index}")
            self._prop_labels["path"].setText("—")
            self._prop_labels["type"].setText("字幕")
            self._prop_labels["timeline_start"].setText(_fmt(entry.start))
            self._prop_labels["timeline_end"].setText(_fmt(entry.end))
            self._prop_labels["duration"].setText(f"{entry.duration:.1f}s")
            self._prop_labels["source_offset"].setText("—")
            self._prop_labels["speed"].setText("—")
            self._prop_labels["muted"].setText("—")
            self._prop_labels["locked"].setText("—")
            self._prop_labels["resolution_orig"].setText("—")
            self._prop_labels["resolution_target"].setText("—")
            self._prop_labels["effects"].setText("—")
            return

        # TimelineClip
        clip = obj
        import os

        name = os.path.basename(clip.source_path) if clip.source_path else "—"
        self._prop_labels["filename"].setText(name)
        self._prop_labels["path"].setText(clip.source_path or "—")
        ext = os.path.splitext(clip.source_path or "")[1].lower()
        if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
            ftype = "视频"
        elif ext in {".mp3", ".wav", ".aac", ".m4a", ".ogg"}:
            ftype = "音频"
        elif ext == ".srt":
            ftype = "字幕"
        else:
            ftype = ext if ext else "—"
        self._prop_labels["type"].setText(ftype)

        self._prop_labels["timeline_start"].setText(_fmt(clip.start))
        self._prop_labels["timeline_end"].setText(_fmt(clip.end))
        self._prop_labels["duration"].setText(f"{clip.duration:.1f}s")
        self._prop_labels["source_offset"].setText(f"{clip.source_start:.1f}s")
        self._prop_labels["speed"].setText(f"{clip.speed:.1f}×")
        self._prop_labels["muted"].setText("是" if clip.muted else "否")
        locked_text = []
        if clip.locked:
            locked_text.append("锁定")
        if clip.position_fixed:
            locked_text.append("固定位置")
        self._prop_labels["locked"].setText(", ".join(locked_text) if locked_text else "否")

        try:
            info = pvt_bridge.probe(clip.source_path)
            orig_w, orig_h = info.get("width", 0), info.get("height", 0)
        except Exception:
            orig_w, orig_h = 0, 0
        if orig_w and orig_h:
            self._prop_labels["resolution_orig"].setText(f"{orig_w}×{orig_h}")
        else:
            self._prop_labels["resolution_orig"].setText("—")
        if clip.target_width and clip.target_height:
            self._prop_labels["resolution_target"].setText(f"{clip.target_width}×{clip.target_height}")
        else:
            self._prop_labels["resolution_target"].setText("—")

        eff = getattr(clip, "effects", None)
        if eff:
            names = [e.get("name", "?") if isinstance(e, dict) else getattr(e, "name", "?") for e in eff]
            self._prop_labels["effects"].setText(", ".join(names))
        else:
            self._prop_labels["effects"].setText("—")

    def _on_timeline_clip_changed(self, clip):
        """素材属性变更（变速/裁剪）→ 同步预览状态 + 刷新属性面板"""
        if clip is not None and not self._timeline_widget.selected_subtitle:
            self._update_property_panel(clip)
        if not self._preview_widget.timeline_linked:
            return
        sel = self._timeline_widget._selected
        if sel is not clip:
            return
        self._preview_widget.set_active_duration(clip.duration, clip.speed)
        self._preview_widget.set_source_offset(clip.source_start)

    def _on_resolution_mismatch(self, clip, project_w: int, project_h: int):
        """素材分辨率与项目基准不一致时弹窗提示"""
        clip_w = 0
        clip_h = 0
        try:
            info = pvt_bridge.probe(clip.source_path)
            clip_w = info.get("width", 0)
            clip_h = info.get("height", 0)
        except Exception:
            pass
        QMessageBox.information(
            self,
            "分辨率自动统一",
            f"素材「{clip.label}」分辨率 ({clip_w}×{clip_h}) 与项目基准 ({project_w}×{project_h}) 不一致，\n"
            f"已自动将其标记为导出时转换为 {project_w}×{project_h}。",
        )

    def _on_timeline_subtitle_edit(self, entry, idx):
        """双击字幕 → 弹出修改窗口（文字+时间戳+字号）"""
        from PySide6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QPushButton,
            QPlainTextEdit,
            QLabel,
            QDoubleSpinBox,
            QSpinBox,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(f"修改字幕 #{entry.index}")
        dlg.setMinimumSize(520, 350)
        dlg.setStyleSheet("QDialog { background: #1e1e24; } QLabel { color: #ccc; }")

        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)

        # 时间戳编辑
        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("开始:"))
        start_spin = QDoubleSpinBox()
        start_spin.setRange(0, 99999)
        start_spin.setDecimals(1)
        start_spin.setValue(entry.start)
        start_spin.setSuffix(" s")
        start_spin.setStyleSheet(
            "QDoubleSpinBox { background:#25252b; color:#e0e0e0; border:1px solid #3a3a42;"
            " border-radius:3px; padding:3px 6px; font-size:12px; }"
        )
        time_row.addWidget(start_spin)

        time_row.addWidget(QLabel("结束:"))
        end_spin = QDoubleSpinBox()
        end_spin.setRange(0, 99999)
        end_spin.setDecimals(1)
        end_spin.setValue(entry.end)
        end_spin.setSuffix(" s")
        end_spin.setStyleSheet(start_spin.styleSheet())
        time_row.addWidget(end_spin)

        # 字号（全局）
        time_row.addWidget(QLabel("字号:"))
        fs_spin = QSpinBox()
        fs_spin.setRange(8, 72)
        fs_spin.setValue(self._timeline_widget._subtitle_font_size)
        fs_spin.setStyleSheet(
            "QSpinBox { background:#25252b; color:#e0e0e0; border:1px solid #3a3a42;"
            " border-radius:3px; padding:3px 6px; font-size:12px; width:50px; }"
        )
        time_row.addWidget(fs_spin)

        time_row.addStretch()
        layout.addLayout(time_row)

        # 文字编辑
        ed = QPlainTextEdit()
        ed.setPlainText(entry.text)
        ed.setStyleSheet(
            "QPlainTextEdit { background:#25252b; color:#e0e0e0; border:1px solid #3a3a42;"
            " border-radius:4px; font-size:14px; padding:8px; }"
        )
        layout.addWidget(ed, 1)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet(
            "QPushButton { background:#3a8cff; color:white; border:none; border-radius:4px;"
            " padding:6px 28px; font-size:13px; }"
        )
        ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        if dlg.exec():
            entry.start = start_spin.value()
            entry.end = end_spin.value()
            new_text = ed.toPlainText().strip()
            if new_text:
                entry.text = new_text
            # 全局字号
            self._timeline_widget._subtitle_font_size = fs_spin.value()
            self._timeline_widget._update_duration()
            self._timeline_widget._update_scrollbar()
            self._timeline_widget.update()
            oplog.operation("修改字幕", f"#{entry.index} {entry.text[:30]}")

    def _update_time_display(self, pos: float):
        if self._time_editing:
            return  # 用户正在输入，不覆盖

        def fmt(s):
            h = int(s // 3600)
            m = int((s % 3600) // 60)
            sec = int(s % 60)
            if h > 0:
                return f"{h:02d}:{m:02d}:{sec:02d}"
            return f"{m:02d}:{sec:02d}"

        def fmt_ms(s):
            """MM:SS.S 格式，带一位小数"""
            h = int(s // 3600)
            m = int((s % 3600) // 60)
            sec = s - m * 60 - h * 3600
            if h > 0:
                return f"{h:02d}:{m:02d}:{sec:04.1f}"
            return f"{m:02d}:{sec:04.1f}"

        sel = self._timeline_widget._selected
        if sel:
            rel = max(0.0, pos - sel.start)
            self.lbl_time.setText(f"{fmt_ms(rel)} / {fmt_ms(sel.duration)}")
        else:
            dur = self._preview_widget.duration
            self.lbl_time.setText(f"{fmt(pos)} / {fmt(dur)}")

    # ── 时间输入跳转 ──

    def _on_time_label_click(self):
        """点击时间标签 → 弹出对话框输入时间跳转"""
        from PySide6.QtWidgets import QInputDialog

        cur = self._preview_widget.position if self._preview_widget.current_path else 0
        h = int(cur // 3600)
        m = int((cur % 3600) // 60)
        s = int(cur % 60)
        default_text = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        text, ok = QInputDialog.getText(self, "跳转到时间", "输入时间 (MM:SS 或 HH:MM:SS):", text=default_text)
        if ok and text:
            sec = self._parse_time_input(text)
            if sec >= 0 and self._preview_widget.current_path:
                self._preview_widget.seek(sec)

    @staticmethod
    def _parse_time_input(text: str) -> float:
        """解析时间输入，支持 HH:MM:SS 或 MM:SS 格式，返回秒数"""
        text = text.strip()
        if "/" in text:
            text = text.split("/")[0].strip()
        parts = text.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 1 and parts[0]:
                return float(parts[0])
        except (ValueError, IndexError):
            pass
        return -1

    # ── 操作 ──

    def _make_media_item_widget(self, name: str, path: str) -> QWidget:
        """创建媒体素材项的控件：文件名 + [+]按钮 + [删除]按钮"""
        w = _MediaItemWidget()
        w._list_widget = self.media_list
        w.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(w)
        layout.setContentsMargins(6, 1, 4, 1)
        layout.setSpacing(4)

        # 在 `_` `-` `.` 后插入零宽空格，使长文件名可换行
        display_name = name.replace("_", "_​").replace("-", "-​").replace(".", ".​")
        label = QLabel(display_name)
        label.setWordWrap(True)
        label.setToolTip(name)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label.setStyleSheet("color: #d0d0d0; font-size: 16px; background: transparent;")
        layout.addWidget(label, 1)
        w._label = label

        trash_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        btn_fav = QPushButton("+")
        btn_fav.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        btn_fav.setMinimumSize(32, 0)
        btn_fav.setToolTip("添加到时间轴")
        btn_fav.setStyleSheet(
            "QPushButton { background:transparent; color:#3a8cff; border:none; "
            "border-radius:4px; font-size:20px; font-weight:bold; padding:0; } "
            "QPushButton:hover { background:rgba(58,140,255,0.25); color:#5b9dff; }"
        )
        btn_fav.clicked.connect(lambda: self._on_load_to_timeline(path))

        btn_del = QPushButton()
        btn_del.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        btn_del.setMinimumSize(28, 0)
        btn_del.setIcon(trash_icon)
        btn_del.setIconSize(QSize(16, 16))
        btn_del.setToolTip("从媒体库删除")
        btn_del.setStyleSheet(
            "QPushButton { background:transparent; border:none; border-radius:4px; } "
            "QPushButton:hover { background:rgba(255,80,60,0.25); }"
        )
        btn_del.clicked.connect(lambda: self._on_delete_media(path))

        btn_fav.hide()
        btn_del.hide()
        layout.addWidget(btn_fav)
        layout.addWidget(btn_del)

        w._btn_add = btn_fav
        w._btn_del = btn_del
        return w

    def _on_media_current_changed(self, current, previous):
        """选中项变化 — 按钮由 hover 事件处理，此处仅记录"""

    def _add_media_files(self, paths):
        """添加文件到媒体列表（去重）"""
        existing = set()
        for i in range(self.media_list.count()):
            p = self.media_list.item(i).data(Qt.ItemDataRole.UserRole)
            if p:
                existing.add(p)
        for f in paths:
            if f in existing:
                continue
            name = os.path.basename(f)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, f)
            item.setToolTip(f)
            item_widget = self._make_media_item_widget(name, f)
            self.media_list.addItem(item)
            self.media_list.setItemWidget(item, item_widget)
            item.setSizeHint(item_widget.sizeHint())
            self.media_list.scheduleDelayedItemsLayout()
            existing.add(f)
            self._media_files.append(f)
        self._status_label.setText(f"媒体素材: {self.media_list.count()} 个文件")

    def _on_import_media(self):
        self._oplog("导入素材")
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "导入素材",
            self._last_import_dir,
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.webm);;音频文件 (*.mp3 *.wav *.aac *.m4a);;字幕文件 (*.srt);;所有文件 (*.*)",
        )
        if files:
            self._last_import_dir = os.path.dirname(files[0])
            self._add_media_files(files)

    def _on_media_selected(self, item):
        """双击素材 — 仅在预览窗口播放，不影响时间轴"""
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".srt":
            # 双击字幕直接加载到时间轴
            self._on_load_to_timeline(path)
            return
        if path == self._current_video and self._preview_widget.current_path:
            self._on_play_pause()
        else:
            self._load_video(path)
            QTimer.singleShot(500, self._on_play)

    def _on_load_to_timeline(self, path: str):
        """右键 → 加载到时间轴（自动接在尾部）"""
        ext = os.path.splitext(path)[1].lower()
        audio_exts = {".mp3", ".wav", ".aac", ".m4a", ".ogg"}
        if ext == ".srt":
            self._timeline_widget.load_subtitles(path)
            self._status_label.setText(f"已加载字幕: {os.path.basename(path)}")
        elif ext not in audio_exts:
            clips = self._timeline_widget._clips
            if not clips:
                # 第一个视频：加载到预览并创建素材
                self._pending_timeline_load = True
                self._load_video(path)
            else:
                # 后续视频：直接追加到尾部，不刷新预览
                self._timeline_widget.append_clip(path, os.path.basename(path))
                self._status_label.setText(f"已追加到时间轴: {os.path.basename(path)}")
        elif ext in audio_exts:
            self._timeline_widget.append_clip(path, os.path.basename(path))
            self._status_label.setText(f"已追加到时间轴: {os.path.basename(path)}")

    def _on_video_loaded(self, path: str):
        """预览区拖拽导入后回调"""
        self._current_video = path
        name = os.path.basename(path)
        # 如果不在列表中则添加
        for i in range(self.media_list.count()):
            if self.media_list.item(i).data(Qt.ItemDataRole.UserRole) == path:
                return
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        item_widget = self._make_media_item_widget(name, path)
        self.media_list.addItem(item)
        self.media_list.setItemWidget(item, item_widget)
        item.setSizeHint(item_widget.sizeHint())
        if path not in self._media_files:
            self._media_files.append(path)

    def _on_delete_media(self, path: str):
        """右键删除媒体素材"""
        # 找到列表中对应的项
        for i in range(self.media_list.count()):
            item = self.media_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == path:
                self.media_list.takeItem(i)
                break
        # 重建 _media_files
        self._media_files.clear()
        for i in range(self.media_list.count()):
            p = self.media_list.item(i).data(Qt.ItemDataRole.UserRole)
            if p:
                self._media_files.append(p)
        # 如果删除的是当前预览视频，清理预览和时间线
        if self._current_video and self._current_video == path:
            self._preview_widget.clear_preview()
            self._current_video = None
            self.lbl_time.setText("00:00 / 00:00")
            self._timeline_widget.load_video("", 0)
            self._timeline_widget.set_position(0.0)
        # 如果删除的是字幕文件，清理时间线字幕
        if path.lower().endswith(".srt"):
            self._timeline_widget.clear_subtitles()
            self._timeline_widget._sync_zoom_slider()
        self._status_label.setText(f"媒体素材: {self.media_list.count()} 个文件")

    def _on_replace_media(self, path: str):
        """右键替换素材"""
        # 找到列表中对应的项
        item = None
        for i in range(self.media_list.count()):
            it = self.media_list.item(i)
            if it and it.data(Qt.ItemDataRole.UserRole) == path:
                item = it
                break
        if not item:
            return
        is_current = self._current_video == path
        new_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择替换素材",
            "",
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.webm);;音频文件 (*.mp3 *.wav *.aac *.m4a);;所有文件 (*.*)",
        )
        if not new_path:
            return
        # 替换列表项
        name = os.path.basename(new_path)
        item.setData(Qt.ItemDataRole.UserRole, new_path)
        item.setToolTip(new_path)
        item_widget = self.media_list.itemWidget(item)
        if item_widget and hasattr(item_widget, "_label"):
            display_name = name.replace("_", "_​").replace("-", "-​").replace(".", ".​")
            item_widget._label.setText(display_name)
            item.setSizeHint(item_widget.sizeHint())
        # 更新 _media_files
        self._media_files.clear()
        for i in range(self.media_list.count()):
            p = self.media_list.item(i).data(Qt.ItemDataRole.UserRole)
            if p:
                self._media_files.append(p)
        # 如果当前正在预览则加载新素材
        if is_current:
            self._load_video(new_path)
            self._timeline_widget.set_position(0.0)
        self._status_label.setText(f"已替换: {name}")

    def _load_video(self, path, audio_source: str = ""):
        self._current_video = path
        self._preview_widget.load(path, audio_source)
        self._status_label.setText(f"已加载: {os.path.basename(path)}")

    def _on_play_pause(self):
        self._oplog("播放/暂停")
        focused = QApplication.focusWidget()
        if focused and isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return
        if not self._preview_widget.current_path:
            if self.media_list.count() > 0:
                self._on_media_selected(self.media_list.item(0))
                # _on_media_selected 内部已设 _on_play 延迟回调，这里不另设定时器
            return

        # 单击 → 播放/暂停切换
        if self._preview_widget.is_playing():
            self._preview_widget.pause()
        else:
            self._on_play()

    def _on_play(self, _retries=20):
        if not self._preview_widget.current_path:
            # 从时间线素材中找第一个有视频源的加载
            for c in self._timeline_widget._clips:
                if os.path.exists(c.source_path):
                    self._load_video(c.source_path)
                    break
        if not self._preview_widget.current_path:
            # 没有时间线素材 → 从媒体列表加载
            if self.media_list.count() > 0:
                path = self.media_list.item(0).data(Qt.ItemDataRole.UserRole)
                if path and os.path.exists(path):
                    self._load_video(path)
        if not self._preview_widget.current_path:
            return
        if self._preview_widget.duration <= 0:
            if _retries > 0:
                QTimer.singleShot(500, lambda: self._on_play(_retries - 1))
            return
        # 动态捕捉所有内容的最大时间跨度（视频/音频/字幕），驱动滑块/时间显示
        clip_max = max((c.end for c in self._timeline_widget._clips), default=0.0)
        sub_max = max((e.end for e in self._timeline_widget._subtitle_entries), default=0.0)
        self._preview_widget.set_active_duration(max(clip_max, sub_max) + 10, 1.0)
        # 全时间线播放，多轨排期表动态切换音视频
        clips = self._timeline_widget._clips
        audio_schedule = []
        video_schedule = []
        first_source_start = 0.0
        # 音频轨素材优先：相同 start 时 track_type="audio" 排在 "video" 前面，
        # 确保配音文件被 _find_schedule_at 优先命中
        for c in sorted(
            clips, key=lambda x: (x.start, x.muted, 0 if getattr(x, "track_type", "") == "audio" else 1, x.end)
        ):
            audio_path = ""
            entry_muted = c.muted
            if not entry_muted and os.path.exists(c.source_path):
                audio_path = c.source_path
            audio_schedule.append((c.start, c.end, audio_path, entry_muted))
            # 视频轨素材：记录 (timeline_start, timeline_end, source_path, source_start)
            if os.path.exists(c.source_path) and getattr(c, "track_type", "") != "audio":
                ss = c.source_start
                video_schedule.append((c.start, c.end, c.source_path, ss))

        # 从第一个视频素材的 source_start 开始解码
        for vs in video_schedule:
            first_source_start = vs[3]
            break
        self._preview_widget.set_source_offset(first_source_start)

        # 确保有视频源（只从视频轨素材取）
        if not self._current_video:
            for c in clips:
                if os.path.exists(c.source_path) and getattr(c, "track_type", "") != "audio":
                    self._load_video(c.source_path)
                    break

        self._preview_widget.set_multi_track_schedule(audio_schedule, video_schedule)
        self._preview_widget.set_muted(False)  # 排期表逐条控制静音
        self._preview_widget.play()

    def _on_pause(self):
        self._preview_widget.pause()

    def _on_go_start(self):
        if self._preview_widget.current_path:
            self._preview_widget.seek(0.0)

    def _on_go_end(self):
        if self._preview_widget.current_path:
            self._preview_widget.seek(self._preview_widget.duration)

    def _on_undo(self):
        """Ctrl+Z — 撤销"""
        self._timeline_widget.undo()

    def _on_redo(self):
        """Ctrl+Shift+Z — 重做"""
        self._timeline_widget.redo()

    def _on_prev_frame(self):
        """后退一帧"""
        if not self._preview_widget.current_path:
            return
        # 文本输入中不触发
        focused = QApplication.focusWidget()
        if focused and isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return
        fps = self._preview_widget.fps
        if fps <= 0:
            fps = 24.0
        frame_dur = 1.0 / fps
        new_pos = max(0.0, self._preview_widget.position - frame_dur)
        self._preview_widget.seek(new_pos)

    def _on_next_frame(self):
        """前进一帧"""
        if not self._preview_widget.current_path:
            return
        focused = QApplication.focusWidget()
        if focused and isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return
        fps = self._preview_widget.fps
        if fps <= 0:
            fps = 24.0
        frame_dur = 1.0 / fps
        new_pos = min(self._preview_widget.duration, self._preview_widget.position + frame_dur)
        self._preview_widget.seek(new_pos)

    def _set_speed(self, speed: float, label: str):
        """设置播放速度"""
        self._oplog(f"播放速度: {label}(×{speed:.1g})")
        self._preview_widget.play_speed = speed
        self._status_label.setText(f"播放速度: {label}(×{speed:.1g})")
        QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))

    # ── 快捷键代理（时间线键盘事件需要） ──

    def _toggle_play(self):
        """空格键播放/暂停"""
        self._on_play_pause()

    def _on_split_click(self):
        """剪刀按钮 → 分割素材"""
        self._oplog("分割素材")
        self._timeline_widget.split_at_playhead()

    def _on_lock_clip(self):
        """锁按钮 → 弹出对话框设置固定位置/锁定素材"""
        self._oplog("锁定设置")
        clip = self._timeline_widget._selected
        if not clip:
            self._status_label.setText("请先选中一个素材")
            QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QDialogButtonBox, QLabel

        dlg = QDialog(self)
        dlg.setWindowTitle("锁定设置")
        dlg.setMinimumWidth(280)
        dlg.setStyleSheet(
            "QDialog { background: #1e1e22; color: #e0e0e0; } "
            "QLabel { color: #ccc; font-size: 13px; } "
            "QCheckBox { color: #ccc; font-size: 13px; spacing: 8px; } "
            "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; "
            "border: 1px solid #3a3a42; background: #2a2a32; } "
            "QCheckBox::indicator:checked { background: #3a8cff; border-color: #3a8cff; } "
            "QPushButton { background: #2a2a32; color: #d0d0d0; border: 1px solid #3a3a42; "
            "border-radius: 4px; padding: 6px 20px; } "
            "QPushButton:hover { background: #3a3a44; }"
        )
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.addWidget(QLabel(f"素材: {clip.label or os.path.basename(clip.source_path)}"))
        cb_pos = QCheckBox("固定位置（禁止拖拽移动）")
        cb_pos.setChecked(clip.position_fixed)
        layout.addWidget(cb_pos)
        cb_lock = QCheckBox("锁定素材（禁止任何操作）")
        cb_lock.setChecked(clip.locked)
        layout.addWidget(cb_lock)
        btns = QDialogButtonBox()
        btns.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(dlg.reject)
        ok_btn = btns.addButton("确定", QDialogButtonBox.ButtonRole.AcceptRole)
        ok_btn.setStyleSheet("background:#3a8cff; color:#fff; border:none;")
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(btns)
        if dlg.exec():
            clip.position_fixed = cb_pos.isChecked()
            clip.locked = cb_lock.isChecked()
            self._status_label.setText(f"已{'锁定' if clip.locked else '解锁'}素材")
            QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))

    def _on_toggle_snap(self, on: bool):
        """吸附开关"""
        self._oplog(f"吸附: {'开' if on else '关'}")
        self._timeline_widget._snap_enabled = on

    def _on_toggle_mute(self, muted: bool):
        """静音选中素材"""
        clip = self._timeline_widget._selected
        if not clip:
            self._status_label.setText("请先选中一个素材")
            QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))
            self._mute_btn.blockSignals(True)
            self._mute_btn.setChecked(False)
            self._mute_btn.blockSignals(False)
            return
        clip.muted = muted
        self._oplog(f"静音: {'开' if muted else '关'} {clip.label}")
        self._preview_widget.set_muted(muted)
        self._timeline_widget.update()

    def _on_proxy(self):
        """打开代理设置对话框并生成代理"""
        clip = self._timeline_widget._selected
        if not clip:
            self._status_label.setText("请先选中一个素材")
            QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))
            return
        if clip.track_type == "audio":
            self._status_label.setText("音频轨素材无需代理")
            QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))
            return
        if clip.proxy_path:
            self._status_label.setText("该素材已有代理文件")
            QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))
            return
        from studio.editor.preview_widget import _probe_resolution

        w, h = _probe_resolution(clip.source_path)
        res_str = f"{w}×{h}" if w and h else ""
        from studio.editor.timeline_widget import ProxyDialog

        dlg = ProxyDialog(clip.label, res_str, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        settings = dlg.get_settings()
        self._status_label.setText("正在生成代理文件...")
        QApplication.processEvents()
        proxy_path = self._timeline_widget.generate_proxy(clip, settings)
        if proxy_path:
            self._status_label.setText(f"代理已生成: {os.path.basename(proxy_path)}")
            QTimer.singleShot(3000, lambda: self._status_label.setText("就绪"))
            self._load_video(proxy_path, clip.source_path)
            self._preview_widget.set_active_duration(clip.duration, clip.speed)
            self._preview_widget.set_source_offset(clip.source_start)
        else:
            self._status_label.setText("代理生成失败，查看日志")
            QTimer.singleShot(3000, lambda: self._status_label.setText("就绪"))

    def _on_fx_click(self):
        """打开特效编辑对话框 — 剪辑模式用时间线选中素材，T2V 模式用素材时间线选中素材"""
        from studio.editor import EffectsDialog

        # ── T2V 模式：当前选中的素材时间线素材 ──
        if self._current_mode == "text_to_video":
            mat = self._t2v_material_timeline.get_selected_material()
            idx = self._t2v_material_timeline.get_selected_index()
            if not mat or not mat.local_path:
                self._status_label.setText("请先在素材时间线中点击选中一个素材")
                QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))
                return

            self._preview_widget.pause()

            def _t2v_preview(effects: list):
                try:
                    from studio.editor.effects import build_ffmpeg_filter_chain
                    import subprocess, tempfile

                    chain = build_ffmpeg_filter_chain(effects)
                    fd, tmp = tempfile.mkstemp(suffix=".png")
                    os.close(fd)
                    is_video = mat.media_type == "video" and mat.duration > 0
                    cmd = ["ffmpeg", "-y"]
                    if is_video:
                        cmd += ["-ss", "0.5"]
                    cmd += ["-i", mat.local_path]
                    if not is_video:
                        cmd += ["-t", "1"]
                    cmd += ["-vframes", "1"]
                    if chain:
                        cmd += ["-vf", chain]
                    cmd += [tmp]
                    subprocess.run(cmd, capture_output=True, timeout=8)
                    if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                        pm = QPixmap(tmp)
                        if not pm.isNull():
                            self._preview_widget.show_still_frame(pm)
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                except Exception:
                    pass

            label = f"素材 {idx + 1} [{mat.source}]"
            dlg = EffectsDialog(label, mat.effects, self, preview_callback=_t2v_preview)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_effects = dlg.get_effects()
                self._t2v_material_timeline.update_material_effects(idx, new_effects)
                # 同步到 shots 数据
                shots = self._t2v_panel.get_shots()
                for shot in shots:
                    if shot.materials and idx < len(shot.materials):
                        shot.materials[idx]["effects"] = [
                            {"effect_id": e.effect_id, "params": e.params, "enabled": e.enabled} for e in new_effects
                        ]
                eff_count = len(new_effects)
                self._status_label.setText(f"已应用 {eff_count} 个特效" if eff_count > 0 else "已清除全部特效")
                QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))
            self._preview_widget.clear_still_frame()
            return

        # ── 剪辑模式：时间线选中素材 ──
        clip = self._timeline_widget._selected
        if not clip:
            self._status_label.setText("请先选中一个素材")
            QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))
            return
        if clip.track_type == "audio":
            self._status_label.setText("音频轨素材暂不支持特效")
            QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))
            return

        was_playing = self._preview_widget.is_playing()
        if was_playing:
            self._preview_widget.pause()
        seek_pos = self._preview_widget.position
        source_offset = self._preview_widget._source_offset
        speed = self._preview_widget._speed
        source_path = clip.proxy_path or clip.source_path

        def _do_preview(filter_chain: str):
            import subprocess, tempfile

            try:
                abs_sec = source_offset + seek_pos * speed
                fd, tmp = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                cmd = ["ffmpeg", "-y", "-ss", str(abs_sec), "-i", source_path, "-vframes", "1"]
                if filter_chain:
                    cmd += ["-vf", filter_chain]
                cmd += [tmp]
                r = subprocess.run(cmd, capture_output=True, timeout=8)
                if r.returncode == 0 and os.path.exists(tmp):
                    pm = QPixmap(tmp)
                    if not pm.isNull():
                        self._preview_widget.show_still_frame(pm)
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            except Exception:
                pass

        dlg = EffectsDialog(clip.label, list(clip.effects), self, preview_callback=_do_preview)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            clip.effects = dlg.get_effects()
            self._timeline_widget.update()
            eff_count = len(clip.effects)
            self._status_label.setText(f"已应用 {eff_count} 个特效" if eff_count > 0 else "已清除全部特效")
            QTimer.singleShot(2000, lambda: self._status_label.setText("就绪"))

        self._preview_widget.clear_still_frame()
        QTimer.singleShot(50, lambda: self._preview_widget.seek(seek_pos))

    def _oplog(self, msg: str):
        """记录操作日志"""
        try:
            from . import oplog as _op

            _op.operation(msg)
        except Exception:
            pass

    def _on_play_finished(self):
        """播放完当前段 → 检查排期表中是否还有后续内容，有则继续"""
        clips = sorted(self._timeline_widget._clips, key=lambda c: c.start)
        if not clips:
            return
        pos = self._preview_widget.position
        # 找到下一个有视频源的素材，切换视频并继续播放
        for c in clips:
            if c.start > pos + 0.1 and os.path.exists(c.source_path):
                self._preview_widget.seek(c.start)
                self._preview_widget.play()
                return
        # 没有后续视频 → 检查是否有后续纯音频
        schedule = self._preview_widget._audio_schedule
        for start, end, apath, muted in schedule:
            if start > pos + 0.05 and apath and not muted and os.path.exists(apath):
                # 纯音频继续播放（视频停在最后一帧）
                self._preview_widget._playing = True
                self._preview_widget._schedule_idx = -1  # 强制切换
                self._preview_widget._check_schedule()
                return
        # 没有后续内容 → 停止
        last_end = max((c.end for c in clips), default=pos)
        self._timeline_widget.set_position(last_end)
        self._preview_widget.pause()

    def _step_forward(self):
        """方向键→逐帧前进"""
        self._on_next_frame()

    def _step_backward(self):
        """方向键←逐帧后退"""
        self._on_prev_frame()

    # ── 字幕编辑 ──

    def _on_export_clip(self):
        """顶部工具栏导出按钮 — 显示导出选项对话框"""
        if self._current_mode == "translate":
            self._status_label.setText("在右侧面板设置参数后点击「开始翻译」")
            return

        path = self._preview_widget.current_path
        timeline_clips = self._timeline_widget._clips

        if not timeline_clips and not path:
            self._status_label.setText("请先加载视频")
            return

        from studio.editor import ExportDialog

        dlg = ExportDialog(
            self,
            duration=self._preview_widget.duration if path else 0,
            source_path=path or "",
        )
        if dlg.exec() != ExportDialog.DialogCode.Accepted:
            return

        out_path = dlg.output_path
        if not out_path:
            return

        fmt = dlg.format

        # ── GIF 导出 ──
        if fmt == "gif":
            if timeline_clips:
                c = timeline_clips[0]
                seg = ClipSegment(source_path=c.source_path, start=c.start, end=c.end, label=c.label)
            else:
                seg = ClipSegment(source_path=path, start=0, end=self._preview_widget.duration)
            self._engine.export_gif(seg, out_path, fps=dlg.gif_fps, scale=dlg.gif_scale)
            self._status_label.setText("正在导出 GIF ...")
            return

        # ── MP3 导出 ──
        if fmt == "mp3":
            if timeline_clips:
                c = timeline_clips[0]
                seg = ClipSegment(source_path=c.source_path, start=c.start, end=c.end, label=c.label)
            else:
                seg = ClipSegment(source_path=path, start=0, end=self._preview_widget.duration)
            self._engine.export_mp3(seg, out_path, bitrate=dlg.mp3_bitrate)
            self._status_label.setText("正在导出 MP3 ...")
            return

        # ── 视频导出 ──
        opts = ExportOptions(
            format=fmt,
            resolution=dlg.resolution,
            video_codec=dlg.video_codec,
            quality=dlg.quality,
            audio_codec=dlg.audio_codec,
            use_gpu=dlg.use_gpu,
        )

        if timeline_clips:
            segs = [
                ClipSegment(
                    source_path=c.source_path,
                    start=c.start,
                    end=c.end,
                    label=c.label,
                    speed=c.speed if abs(c.speed - 1.0) > 0.01 else 1.0,
                    effects=getattr(c, "effects", []) or [],
                )
                for c in timeline_clips
            ]
            has_effects = any(s.effects for s in segs)
            if has_effects:
                self._engine.merge_with_effects(segs, out_path, opts=opts)
                self._status_label.setText(f"正在特效合并 {len(segs)} 个素材...")
            else:
                self._engine.merge(segs, out_path, opts=opts)
                self._status_label.setText(f"正在合并 {len(segs)} 个素材...")
        else:
            seg = ClipSegment(source_path=path, start=0, end=self._preview_widget.duration, label="整片导出")
            self._engine.trim(seg, out_path, opts=opts)
            self._pending_trim = (seg, out_path)
            self._status_label.setText("正在导出 ...")

    # ── 引擎回调 ──

    def _on_engine_progress(self, pct: float):
        self._status_label.setText(f"剪辑中 ... {pct:.0f}%")

    def _on_engine_status(self, msg: str):
        self._status_label.setText(msg)

    def _on_engine_finished(self, success: bool, msg: str):
        if not success:
            self._status_label.setText(f"剪辑失败: {msg}")
            return

        # 裁剪完成
        if hasattr(self, "_pending_trim"):
            seg, out_path = self._pending_trim
            if os.path.exists(out_path):
                self._add_media_files([out_path])
                self._status_label.setText(f"裁剪完成: {out_path}")
            del self._pending_trim
            return

        self._status_label.setText("完成")

    # ── 音频操作（TimelineClip 参数） ─────────────────────

    def _merge_timeline_clips(self, clips, source_path: str) -> str:
        """将时间线上同源视频的所有 clip 按顺序合并为一个临时文件"""
        import tempfile
        import subprocess
        import os

        tmp_dir = tempfile.mkdtemp(prefix="pvt_merge_")
        trimmed = []

        try:
            # 检测最佳可用编码器（含硬件加速）
            from videotrans.util.help_ffmpeg import get_video_codec
            import glob

            vcodec = get_video_codec()
            hw_init = []
            vf_filter = None
            if vcodec in ("h264_nvenc", "hevc_nvenc"):
                enc_opts = ["-cq", "23", "-preset", "p4"]
            elif vcodec in ("h264_vaapi", "hevc_vaapi"):
                devices = glob.glob("/dev/dri/renderD*")
                device = devices[0] if devices else "/dev/dri/renderD128"
                hw_init = ["-init_hw_device", f"vaapi=vaapi0:{device}"]
                vf_filter = "format=nv12,hwupload=derive_device=vaapi"
                enc_opts = ["-qp", "23", "-preset", "fast"]
            elif vcodec in ("h264_qsv", "hevc_qsv"):
                enc_opts = ["-global_quality", "23", "-preset", "fast"]
                vf_filter = "hwupload=extra_hw_frames=64"
            elif vcodec in ("h264_amf", "hevc_amf"):
                enc_opts = ["-qp_p", "23", "-quality", "balanced"]
            elif vcodec == "h264_videotoolbox":
                enc_opts = ["-q:v", "60"]
            else:
                enc_opts = ["-preset", "fast", "-crf", "22"]

            for i, clip in enumerate(clips):
                if clip.duration <= 0 or not os.path.exists(clip.source_path):
                    continue
                out = os.path.join(tmp_dir, f"trim_{i:04d}.mp4")
                cmd = [
                    "ffmpeg",
                    "-y",
                    *hw_init,
                    "-ss",
                    str(clip.start),
                    "-i",
                    clip.source_path,
                    "-t",
                    str(clip.duration),
                    "-c:v",
                    vcodec,
                    *enc_opts,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-movflags",
                    "+faststart",
                ]
                if vf_filter:
                    cmd.extend(["-vf", vf_filter])
                cmd.append(out)
                result = subprocess.run(cmd, capture_output=True, timeout=3600)
                if result.returncode != 0:
                    stderr_tail = result.stderr.decode("utf-8", errors="replace")[-500:]
                    logger.warning(
                        f"[Merge] clip {i} ffmpeg 失败 (exit={result.returncode})\n  cmd: {' '.join(cmd)}\n  stderr_tail: ...{stderr_tail}"
                    )
                if os.path.exists(out) and os.path.getsize(out) > 1000:
                    trimmed.append(out)

            if not trimmed:
                return None

            # 用 concat demuxer 合并
            merged = os.path.join(tmp_dir, "merged.mp4")
            concat_file = os.path.join(tmp_dir, "concat.txt")
            with open(concat_file, "w", encoding="utf-8") as f:
                for fp in trimmed:
                    f.write(f"file '{fp}'\n")

            concat_cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", merged]
            subprocess.run(concat_cmd, capture_output=True, timeout=3600)

            if os.path.exists(merged) and os.path.getsize(merged) > 1000:
                return merged
            return None

        except Exception:
            import shutil

            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
            return None

    def _translate_status(self, msg: str):
        """从后台线程安全更新状态栏"""
        cfg.app_cfg.global_msg.append({"text": msg, "type": "logs"})

    def _on_translate_start(self, params: dict):
        """开始翻译任务"""
        path = self._preview_widget.current_path
        if not path or not os.path.exists(path):
            self.translate_panel.log("请先加载视频文件")
            self.translate_panel.set_running(False)
            return

        self.translate_panel.log(f"源语言: {params['source_language_code']}")
        self.translate_panel.log(f"目标语言: {params['target_language_code']}")

        # 检查时间线上是否有剪辑好的片段
        video_clips = self._timeline_widget.video_track._clips
        source_duration = getattr(self._timeline_widget, "_duration", None)
        needs_merge = len(video_clips) > 0 and not (
            len(video_clips) == 1
            and video_clips[0].start == 0.0
            and (source_duration is None or abs(video_clips[0].duration - source_duration) < 0.5)
        )

        if needs_merge:
            self.translate_panel.log("检测到时间线素材，正在合并...")
            self._status_label.setText("正在合并时间线素材...")
        else:
            self._status_label.setText("正在初始化翻译任务...")

        # 在后台线程执行
        self._translate_thread = threading.Thread(
            target=self._run_translate_pipeline, args=(path, params, video_clips if needs_merge else None), daemon=True
        )
        # 重置字幕编辑状态
        self._subtitle_edit_pending = False
        self._subtitle_dialog_open = False
        self._subtitle_resume.clear()
        self._translate_running = True
        self._translate_stopped = False
        self._translate_thread.start()

        # 启动日志轮询
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(300)
        self._log_timer.timeout.connect(self._poll_translate_logs)
        self._log_timer.start()

    def _run_translate_pipeline(self, path: str, params: dict, timeline_clips=None):
        """执行翻译管线（在后台线程运行）"""
        import subprocess
        import tempfile
        import shutil

        try:
            from videotrans.task.trans_create import TransCreate
            from videotrans.task.taskcfg import TaskCfgVTT
            from videotrans.util import tools
            from pathlib import Path
            import re

            # 如果时间线上有剪辑片段，先合并为完整视频
            merged_temp = None
            if timeline_clips:
                self._translate_status("合并时间线素材...")
                merged_temp = self._merge_timeline_clips(timeline_clips, path)
                if merged_temp and os.path.exists(merged_temp):
                    path = merged_temp
                    self.translate_panel.log(f"时间线已合并")

            # 准备文件信息 — 用原始路径取输出名，避免 temp 文件名
            orig_video_name = timeline_clips[0].source_path if timeline_clips else path
            file_obj = tools.format_video(Path(orig_video_name).absolute().as_posix())
            nospace = re.sub(r'[\s\. #*?!:"]', "-", file_obj["basename"])
            cache_folder = f'{TEMP_DIR}/{file_obj["uuid"]}'

            # 支持自定义输出目录
            override_dir = params.get("target_dir_override", "")
            if override_dir:
                target_dir = override_dir
            else:
                target_dir = f"{ROOT_DIR}/output/{nospace}"
            Path(cache_folder).mkdir(parents=True, exist_ok=True)
            Path(target_dir).mkdir(parents=True, exist_ok=True)

            # 通用参数
            base_params = {
                "name": path,
                "cache_folder": cache_folder,
                "target_dir": target_dir,
                "uuid": file_obj.get("uuid"),
            }
            base_params.update(file_obj)
            # update(file_obj) 可能覆盖 name，恢复为合并后的临时文件路径
            base_params["name"] = path

            # 保存全局设置（VAD、并发、BGM 等）
            from videotrans.configure.config import settings

            try:
                settings["threshold"] = min(0.9, max(float(params.get("threshold", "0.5")), 0.1))
                settings["min_speech_duration_ms"] = int(params.get("min_speech_duration_ms", "1000"))
                settings["min_silence_duration_ms"] = int(params.get("min_silence_duration_ms", "250"))
                settings["max_speech_duration_s"] = int(params.get("max_speech_duration_s", "8"))
            except ValueError:
                pass
            settings["loop_backaudio"] = int(params.get("is_loop_bgm", 0))
            try:
                settings["backaudio_volume"] = float(params.get("bgmvolume", "0.8"))
            except ValueError:
                pass
            settings["dubbing_wait"] = params.get("dubbing_wait", "0")
            settings["trans_thread"] = params.get("trans_thread", "5")
            settings["aitrans_thread"] = params.get("aitrans_thread", "100")
            settings["translation_wait"] = params.get("translation_wait", "0")
            settings["cjk_len"] = int(params.get("cjk_len", 20))
            settings["other_len"] = int(params.get("other_len", 60))
            settings["aisendsrt"] = params.get("aisendsrt", False)
            settings.save()

            # 说话人分类转换：index 0=不限(0), 1=2人, 2=3人, ...
            diariz_idx = int(params.get("nums_diariz", 0))
            nums_diariz = diariz_idx + 1 if diariz_idx > 0 else 0

            # 设置运行状态为 ing，否则 TransCreate._exit() 返回 True 导致所有步骤跳过
            cfg.app_cfg.current_status = "ing"

            # 拼接完整配置
            cfg_params = {
                **base_params,
                # 语言
                "source_language_code": params["source_language_code"],
                "target_language_code": params["target_language_code"],
                "source_language": params.get("source_language", ""),
                "target_language": params.get("target_language", ""),
                # 翻译
                "translate_type": int(params["translate_type"]),
                # 识别
                "recogn_type": int(params.get("recogn_type", 0)),
                "model_name": params.get("model_name", "tiny"),
                "remove_noise": params.get("remove_noise", False),
                "rephrase": int(params.get("rephrase", 2)),
                # 配音
                "tts_type": int(params["tts_type"]),
                "voice_role": params.get("voice_role", ""),
                "voice_rate": params.get("voice_rate", "+0%"),
                "volume": params.get("volume", "+0%"),
                "pitch": params.get("pitch", "+0Hz"),
                "voice_autorate": params.get("voice_autorate", False),
                "video_autorate": params.get("video_autorate", False),
                "remove_silent_mid": params.get("remove_silent_mid", False),
                "align_sub_audio": params.get("align_sub_audio", False),
                # 字幕
                "subtitle_type": int(params["subtitle_type"]),
                "output_srt": int(params.get("output_srt", 0)),
                "subtitles": getattr(self, "_imported_sub", ""),
                # 背景音
                "is_separate": params.get("is_separate", False),
                "embed_bgm": params.get("embed_bgm", False),
                "back_audio": params.get("back_audio", ""),
                # 高级
                "enable_diariz": params.get("enable_diariz", False),
                "nums_diariz": nums_diariz,
                "fix_punc": params.get("fix_punc", False),
                "recogn2pass": params.get("recogn2pass", False),
                # 其它
                "is_cuda": params.get("is_cuda", False) or cfg.settings.get("cuda", False),
                "only_out_mp4": params.get("only_out_mp4", False),
                "clear_cache": params.get("clear_cache", True),
                "detect_language": params.get("source_language_code", "auto"),
            }

            task_cfg = TaskCfgVTT(**cfg_params)
            trk = TransCreate(cfg=task_cfg)

            # 记录字幕路径以便轮询更新
            self._translate_source_sub = trk.cfg.source_sub
            self._translate_target_sub = trk.cfg.target_sub

            # ── 断点续跑检查点 ──
            from videotrans.task.pipeline_checkpoint import PipelineCheckpoint

            ckpt = PipelineCheckpoint(target_dir, cfg=trk.cfg)

            def _run_step(name, fn, *args, **kwargs):
                """执行管线步骤，已完成的自动跳过"""
                if ckpt.is_done(name):
                    self.translate_panel.log(f"[断点续跑] {name} 已完成，跳过")
                    return
                self._set_step(name)
                result = fn(*args, **kwargs)
                ckpt.mark_done(name)
                return result

            self._set_step("提取音频")
            trk.prepare()
            ckpt.mark_done("prepare")
            _run_step("音频转字幕", trk.recogn)

            # 暂停：让用户修改原文字幕
            if trk.cfg.source_sub and os.path.exists(trk.cfg.source_sub):
                self.translate_panel.log("原文字幕已生成，等待修改...")
                self._pause_for_subtitle_edit(trk.cfg.source_sub)

            # 保存原字幕备份
            import shutil

            if trk.cfg.source_sub and os.path.exists(trk.cfg.source_sub):
                src_save = os.path.join(target_dir, f"{nospace}_原字幕.srt")
                try:
                    shutil.copy2(trk.cfg.source_sub, src_save)
                    cfg.app_cfg.global_msg.append({"text": f"原字幕已保存: {src_save}", "type": "logs"})
                except Exception as e:
                    cfg.app_cfg.global_msg.append({"text": f"保存原字幕失败: {e}", "type": "error"})

            _run_step("说话人分离", trk.diariz)
            self.translate_panel.log(
                f"shoud_trans={trk.shoud_trans}, 源={params['source_language_code']}, 目标={params['target_language_code']}"
            )
            _run_step("翻译字幕", trk.trans)

            # 暂停：让用户修改翻译字幕
            if trk.cfg.target_sub and os.path.exists(trk.cfg.target_sub):
                self.translate_panel.log("翻译字幕已生成，等待修改...")
                self._pause_for_subtitle_edit(trk.cfg.target_sub)
            else:
                self.translate_panel.log(f"翻译字幕文件不存在: {trk.cfg.target_sub} (shoud_trans={trk.shoud_trans})")
                if trk.shoud_trans and trk.cfg.target_sub:
                    self.translate_panel.log(f"→ shoud_trans=True 但文件不存在，trans() 可能抛异常或未写入")
                elif not trk.shoud_trans:
                    self.translate_panel.log(
                        f"→ 源语言=目标语言({params['source_language_code']}=={params['target_language_code']})，翻译已跳过"
                    )

            # 保存翻译字幕备份
            if trk.cfg.target_sub and os.path.exists(trk.cfg.target_sub):
                tgt_save = os.path.join(target_dir, f"{nospace}_中文字幕.srt")
                try:
                    shutil.copy2(trk.cfg.target_sub, tgt_save)
                    cfg.app_cfg.global_msg.append({"text": f"翻译字幕已保存: {tgt_save}", "type": "logs"})
                except Exception as e:
                    cfg.app_cfg.global_msg.append({"text": f"保存翻译字幕失败: {e}", "type": "error"})

            _run_step("配音", trk.dubbing)
            _run_step("对齐控制", trk.align)
            _run_step("二次识别", trk.recogn2pass)
            _run_step("合成", trk.assembling)
            trk.task_done()

            self._translate_success = True
            self._translate_done = True

        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            logger.error(f"管线异常\n{tb}")
            self._translate_error = f"{e}\n{tb}"
            self._translate_done = True
            self._translate_success = False
        finally:
            cfg.app_cfg.current_status = "stop"
            # 清理合并产生的临时文件
            merged_path = None
            try:
                merged_path = merged_temp
            except NameError:
                pass
            if merged_path and os.path.exists(merged_path):
                parent = os.path.dirname(merged_path)
                try:
                    shutil.rmtree(parent, ignore_errors=True)
                except Exception:
                    pass

    def _poll_translate_logs(self):
        """轮询翻译日志、字幕更新和完成状态"""
        # 读取全局消息
        while cfg.app_cfg.global_msg:
            msg = cfg.app_cfg.global_msg.pop(0)
            if isinstance(msg, dict):
                text = msg.get("text", "")
                msg_type = msg.get("type", "logs")
                if msg_type == "error":
                    self.translate_panel.log(f"❌ {text}")
                    self._status_label.setText(f"错误: {text}")
                elif msg_type == "logs":
                    self.translate_panel.log(text)
                elif msg_type == "replace_subtitle":
                    # 字幕内容更新 → 刷新左侧字幕视图
                    if text:
                        self._update_subtitle_view(text)
                elif msg_type == "set_precent":
                    # 格式: "<elapsed>???<percent>"
                    if "???" in text:
                        parts = text.split("???")
                        if len(parts) == 2:
                            self._pipeline_pct = int(parts[1])
                            self._update_pipeline_status()

        # 轮询字幕文件更新
        self._poll_subtitle_files()

        # 检测是否有待打开的字幕编辑对话框
        if self._subtitle_edit_pending and not self._subtitle_dialog_open:
            self._subtitle_dialog_open = True
            self._open_subtitle_dialog()

        # 检查完成
        if getattr(self, "_translate_done", False):
            self._log_timer.stop()
            self.translate_panel.set_running(False)

            if getattr(self, "_translate_stopped", False):
                self.translate_panel.log("⏹ 翻译已停止")
                self._status_label.setText("翻译已停止")
            elif getattr(self, "_translate_success", False):
                self.translate_panel.log("✅ 翻译任务完成！")
                self._status_label.setText("翻译完成")
            else:
                err = getattr(self, "_translate_error", "未知错误")
                self.translate_panel.log(f"❌ 翻译失败: {err}")
                self._status_label.setText("翻译失败")

            self._translate_done = False

    def _set_step(self, name: str):
        """切换到新的管线步骤，重置百分比，更新状态栏"""
        self._pipeline_step = name
        self._pipeline_pct = 0
        self._status_label.setText(name)

    def _update_pipeline_status(self):
        """根据当前步骤和百分比更新左下角状态栏"""
        step = self._pipeline_step or "处理中"
        pct = self._pipeline_pct
        if pct > 0:
            self._status_label.setText(f"{step}  {pct}%")
        else:
            self._status_label.setText(step)

    def _pause_for_subtitle_edit(self, file_path: str):
        """在管线线程中调用，阻塞等待用户修改字幕或超时"""
        self._subtitle_edit_file = file_path
        self._subtitle_edit_pending = True
        # 等待最长 30 秒（对话框有 20 秒倒计时，留缓冲）
        # 对话框关闭（用户点击/超时）后会设置 resume，线程立即继续
        if not self._subtitle_resume.wait(30):
            self.translate_panel.log("等待超时（30秒），自动继续")
        self._subtitle_resume.clear()
        self._subtitle_edit_pending = False
        self._subtitle_dialog_open = False

    def _open_subtitle_dialog(self):
        """在主线程打开字幕编辑对话框"""
        if not self._subtitle_edit_file or not os.path.exists(self._subtitle_edit_file):
            self._subtitle_resume.set()
            return
        try:
            text = Path(self._subtitle_edit_file).read_text(encoding="utf-8")
            is_source = self._subtitle_edit_file == getattr(self, "_translate_source_sub", "")
            title = "原文字幕" if is_source else "翻译字幕"
            dialog = SubtitleEditDialog(self, title, text, self._subtitle_edit_file)
            dialog.exec()  # 阻塞直到用户点击或超时
            dialog.save()
        except Exception as e:
            self.translate_panel.log(f"打开字幕编辑对话框失败: {e}")
        finally:
            self._subtitle_resume.set()

    def _on_import_src_sub(self):
        """导入原文字幕文件"""
        fname, _ = QFileDialog.getOpenFileName(self, "导入原文字幕", "", "SRT文件(*.srt *.txt)")
        if not fname:
            return
        try:
            content = Path(fname).read_text(encoding="utf-8")
        except UnicodeError:
            content = Path(fname).read_text(encoding="gbk")
        if not content:
            return
        self._src_sub_edit.setPlainText(content)
        # 如果管线正在运行，同步写入管线所用的源字幕文件
        src_path = getattr(self, "_translate_source_sub", None)
        if src_path:
            Path(src_path).write_text(content, encoding="utf-8")
        self.translate_panel.log(f"已导入原文字幕: {os.path.basename(fname)}")

    def _on_import_tgt_sub(self):
        """导入翻译字幕文件"""
        fname, _ = QFileDialog.getOpenFileName(self, "导入翻译字幕", "", "SRT文件(*.srt *.txt)")
        if not fname:
            return
        try:
            content = Path(fname).read_text(encoding="utf-8")
        except UnicodeError:
            content = Path(fname).read_text(encoding="gbk")
        if not content:
            return
        self._tgt_sub_edit.setPlainText(content)
        # 如果管线正在运行，同步写入管线所用的翻译字幕文件
        tgt_path = getattr(self, "_translate_target_sub", None)
        if tgt_path:
            Path(tgt_path).write_text(content, encoding="utf-8")
        self.translate_panel.log(f"已导入翻译字幕: {os.path.basename(fname)}")

    def _update_subtitle_view(self, text: str):
        """根据信号内容更新左侧字幕视图"""
        if "-->" in text:
            self._src_sub_edit.setPlainText(text)
        else:
            self._tgt_sub_edit.setPlainText(text)

    def _poll_subtitle_files(self):
        """轮询字幕文件变化并更新左侧视图"""
        src = getattr(self, "_translate_source_sub", None)
        tgt = getattr(self, "_translate_target_sub", None)
        if src and os.path.exists(src):
            try:
                with open(src, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                if txt and txt != self._src_sub_edit.toPlainText():
                    self._src_sub_edit.setPlainText(txt)
            except Exception:
                pass
        if tgt and os.path.exists(tgt):
            try:
                with open(tgt, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                if txt and txt != self._tgt_sub_edit.toPlainText():
                    self._tgt_sub_edit.setPlainText(txt)
            except Exception:
                pass

    def _on_translate_stop(self):
        """停止翻译"""
        self._translate_running = False
        self._translate_stopped = True
        cfg.app_cfg.exit_soft = True
        # 如果正在等待字幕编辑，取消等待让管线线程退出
        if self._subtitle_edit_pending:
            self._subtitle_resume.set()
        self.translate_panel.log("⏹ 已停止")
        self._status_label.setText("正在停止...")
        # 让 _poll_translate_logs 中的 _translate_done 检测处理最终 UI 更新

    def _on_settings_category(self, category: str):
        from studio.settings_dialog import StudioSettingsDialog

        dlg = StudioSettingsDialog(self, initial_category=category)
        dlg.exec()

    def _on_dubbing_advanced(self):
        """打开配音高级设置对话框"""
        from studio.dubbing_advanced_dialog import DubbingAdvancedDialog

        dlg = DubbingAdvancedDialog(self)
        dlg.exec()

    # ── 设置持久化 ──

    def _load_settings(self):
        sets = QSettings("pyvideotrans", "studio")
        geo = sets.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        state = sets.value("windowState")
        if state:
            self.restoreState(state)
        fs = sets.value("subtitleFontSize")
        if fs:
            self._subtitle_font_size = int(fs)
        fb = sets.value("subtitleFontBold")
        if fb is not None:
            self._subtitle_font_bold = fb.lower() == "true"
        # 应用字幕样式到预览
        if hasattr(self, "_preview_widget"):
            self._preview_widget.update_subtitle_style(self._subtitle_font_size, self._subtitle_font_bold)

    def _save_settings(self):
        sets = QSettings("pyvideotrans", "studio")
        sets.setValue("geometry", self.saveGeometry())
        sets.setValue("windowState", self.saveState())
        sets.setValue("subtitleFontSize", self._subtitle_font_size)
        sets.setValue("subtitleFontBold", self._subtitle_font_bold)

    def closeEvent(self, event):
        """关闭时询问是否保存项目"""
        import json

        try:
            from . import oplog as _op

            _op.stop()
        except Exception:
            pass

        dlg = QMessageBox(self)
        dlg.setWindowTitle("pyvideotrans Studio")
        dlg.setText("是否保存当前项目？")
        dlg.setIcon(QMessageBox.Icon.Question)
        dlg.setStyleSheet("""
            QMessageBox {
                background-color: #1a1a1e;
                color: #e0e0e0;
            }
            QMessageBox QLabel {
                color: #e0e0e0;
                font-size: 14px;
            }
            QPushButton {
                background-color: #2a2a32;
                color: #d0d0d0;
                border: 1px solid #3a3a42;
                border-radius: 6px;
                padding: 8px 24px;
                font-size: 13px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #3a3a44;
            }
            QPushButton#saveBtn {
                background-color: #3a8cff;
                color: #ffffff;
                border: none;
                font-weight: bold;
            }
            QPushButton#saveBtn:hover {
                background-color: #4a9cff;
            }
        """)
        save_btn = dlg.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        save_btn.setObjectName("saveBtn")
        no_btn = dlg.addButton("不保存", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = dlg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        dlg.setDefaultButton(cancel_btn)
        dlg.exec()

        clicked = dlg.clickedButton()
        if clicked == cancel_btn:
            event.ignore()
            return
        if clicked == save_btn:
            save_path, _ = QFileDialog.getSaveFileName(self, "保存项目", "", "项目文件 (*.pvtproj);;所有文件 (*.*)")
            if not save_path:
                # 取消保存对话框 = 相当于取消关闭
                event.ignore()
                return
            self._project_path = save_path
            self._save_project(save_path)
        # 不保存：直接跳过
        self._save_settings()
        for attr in ("_pending_trim",):
            if hasattr(self, attr):
                delattr(self, attr)
        # 先取消引擎，再清理预览
        self._engine.cancel()
        self._preview_widget.pause()
        self._preview_widget.cleanup()
        super().closeEvent(event)

    def _save_project(self, path: str):
        """将当前项目状态保存为 .pvtproj 文件"""
        import json

        if not path.lower().endswith(".pvtproj"):
            path += ".pvtproj"

        def clip_to_dict(c) -> dict:
            d = {
                "source_path": c.source_path,
                "source_start": c.source_start,
                "start": c.start,
                "duration": c.duration,
                "source_duration": c.source_duration,
                "label": c.label,
                "track_type": getattr(c, "track_type", ""),
                "muted": c.muted,
                "speed": c.speed,
                "locked": c.locked,
                "position_fixed": c.position_fixed,
                "link_group": getattr(c, "link_group", ""),
                "display_scale": getattr(c, "display_scale", 1.0),
                "proxy_path": getattr(c, "proxy_path", ""),
                "target_width": getattr(c, "target_width", 0),
                "target_height": getattr(c, "target_height", 0),
                "effects": [
                    e if isinstance(e, dict) else {"name": e.name, "params": e.params}
                    for e in getattr(c, "effects", [])
                ],
            }
            return d

        project = {
            "version": 7,
            "media_files": list(self._media_files),
            "current_video": self._current_video or "",
            "duration": self._preview_widget.duration,
            "position": self._preview_widget.position,
            "clips": [clip_to_dict(c) for c in self._timeline_widget._clips],
            "subtitles": [
                {"index": e.index, "start": e.start, "end": e.end, "text": e.text}
                for e in self._timeline_widget._subtitle_entries
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(project, f, ensure_ascii=False, indent=2)
        self._status_label.setText(f"项目已保存: {os.path.basename(path)}")

    def _on_save_project(self):
        """文件菜单 → 保存（有路径则直接保存，否则另存为）"""
        if self._project_path:
            self._save_project(self._project_path)
        else:
            self._on_save_project_as()

    def _on_save_project_as(self):
        """文件菜单 → 另存为"""
        save_path, _ = QFileDialog.getSaveFileName(
            self, "另存为", self._project_path or "", "项目文件 (*.pvtproj);;所有文件 (*.*)"
        )
        if not save_path:
            return
        self._project_path = save_path
        self._save_project(save_path)

    def _on_open_project(self):
        """文件菜单 → 打开项目"""
        # 如果当前有未保存的修改，先询问
        if not self._timeline_widget.is_empty:
            dlg = QMessageBox(self)
            dlg.setWindowTitle("pyvideotrans Studio")
            dlg.setText("当前项目尚未保存，是否先保存？")
            dlg.setIcon(QMessageBox.Icon.Question)
            dlg.setStyleSheet("""
                QMessageBox { background-color: #1a1a1e; color: #e0e0e0; }
                QMessageBox QLabel { color: #e0e0e0; font-size: 14px; }
                QPushButton { background-color: #2a2a32; color: #d0d0d0;
                    border: 1px solid #3a3a42; border-radius: 6px;
                    padding: 8px 24px; font-size: 13px; min-width: 80px; }
                QPushButton:hover { background-color: #3a3a44; }
            """)
            btn_save = dlg.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
            btn_not = dlg.addButton("不保存", QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = dlg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            dlg.setDefaultButton(btn_cancel)
            dlg.exec()
            clicked = dlg.clickedButton()
            if clicked == btn_cancel:
                return
            if clicked == btn_save:
                self._on_save_project()

        open_path, _ = QFileDialog.getOpenFileName(self, "打开项目", "", "项目文件 (*.pvtproj);;所有文件 (*.*)")
        if not open_path:
            return
        self._load_project(open_path)

    def _load_project(self, path: str):
        """从 .pvtproj 文件加载项目"""
        import json
        from studio.editor import TimelineClip

        try:
            with open(path, "r", encoding="utf-8") as f:
                project = json.load(f)
        except Exception as e:
            self._status_label.setText(f"打开项目失败: {e}")
            return

        # 清空当前状态
        self._preview_widget.clear_preview()
        self._timeline_widget.clear_all()
        self.media_list.clear()
        self._media_files = []
        self._current_video = None
        # 恢复媒体列表
        for mpath in project.get("media_files", []):
            if os.path.exists(mpath):
                name = os.path.basename(mpath)
                item = QListWidgetItem(f"  {name}")
                item.setData(Qt.ItemDataRole.UserRole, mpath)
                item.setToolTip(mpath)
                self.media_list.addItem(item)
                self._media_files.append(mpath)

        # 恢复时长和位置
        duration = project.get("duration", 0)
        position = project.get("position", 0)
        self._timeline_widget.set_duration(duration)
        self._timeline_widget.set_position(position)

        # 恢复素材
        clips_data = project.get("clips", [])
        # 也兼容旧版多轨格式
        if not clips_data:
            for key in ("video_clips", "audio_clips", "bgm_clips", "subtitle_clips"):
                clips_data.extend(project.get(key, []))
        for cd in clips_data:
            clip = TimelineClip(
                source_path=cd.get("source_path", ""),
                source_start=cd.get("source_start", 0.0),
                start=cd.get("start", 0),
                duration=cd.get("duration", 0),
                source_duration=cd.get("source_duration", 0),
                label=cd.get("label", ""),
                speed=cd.get("speed", 1.0),
                muted=cd.get("muted", False),
                track_type=cd.get("track_type", ""),
                locked=cd.get("locked", False),
                position_fixed=cd.get("position_fixed", False),
                link_group=cd.get("link_group", ""),
                display_scale=cd.get("display_scale", 1.0),
                proxy_path=cd.get("proxy_path", ""),
                target_width=cd.get("target_width", 0),
                target_height=cd.get("target_height", 0),
            )
            # 恢复特效
            effects_data = cd.get("effects", [])
            if effects_data:
                clip.effects = effects_data
            self._timeline_widget._clips.append(clip)

        # 对老项目（缺少 source_start）做迁移：按 source_path 分组，
        # 根据时间线顺序推算每个素材在源文件中的偏移
        need_migration = all(c.source_start == 0.0 for c in self._timeline_widget._clips)
        if need_migration and any(c.speed != 1.0 for c in self._timeline_widget._clips):
            from collections import defaultdict

            groups = defaultdict(list)
            for i, c in enumerate(self._timeline_widget._clips):
                groups[c.source_path].append((i, c))
            for grp_clips in groups.values():
                grp_clips.sort(key=lambda x: x[1].start)
                running_offset = 0.0
                for idx, c in grp_clips:
                    self._timeline_widget._clips[idx].source_start = running_offset
                    running_offset += c.duration * c.speed

        # 恢复字幕
        from studio.editor.models import SubtitleEntry

        self._timeline_widget._subtitle_entries = [
            SubtitleEntry(
                index=s.get("index", i + 1),
                start=s.get("start", 0),
                end=s.get("end", 0),
                text=s.get("text", ""),
            )
            for i, s in enumerate(project.get("subtitles", []))
        ]

        self._timeline_widget._update_duration()
        self._timeline_widget.clips_changed.emit()
        self._timeline_widget._sync_zoom_slider()
        self._timeline_widget._update_scrollbar()
        self._timeline_widget.update()

        # 加载当前视频到预览
        current_video = project.get("current_video", "")
        if current_video and os.path.exists(current_video):
            self._load_video(current_video)
            self._preview_widget.seek(position)

        self._project_path = path
        self._status_label.setText(f"项目已打开: {os.path.basename(path)}")
