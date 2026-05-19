# -*- coding: utf-8 -*-
"""
剪映风格设置对话框 — pyvideotrans Studio
替代原 Ui_setini 的纯文本滚动列表，改为左侧导航 + 右侧内容区布局
"""

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QLabel,
    QScrollArea,
    QComboBox,
    QCheckBox,
    QLineEdit,
    QPlainTextEdit,
    QFileDialog,
    QSizePolicy,
    QFrame,
    QStackedWidget,
)

from videotrans.configure.config import ROOT_DIR, tr, settings, app_cfg

# ── 分类定义 ──────────────────────────────────────────────
# 每个分类：key → (显示名称, 设置项列表)
# 每项：(key, widget_type_hint)
# widget_type 由值类型自动推断，特殊项特殊处理

CATEGORIES = [
    (
        "common",
        "通用设置",
        [
            "lang",
            "homedir",
            "countdown_sec",
            "dont_notify",
            "batch_single",
            "show_more_settings",
            "process_max",
            "process_max_gpu",
            "multi_gpus",
            "llm_chunk_size",
            "llm_ai_type",
            "gemini_recogn_chunk",
        ],
    ),
    (
        "whisper",
        "语音识别",
        [
            "model_list",
            "Whisper_cpp_models",
            "threshold",
            "vad_type",
            "max_speech_duration_s",
            "min_speech_duration_ms",
            "min_silence_duration_ms",
            "merge_short_sub",
            "speaker_type",
            "hf_token",
            "cuda_com_type",
            "beam_size",
            "best_of",
            "condition_on_previous_text",
            "zh_hant_s",
            "noise_separate_nums",
            "uvr_models",
            "whisper_prepare",
            "no_speech_threshold",
            "temperature",
            "repetition_penalty",
            "compression_ratio_threshold",
            "hotwords",
        ],
    ),
    (
        "trans",
        "翻译设置",
        [
            "trans_thread",
            "aitrans_thread",
            "translation_wait",
            "aisendsrt",
            "aitrans_temperature",
            "aitrans_context",
        ],
    ),
    (
        "dubbing",
        "配音设置",
        [
            "dubbing_thread",
            "dubbing_wait",
            "remove_dubb_silence",
            "save_segment_audio",
            "normal_text",
            "azure_lines",
            "chattts_voice",
            "edgetts_max_concurrent_tasks",
            "edgetts_retry_nums",
        ],
    ),
    (
        "justify",
        "字幕对齐",
        [
            "max_audio_speed_rate",
            "max_video_pts_rate",
            "cjk_len",
            "other_len",
        ],
    ),
    (
        "video",
        "视频输出",
        [
            "crf",
            "preset",
            "video_codec",
            "force_lib",
            "hw_decode",
            "ffmpeg_cmd",
        ],
    ),
    (
        "prompt_init",
        "Whisper提示词",
        [
            "initial_prompt_zh-cn",
            "initial_prompt_zh-tw",
            "initial_prompt_en",
            "initial_prompt_fr",
            "initial_prompt_de",
            "initial_prompt_ja",
            "initial_prompt_ko",
            "initial_prompt_ru",
            "initial_prompt_es",
            "initial_prompt_th",
            "initial_prompt_it",
            "initial_prompt_el",
            "initial_prompt_nb",
            "initial_prompt_pt",
            "initial_prompt_vi",
            "initial_prompt_ar",
            "initial_prompt_tr",
            "initial_prompt_hi",
            "initial_prompt_hu",
            "initial_prompt_uk",
            "initial_prompt_id",
            "initial_prompt_ms",
            "initial_prompt_kk",
            "initial_prompt_cs",
            "initial_prompt_pl",
            "initial_prompt_nl",
            "initial_prompt_sv",
            "initial_prompt_he",
            "initial_prompt_bn",
            "initial_prompt_fa",
            "initial_prompt_ur",
            "initial_prompt_yue",
            "initial_prompt_fil",
        ],
    ),
]

