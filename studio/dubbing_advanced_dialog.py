# -*- coding: utf-8 -*-
"""
配音高级设置参数对话框 — 从顶部菜单打开的所有高级参数面板
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QLineEdit,
    QFileDialog,
    QScrollArea,
    QWidget,
    QFrame,
)

from videotrans.configure.config import settings

_DIALOG_STYLE = """
    QDialog {
        background-color: #1a1a1e;
    }
    QLabel {
        color: #cccccc; font-size: 12px;
    }
    QLineEdit {
        background-color: #2a2a32; color: #e0e0e0;
        border: 1px solid #3a3a42; border-radius: 4px;
        padding: 2px 8px; font-size: 12px;
    }
    QSpinBox {
        background-color: #2a2a32; color: #e0e0e0;
        border: 1px solid #3a3a42; border-radius: 4px;
        padding: 2px 4px; font-size: 12px;
    }
    QCheckBox {
        color: #aaaaaa; font-size: 12px; spacing: 4px;
    }
    QCheckBox::indicator {
        border: 1px solid #888888; border-radius: 2px;
        width: 14px; height: 14px;
    }
    QCheckBox::indicator:hover { border-color: #aaaaaa; }
    QCheckBox::indicator:checked { background-color: #3a8cff; border-color: #3a8cff; }
    QComboBox {
        background-color: #2a2a32; color: #e0e0e0;
        border: 1px solid #3a3a42; border-radius: 4px;
        padding: 2px 8px; font-size: 12px; min-height: 22px;
    }
    QComboBox::drop-down { border: none; width: 20px; }
    QComboBox QAbstractItemView {
        background-color: #2a2a32; color: #e0e0e0;
        selection-background-color: #3a8cff; selection-color: #ffffff;
        border: 1px solid #4a4a54; outline: none;
    }
    QPushButton {
        background-color: #2a2a32; color: #aaa;
        border: 1px solid #3a3a42; border-radius: 4px;
        padding: 4px 12px; font-size: 12px;
    }
    QPushButton:hover {
        background-color: #3a3a42; color: #ddd;
    }
    QPushButton#accentBtn {
        background-color: #3a8cff; color: #ffffff;
        border: none; border-radius: 4px;
        font-size: 13px; font-weight: bold;
        padding: 6px 24px;
    }
    QPushButton#accentBtn:hover {
        background-color: #4a9cff;
    }
