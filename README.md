# pyvideotrans-studio

剪映风格视频翻译 + 轻量剪辑桌面应用。集成 Whisper 语音识别、多引擎翻译、AI 配音、时间线编辑。

## 功能

- **视频翻译**: 自动语音识别 → 翻译 → AI 配音，支持 50+ 语言
- **时间线剪辑**: 单轨时间线，支持裁剪/分割/合并/变速/特效
- **文字生视频**: LLM 分镜脚本 → 素材获取 → TTS 旁白 → 自动合成
- **多引擎支持**: OpenAI / DeepSeek / Gemini / Claude / 本地 LLM
- **GPU 加速**: NVIDIA CUDA / AMD ROCm / Intel QSV 自动检测

## 平台支持

- Linux (主要开发平台)
- Windows
- macOS (实验性)

## 快速开始

### 1. 安装

```bash
git clone https://github.com/jianchang512/pyvideotrans.git
cd pyvideotrans-studio
python main.py
```

首次运行自动检测环境、创建虚拟环境、生成专属安装脚本。

### 2. 日常使用

```bash
python sv.py
```

### 3. 遇到问题

```bash
python main.py   # 重新检测环境和依赖
```

## 依赖

- Python 3.10+
- ffmpeg / ffprobe / ffplay
- PyTorch (CPU 或 GPU 版)
- PySide6

详细依赖见 `pyproject.toml`。

## 许可证

MIT License