# 标题映射（中文）
TITLES = {
    "process_max": "最大进程数[重启生效]",
    "cjk_len": "中日韩字幕单行字符数",
    "other_len": "其他语言字幕单行字符数",
    "process_max_gpu": "GPU同时任务数[重启生效]",
    "multi_gpus": "多显卡模式[重启生效]",
    "max_audio_speed_rate": "音频加速最大倍数",
    "max_video_pts_rate": "视频慢放最大倍数",
    "batch_single": "批量翻译时强制串行",
    "dont_notify": "禁用桌面通知",
    "llm_ai_type": "LLM重新断句所用AI渠道",
    "gemini_recogn_chunk": "Gemini语音识别每批切片数",
    "llm_chunk_size": "LLM重新断句每批字幕行数",
    "aitrans_temperature": "AI翻译模型温度值",
    "aitrans_context": "AI翻译附带完整原字幕",
    "remove_dubb_silence": "移除配音前后静音缓冲",
    "hw_decode": "视频合成GPU硬解码",
    "normal_text": "文本规范化",
    "uvr_models": "分离背景声模型",
    "whisper_prepare": "Whisper预分割音频?",
    "temperature": "采样温度",
    "repetition_penalty": "重复惩罚",
    "compression_ratio_threshold": "文本压缩率",
    "no_speech_threshold": "no speech threshold",
    "speaker_type": "说话人分离模型",
    "hf_token": "Huggingface的token",
    "show_more_settings": "主界面显示所有参数?",
    "edgetts_max_concurrent_tasks": "EdgeTTS配音并发数",
    "edgetts_retry_nums": "EdgeTTS失败重试次数",
    "noise_separate_nums": "人声背景分离线程数",
    "model_list": "faster-whisper模型",
    "Whisper_cpp_models": "whisper.cpp模型",
    "homedir": "设置输出目录",
    "lang": "软件界面语言",
    "save_segment_audio": "保留每条字幕的配音文件",
    "crf": "视频输出质量控制",
    "force_lib": "强制软编码视频?",
    "preset": "输出视频压缩率",
    "ffmpeg_cmd": "自定义ffmpeg命令参数",
    "video_codec": "264/265编码",
    "threshold": "语音阈值",
    "max_speech_duration_s": "最长语音持续秒数",
    "min_speech_duration_ms": "最短语音持续毫秒",
    "min_silence_duration_ms": "静音分割持续毫秒",
    "merge_short_sub": "合并过短字幕到邻近",
    "vad_type": "选择VAD",
    "trans_thread": "传统翻译渠道每批字幕行数",
    "aitrans_thread": "AI翻译渠道每批字幕行数",
    "aisendsrt": "发送完整字幕",
    "translation_wait": "翻译后暂停秒",
    "dubbing_wait": "配音后暂停秒",
    "dubbing_thread": "并发配音线程数",
    "countdown_sec": "单视频交互翻译暂停倒计时",
    "cuda_com_type": "GPU数据类型",
    "beam_size": "识别准确度beam_size",
    "best_of": "识别准确度best_of",
    "condition_on_previous_text": "启用上下文感知",
    "hotwords": "热词",
    "zh_hant_s": "字幕繁体转简体",
    "azure_lines": "AzureTTS批量行数",
    "chattts_voice": "ChatTTS音色值",
    "initial_prompt_zh-cn": "whisper模型简体中文提示词",
    "initial_prompt_zh-tw": "whisper模型繁体中文提示词",
    "initial_prompt_en": "whisper模型英语提示词",
    "initial_prompt_fr": "whisper模型法语提示词",
    "initial_prompt_de": "whisper模型德语提示词",
    "initial_prompt_ja": "whisper模型日语提示词",
    "initial_prompt_ko": "whisper模型韩语提示词",
    "initial_prompt_ru": "whisper模型俄语提示词",
    "initial_prompt_es": "whisper模型西班牙语提示词",
    "initial_prompt_th": "whisper模型泰国语提示词",
    "initial_prompt_it": "whisper模型意大利语提示词",
    "initial_prompt_pt": "whisper模型葡萄牙语提示词",
    "initial_prompt_vi": "whisper模型越南语提示词",
    "initial_prompt_ar": "whisper模型阿拉伯语提示词",
    "initial_prompt_tr": "whisper模型土耳其语提示词",
    "initial_prompt_hi": "whisper模型印度语提示词",
    "initial_prompt_hu": "whisper模型匈牙利语提示词",
    "initial_prompt_uk": "whisper模型乌克兰语提示词",
    "initial_prompt_id": "whisper模型印尼语提示词",
    "initial_prompt_ms": "whisper模型马来语提示词",
    "initial_prompt_kk": "whisper模型哈萨克语提示词",
    "initial_prompt_cs": "whisper模型捷克语提示词",
    "initial_prompt_pl": "whisper模型波兰语提示词",
    "initial_prompt_nl": "whisper模型荷兰语提示词",
    "initial_prompt_bn": "whisper模型孟加拉语提示词",
    "initial_prompt_he": "whisper模型希伯来语提示词",
    "initial_prompt_sv": "whisper模型瑞典语提示词",
    "initial_prompt_fa": "whisper模型波斯语提示词",
    "initial_prompt_ur": "whisper模型乌尔都语提示词",
    "initial_prompt_yue": "whisper模型粤语提示词",
    "initial_prompt_fil": "whisper模型菲律宾语提示词",
    "initial_prompt_nb": "whisper模型挪威语提示词",
    "initial_prompt_el": "whisper模型希腊语提示词",
}