"""


class DubbingAdvancedDialog(QDialog):
    """配音高级设置参数对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配音高级设置参数")
        self.setMinimumSize(680, 520)
        self.resize(720, 560)
        self.setStyleSheet(_DIALOG_STYLE)

        self._build_ui()
        self._load_from_config()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(10)

        # ── 1. VAD 参数 ──
        vad_group = self._make_group("VAD 语音活动检测")
        vad_row = QHBoxLayout()
        vad_row.setSpacing(6)
        vad_labels = [
            ("threshold:", "threshold", "0.5"),
            ("min_speech_ms:", "min_speech_duration_ms", "1000"),
            ("min_silence_ms:", "min_silence_duration_ms", "250"),
            ("max_speech_s:", "max_speech_duration_s", "8"),
        ]
        self._vad_widgets = {}
        for label, key, default in vad_labels:
            lbl = QLabel(label)
            le = QLineEdit(default)
            le.setFixedHeight(22)
            le.setMaximumWidth(70)
            vad_row.addWidget(lbl)
            vad_row.addWidget(le)
            self._vad_widgets[key] = le
        self.fix_punc_cb = QCheckBox("标点恢复")
        vad_row.addWidget(self.fix_punc_cb)
        self.enable_diariz_cb = QCheckBox("说话人分类")
        vad_row.addWidget(self.enable_diariz_cb)
        self.nums_diariz = QComboBox()
        self.nums_diariz.addItems(["不限", "2", "3", "4", "5", "6", "7", "8", "9", "10"])
        self.nums_diariz.setMaximumWidth(60)
        vad_row.addWidget(self.nums_diariz)
        vad_row.addStretch()
        vad_group.layout().addLayout(vad_row)
        cl.addWidget(vad_group)

        # ── 2. 翻译并发 ──
        trans_group = self._make_group("翻译并发参数")
        tc_row = QHBoxLayout()
        tc_row.setSpacing(6)
        tc_row.addWidget(QLabel("普通每批行数:"))
        self.trans_thread = QLineEdit("5")
        self.trans_thread.setFixedHeight(22)
        self.trans_thread.setMaximumWidth(60)
        tc_row.addWidget(self.trans_thread)
        tc_row.addWidget(QLabel("AI每批行数:"))
        self.aitrans_thread = QLineEdit("100")
        self.aitrans_thread.setFixedHeight(22)
        self.aitrans_thread.setMaximumWidth(60)
        tc_row.addWidget(self.aitrans_thread)
        tc_row.addWidget(QLabel("等待/s:"))
        self.translation_wait = QLineEdit("0")
        self.translation_wait.setFixedHeight(22)
        self.translation_wait.setMaximumWidth(60)
        tc_row.addWidget(self.translation_wait)
        tc_row.addStretch()
        trans_group.layout().addLayout(tc_row)
        cl.addWidget(trans_group)

        # ── 3. 配音微调 ──
        dub_group = self._make_group("配音微调")
        dub_row = QHBoxLayout()
        dub_row.setSpacing(6)
        dub_row.addWidget(QLabel("配音等待/s:"))
        self.dubbing_wait = QLineEdit("0")
        self.dubbing_wait.setFixedHeight(22)
        self.dubbing_wait.setMaximumWidth(60)
        dub_row.addWidget(self.dubbing_wait)
        dub_row.addWidget(QLabel("语速:"))
        self.voice_rate = QSpinBox()
        self.voice_rate.setRange(-50, 50)
        self.voice_rate.setValue(0)
        self.voice_rate.setSuffix("%")
        self.voice_rate.setMaximumWidth(70)
        dub_row.addWidget(self.voice_rate)
        dub_row.addWidget(QLabel("音量:"))
        self.volume_rate = QSpinBox()
        self.volume_rate.setRange(-95, 100)
        self.volume_rate.setValue(0)
        self.volume_rate.setSuffix("%")
        self.volume_rate.setMaximumWidth(70)
        dub_row.addWidget(self.volume_rate)
        dub_row.addWidget(QLabel("音调:"))
        self.pitch_rate = QSpinBox()
        self.pitch_rate.setRange(-100, 100)
        self.pitch_rate.setValue(0)
        self.pitch_rate.setSuffix("Hz")
        self.pitch_rate.setMaximumWidth(70)
        dub_row.addWidget(self.pitch_rate)
        dub_row.addStretch()
        dub_group.layout().addLayout(dub_row)
        cl.addWidget(dub_group)

        # ── 4. 硬字幕单行字符 ──
        sub_group = self._make_group("硬字幕排版")
        cl_row = QHBoxLayout()
        cl_row.setSpacing(6)
        cl_row.addWidget(QLabel("中日韩单行字符:"))
        self.cjklinenums = QSpinBox()
        self.cjklinenums.setRange(5, 100)
        self.cjklinenums.setValue(20)
        self.cjklinenums.setMaximumWidth(70)
        cl_row.addWidget(self.cjklinenums)
        cl_row.addWidget(QLabel("其他:"))
        self.othlinenums = QSpinBox()
        self.othlinenums.setRange(5, 100)
        self.othlinenums.setValue(60)
        self.othlinenums.setMaximumWidth(70)
        cl_row.addWidget(self.othlinenums)
        self.set_ass_btn = QPushButton("  修改硬字幕样式  ")
        self.set_ass_btn.setFixedHeight(24)
        cl_row.addWidget(self.set_ass_btn)
        cl_row.addStretch()
        sub_group.layout().addLayout(cl_row)
        cl.addWidget(sub_group)

        # ── 5. 背景音管理 ──
        bgm_group = self._make_group("背景音管理")
        bgm_row = QHBoxLayout()
        bgm_row.setSpacing(6)

        self.is_separate_cb = QCheckBox("人声背景音分离")
        bgm_row.addWidget(self.is_separate_cb)
        self.embed_bgm_cb = QCheckBox("嵌入背景音乐")
        bgm_row.addWidget(self.embed_bgm_cb)
        self.is_loop_bgm = QComboBox()
        self.is_loop_bgm.addItems(["BGM短暂拉长", "循环播放BGM"])
        self.is_loop_bgm.setMaximumWidth(120)
        bgm_row.addWidget(self.is_loop_bgm)
        bgm_row.addWidget(QLabel("音量:"))
        self.bgmvolume = QLineEdit("0.8")
        self.bgmvolume.setFixedHeight(22)
        self.bgmvolume.setMaximumWidth(60)
        bgm_row.addWidget(self.bgmvolume)
        self.add_back_btn = QPushButton("选择背景音")
        self.add_back_btn.setFixedHeight(24)
        bgm_row.addWidget(self.add_back_btn)
        self.back_audio_edit = QLineEdit()
        self.back_audio_edit.setPlaceholderText("背景音频路径...")
        self.back_audio_edit.setFixedHeight(22)
        bgm_row.addWidget(self.back_audio_edit, 1)
        bgm_row.addStretch()
        bgm_group.layout().addLayout(bgm_row)
        cl.addWidget(bgm_group)

        cl.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # ── 按钮行 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setObjectName("accentBtn")
        self.btn_ok.setFixedHeight(30)
        self.btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(self.btn_ok)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedHeight(30)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        # ── 连接信号 ──
        self.set_ass_btn.clicked.connect(self._on_set_ass)
        self.add_back_btn.clicked.connect(self._on_select_bgm)

    def _make_group(self, title: str):
        """创建带标题的分组容器"""
        from PySide6.QtWidgets import QGroupBox

        g = QGroupBox(title)
        g.setStyleSheet("""
            QGroupBox {
                color: #3a8cff; font-size: 13px; font-weight: bold;
                border: 1px solid #3a3a42; border-radius: 6px;
                margin-top: 12px; padding: 12px 8px 8px 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px; padding: 0 6px;
            }
        """)
        gl = QVBoxLayout(g)
        gl.setContentsMargins(4, 8, 4, 4)
        gl.setSpacing(4)
        return g

    # ── 加载/保存 ──

    @staticmethod
    def _parse_int(v) -> int:
        """兼容旧格式 '+0%' / '+0Hz' 和纯数字"""
        if isinstance(v, int):
            return v
        try:
            return int(str(v).replace("%", "").replace("Hz", "").replace("+", ""))
        except (ValueError, TypeError):
            return 0

    def _load_from_config(self):
        """从全局配置加载当前值"""
        from videotrans.configure import config as cfg

        # VAD
        for key, default in [
            ("threshold", "0.5"),
            ("min_speech_duration_ms", "1000"),
            ("min_silence_duration_ms", "250"),
            ("max_speech_duration_s", "8"),
        ]:
            w = self._vad_widgets.get(key)
            if w:
                w.setText(str(cfg.params.get(key, default)))
        self.fix_punc_cb.setChecked(cfg.params.get("fix_punc", False))
        self.enable_diariz_cb.setChecked(cfg.params.get("enable_diariz", False))
        self.nums_diariz.setCurrentIndex(int(cfg.params.get("nums_diariz", 0)))
        # 翻译
        self.trans_thread.setText(str(cfg.params.get("trans_thread", "5")))
        self.aitrans_thread.setText(str(cfg.params.get("aitrans_thread", "100")))
        self.translation_wait.setText(str(cfg.params.get("translation_wait", "0")))
        # 配音
        self.dubbing_wait.setText(str(cfg.params.get("dubbing_wait", "0")))
        self.voice_rate.setValue(self._parse_int(cfg.params.get("voice_rate", 0)))
        self.volume_rate.setValue(self._parse_int(cfg.params.get("volume", 0)))
        self.pitch_rate.setValue(self._parse_int(cfg.params.get("pitch", 0)))
        # 字幕
        self.cjklinenums.setValue(int(cfg.params.get("cjk_len", 20)))
        self.othlinenums.setValue(int(cfg.params.get("other_len", 60)))
        # BGM
        self.is_separate_cb.setChecked(cfg.params.get("is_separate", False))
        self.embed_bgm_cb.setChecked(cfg.params.get("embed_bgm", False))
        self.is_loop_bgm.setCurrentIndex(int(cfg.params.get("is_loop_bgm", 0)))
        self.bgmvolume.setText(str(cfg.params.get("bgmvolume", "0.8")))
        self.back_audio_edit.setText(cfg.params.get("back_audio", ""))

    def _save_to_config(self):
        """持久化到全局配置"""
        from videotrans.configure import config as cfg

        vr = self.voice_rate.value()
        vl = self.volume_rate.value()
        pt = self.pitch_rate.value()
        params = {
            "threshold": self._vad_widgets["threshold"].text(),
            "min_speech_duration_ms": self._vad_widgets["min_speech_duration_ms"].text(),
            "min_silence_duration_ms": self._vad_widgets["min_silence_duration_ms"].text(),
            "max_speech_duration_s": self._vad_widgets["max_speech_duration_s"].text(),
            "enable_diariz": self.enable_diariz_cb.isChecked(),
            "nums_diariz": self.nums_diariz.currentIndex(),
            "fix_punc": self.fix_punc_cb.isChecked(),
            "trans_thread": self.trans_thread.text(),
            "aitrans_thread": self.aitrans_thread.text(),
            "translation_wait": self.translation_wait.text(),
            "dubbing_wait": self.dubbing_wait.text(),
            "voice_rate": vr,
            "volume": vl,
            "pitch": pt,
            "cjk_len": self.cjklinenums.value(),
            "other_len": self.othlinenums.value(),
            "is_separate": self.is_separate_cb.isChecked(),
            "embed_bgm": self.embed_bgm_cb.isChecked(),
            "is_loop_bgm": self.is_loop_bgm.currentIndex(),
            "bgmvolume": self.bgmvolume.text(),
            "back_audio": self.back_audio_edit.text().strip(),
        }
        cfg.params.getset_params(params)

    def _on_ok(self):
        self._save_to_config()
        self.accept()

    # ── 子对话框 ──

    def _on_set_ass(self):
        """打开 ASS 字幕样式设置"""
        from videotrans.component.set_ass import ASSStyleDialog

        dlg = ASSStyleDialog()
        dlg.setStyleSheet(self.styleSheet())
        dlg.exec()

    def _on_select_bgm(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景音乐", "", "音频文件 (*.mp3 *.wav *.aac *.m4a *.flac);;所有文件 (*.*)"
        )
        if path:
            self.back_audio_edit.setText(path)
