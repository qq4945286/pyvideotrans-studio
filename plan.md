# pyvideotrans-studio 项目方案

## 目标

将 pyvideotrans 改造为剪映风格的独立视频翻译+轻量剪辑工具，告别原版复杂界面。

## 项目结构

```
pyvideotrans-studio/
├── main.py                        # 唯一入口
├── pyproject.toml                 # 项目配置与依赖
├── studio.sh                      # 启动脚本
├── CLAUDE.md                      # AI 辅助开发规范
├── plan.md                        # 本方案说明
│
├── studio/                        # ★ 应用层（剪映风格界面）
│   ├── main_window.py             #   主窗口
│   ├── preview.py                 #   视频预览播放器
│   ├── timeline.py                #   底部时间线
│   ├── editor.py                  #   剪辑引擎 (ffmpeg)
│   ├── export_dialog.py           #   导出选项对话框
│   ├── gpu_accel.py               #   GPU 加速检测
│   ├── settings_dialog.py         #   设置对话框
│   ├── translate_panel.py         #   翻译配音参数面板
│   └── pvt_bridge.py              #   Rust CLI 桥接
│
├── videotrans/                    # ★ 核心引擎（精简自原项目）
│   ├── configure/                 #   配置管理
│   ├── task/                      #   翻译管线任务
│   ├── util/                      #   工具函数
│   ├── process/                   #   进程管理
│   ├── component/                 #   设置对话框组件
│   ├── recognition/               #   语音识别
│   ├── translator/                #   翻译引擎
│   ├── tts/                       #   配音引擎
│   ├── language/                  #   语言文件 (zh/en)
│   ├── styles/                    #   暗色主题 QSS
│   └── ui/                        #   Qt UI 表单 (各服务配置界面)
│
├── pvt-core/                      # Rust CLI 核心工具
│   └── target/release/pvt-core    #   编译后二进制 (3.8MB)
│
└── tmp/                           # 运行时临时文件
```

## 设计原则

### 1. 分层清晰

- `studio/` — 纯 UI/交互层，只负责界面和用户操作
- `videotrans/` — 纯业务逻辑层，不感知 UI 形态
- 交互层通过 import 调用业务层，不反向依赖

### 2. 不重复造轮子

- 直接复用原 `videotrans/` 核心管线代码（语音识别、翻译、TTS、合成）
- 只改 import 路径，不改内部逻辑

### 3. 体积最小化

- 排除原版 `videotrans/mainwin/`（旧 UI 界面）
- 排除测试文件（`testcli.py`, `testcuda.py`, `test_pipeline.py`）
- 排除原版入口（`cli.py`, `sp.py`, `run_workflow.py`）
- 核心引擎 14MB（纯 Python），主体体积来自 PyTorch 和模型

## 搬移计划

### Step 1: 创建目录结构
- `pyvideotrans-studio/` 根目录
- `studio/` 应用层
- `videotrans/` 核心引擎
- `pvt-core/` Rust 工具

### Step 2: 搬移核心引擎
- 拷贝 `videotrans/` → `pyvideotrans-studio/videotrans/`
- 排除：`__pycache__/`, `mainwin/`
- 保留：`ui/`（component 依赖其表单类）

### Step 3: 搬移应用层
- 拷贝 `videotrans/studio/` → `pyvideotrans-studio/studio/`
- 修复所有 `from videotrans.studio.xxx` → `from studio.xxx`
- 修复 `pvt_bridge.py` 路径解析（少一层 parent）

### Step 4: 创建入口
- `main.py` — Qt 应用启动 + sys.path 设置
- `pyproject.toml` — 项目元数据和依赖
- `studio.sh` — 一键启动脚本

### Step 5: 清理根目录
- 删除原 `cli.py`, `sp.py`, 测试文件等
- 原 `videotrans/` 保留不动（备查）

## 未来扩展

以下功能计划在后续版本添加：

- **导入 SRT 字幕文件** — 直接加载外部字幕到时间线
- **字幕编辑** — 在时间线上可视化编辑字幕
- **更多导出预设** — 适配不同平台格式
- **批量处理队列** — 多视频排队处理
- **快捷键自定义** — 用户可配置快捷键

## 关于进口替换

搬移后 import 变化：

| 原代码 | 新代码 |
|--------|--------|
| `from videotrans.studio.preview import PreviewWidget` | `from studio.preview import PreviewWidget` |
| `from videotrans.studio.timeline import ...` | `from studio.timeline import ...` |
| `from videotrans.studio.pvt_bridge import ...` | `from studio.pvt_bridge import ...` |
| `from videotrans.configure.config import ...` | 不变 ✅ |
| `from videotrans.task.trans_create import ...` | 不变 ✅ |
| `from videotrans.util.tools import ...` | 不变 ✅ |
| `from videotrans.component.set_form import ...` | 不变 ✅ |

核心引擎内部 import 全部不变。只改 `studio/` 对 `videotrans.studio` 的自引用。