# 组合框选项
COMBO_OPTIONS = {
    "cuda_com_type": [
        "default",
        "auto",
        "int8",
        "int16",
        "float16",
        "float32",
        "bfloat16",
        "int8_float16",
        "int8_float32",
        "int8_bfloat16",
    ],
    "llm_ai_type": ["openai", "deepseek"],
    "vad_type": ["tenvad", "silero"],
    "speaker_type": ["built", "ali_CAM", "pyannote", "reverb"],
    "video_codec": ["264", "265"],
    "preset": ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"],
    "uvr_models": [
        "UVR-MDX-NET-Inst_HQ_4",
        "UVR-MDX-NET-Inst_HQ_1",
        "UVR-MDX-NET-Inst_HQ_2",
        "UVR-MDX-NET-Inst_HQ_3",
        "UVR-MDX-NET-Inst_HQ_5",
        "UVR-MDX-NET-Inst_Main",
        "UVR-MDX-NET-Inst_1",
        "UVR-MDX-NET-Inst_2",
        "UVR-MDX-NET-Inst_3",
    ],
}

# 提示文本
TIPS = {
    "lang": "设置软件界面语言，修改后需要重启软件",
    "countdown_sec": "当单视频交互翻译时，暂停倒计时秒数(设为0将跳过编辑窗口)",
    "homedir": "用于保存视频分离、字幕配音、字幕翻译等结果的位置",
    "llm_chunk_size": "LLM重新断句时每批发送的字幕行数，默认20",
    "llm_ai_type": "LLM重新断句时使用的AI渠道",
    "gemini_recogn_chunk": "Gemini语音识别每次发送的音频切片数",
    "dont_notify": "任务完成或失败后不显示桌面通知",
    "batch_single": "批量翻译时按顺序一个个翻译",
    "show_more_settings": "主界面默认隐藏大部分参数，选中则显示所有参数",
    "process_max": "最大进程数，越大越快但可能爆内存(重启生效)",
    "process_max_gpu": "GPU同时执行任务数，除非显存>20G请设为1(重启生效)",
    "multi_gpus": "多张显存一致的显卡时可启用(重启生效)",
    "crf": "视频转码损失控制，0=无损但视频巨大，51=质量差文件小",
    "preset": "编码速度和质量平衡",
    "video_codec": "libx264(兼容好)或libx265(压缩高)",
    "force_lib": "强制ffmpeg使用软编解码",
    "hw_decode": "最后一步合成时GPU硬解码(更快但易出错)",
    "ffmpeg_cmd": "自定义ffmpeg命令参数",
    "threshold": "音频片段被认为是语音的最低概率",
    "max_speech_duration_s": "单个语音片段的最大长度(秒)",
    "min_speech_duration_ms": "最短语音持续毫秒，小于此值合并到相邻",
    "merge_short_sub": "选中才会合并短字幕",
    "min_silence_duration_ms": "静音分割等待时长(ms)",
    "vad_type": "选择要使用的VAD",
    "no_speech_threshold": "减小可降低幻觉但可能遗漏文字",
    "temperature": "采样温度",
    "hotwords": "告诉模型哪些词可能出现，英文逗号分隔",
    "repetition_penalty": "增大有利于减少重复",
    "compression_ratio_threshold": "减小有利于减少重复",
    "whisper_prepare": "提前将音频切割为句子片段后再发给whisper",
    "speaker_type": "用于说话人分离的模型",
    "hf_token": "huggingface.co的token",
    "model_list": "faster-whisper模型列表，英文逗号分隔",
    "Whisper_cpp_models": "whisper.cpp模型名称列表，英文逗号分隔",
    "cuda_com_type": "GPU数据类型，int8=快但精度低，float32=慢但精度高",
    "beam_size": "字幕识别精度1-5，越大越耗显存",
    "best_of": "字幕识别精度1-5，越大越耗显存",
    "condition_on_previous_text": "启用上下文感知，效果更好但可能重复",
    "zh_hant_s": "强制将识别出的繁体字幕转为简体",
    "noise_separate_nums": "人声背景声分离线程数",
    "uvr_models": "选择分离背景声时所用模型",
    "trans_thread": "传统翻译渠道每次发送字幕行数",
    "aitrans_thread": "AI翻译渠道每次发送字幕行数",
    "translation_wait": "每次翻译后暂停秒数",
    "aisendsrt": "是否在使用AI翻译时发送完整字幕格式内容",
    "aitrans_temperature": "AI翻译模型温度值，默认0.2",
    "aitrans_context": "附带完整原字幕作为AI上下文(需超长上下文模型)",
    "dubbing_thread": "同时配音的线程数",
    "dubbing_wait": "每次配音后暂停秒数",
    "remove_dubb_silence": "移除每条字幕配音前后静音缓冲",
    "save_segment_audio": "保留每行字幕的配音结果",
    "normal_text": "配音前对文本规范化处理",
    "azure_lines": "Azure TTS批量配音行数",
    "chattts_voice": "ChatTTS音色值",
    "edgetts_max_concurrent_tasks": "EdgeTTS并发数，越大越快但可能限流",
    "edgetts_retry_nums": "EdgeTTS失败后重试次数",
    "max_audio_speed_rate": "最大音频加速倍数，默认100",
    "max_video_pts_rate": "视频慢放最大倍数，默认10",
    "cjk_len": "中日韩字幕单行字符数，多于将换行",
    "other_len": "其他语言字幕单行字符数，多于将换行",
    "initial_prompt_zh-cn": "简体中文语音提示词",
    "initial_prompt_zh-tw": "繁体中文语音提示词",
    "initial_prompt_en": "英语语音提示词",
    "initial_prompt_fr": "法语语音提示词",
    "initial_prompt_de": "德语语音提示词",
    "initial_prompt_ja": "日语语音提示词",
    "initial_prompt_ko": "韩语语音提示词",
    "initial_prompt_ru": "俄语语音提示词",
    "initial_prompt_es": "西班牙语语音提示词",
    "initial_prompt_th": "泰国语语音提示词",
    "initial_prompt_it": "意大利语语音提示词",
    "initial_prompt_pt": "葡萄牙语语音提示词",
    "initial_prompt_vi": "越南语语音提示词",
    "initial_prompt_ar": "阿拉伯语语音提示词",
    "initial_prompt_tr": "土耳其语语音提示词",
    "initial_prompt_hi": "印度语语音提示词",
    "initial_prompt_hu": "匈牙利语语音提示词",
    "initial_prompt_uk": "乌克兰语语音提示词",
    "initial_prompt_id": "印尼语语音提示词",
    "initial_prompt_ms": "马来西亚语语音提示词",
    "initial_prompt_kk": "哈萨克语语音提示词",
    "initial_prompt_cs": "捷克语语音提示词",
    "initial_prompt_pl": "波兰语语音提示词",
    "initial_prompt_nl": "荷兰语语音提示词",
    "initial_prompt_bn": "孟加拉语语音提示词",
    "initial_prompt_he": "希伯来语语音提示词",
    "initial_prompt_sv": "瑞典语语音提示词",
    "initial_prompt_fa": "波斯语语音提示词",
    "initial_prompt_ur": "乌尔都语语音提示词",
    "initial_prompt_yue": "粤语语音提示词",
    "initial_prompt_fil": "菲律宾语语音提示词",
    "initial_prompt_nb": "挪威语语音提示词",
    "initial_prompt_el": "希腊语语音提示词",
}


