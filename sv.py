#!/usr/bin/env python3
"""pyvideotrans-studio 快速启动（跳过环境检测）"""

import sys
import os
from pathlib import Path

# 确保能找到 studio/ 和 videotrans/ 包
_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── 虚拟环境自举（检测/创建 venv + 安装依赖） ──
from _bootstrap_venv import ensure_venv

ensure_venv()

_SHIM_DIR = _PROJECT_ROOT / "studio"

# ── fcitx5 中文输入：LD_LIBRARY_PATH 优先 PySide6 Qt 6.11，避免系统 Qt 6.8 版本冲突 ──
if sys.platform == "linux" and not os.environ.get("_PV_STUDIO_QT_PATH"):
    try:
        import PySide6

        _qt_lib = Path(PySide6.__file__).resolve().parent / "Qt" / "lib"
        if _qt_lib.is_dir():
            _env = os.environ.copy()
            _env["LD_LIBRARY_PATH"] = f"{_qt_lib}:" + _env.get("LD_LIBRARY_PATH", "")
            _env["_PV_STUDIO_QT_PATH"] = "1"
            os.execve(sys.executable, [sys.executable] + sys.argv, _env)
    except Exception:
        pass

os.environ["DESKTOP_APP_ID"] = "pyvideotrans-studio"

# ── 导入 Qt ──
try:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("\n❌ PySide6 未安装或加载失败。")
    print("请先运行 python main.py 完成环境检测与依赖安装。")
    sys.exit(1)

# 抑制以下无害 Qt 警告（dxcb 插件缺失、D-Bus 门户注册）：
#   "Could not find the Qt platform plugin 'dxcb'"
#   "Failed to register with host portal"
os.environ["QT_LOGGING_RULES"] = "qt.qpa.plugin=false;qt.qpa.services=false"

# ── fcitx5 中文输入 ──
os.environ["QT_IM_MODULE"] = "fcitx"
os.environ["QT_API"] = "pyside6"

from videotrans.configure import config

config.init_run()
config.app_cfg.current_status = "stop"

from studio.main_window import StudioMainWindow


def main():
    print("=" * 58)
    print("   pyvideotrans-studio  快速启动")
    print("=" * 58)
    print("   提示：如果启动失败或依赖报错，请运行以下命令重新检测环境：")
    print("   python main.py")
    print("=" * 58)
    print()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    icon_path = str(_SHIM_DIR / "logo_icon_64.png")
    app.setWindowIcon(QIcon(icon_path))

    win = StudioMainWindow()
    win.setWindowIcon(QIcon(icon_path))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
