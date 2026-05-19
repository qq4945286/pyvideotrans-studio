# OpenWolf 上下文管理（最高优先级）
本项目启用 OpenWolf 做 AI 上下文精简与 Token 优化。
✅ 每次新会话必须优先读取 .wolf/OPENWOLF.md
✅ 编写代码前先查阅 .wolf/cerebrum.md 记录的已知问题与开发偏好
✅ 读取项目文件前先看 .wolf/anatomy.md 文件摘要，能不读就不读，节省开销

# 全局强制规则
- 所有界面弹窗、提示、报错日志**必须使用标准简体中文**
- 发现代码问题直接一次性修复，不反复询问确认
- 遵循：问题监控 → 记录归档 → 批量统一修复 的工作习惯
- 严格遵守本文件所有开发规范，禁止私自简化、遗漏、违背规则


# pyvideotrans-studio 开发规范

## 项目概述

剪映风格视频翻译 + 轻量剪辑桌面应用。基于 PySide6 + ffmpeg，核心管线复用原 pyvideotrans 引擎。

## 交互约定

- 所有提示/确认/错误消息必须使用**简体中文**
- 发现问题直接修复，无需询问确认
- 工作习惯：问题监控 → 记录 → 批量修复

## Python 规范

### 导入顺序
1. 标准库（os, sys, json, pathlib, threading 等）
2. 第三方库（PySide6, numpy, torch 等）
3. 本项目模块（videotrans.xxx, studio.xxx）

### 命名约定
- 类名：PascalCase（`StudioMainWindow`, `TranslatePanel`）
- 函数/方法：snake_case（`_on_export_clip`, `_poll_translate_logs`）
- 变量：snake_case（`app_cfg`, `source_wav`）
- 私有成员：`_` 前缀（`_playing`, `_subtitle_edit_pending`）
- 常量：UPPER_SNAKE_CASE（`DARK_STYLE_QSS`, `TEMP_DIR`）

### 类型注解
函数参数和返回值尽量加类型注解：
```python
def get_video_duration(path: str) -> float: ...
```

## Qt/PySide6 规范

### 线程安全（关键！）
- **QPixmap 只能在主线程创建/使用**，工作线程用 QImage 传递
- **QWidget/QDialog 只能在主线程操作**
- 耗时操作必须放工作线程（QThread / threading.Thread）
- 线程间通信用 Signal / 共享队列 + QTimer 轮询
- 子线程退出：terminate() → stop() → wait(3000) 三步安全退出
- `QThread.destroyed` 崩溃：确保线程函数已退出再析构

### 信号槽
- 跨线程信号必须使用 `QueuedConnection`（默认即可）
- 信号连接前先 `disconnect` 防止重复累积

### UI 模式
- 暗色主题（#1a1a1e 底色, #3a8cff 主题蓝）
- 所有对话框统一加载 `DARK_STYLE_QSS`
- 对话框用 `QDialog`，模态调用

## ffmpeg 规范

### 视频裁剪
- 必须加 `-g 1`（全关键帧），否则拼接时画面不同步
- 编码器映射：
  - VAAPI (AMD): `h264_vaapi` + `-init_hw_device vaapi` + `format=nv12,hwupload`
  - NVENC (NVIDIA): `h264_nvenc` + `-cq`（比 CRF 约高 3 档）
  - AMF (AMD Windows): `h264_amf` + `-qp_p`（比 CRF 高 8 档）
  - QSV (Intel): `h264_qsv` + `-global_quality`
  - 回退: `libx264` + `-crf` + `force_cpu=True`
- 自动多策略回退：HW → libx264 → 无变速兜底
- `-fps_mode vfr` 保证拼接兼容

### 音频处理
- 分离音频用 `-vn -ac 2 -b:a 128k -c:a aac`
- 降噪用 ffmpeg afftdn 滤波器
- 提取音频后立即保存副本到输出目录

## Studio Pipeline 规范

### 状态管理
- `current_status` 必须设为 `'ing'` 否则管线秒跳过（字符串，不是变量！）
- 管线步骤：prepare → recogn → diariz → trans → dubbing → align → recogn2pass → assembling
- 字幕暂停编辑用 `_subtitle_resume` (threading.Event) 同步主线程与工作线程

### 配置
- 全局配置通过 `videotrans.configure.config` 的 `app_cfg` / `settings` 访问
- 暗色样式表 `DARK_STYLE_QSS` 在 `config.py` 中加载

## 文件结构

```
pyvideotrans-studio/
├── main.py            # 入口
├── studio/            # UI 层
│   ├── main_window.py
│   ├── preview.py     # 视频预览（FrameExtractor + 音频播放）
│   ├── timeline.py    # 时间线（缩略图轨道 + 标尺 + 剪辑）
│   ├── editor.py      # 剪辑引擎（QProcess）
│   ├── export_dialog.py
│   ├── gpu_accel.py
│   ├── settings_dialog.py
│   ├── translate_panel.py
│   └── pvt_bridge.py  # Rust CLI 调用
├── videotrans/        # 核心引擎
│   ├── configure/     # config.py, settings
│   ├── task/          # trans_create.py, _rate.py
│   ├── util/          # tools.py, help_ffmpeg.py, gpus.py
│   ├── component/     # 各配置对话框
│   ├── recognition/   # 语音识别
│   ├── translator/    # 翻译引擎
│   ├── tts/           # 配音引擎
│   ├── process/       # 进程管理
│   ├── ui/            # Qt UI 表单
│   └── language/      # zh.json, en.json
└── pvt-core/          # Rust 工具
```

## 记忆管理

- 使用 `/home/deepin/.claude/projects/-home-deepin-pyvideotrans/memory/` 持久化记忆
- 重要 Bug 修复、用户偏好、项目进度必须写入记忆
- 代码实现细节不要写记忆，git log 里有