# ── 样式 ──────────────────────────────────────────────────

DIALOG_STYLE = """
QDialog {
    background-color: #1a1a1e;
    color: #e0e0e0;
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
    font-size: 13px;
}
QScrollArea {
    background-color: #1a1a1e;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background-color: #1a1a1e;
}
QLabel {
    color: #cccccc;
    background-color: transparent;
}
QLabel#catTitle {
    font-size: 15px;
    font-weight: bold;
    color: #3a8cff;
    padding: 8px 0px;
}
QLabel#fieldLabel {
    font-size: 12px;
    color: #aaaaaa;
    min-width: 120px;
}
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
QPushButton#navBtn {
    text-align: left;
    padding: 12px 20px;
    border: none;
    border-radius: 0px;
    font-size: 13px;
    background-color: transparent;
    color: #aaaaaa;
    margin: 0px;
}
QPushButton#navBtn:hover {
    background-color: #2a2a32;
    color: #ffffff;
}
QPushButton#navBtn:checked {
    background-color: #3a8cff22;
    color: #3a8cff;
    border-left: 3px solid #3a8cff;
}
QPushButton#saveBtn {
    background-color: #3a8cff;
    color: #ffffff;
    border: none;
    font-weight: bold;
    padding: 8px 32px;
    border-radius: 6px;
}
QPushButton#saveBtn:hover {
    background-color: #4a9cff;
}
QComboBox {
    background-color: #2a2a32;
    color: #d0d0d0;
    border: 1px solid #3a3a42;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 24px;
}
QComboBox:hover {
    border-color: #4a4a54;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox::down-arrow {
    image: none;
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #2a2a32;
    color: #d0d0d0;
    border: 1px solid #3a3a42;
    selection-background-color: #3a8cff;
}
QCheckBox {
    color: #cccccc;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4a4a54;
    border-radius: 3px;
    background-color: #2a2a32;
}
QCheckBox::indicator:checked {
    background-color: #3a8cff;
    border-color: #3a8cff;
}
QLineEdit {
    background-color: #2a2a32;
    color: #e0e0e0;
    border: 1px solid #3a3a42;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 24px;
}
QLineEdit:focus {
    border-color: #3a8cff;
}
QPlainTextEdit {
    background-color: #2a2a32;
    color: #e0e0e0;
    border: 1px solid #3a3a42;
    border-radius: 4px;
    padding: 4px 8px;
}
QPlainTextEdit:focus {
    border-color: #3a8cff;
}
QScrollBar:vertical {
    background-color: #1a1a1e;
    width: 6px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #3a3a44;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #4a4a54;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QFrame#separator {
    background-color: #2a2a30;
    max-height: 1px;
}
"""


