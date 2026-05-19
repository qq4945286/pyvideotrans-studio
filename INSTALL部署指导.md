# pyvideotrans-studio 安装指导

## 系统要求

| 平台 | 最低要求 | 推荐配置 |
|------|---------|---------|
| **操作系统** | Linux (Ubuntu 20.04+, Deepin 23+, CentOS 8+), Windows 10+, macOS 12+ | Linux / Windows 11 |
| **Python** | 3.10 - 3.12 | 3.11 |
| **内存** | 8 GB | 16 GB+ |
| **显卡** | 无（CPU 模式可用） | NVIDIA CUDA / AMD ROCm |
| **磁盘空间** | 2 GB | 10 GB+（含模型文件） |

---

## 快速安装（3 步）

### 第 1 步：确保 Python 已安装

```bash
python3 --version
# 输出应 >= 3.10
# 如果没有 Python，请访问 https://python.org 下载
```

### 第 2 步：运行环境检测

```bash
cd pyvideotrans-studio
python main.py
```

首次运行会自动执行环境检测：
- 识别你的操作系统和 Python 版本
- 检测 GPU 类型（NVIDIA / AMD / Intel / 无）
- 检查依赖包安装情况
- 生成专属安装脚本 `install_deps.sh`（Windows 为 `install_deps.bat`）

### 第 3 步：安装依赖

**方式一：使用自动生成的脚本（推荐）**

```bash
# Linux / macOS
bash install_deps.sh

# Windows
双击 install_deps.bat
```

**方式二：手动安装**

```bash
pip install -r requirements.txt
```

**方式三：分步安装**

```bash
# 1. torch + torchaudio（按 GPU 类型选择下方对应命令安装）
# 2. 其余全部依赖
pip install PySide6 pydub tqdm numpy requests beautifulsoup4 transformers sentencepiece librosa soundfile pandas scipy
```

---

## 安装 PyTorch（按 GPU 类型选择）

PyTorch 索引版本需与 GPU 驱动匹配，以下为常见安装方式：

| 环境 | 参考命令 |
|-----|---------|
| **NVIDIA CUDA 12.x** | `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124` |
| **NVIDIA CUDA 11.8** | `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118` |
| **AMD ROCm 6.x** | `pip install torch torchaudio --index-url https://download.pytorch.org/whl/rocm6.2` |
| **AMD ROCm 7.x** | `pip install torch torchaudio --index-url https://download.pytorch.org/whl/rocm6.2`（ROCm 7.2 兼容 rocm6.2 索引） |
| **Intel XPU** | `pip install torch torchaudio --index-url https://download.pytorch.org/whl/xpu` |
| **CPU（无 GPU）** | `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu` |
| **macOS** | `pip install torch torchaudio`（自动选择 MPS 加速） |

> 提示：具体支持哪些索引版本，可参考 [pytorch.org](https://pytorch.org/get-started/locally/) 或运行环境检测向导自动识别。

---

## 启动软件

```bash
cd pyvideotrans-studio
python main.py
```

---

## 常见问题

### Q: 启动后提示 "ModuleNotFoundError: No module named 'PySide6'"

核心依赖未安装，运行：

```bash
pip install PySide6
```

### Q: 运行 main.py 后闪退或没反应

请先运行环境检测查看具体错误：

```bash
python -c "from studio.setup_wizard import run; run(force=True)"
```

### Q: Linux 下无法输入中文

fcitx5 中文输入已在 deepin/Ubuntu 下通过自动补丁支持。如果仍无法输入：

1. 确保已安装 fcitx5：`sudo apt install fcitx5 fcitx5-chinese-addons`
2. 确保环境变量：`export QT_IM_MODULE=fcitx`

### Q: GPU 检测不到

- NVIDIA：运行 `nvidia-smi` 确认驱动已安装
- AMD ROCm：运行 `rocminfo` 确认 ROCm 已安装
- 部分虚拟机或远程桌面无法直通 GPU，属正常现象

### Q: Windows 下 antivirus 报毒

`install_deps.bat` 是纯文本脚本，无任何可执行代码。可忽略安全警告。

### Q: 安装 torch 失败

尝试使用国内镜像源：

```bash
pip install torch torchaudio -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 目录结构说明

```
pyvideotrans-studio/
├── main.py                  # 程序入口
├── INSTALL.md               # 本文件 — 安装指导
├── USAGE.md                 # 使用说明
├── requirements.txt         # 依赖列表
├── install_deps.sh          # 自动生成的 Linux 安装脚本
├── install_deps.bat         # 自动生成的 Windows 安装脚本
├── studio/                  # 界面模块
│   ├── main_window.py       # 主窗口
│   ├── translate_panel.py   # 翻译配音面板
│   ├── timeline.py          # 时间线
│   ├── preview.py           # 视频预览
│   ├── editor.py            # 剪辑引擎
│   ├── export_dialog.py     # 导出对话框
│   ├── dubbing_advanced_dialog.py  # 配音高级设置
│   └── setup_wizard.py      # 环境检测向导
├── videotrans/              # 核心引擎（复用原 pyvideotrans）
└── pvt-core/                # Rust 工具（可选）
```
