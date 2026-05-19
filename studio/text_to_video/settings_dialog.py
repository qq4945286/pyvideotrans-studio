# -*- coding: utf-8 -*-
"""
文字生视频设置对话框 — API Key / ComfyUI / TTS / 输出参数
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QCheckBox,
    QGroupBox,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QFormLayout,
    QDialogButtonBox,
    QFileDialog,
    QTabWidget,
    QWidget,
    QMessageBox,
)

from videotrans.configure import config as cfg


class TextToVideoSettingsDialog(QDialog):
    """文字生视频设置"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("文字生视频设置")
        self.setMinimumSize(500, 450)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a1e; }
            QLabel { color: #ccc; font-size: 13px; }
            QGroupBox {
                color: #aaa; font-size: 12px; font-weight: bold;
                border: 1px solid #2a2a30; border-radius: 6px;
                margin-top: 8px; padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
            }
            QLineEdit {
                background-color: #2a2a30; color: #e0e0e0;
                border: 1px solid #3a3a42; border-radius: 4px; padding: 6px;
            }
            QLineEdit:focus { border-color: #3a8cff; }
            QComboBox {
                background-color: #2a2a30; color: #e0e0e0;
                border: 1px solid #3a3a42; border-radius: 4px; padding: 6px;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #2a2a30; color: #e0e0e0;
                border: 1px solid #3a3a42; border-radius: 4px; padding: 4px;
            }
        """)
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #2a2a30; background-color: #1a1a1e; }
            QTabBar::tab {
                background-color: #222226; color: #888; padding: 8px 16px;
                border: none; border-bottom: 2px solid transparent;
            }
            QTabBar::tab:selected {
                color: #3a8cff; border-bottom: 2px solid #3a8cff;
            }
            QTabBar::tab:hover { color: #ccc; }
        """)

        # ── Tab 1: API 密钥 ──
        api_tab = QWidget()
        api_form = QFormLayout(api_tab)
        api_form.setSpacing(10)

        self._pexels_key = QLineEdit()
        self._pexels_key.setPlaceholderText("在 https://www.pexels.com/api/ 免费注册获取")
        api_form.addRow("Pexels API Key:", self._pexels_key)

        self._pixabay_key = QLineEdit()
        self._pixabay_key.setPlaceholderText("在 https://pixabay.com/api/docs/ 免费注册获取")
        api_form.addRow("Pixabay API Key:", self._pixabay_key)

        tabs.addTab(api_tab, "API 密钥")

        # ── Tab 2: LLM API（分镜分析）──
        llm_tab = QWidget()
        llm_form = QFormLayout(llm_tab)
        llm_form.setSpacing(10)

        llm_hint = QLabel(
            "用于 AI 分镜分析。支持 OpenAI 兼容 API（DeepSeek、通义千问等均可）。\n"
            "留空则使用全局「翻译渠道」中的 ChatGPT 配置。"
        )
        llm_hint.setStyleSheet("color: #888; font-size: 11px; margin-bottom: 8px;")
        llm_hint.setWordWrap(True)
        llm_form.addRow(llm_hint)

        # 服务商快捷选择
        self._llm_provider = QComboBox()
        self._llm_provider.addItems(["自定义", "DeepSeek", "OpenAI", "通义千问 (DashScope)", "SiliconFlow (硅基流动)"])
        self._llm_provider.currentIndexChanged.connect(self._on_llm_provider_changed)
        llm_form.addRow("服务商:", self._llm_provider)

        self._t2v_llm_api = QLineEdit()
        self._t2v_llm_api.setPlaceholderText("https://api.deepseek.com/v1")
        llm_form.addRow("API 地址:", self._t2v_llm_api)

        self._t2v_llm_key = QLineEdit()
        self._t2v_llm_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._t2v_llm_key.setPlaceholderText("sk-...")
        llm_form.addRow("API Key:", self._t2v_llm_key)

        self._t2v_llm_model = QLineEdit()
        self._t2v_llm_model.setPlaceholderText("deepseek-chat")
        llm_form.addRow("模型:", self._t2v_llm_model)

        self._t2v_llm_proxy = QLineEdit()
        self._t2v_llm_proxy.setPlaceholderText("http://127.0.0.1:7890")
        llm_form.addRow("HTTP 代理:", self._t2v_llm_proxy)

        llm_test_row = QHBoxLayout()
        self._llm_status = QLabel("未测试")
        self._llm_status.setStyleSheet("color: #666;")
        llm_test_row.addWidget(self._llm_status)
        llm_test_btn = QPushButton("测试连接")
        llm_test_btn.clicked.connect(self._test_llm)
        llm_test_row.addWidget(llm_test_btn)
        llm_form.addRow("状态:", llm_test_row)

        tabs.addTab(llm_tab, "LLM API")

        # ── Tab 3: ComfyUI ──
        comfy_tab = QWidget()
        comfy_form = QFormLayout(comfy_tab)
        comfy_form.setSpacing(10)

        self._comfyui_url = QLineEdit()
        self._comfyui_url.setPlaceholderText("http://127.0.0.1:8188")
        self._comfyui_url.setText("http://127.0.0.1:8188")
        comfy_form.addRow("服务地址:", self._comfyui_url)

        comfy_status_row = QHBoxLayout()
        self._comfyui_status = QLabel("未检测")
        self._comfyui_status.setStyleSheet("color: #666;")
        comfy_status_row.addWidget(self._comfyui_status)
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self._test_comfyui)
        comfy_status_row.addWidget(test_btn)
        comfy_form.addRow("状态:", comfy_status_row)

        self._comfyui_workflow = QLineEdit()
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_workflow)
        wf_row = QHBoxLayout()
        wf_row.addWidget(self._comfyui_workflow)
        wf_row.addWidget(browse_btn)
        comfy_form.addRow("Workflow:", wf_row)

        tabs.addTab(comfy_tab, "ComfyUI")

        # ── Tab 3: TTS + 输出 ──
        out_tab = QWidget()
        out_form = QFormLayout(out_tab)
        out_form.setSpacing(10)

        # TTS 引擎选择
        self._tts_engine = QComboBox()
        self._tts_engine.addItems(["Edge-TTS (在线)", "CosyVoice (本地)"])
        self._tts_engine.setToolTip("选择配音引擎：Edge-TTS 需联网，CosyVoice 需本地运行服务")
        out_form.addRow("配音引擎:", self._tts_engine)

        # Edge-TTS 语音选择
        self._tts_voice = QComboBox()
        self._tts_voice.addItems(
            [
                "zh-CN-YunjianNeural",
                "zh-CN-XiaoxiaoNeural",
                "zh-CN-YunxiNeural",
                "zh-CN-XiaoyiNeural",
                "zh-CN-YunyangNeural",
                "zh-CN-YunhaoNeural",
            ]
        )
        out_form.addRow("Edge-TTS 语音:", self._tts_voice)

        # CosyVoice 服务地址
        self._cosyvoice_url = QLineEdit()
        self._cosyvoice_url.setPlaceholderText("http://127.0.0.1:7860")
        out_form.addRow("CosyVoice 地址:", self._cosyvoice_url)

        # CosyVoice 音色
        self._cosyvoice_role = QComboBox()
        self._cosyvoice_role.addItem("clone (克隆音色)")
        self._load_cosyvoice_roles()
        out_form.addRow("CosyVoice 音色:", self._cosyvoice_role)

        self._tts_speed = QDoubleSpinBox()
        self._tts_speed.setRange(0.5, 3.0)
        self._tts_speed.setSingleStep(0.1)
        self._tts_speed.setValue(1.2)
        out_form.addRow("语速:", self._tts_speed)

        self._orientation = QComboBox()
        self._orientation.addItems(["横屏", "竖屏"])
        out_form.addRow("视频方向:", self._orientation)

        self._resolution = QComboBox()
        self._resolution.addItems(
            [
                "720p (1280×720)",
                "1080p (1920×1080)",
                "2K (2560×1440)",
                "4K (3840×2160)",
            ]
        )
        self._resolution.setCurrentIndex(1)  # 默认 1080p
        out_form.addRow("分辨率:", self._resolution)

        self._fps = QSpinBox()
        self._fps.setRange(15, 60)
        self._fps.setValue(30)
        out_form.addRow("帧率 (FPS):", self._fps)

        self._subtitle_enabled = QCheckBox("叠加字幕")
        self._subtitle_enabled.setChecked(True)
        out_form.addRow("字幕:", self._subtitle_enabled)

        tabs.addTab(out_tab, "配音与输出")

        layout.addWidget(tabs)

        # 按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _load_cosyvoice_roles(self):
        """加载 CosyVoice 音色列表"""
        from videotrans.util.help_role import get_cosyvoice_role

        rolelist = get_cosyvoice_role()
        self._cosyvoice_role.clear()
        self._cosyvoice_role.addItem("clone (克隆音色)")
        for name in rolelist:
            if name in ("No", "clone"):
                continue
            self._cosyvoice_role.addItem(name)

    def _load_settings(self):
        """从现有配置加载"""
        self._pexels_key.setText(cfg.params.get("pexels_api_key", ""))
        self._pixabay_key.setText(cfg.params.get("pixabay_api_key", ""))
        self._comfyui_url.setText(cfg.params.get("comfyui_url", "http://127.0.0.1:8188"))
        self._comfyui_workflow.setText(cfg.params.get("comfyui_workflow", ""))

        # TTS 引擎
        engine = cfg.params.get("t2v_tts_engine", "edgetts")
        self._tts_engine.setCurrentIndex(0 if engine == "edgetts" else 1)

        self._tts_speed.setValue(float(cfg.params.get("tts_speed", 1.2)))

        voice = cfg.params.get("tts_voice", "zh-CN-YunjianNeural")
        idx = self._tts_voice.findText(voice)
        if idx >= 0:
            self._tts_voice.setCurrentIndex(idx)

        # CosyVoice 配置
        self._cosyvoice_url.setText(cfg.params.get("cosyvoice_url", ""))
        cosy_role = cfg.params.get("t2v_cosyvoice_role", "clone")
        idx = self._cosyvoice_role.findText(cosy_role)
        if idx >= 0:
            self._cosyvoice_role.setCurrentIndex(idx)

        orient = cfg.params.get("orientation", "landscape")
        self._orientation.setCurrentIndex(0 if orient == "landscape" else 1)

        # 分辨率映射
        res_map = {"1280x720": 0, "1920x1080": 1, "2560x1440": 2, "3840x2160": 3}
        res_str = cfg.params.get("t2v_resolution", "1920x1080")
        self._resolution.setCurrentIndex(res_map.get(res_str, 1))

        self._fps.setValue(int(cfg.params.get("fps", 30)))
        self._subtitle_enabled.setChecked(cfg.params.get("subtitle_enabled", True) is True)

        # LLM API 配置（首次默认 DeepSeek）
        saved_api = cfg.params.get("t2v_llm_api", "")
        saved_key = cfg.params.get("t2v_llm_key", "")
        saved_model = cfg.params.get("t2v_llm_model", "")
        if not saved_api and not saved_key:
            # 首次使用：默认选中 DeepSeek
            idx = self._llm_provider.findText("DeepSeek")
            if idx >= 0:
                self._llm_provider.setCurrentIndex(idx)
                self._t2v_llm_api.setText("https://api.deepseek.com/v1")
                self._t2v_llm_model.setText("deepseek-chat")
        else:
            self._t2v_llm_api.setText(saved_api)
            self._t2v_llm_key.setText(saved_key)
            self._t2v_llm_model.setText(saved_model)
        self._t2v_llm_proxy.setText(cfg.params.get("t2v_llm_proxy", ""))

    def _on_save(self):
        """保存设置"""
        cfg.params["pexels_api_key"] = self._pexels_key.text().strip()
        cfg.params["pixabay_api_key"] = self._pixabay_key.text().strip()
        cfg.params["comfyui_url"] = self._comfyui_url.text().strip()
        cfg.params["comfyui_workflow"] = self._comfyui_workflow.text().strip()
        # TTS 引擎
        cfg.params["t2v_tts_engine"] = "edgetts" if self._tts_engine.currentIndex() == 0 else "cosyvoice"
        cfg.params["tts_voice"] = self._tts_voice.currentText()
        cfg.params["tts_speed"] = str(self._tts_speed.value())
        # CosyVoice 配置
        cfg.params["cosyvoice_url"] = self._cosyvoice_url.text().strip()
        cfg.params["t2v_cosyvoice_role"] = self._cosyvoice_role.currentText()
        cfg.params["orientation"] = "landscape" if self._orientation.currentIndex() == 0 else "portrait"
        res_values = ["1280x720", "1920x1080", "2560x1440", "3840x2160"]
        cfg.params["t2v_resolution"] = res_values[self._resolution.currentIndex()]
        cfg.params["fps"] = str(self._fps.value())
        cfg.params["subtitle_enabled"] = self._subtitle_enabled.isChecked()

        # LLM API 配置
        cfg.params["t2v_llm_api"] = self._t2v_llm_api.text().strip()
        cfg.params["t2v_llm_key"] = self._t2v_llm_key.text().strip()
        cfg.params["t2v_llm_model"] = self._t2v_llm_model.text().strip()
        t2v_proxy = self._t2v_llm_proxy.text().strip()
        cfg.params["t2v_llm_proxy"] = t2v_proxy
        if t2v_proxy:
            os.environ["HTTPS_PROXY"] = t2v_proxy
            os.environ["HTTP_PROXY"] = t2v_proxy

        cfg.params.save()
        self.accept()

    def _test_comfyui(self):
        url = self._comfyui_url.text().strip()
        try:
            import urllib.request, json

            req = urllib.request.Request(f"{url}/system_stats", headers={"User-Agent": "pyvideotrans/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    self._comfyui_status.setText("✓ 已连接")
                    self._comfyui_status.setStyleSheet("color: #4caf50;")
                    return
        except Exception:
            pass
        self._comfyui_status.setText("✗ 无法连接")
        self._comfyui_status.setStyleSheet("color: #f44336;")

    def _browse_workflow(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 ComfyUI Workflow", "", "JSON 文件 (*.json);;所有文件 (*)")
        if path:
            self._comfyui_workflow.setText(path)

    # LLM 服务商预设
    _LLM_PROVIDERS = {
        "DeepSeek": ("https://api.deepseek.com/v1", "deepseek-chat"),
        "OpenAI": ("https://api.openai.com/v1", "gpt-4o"),
        "通义千问 (DashScope)": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
        "SiliconFlow (硅基流动)": ("https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V3"),
    }

    def _on_llm_provider_changed(self, idx: int):
        name = self._llm_provider.currentText()
        if name in self._LLM_PROVIDERS:
            api_url, model = self._LLM_PROVIDERS[name]
            self._t2v_llm_api.setText(api_url)
            self._t2v_llm_model.setText(model)

    def _test_llm(self):
        """测试 LLM API 连通性"""
        api_url = self._t2v_llm_api.text().strip() or "https://api.openai.com/v1"
        api_key = self._t2v_llm_key.text().strip()
        proxy = self._t2v_llm_proxy.text().strip()

        if not api_url.startswith("http"):
            api_url = "https://" + api_url

        def _run():
            try:
                import httpx

                kwargs = {"timeout": 10}
                if proxy:
                    kwargs["proxy"] = proxy
                resp = httpx.get(
                    f"{api_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    **kwargs,
                )
                if resp.status_code in (200, 401):
                    return True, "✓ 已连接"
                return False, f"✗ HTTP {resp.status_code}"
            except Exception as e:
                return False, f"✗ {str(e)[:40]}"

        import threading

        def _test():
            ok, msg = _run()
            self._llm_status.setText(msg)
            self._llm_status.setStyleSheet(f"color: {'#4caf50' if ok else '#f44336'};")

        threading.Thread(target=_test, daemon=True).start()
        self._llm_status.setText("检测中...")
        self._llm_status.setStyleSheet("color: #f90;")

    def get_config(self) -> dict:
        """获取设置字典"""
        orient = "landscape" if self._orientation.currentIndex() == 0 else "portrait"
        res_values = [(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)]
        w, h = res_values[self._resolution.currentIndex()]
        if orient == "portrait":
            w, h = h, w
        return {
            "pexels_api_key": self._pexels_key.text().strip(),
            "pixabay_api_key": self._pixabay_key.text().strip(),
            "comfyui_url": self._comfyui_url.text().strip(),
            "comfyui_workflow": self._comfyui_workflow.text().strip(),
            "tts_voice": self._tts_voice.currentText(),
            "tts_speed": self._tts_speed.value(),
            "orientation": orient,
            "resolution": (w, h),
            "fps": self._fps.value(),
            "subtitle_enabled": self._subtitle_enabled.isChecked(),
        }