class StudioSettingsDialog(QDialog):
    """剪映风格设置对话框 — 左侧导航 + 右侧 QStackedWidget"""

    def __init__(self, parent=None, initial_category="common"):
        super().__init__(parent)
        self._widgets = {}  # key → QWidget（所有分类的控件引用）
        self._initial_category = initial_category
        self._nav_btns = {}
        self._category_index = {}  # key → stacked index
        self._content_stack = None

        self.setWindowTitle("设置")
        self.setMinimumSize(820, 560)
        self.resize(820, 620)
        self.setStyleSheet(DIALOG_STYLE)

        self._build_ui()
        self._switch_category(initial_category)

    # ── 构建 UI ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        title_bar = QWidget()
        title_bar.setStyleSheet("background-color: #1e1e22; border-bottom: 1px solid #2a2a30;")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(16, 12, 16, 12)

        title = QLabel("设置")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #e0e0e0; background: transparent;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        layout.addWidget(title_bar)

        # 主体
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ── 左侧导航 ──
        nav_panel = QWidget()
        nav_panel.setFixedWidth(160)
        nav_panel.setStyleSheet("background-color: #1e1e22; border-right: 1px solid #2a2a30;")

        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(0, 8, 0, 8)
        nav_layout.setSpacing(0)

        for key, label, _ in CATEGORIES:
            btn = QPushButton(label)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, k=key: self._switch_category(k))
            nav_layout.addWidget(btn)
            self._nav_btns[key] = btn

        nav_layout.addStretch()
        body.addWidget(nav_panel)

        # ── 右侧内容（QStackedWidget，每页一个分类）──
        self._content_stack = QStackedWidget()
        for idx, (cat_key, cat_label, fields) in enumerate(CATEGORIES):
            page = self._build_category_page(cat_label, fields)
            self._content_stack.addWidget(page)
            self._category_index[cat_key] = idx

        body.addWidget(self._content_stack, 1)
        layout.addLayout(body, 1)

        # ── 底部按钮 ──
        bottom = QWidget()
        bottom.setStyleSheet("background-color: #1e1e22; border-top: 1px solid #2a2a30;")
        btn_layout = QHBoxLayout(bottom)
        btn_layout.setContentsMargins(16, 10, 16, 10)

        help_btn = QPushButton("查看教程")
        help_btn.clicked.connect(lambda: self._open_help())
        btn_layout.addWidget(help_btn)
        btn_layout.addStretch()

        save_btn = QPushButton("保存并关闭")
        save_btn.setObjectName("saveBtn")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        layout.addWidget(bottom)

    def _build_category_page(self, cat_label: str, fields: list) -> QScrollArea:
        """为一个分类创建整页内容（ScrollArea → Widget → VBoxLayout）"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(14)

        # 分类标题
        title = QLabel(cat_label)
        title.setObjectName("catTitle")
        layout.addWidget(title)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # 逐项创建控件
        for field_key in fields:
            row = self._create_field_row(field_key)
            if row:
                layout.addLayout(row)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    # ── 切换分类 ──

    def _switch_category(self, key):
        for k, btn in self._nav_btns.items():
            btn.setChecked(k == key)
        idx = self._category_index.get(key, 0)
        self._content_stack.setCurrentIndex(idx)

    # ── 创建单行控件 ──

    def _create_field_row(self, key):
        val = str(settings.get(key, ""))
        title_text = TITLES.get(key, key)
        tip_text = TIPS.get(key, "")

        row = QHBoxLayout()
        row.setSpacing(20)

        label = QLabel(title_text)
        label.setObjectName("fieldLabel")
        label.setToolTip(tip_text)
        label.setFixedWidth(180)
        row.addWidget(label)

        # 组合框
        if key in COMBO_OPTIONS:
            cb = QComboBox()
            cb.addItems(COMBO_OPTIONS[key])
            if val in COMBO_OPTIONS[key]:
                cb.setCurrentText(val)
            cb.setToolTip(tip_text)
            cb.setMinimumHeight(30)
            row.addWidget(cb, 1)
            self._widgets[key] = cb
            return row

        # 界面语言（动态列表）
        if key == "lang":
            cb = QComboBox()
            support = list(app_cfg.SUPPORT_LANG.keys()) if hasattr(app_cfg, "SUPPORT_LANG") else []
            if not support:
                from pathlib import Path

                support = [
                    p.stem for p in Path(f"{ROOT_DIR}/videotrans/language").glob("*.json") if p.stat().st_size > 0
                ]
            cb.addItems(support)
            if val in support:
                cb.setCurrentText(val)
            cb.setToolTip(tip_text)
            cb.setMinimumHeight(30)
            row.addWidget(cb, 1)
            self._widgets[key] = cb
            return row

        # homedir（目录选择）
        if key == "homedir":
            btn = QPushButton(val if val else "点击选择目录")
            btn.setToolTip(tip_text)
            btn.setMinimumHeight(30)
            btn.clicked.connect(lambda: self._pick_dir(btn))
            row.addWidget(btn, 1)
            self._widgets[key] = btn
            return row

        # 布尔值 → QCheckBox
        if val.lower() in ["true", "false", ""]:
            cb = QCheckBox()
            cb.setChecked(val.lower() == "true")
            cb.setToolTip(tip_text)
            cb.setMinimumHeight(30)
            row.addWidget(cb, 1)
            self._widgets[key] = cb
            return row

        # 多行文本 → QPlainTextEdit
        if key in ["model_list", "Whisper_cpp_models"]:
            te = QPlainTextEdit()
            te.setPlainText(val)
            te.setToolTip(tip_text)
            te.setFixedHeight(60)
            row.addWidget(te, 1)
            self._widgets[key] = te
            return row

        # 普通文本 → QLineEdit
        le = QLineEdit()
        le.setText(val)
        le.setToolTip(tip_text)
        le.setPlaceholderText(tip_text)
        le.setMinimumHeight(30)
        row.addWidget(le, 1)
        self._widgets[key] = le
        return row

    # ── 目录选择 ──

    def _pick_dir(self, btn):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", str(Path.home()))
        if d:
            btn.setText(d)

    # ── 加载 / 保存 ──

    def _load_values(self):
        """各控件已通过 settings 初始化，无需额外操作"""
        pass

    def _on_save(self):
        for key, widget in self._widgets.items():
            if isinstance(widget, QComboBox):
                settings[key] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                settings[key] = "true" if widget.isChecked() else "false"
            elif isinstance(widget, QPlainTextEdit):
                settings[key] = widget.toPlainText()
            elif isinstance(widget, QPushButton):
                # homedir
                settings[key] = widget.text()
            elif isinstance(widget, QLineEdit):
                settings[key] = widget.text()
        settings.save()
        self.accept()

    def _open_help(self):
        from videotrans.util import tools

        tools.open_url(url="https://pyvideotrans.com/getstart")
