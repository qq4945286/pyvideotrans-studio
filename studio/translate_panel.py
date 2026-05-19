# -*- coding: utf-8 -*-
"""
翻译/配音参数面板 — 完整移植原版所有控件和行为
"""

import os
import time
import threading
import tempfile
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QScrollArea,
    QPlainTextEdit,
    QFrame,
    QSizePolicy,
    QFileDialog,
    QLineEdit,
    QGroupBox,
    QSplitter,
)

from videotrans.configure.config import tr, settings, logger, ROOT_DIR, TEMP_DIR
from videotrans.configure import config as cfg
from videotrans.util import tools, contants
from videotrans import translator, recognition, tts

# ── 主面板 ─────────────────────────────────────────────


class TranslatePanel(QWidget):
    """翻译/配音参数面板 — 完整功能版"""

    start_requested = Signal(dict)
    stop_requested = Signal()
    log_signal = Signal(str)  # 跨线程安全日志信号

    _CHECK_STYLE = """
        QCheckBox {
            color: #aaaaaa; font-size: 12px; spacing: 4px;
        }
        QCheckBox::indicator {
            border: 1px solid #888888; border-radius: 2px;
            width: 14px; height: 14px;
        }
        QCheckBox::indicator:hover { border-color: #aaaaaa; }
        QCheckBox::indicator:checked { background-color: #3a8cff; border-color: #3a8cff; }
    """

    _COMBO_STYLE = """
        QComboBox {
            background-color: #2a2a32; color: #e0e0e0;
            border: 1px solid #3a3a42; border-radius: 4px;
            padding: 2px 8px; font-size: 12px; min-height: 22px;
        }
        QComboBox:hover { border-color: #4a4a54; }
        QComboBox::drop-down { border: none; width: 20px; }
        QComboBox QAbstractItemView {
            background-color: #2a2a32; color: #e0e0e0;
            selection-background-color: #3a8cff; selection-color: #ffffff;
            border: 1px solid #4a4a54; outline: none;
        }
        QComboBox QAbstractItemView::item {
            padding: 4px 8px; min-height: 24px;
        }
        QComboBox QAbstractItemView::item:hover {
            background-color: #3a3a42;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_rolelist = []
        self._build_ui()
        self._load_config()
        self._bind_signals()
        self.log_signal.connect(self._on_log)

    # ── UI 构建 ──

    def _wrap_scroll(self, widget):
        """将内容包装到滚动区域"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidget(widget)
        return scroll

    def _section(self, title: str, content: QWidget = None) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #222226;
                border: 1px solid #2a2a30;
                border-radius: 4px; padding: 4px;
            }
        """)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(8, 4, 8, 4)
        fl.setSpacing(4)
        if title:
            lbl = QLabel(title)
            lbl.setStyleSheet("color:#3a8cff; font-size:12px; font-weight:bold; background:transparent; border:none;")
            fl.addWidget(lbl)
        if content:
            fl.addWidget(content)
        return frame

    def _form_row(self, label_text: str, widget) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent; border:none;")
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color:#cccccc; font-size:12px; min-width:60px;")
        lbl.setFixedWidth(60)
        hl.addWidget(lbl)
        hl.addWidget(widget, 1)
        return w

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # 容器（放入 QScrollArea）
        container = QWidget()
        container.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── 第 1 行：字幕导入 / 文件操作 ──
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self.import_sub_btn = QPushButton("  📂 导入已有字幕")
        self.import_sub_btn.setFixedHeight(26)
        self.import_sub_btn.setStyleSheet(
            "background:#2a2a32; color:#ccc; border:1px solid #3a3a42; border-radius:4px; font-size:12px; padding:0 10px;"
        )
        row1.addWidget(self.import_sub_btn)

        row1.addSpacing(8)

        self.clear_cache_cb = QCheckBox("清理缓存")
        self.clear_cache_cb.setStyleSheet(self._CHECK_STYLE)
        row1.addWidget(self.clear_cache_cb)

        row1.addSpacing(6)

        self.only_out_mp4_cb = QCheckBox("仅输出 MP4")
        self.only_out_mp4_cb.setStyleSheet(self._CHECK_STYLE)
        row1.addWidget(self.only_out_mp4_cb)

        row1.addSpacing(12)

        # 输出到目录
        out_label = QLabel("输出到")
        out_label.setStyleSheet("color:#cccccc; font-size:12px;")
        row1.addWidget(out_label)

        self._output_dir_edit = QLineEdit()
        self._output_dir_edit.setStyleSheet(
            "QLineEdit { background-color: #2a2a32; color: #e0e0e0; "
            "border: 1px solid #3a3a42; border-radius: 4px; padding: 2px 8px; font-size: 12px; }"
        )
        self._output_dir_edit.setPlaceholderText("默认输出目录")
        self._output_dir_edit.setFixedHeight(24)
        self._output_dir_edit.setMinimumWidth(80)
        self._output_dir_edit.setMaximumWidth(250)
        row1.addWidget(self._output_dir_edit, 1)

        self._output_dir_btn = QPushButton("📁")
        self._output_dir_btn.setFixedSize(28, 24)
        self._output_dir_btn.setStyleSheet(
            "background:#2a2a32; color:#ccc; border:1px solid #3a3a42; border-radius:4px; font-size:12px;"
        )
        self._output_dir_btn.clicked.connect(self._on_select_output_dir)
        row1.addWidget(self._output_dir_btn)

        row1.addStretch()
        layout.addLayout(row1)

        # ── 第 2 行：语音识别 ──
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        reg_label = QLabel("语音识别")
        reg_label.setStyleSheet("color:#3a8cff; font-size:12px; font-weight:bold; padding:0 4px;")
        row2.addWidget(reg_label)

        self.recogn_type = QComboBox()
        self.recogn_type.setStyleSheet(self._COMBO_STYLE)
        self.recogn_type.setMinimumWidth(140)
        self.recogn_type.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row2.addWidget(self.recogn_type)

        self.model_name_help = QPushButton("模型")
        self.model_name_help.setFixedHeight(24)
        self.model_name_help.setFixedWidth(60)
        self.model_name_help.setStyleSheet(
            "background:#2a2a32; color:#aaa; border:1px solid #3a3a42; border-radius:4px; font-size:11px;"
        )
        row2.addWidget(self.model_name_help)

        self.model_name = QComboBox()
        self.model_name.setStyleSheet(self._COMBO_STYLE)
        self.model_name.setMinimumWidth(120)
        self.model_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row2.addWidget(self.model_name)

        self.rephrase_combo = QComboBox()
        self.rephrase_combo.addItems(["默认断句", "LLM 重新断句"])
        self.rephrase_combo.setStyleSheet(self._COMBO_STYLE)
        self.rephrase_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row2.addWidget(self.rephrase_combo)

        self.remove_noise_cb = QCheckBox("降噪")
        self.remove_noise_cb.setStyleSheet(self._CHECK_STYLE)
        row2.addWidget(self.remove_noise_cb)

        self.recogn2pass_cb = QCheckBox("二次识别")
        self.recogn2pass_cb.setStyleSheet(self._CHECK_STYLE)
        row2.addWidget(self.recogn2pass_cb)

        row2.addStretch()
        layout.addLayout(row2)

        # ── 第 3 行：翻译设置 ──
        row3 = QHBoxLayout()
        row3.setSpacing(6)

        trans_label = QLabel("翻译服务")
        trans_label.setStyleSheet("color:#3a8cff; font-size:12px; font-weight:bold; padding:0 4px;")
        row3.addWidget(trans_label)

        self.translate_type = QComboBox()
        self.translate_type.setStyleSheet(self._COMBO_STYLE)
        self.translate_type.setMinimumWidth(140)
        self.translate_type.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row3.addWidget(self.translate_type)

        src_label = QLabel("源语言")
        src_label.setStyleSheet("color:#cccccc; font-size:12px;")
        row3.addWidget(src_label)

        self.source_language = QComboBox()
        self.source_language.setStyleSheet(self._COMBO_STYLE)
        self.source_language.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.source_language.currentIndexChanged.connect(self._on_source_language_change)
        row3.addWidget(self.source_language)

        tgt_label = QLabel("目标语言")
        tgt_label.setStyleSheet("color:#cccccc; font-size:12px;")
        row3.addWidget(tgt_label)

        self.target_language = QComboBox()
        self.target_language.setStyleSheet(self._COMBO_STYLE)
        self.target_language.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row3.addWidget(self.target_language)

        self.aisendsrt_cb = QCheckBox("发送完整字幕")
        self.aisendsrt_cb.setStyleSheet(self._CHECK_STYLE)
        row3.addWidget(self.aisendsrt_cb)

        self.glossary_btn = QPushButton("术语表")
        self.glossary_btn.setFixedHeight(24)
        self.glossary_btn.setFixedWidth(80)
        self.glossary_btn.setStyleSheet(
            "background:#2a2a32; color:#aaa; border:1px solid #3a3a42; border-radius:4px; font-size:11px;"
        )
        row3.addWidget(self.glossary_btn)

        layout.addLayout(row3)

        # ── 第 4 行：配音设置 ──
        row4 = QHBoxLayout()
        row4.setSpacing(6)

        dub_label = QLabel("配音引擎")
        dub_label.setStyleSheet("color:#3a8cff; font-size:12px; font-weight:bold; padding:0 4px;")
        row4.addWidget(dub_label)

        self.tts_type = QComboBox()
        self.tts_type.setStyleSheet(self._COMBO_STYLE)
        self.tts_type.setMinimumWidth(140)
        self.tts_type.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row4.addWidget(self.tts_type)

        self.tts_config_btn = QPushButton("⚙")
        self.tts_config_btn.setFixedSize(26, 26)
        self.tts_config_btn.setToolTip("重新配置当前配音引擎")
        self.tts_config_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a3a; color: #aaa;
                border: 1px solid #3a3a4a; border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #3a3a5a; color: #ccc; }
        """)
        self.tts_config_btn.clicked.connect(self._on_tts_config)
        row4.addWidget(self.tts_config_btn)

        role_label = QLabel("音色")
        role_label.setStyleSheet("color:#cccccc; font-size:12px;")
        row4.addWidget(role_label)

        self.voice_role = QComboBox()
        self.voice_role.setStyleSheet(self._COMBO_STYLE)
        self.voice_role.setMinimumWidth(120)
        self.voice_role.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row4.addWidget(self.voice_role)

        self.listen_btn = QPushButton("  🎧 试听  ")
        self.listen_btn.setFixedHeight(26)
        self.listen_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a4a2a; color: #8bc34a;
                border: 1px solid #3a5a3a; border-radius: 4px;
                font-size: 12px; font-weight: bold; padding: 0 8px;
            }
            QPushButton:hover { background-color: #3a5a4a; }
            QPushButton:disabled { background: #333; color: #666; border-color: #444; }
        """)
        self.listen_btn.setVisible(False)
        row4.addWidget(self.listen_btn)

        layout.addLayout(row4)

        # ── 第 5 行：对齐控制 / 字幕 / 代理 ──
        row5 = QHBoxLayout()
        row5.setSpacing(6)

        align_label = QLabel("对齐控制")
        align_label.setStyleSheet("color:#3a8cff; font-size:12px; font-weight:bold; padding:0 4px;")
        row5.addWidget(align_label)

        self.voice_autorate_cb = QCheckBox("配音自动加速")
        self.voice_autorate_cb.setStyleSheet(self._CHECK_STYLE)
        row5.addWidget(self.voice_autorate_cb)

        self.video_autorate_cb = QCheckBox("视频慢速")
        self.video_autorate_cb.setStyleSheet(self._CHECK_STYLE)
        row5.addWidget(self.video_autorate_cb)

        self.remove_silent_mid_cb = QCheckBox("删除静音片段")
        self.remove_silent_mid_cb.setStyleSheet(self._CHECK_STYLE)
        self.remove_silent_mid_cb.setVisible(False)
        row5.addWidget(self.remove_silent_mid_cb)

        self.align_sub_audio_cb = QCheckBox("强制对齐字幕音频")
        self.align_sub_audio_cb.setStyleSheet(self._CHECK_STYLE)
        self.align_sub_audio_cb.setVisible(False)
        row5.addWidget(self.align_sub_audio_cb)

        self.subtitle_type = QComboBox()
        self.subtitle_type.setStyleSheet(self._COMBO_STYLE)
        self.subtitle_type.setMinimumWidth(130)
        self.subtitle_type.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row5.addWidget(self.subtitle_type)

        self.output_srt = QComboBox()
        self.output_srt.addItems(["默认", "目标在下(双语)", "目标在上(双语)"])
        self.output_srt.setStyleSheet(self._COMBO_STYLE)
        self.output_srt.setVisible(False)
        row5.addWidget(self.output_srt)

        proxy_label = QLabel("网络代理")
        proxy_label.setStyleSheet("color:#cccccc; font-size:12px;")
        row5.addWidget(proxy_label)

        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("请填写真实代理地址")
        self.proxy_edit.setStyleSheet(
            "QLineEdit { background-color: #2a2a32; color: #e0e0e0; "
            "border: 1px solid #888888; border-radius: 4px; padding: 2px 8px; font-size: 12px; }"
        )
        self.proxy_edit.setFixedHeight(22)
        self.proxy_edit.setMinimumWidth(140)
        self.proxy_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row5.addWidget(self.proxy_edit)

        layout.addLayout(row5)

        # ── 第 6 行：CUDA/ROCM + 开始/停止按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.enable_cuda_cb = QCheckBox("CUDA/ROCM 加速")
        self.enable_cuda_cb.setStyleSheet(self._CHECK_STYLE)
        btn_row.addWidget(self.enable_cuda_cb)

        btn_row.addStretch()

        self.btn_start = QPushButton("  ▶ 开始执行  ")
        self.btn_start.setObjectName("accentBtn")
        self.btn_start.setFixedHeight(32)
        self.btn_start.setStyleSheet("""
            QPushButton#accentBtn {
                background-color: #3a8cff; color: #fff; border: none;
                border-radius: 6px; font-size: 14px; font-weight: bold; padding: 0 20px;
            }
            QPushButton#accentBtn:hover { background-color: #4a9cff; }
            QPushButton#accentBtn:disabled { background-color: #555; color: #999; }
        """)
        self.btn_start.clicked.connect(self._on_start)
        btn_row.addWidget(self.btn_start)

        self.btn_stop = QPushButton("  ■ 停止  ")
        self.btn_stop.setFixedHeight(32)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #cc4444; color: #fff; border: none;
                border-radius: 6px; font-size: 13px; padding: 0 16px;
            }
            QPushButton:hover { background-color: #dd5555; }
            QPushButton:disabled { background-color: #553333; color: #887777; }
        """)
        self.btn_stop.clicked.connect(self._on_stop)
        btn_row.addWidget(self.btn_stop)

        layout.addLayout(btn_row)

        # ── 可拖拽分割：上部参数区 / 下部运行日志 ──
        self._content_splitter = QSplitter(Qt.Orientation.Vertical)
        self._content_splitter.setHandleWidth(4)
        self._content_splitter.setStyleSheet("QSplitter::handle { background-color: #3a3a42; }")

        # 上半部：滚动参数区
        self._content_splitter.addWidget(self._wrap_scroll(container))

        # 下半部：运行日志
        log_widget = QWidget()
        log_widget.setStyleSheet("background:transparent;")
        log_inner = QVBoxLayout(log_widget)
        log_inner.setContentsMargins(12, 4, 12, 8)
        log_inner.setSpacing(4)

        log_label = QLabel("运行日志")
        log_label.setStyleSheet("color:#888888; font-size:11px;")
        log_inner.addWidget(log_label)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(500)
        self.log_output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0d0d0f; color: #a0a0a0;
                border: 1px solid #2a2a30; border-radius: 4px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 11px; padding: 4px;
            }
        """)
        self.log_output.setMinimumHeight(60)
        log_inner.addWidget(self.log_output, 1)

        self._content_splitter.addWidget(log_widget)
        self._content_splitter.setStretchFactor(0, 3)
        self._content_splitter.setStretchFactor(1, 1)

        outer_layout.addWidget(self._content_splitter, 1)

    # ── 配置加载 ──

    def _load_config(self):
        from videotrans.translator import TRANSLASTE_NAME_LIST, LANGNAME_DICT
        from videotrans.recognition import RECOGN_NAME_LIST
        from videotrans.tts import TTS_NAME_LIST

        lang_names = list(LANGNAME_DICT.values())
        lang_codes = list(LANGNAME_DICT.keys())

        # 语言
        self.source_language.clear()
        self.source_language.addItems([tr("Auto Detect")] + lang_names)
        self.target_language.clear()
        self.target_language.addItems(["-"] + lang_names)

        # 翻译
        self.translate_type.clear()
        self.translate_type.addItems(TRANSLASTE_NAME_LIST)

        # 识别
        self.recogn_type.clear()
        self.recogn_type.addItems(RECOGN_NAME_LIST)

        # TTS
        self.tts_type.clear()
        self.tts_type.addItems(TTS_NAME_LIST)

        # 字幕
        self.subtitle_type.clear()
        self.subtitle_type.addItems(
            [
                tr("nosubtitle"),
                tr("embedsubtitle"),
                tr("softsubtitle"),
                tr("embedsubtitle2"),
                tr("softsubtitle2"),
            ]
        )

        # 从设置恢复
        try:
            saved = cfg.params
            if saved.get("source_language", "") in lang_names:
                self.source_language.setCurrentText(saved["source_language"])
            if saved.get("target_language", "") in lang_names:
                self.target_language.setCurrentText(saved["target_language"])
            self.translate_type.setCurrentIndex(int(saved.get("translate_type", 0)))
            self.tts_type.setCurrentIndex(int(saved.get("tts_type", 0)))
            self.recogn_type.setCurrentIndex(int(saved.get("recogn_type", 0)))
            self.subtitle_type.setCurrentIndex(int(saved.get("subtitle_type", 0)))
            self.rephrase_combo.setCurrentIndex(int(saved.get("rephrase", 0)))
            if saved.get("model_name", ""):
                self.model_name.setCurrentText(saved["model_name"])
            self.voice_autorate_cb.setChecked(bool(saved.get("voice_autorate", False)))
            self.video_autorate_cb.setChecked(bool(saved.get("video_autorate", False)))
            self.enable_cuda_cb.setChecked(bool(saved.get("is_cuda", False)))
            self.remove_silent_mid_cb.setChecked(bool(saved.get("remove_silent_mid", False)))
            self.align_sub_audio_cb.setChecked(bool(saved.get("align_sub_audio", False)))
            self.recogn2pass_cb.setChecked(bool(saved.get("recogn2pass", False)))
            self.remove_noise_cb.setChecked(bool(saved.get("remove_noise", False)))
            self.clear_cache_cb.setChecked(bool(saved.get("clear_cache", False)))
        except Exception:
            pass

        # 代理
        if cfg.app_cfg.proxy:
            self.proxy_edit.setText(cfg.app_cfg.proxy)

        # 初始化模型列表
        self._update_model_list()
        # 初始化音色
        self._on_tts_type_change(self.tts_type.currentIndex())

    # ── 信号绑定 ──

    def _bind_signals(self):
        self.tts_type.currentIndexChanged.connect(self._on_tts_type_change)
        self.recogn_type.currentIndexChanged.connect(self._on_recogn_type_change)
        self.translate_type.currentIndexChanged.connect(self._on_translate_type_change)
        self.model_name.currentIndexChanged.connect(self._on_model_type_change)
        self.voice_role.currentTextChanged.connect(self._on_show_listen_btn)
        self.target_language.currentTextChanged.connect(self._on_target_language_change)
        self.voice_autorate_cb.toggled.connect(self._on_voice_autorate_toggle)
        self.video_autorate_cb.toggled.connect(self._on_video_autorate_toggle)
        self.listen_btn.clicked.connect(self._on_listen_voice)
        self.glossary_btn.clicked.connect(self._on_glossary)
        self.import_sub_btn.clicked.connect(self._on_import_sub)
        self.model_name_help.clicked.connect(self._on_model_help)
        self.subtitle_type.currentIndexChanged.connect(self._on_subtitle_type_change)
        self.proxy_edit.textChanged.connect(self._on_proxy_change)

    # ── 语音识别相关 ──

    def _on_recogn_type_change(self):
        idx = self.recogn_type.currentIndex()
        # 本地部署大模型 → 文件路径配置
        if idx == recognition.Whisper_CPP:
            if not self._check_cpp_path():
                return
        elif idx == recognition.Faster_Whisper_XXL:
            if not self._check_xxl_path():
                return
        # 在线AI模型 / API类 → 弹出API密钥/地址配置窗口
        if recognition.is_input_api(recogn_type=idx) is not True:
            return
        self._update_model_list()
        self._check_lang_compat()

    def _update_model_list(self):
        idx = self.recogn_type.currentIndex()
        self.model_name.clear()
        enable = True
        tip = ""
        if idx in (recognition.FASTER_WHISPER, recognition.Faster_Whisper_XXL, recognition.WHISPERX_API):
            self.model_name.addItems(cfg.settings.WHISPER_MODEL_LIST)
        elif idx == recognition.OPENAI_WHISPER:
            self.model_name.addItems(contants.Openai_Whisper_Models)
        elif idx == recognition.Deepgram:
            self.model_name.addItems(contants.DEEPGRAM_MODEL)
        elif idx == recognition.Whisper_CPP:
            self.model_name.addItems(cfg.settings.Whisper_CPP_MODEL_LIST)
        elif idx == recognition.WHISPER_NET:
            self.model_name.addItems(cfg.settings.Whisper_NET_MODEL_LIST)
        elif idx == recognition.QWENASR:
            self.model_name.addItems(["1.7B", "0.6B"])
        elif idx == recognition.HUGGINGFACE_ASR:
            self.model_name.addItems(list(recognition.HUGGINGFACE_ASR_MODELS.keys()))
        elif idx == recognition.FUNASR_CN:
            self.model_name.addItems(contants.FUNASR_MODEL)
        elif idx == recognition.MOONSHINE:
            src_text = self.source_language.currentText()
            lang = translator.get_code(show_text=src_text)
            import logging

            logging.debug(f"[Moonshine] source_language={src_text!r} -> code={lang!r}")
            self.model_name.addItems(recognition.get_moonshine_models(lang))
        else:
            enable = False
            self.model_name.addItems(["无需选择"])
            tip = "该识别渠道无需选择模型参数，如需配置请通过菜单栏设置"

        self.model_name.setEnabled(enable)
        self.model_name_help.setEnabled(enable)
        # 恢复上次选择
        saved_model = cfg.params.get("model_name", "")
        if saved_model:
            self.model_name.setCurrentText(saved_model)

    def _on_model_type_change(self):
        self._check_lang_compat()

    def _check_lang_compat(self):
        lang = translator.get_code(show_text=self.source_language.currentText())
        if not lang:
            return
        res = recognition.is_allow_lang(
            langcode=lang, recogn_type=self.recogn_type.currentIndex(), model_name=self.model_name.currentText()
        )
        # 这里可以显示提示，由于没有 show_tips 控件，暂时忽略

    def _check_cpp_path(self):
        cpp_path = cfg.settings.get("Whisper_cpp", "")
        if not cpp_path or not Path(cpp_path).exists():
            from videotrans.component.set_cpp import SetWhisperCPP

            dlg = SetWhisperCPP()
            if not dlg.exec():
                self.recogn_type.setCurrentIndex(0)
                return False
        return True

    def _check_xxl_path(self):
        import sys

        if sys.platform != "win32":
            return False
        xxl_path = cfg.settings.get("Faster_Whisper_XXL", "")
        if not xxl_path or not Path(xxl_path).exists():
            from videotrans.component.set_xxl import SetFasterXXL

            dlg = SetFasterXXL()
            if not dlg.exec():
                self.recogn_type.setCurrentIndex(0)
                return False
        return True

    def _on_model_help(self):
        from PySide6.QtWidgets import QMessageBox

        msg = (
            "从 tiny 到 large-v3，识别效果越来越好，但模型越来越大，速度越来越慢。\n\n"
            ".en 后缀模型和 distil 开头的模型仅用于识别英文发音视频。"
        )
        box = QMessageBox(self)
        box.setWindowTitle("模型说明")
        box.setText(msg)
        box.setStyleSheet(
            "QMessageBox { background:#1a1a1e; color:#e0e0e0; } "
            "QPushButton { background:#2a2a32; color:#ccc; border:1px solid #3a3a42; "
            "border-radius:4px; padding:6px 20px; }"
        )
        box.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    # ── 翻译相关 ──

    def _on_translate_type_change(self, idx):
        """翻译渠道变化时检测条件（如 API key 配置）"""
        from videotrans.translator import is_allow_translate

        t = self.target_language.currentText()
        if t and t != "-":
            is_allow_translate(translate_type=idx, show_target=t)

    def _on_source_language_change(self):
        if self.recogn_type.currentIndex() == recognition.MOONSHINE:
            self._update_model_list()

    def _on_target_language_change(self, t):
        code = translator.get_code(show_text=t)
        if code and code != "-":
            tts.is_allow_lang(langcode=code, tts_type=self.tts_type.currentIndex())
        self._set_voice_role(t)

    def _set_voice_role(self, t):
        """目标语言改变时，按语言过滤音色"""
        if not self._change_by_lang(self.tts_type.currentIndex()):
            # 非语言相关引擎，只需控制试听按钮
            role = self.voice_role.currentText()
            if role != "No":
                self.listen_btn.setVisible(True)
                self.listen_btn.setEnabled(True)
            else:
                self.listen_btn.setVisible(False)
            return

        self.listen_btn.setVisible(False)
        self.voice_role.clear()
        if t == "-":
            self.voice_role.addItems(["No"])
            return

        code = translator.get_code(show_text=t)
        if not code:
            self.voice_role.addItems(["No"])
            return
        vt = code.split("-")[0]
        tts_type = self.tts_type.currentIndex()

        try:
            if tts_type == tts.EDGE_TTS:
                rolelist = tools.get_edge_rolelist()
            elif tts_type == tts.KOKORO_TTS:
                rolelist = tools.get_kokoro_rolelist()
            elif tts_type == tts.MINIMAXI_TTS:
                rolelist = tools.get_minimaxi_rolelist()
            elif tts_type == tts.AI302_TTS:
                rolelist = tools.get_302ai()
            elif tts_type == tts.DOUBAO_TTS:
                rolelist = tools.get_doubao_rolelist()
            elif tts_type == tts.DOUBAO2_TTS:
                rolelist = tools.get_doubao2_rolelist()
            elif tts_type == tts.PIPER_TTS:
                rolelist = tools.get_piper_role()
            elif tts_type == tts.VITSCNEN_TTS:
                rolelist = tools.get_vits_role()
            else:
                # Azure TTS 等
                rolelist = tools.get_azure_rolelist()
        except Exception:
            rolelist = None

        if not rolelist:
            self.voice_role.addItems(["No"])
            return

        if vt not in rolelist:
            self.voice_role.addItems(["No"])
            return

        if tts_type == tts.MINIMAXI_TTS:
            items = list(rolelist[vt].keys())
            self._current_rolelist = items
            self.voice_role.addItems(items)
            return

        if len(rolelist[vt]) < 1:
            self.voice_role.addItems(["No"])
            return

        if isinstance(rolelist[vt], list):
            self._current_rolelist = rolelist[vt]
            self.voice_role.addItems(rolelist[vt])
        else:
            self._current_rolelist = list(rolelist[vt].keys())
            self.voice_role.addItems(self._current_rolelist)

    def _on_glossary(self):
        tools.show_glossary_editor(self)

    def _on_import_sub(self):
        fname, _ = QFileDialog.getOpenFileName(self, "导入字幕文件", "", "SRT文件(*.srt *.txt)")
        if fname:
            try:
                content = Path(fname).read_text(encoding="utf-8")
            except UnicodeError:
                content = Path(fname).read_text(encoding="gbk")
            if content:
                self._imported_sub = content
                self.log(f"已导入字幕: {os.path.basename(fname)}")

    def _on_select_output_dir(self):
        """选择输出目录"""
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if d:
            self._output_dir_edit.setText(Path(d).as_posix())

    def _on_subtitle_type_change(self, idx):
        if idx < 3:
            self.output_srt.setVisible(False)
        else:
            self.output_srt.setCurrentIndex(2)
            self.output_srt.setVisible(True)

    def _on_proxy_change(self, p):
        cfg.app_cfg.proxy = p.strip()
        if cfg.app_cfg.proxy:
            tools.set_proxy(cfg.app_cfg.proxy)
            cfg.settings["proxy"] = cfg.app_cfg.proxy
        else:
            cfg.settings["proxy"] = ""
            tools.set_proxy("del")
        cfg.settings.save()

    # ── TTS/配音相关 ──

    def _change_by_lang(self, tts_type):
        """配音角色是否随语言变化"""
        return tts_type in [
            tts.EDGE_TTS,
            tts.MINIMAXI_TTS,
            tts.AZURE_TTS,
            tts.DOUBAO_TTS,
            tts.DOUBAO2_TTS,
            tts.AI302_TTS,
            tts.KOKORO_TTS,
            tts.PIPER_TTS,
            tts.VITSCNEN_TTS,
            tts.FreeAzure,
        ]

    def _on_tts_config(self):
        """打开当前配音引擎的配置窗口"""
        idx = self.tts_type.currentIndex()
        win_map = {
            tts.COSYVOICE_TTS: ("videotrans.winform.cosyvoice", "cosyvoice"),
            tts.GPTSOVITS_TTS: ("videotrans.winform.gptsovits", "gptsovits"),
            tts.F5_TTS: ("videotrans.winform.f5tts", "f5tts"),
            tts.OMNIVOICE_TTS: ("videotrans.winform.omnivoice", "omnivoice"),
            tts.CHATTERBOX_TTS: ("videotrans.winform.chatterbox", "chatterbox"),
            tts.CLONE_VOICE_TTS: ("videotrans.winform.clone", "clone"),
            tts.FISHTTS: ("videotrans.winform.fishtts", "fishtts"),
            tts.CHATTTS: ("videotrans.winform.chattts", "chattts"),
            tts.KOKORO_TTS: ("videotrans.winform.kokoro", "kokoro"),
            tts.OPENAI_TTS: ("videotrans.winform.openaitts", "openaitts"),
            tts.AI302_TTS: ("videotrans.winform.ai302", "ai302"),
            tts.ELEVENLABS_TTS: ("videotrans.winform.elevenlabs", "elevenlabs"),
            tts.AZURE_TTS: ("videotrans.winform.azuretts", "azuretts"),
            tts.GEMINI_TTS: ("videotrans.winform.gemini", "gemini"),
            tts.TTS_API: ("videotrans.winform.ttsapi", "ttsapi"),
            tts.DOUBAO_TTS: ("videotrans.winform.volcenginetts", "volcenginetts"),
            tts.DOUBAO2_TTS: ("videotrans.winform.doubao2", "doubao2"),
            tts.GLM_TTS: ("videotrans.winform.zhipuai", "zhipuai"),
            tts.QWEN_TTS: ("videotrans.winform.qwentts", "qwentts"),
            tts.XAI_TTS: ("videotrans.winform.xaitts", "xaitts"),
            tts.XIAOMI_TTS: ("videotrans.winform.mitts", "mitts"),
            tts.MINIMAXI_TTS: ("videotrans.winform.minimaxi", "minimaxi"),
            tts.CAMB_TTS: ("videotrans.winform.cambtts", "cambtts"),
            tts.MOSS_TTS: ("videotrans.winform.mosstts", "mosstts"),
        }
        # F5-TTS 系列共享同一个配置窗口
        if idx in (tts.INDEX_TTS, tts.SPARK_TTS, tts.VOXCPM_TTS, tts.DIA_TTS):
            idx = tts.F5_TTS
        if idx in win_map:
            mod_path, attr = win_map[idx]
            import importlib

            mod = importlib.import_module(mod_path)
            getattr(mod, "openwin")()
        else:
            self.log("当前配音引擎无需额外配置")

    def _on_tts_type_change(self, idx):
        """TTS 引擎切换 → 更新音色列表"""
        if tts.is_input_api(tts_type=idx) is not True:
            self.tts_type.setCurrentIndex(0)
            return

        lang = translator.get_code(show_text=self.target_language.currentText())
        if lang and lang != "-":
            res = tts.is_allow_lang(langcode=lang, tts_type=idx)

        cfg.app_cfg.line_roles = {}
        self.voice_role.clear()

        if idx == tts.GOOGLE_TTS:
            self._current_rolelist = ["No", "gtts"]
            self.voice_role.addItems(self._current_rolelist)
        elif idx == tts.OPENAI_TTS:
            roles = ["No"] + cfg.params.get("openaitts_role", contants.OPENAITTS_ROLES).split(",")
            self._current_rolelist = roles
            self.voice_role.addItems(roles)
        elif idx == tts.XAI_TTS:
            roles = ["No"] + contants.XAITTS_ROLES.split(",")
            self._current_rolelist = roles
            self.voice_role.addItems(roles)
        elif idx == tts.XIAOMI_TTS:
            roles = ["No"] + contants.MITTS_ROLES.split(",")
            self._current_rolelist = roles
            self.voice_role.addItems(roles)
        elif idx == tts.QWEN_TTS:
            roles = list(tools.get_qwen3tts_rolelist().keys())
            self._current_rolelist = roles
            self.voice_role.addItems(roles)
        elif idx == tts.GLM_TTS:
            roles = list(tools.get_glmtts_rolelist().keys())
            self._current_rolelist = roles
            self.voice_role.addItems(roles)
        elif idx == tts.GEMINI_TTS:
            self._current_rolelist = contants.GEMINITTS_ROLES.split(",")
            self.voice_role.addItems(self._current_rolelist)
        elif idx == tts.ELEVENLABS_TTS:
            self._current_rolelist = tools.get_elevenlabs_role()
            self.voice_role.addItems(self._current_rolelist)
        elif idx == tts.CAMB_TTS:
            self._current_rolelist = tools.get_camb_role()
            self.voice_role.addItems(self._current_rolelist)
        elif idx == tts.MOSS_TTS:
            self._current_rolelist = tools.get_mosstts_role()
            self.voice_role.addItems(self._current_rolelist)
        elif idx == tts.CLONE_VOICE_TTS:
            self._current_rolelist = cfg.params.get("clone_voicelist", [])
            if not self._current_rolelist or self._current_rolelist[0] != "No":
                self._current_rolelist.insert(0, "No")
            self.voice_role.addItems(self._current_rolelist)
            threading.Thread(target=tools.get_clone_role, daemon=True).start()
        elif idx == tts.CHATTTS:
            self._current_rolelist = list(cfg.settings.ChatTTS_voicelist)
            self.voice_role.addItems(["No"] + self._current_rolelist)
        elif idx == tts.TTS_API:
            raw = cfg.params.get("ttsapi_voice_role", "")
            self._current_rolelist = [r.strip() for r in raw.split(",") if r.strip()]
            self.voice_role.addItems(["No"] + self._current_rolelist)
        elif idx == tts.GPTSOVITS_TTS:
            r = tools.get_gptsovits_role()
            self._current_rolelist = list(r.keys()) if r else []
            self.voice_role.addItems(self._current_rolelist or ["GPT-SoVITS"])
        elif idx == tts.CHATTERBOX_TTS:
            r = tools.get_chatterbox_role()
            self._current_rolelist = r or ["chatterbox"]
            self.voice_role.addItems(self._current_rolelist)
        elif idx == tts.COSYVOICE_TTS:
            r = tools.get_cosyvoice_role()
            self._current_rolelist = list(r.keys()) if r else ["clone"]
            self.voice_role.addItems(self._current_rolelist)
        elif idx == tts.OMNIVOICE_TTS:
            r = tools.get_omnivoice_role()
            self._current_rolelist = list(r.keys()) if r else ["clone"]
            self.voice_role.addItems(self._current_rolelist)
        elif idx == tts.FISHTTS:
            r = tools.get_fishtts_role()
            self._current_rolelist = list(r.keys()) if r else ["No"]
            self.voice_role.addItems(self._current_rolelist)
        elif idx in (tts.F5_TTS, tts.INDEX_TTS, tts.SPARK_TTS, tts.VOXCPM_TTS, tts.DIA_TTS):
            r = tools.get_f5tts_role()
            self._current_rolelist = ["clone"] + list(r.keys()) if r else ["clone"]
            self.voice_role.addItems(self._current_rolelist)
        elif self._change_by_lang(idx):
            self._set_voice_role(self.target_language.currentText())
        else:
            # 兜底
            self._current_rolelist = ["No"]
            self.voice_role.addItems(["No"])

    def _on_show_listen_btn(self, role):
        """角色改变 → 控制试听按钮"""
        voice_role = self.voice_role.currentText()
        tip = tts.clone_tips(self.tts_type.currentIndex(), voice_role, self.recogn_type.currentIndex())
        if voice_role == "No" or voice_role == "clone":
            self.listen_btn.setVisible(False)
            return
        self.listen_btn.setVisible(True)
        self.listen_btn.setEnabled(True)

    def _on_listen_voice(self):
        """试听配音"""
        lang = translator.get_code(show_text=self.target_language.currentText())
        if not lang:
            self.log("请先选择目标语言")
            return

        text = contants.LISTEN_TEXT.get(lang)
        if not text:
            self.log("该语言不支持试听")
            return

        role = self.voice_role.currentText()
        if not role or role == "No":
            self.log("请先选择配音角色")
            return

        if role == "clone":
            self.log("原声克隆无法试听")
            return

        voice_dir = os.path.join(tempfile.gettempdir(), "pyvideotrans")
        os.makedirs(voice_dir, exist_ok=True)

        rate = int(str(cfg.params.get("voice_rate", 0)).strip("+%"))
        rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
        volume = int(str(cfg.params.get("volume", 0)).strip("+%"))
        volume_str = f"+{volume}%" if volume >= 0 else f"{volume}%"
        pitch = int(str(cfg.params.get("pitch", 0)).strip("+%"))
        pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"

        voice_file = os.path.join(voice_dir, f"listen_{time.time()}.wav")
        tts_type = self.tts_type.currentIndex()
        obj = {
            "text": text,
            "rate": rate_str,
            "role": role,
            "filename": voice_file,
            "tts_type": tts_type,
            "language": lang,
            "volume": volume_str,
            "pitch": pitch_str,
        }

        from videotrans.util.ListenVoice import ListenVoice

        raw_text = self.listen_btn.text()

        def feed(d):
            self.listen_btn.setEnabled(True)
            self.listen_btn.setText(raw_text)
            if d != "ok":
                self.log(f"试听失败: {d}")
            else:
                self.log("试听完成")

        self.listen_btn.setEnabled(True)
        self.listen_btn.setText("加载中...")
        self._listen_worker = ListenVoice(parent=self, queue_tts=[obj], language=lang, tts_type=tts_type)
        self._listen_worker.uito.connect(feed)
        self._listen_worker.start()

    # ── 对齐控制 ──

    def _on_voice_autorate_toggle(self, state):
        if state:
            self.remove_silent_mid_cb.setVisible(False)
            self.align_sub_audio_cb.setVisible(False)
        elif not self.video_autorate_cb.isChecked():
            self.remove_silent_mid_cb.setVisible(True)
            self.align_sub_audio_cb.setVisible(True)

    def _on_video_autorate_toggle(self, state):
        if state:
            self.remove_silent_mid_cb.setVisible(False)
            self.align_sub_audio_cb.setVisible(False)
        elif not self.voice_autorate_cb.isChecked():
            self.remove_silent_mid_cb.setVisible(True)
            self.align_sub_audio_cb.setVisible(True)

    # ── 高级设置 ──

    # ── 参数收集 ──

    def _collect_params(self) -> dict:
        from videotrans.translator import TRANSLASTE_NAME_LIST, LANGNAME_DICT
        from videotrans.tts import TTS_NAME_LIST

        lang_names = list(LANGNAME_DICT.values())
        lang_codes = list(LANGNAME_DICT.keys())

        source_name = self.source_language.currentText()
        target_name = self.target_language.currentText()

        source_code = "auto"
        target_code = ""
        for i, name in enumerate(lang_names):
            if name == source_name:
                source_code = lang_codes[i]
            if name == target_name:
                target_code = lang_codes[i]

        return {
            # 语言
            "source_language_code": source_code,
            "target_language_code": target_code or "en",
            "source_language": source_name,
            "target_language": target_name,
            # 翻译
            "translate_type": self.translate_type.currentIndex(),
            "aisendsrt": self.aisendsrt_cb.isChecked(),
            # 识别
            "recogn_type": self.recogn_type.currentIndex(),
            "model_name": self.model_name.currentText(),
            "remove_noise": self.remove_noise_cb.isChecked(),
            "rephrase": self.rephrase_combo.currentIndex(),
            "recogn2pass": self.recogn2pass_cb.isChecked(),
            # VAD（从配音高级设置对话框持久化的配置读取）
            "threshold": cfg.params.get("threshold", "0.5"),
            "min_speech_duration_ms": cfg.params.get("min_speech_duration_ms", "1000"),
            "min_silence_duration_ms": cfg.params.get("min_silence_duration_ms", "250"),
            "max_speech_duration_s": cfg.params.get("max_speech_duration_s", "8"),
            "enable_diariz": cfg.params.get("enable_diariz", False),
            "nums_diariz": cfg.params.get("nums_diariz", 0),
            "fix_punc": cfg.params.get("fix_punc", False),
            # 配音
            "tts_type": self.tts_type.currentIndex(),
            "voice_role": self.voice_role.currentText(),
            "voice_rate": cfg.params.get("voice_rate", 0),
            "volume": cfg.params.get("volume", 0),
            "pitch": cfg.params.get("pitch", 0),
            "voice_autorate": self.voice_autorate_cb.isChecked(),
            "video_autorate": self.video_autorate_cb.isChecked(),
            "remove_silent_mid": self.remove_silent_mid_cb.isChecked(),
            "align_sub_audio": self.align_sub_audio_cb.isChecked(),
            "dubbing_wait": cfg.params.get("dubbing_wait", "0"),
            # 字幕
            "subtitle_type": self.subtitle_type.currentIndex(),
            "output_srt": self.output_srt.currentIndex(),
            # BGM（从配音高级设置对话框持久化的配置读取）
            "is_separate": cfg.params.get("is_separate", False),
            "embed_bgm": cfg.params.get("embed_bgm", False),
            "back_audio": cfg.params.get("back_audio", ""),
            "is_loop_bgm": cfg.params.get("is_loop_bgm", 0),
            "bgmvolume": cfg.params.get("bgmvolume", "0.8"),
            # 其他
            "is_cuda": self.enable_cuda_cb.isChecked(),
            "only_out_mp4": self.only_out_mp4_cb.isChecked(),
            "clear_cache": self.clear_cache_cb.isChecked(),
            "proxy": self.proxy_edit.text().strip(),
            # 高级（从配音高级设置对话框持久化的配置读取）
            "trans_thread": cfg.params.get("trans_thread", "5"),
            "aitrans_thread": cfg.params.get("aitrans_thread", "100"),
            "translation_wait": cfg.params.get("translation_wait", "0"),
            "cjk_len": cfg.params.get("cjk_len", 20),
            "other_len": cfg.params.get("other_len", 60),
            # 输出目录
            "target_dir_override": self._output_dir_edit.text().strip(),
        }

    # ── 操作 ──

    def _on_start(self):
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log_output.clear()
        self.log("开始执行...")
        params = self._collect_params()
        # 保存参数
        cfg.params.getset_params(params)
        self.start_requested.emit(params)

    def _on_stop(self):
        self.btn_stop.setEnabled(False)
        self.log("正在停止...")
        self.stop_requested.emit()

    def log(self, msg: str):
        """跨线程安全 — 通过信号在主线程更新 UI"""
        self.log_signal.emit(msg)

    def _on_log(self, msg: str):
        """在主线程执行的日志更新"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {msg}")
        scrollbar = self.log_output.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def set_running(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def reset(self):
        self.set_running(False)
