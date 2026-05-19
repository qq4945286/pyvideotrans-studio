# -*- coding: utf-8 -*-
"""
操作日志 — 记录每次启动后的所有操作，写入 logs/ 目录
"""

import os
import sys
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_log_path = None
_log_file = None


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:12]


def start():
    global _log_path, _log_file
    now = datetime.now()
    filename = now.strftime("%Y-%m-%d_%H-%M-%S") + ".log"
    _log_path = os.path.join(LOG_DIR, filename)
    _log_file = open(_log_path, "w", encoding="utf-8")
    write("=== pyvideotrans Studio 启动 ===")
    write(f"系统: {sys.platform}")
    write(f"Python: {sys.version.split()[0]}")


def write(msg: str):
    if _log_file and not _log_file.closed:
        _log_file.write(f"[{_timestamp()}] {msg}\n")
        _log_file.flush()


def stop():
    global _log_file
    if _log_file and not _log_file.closed:
        write("=== 程序退出 ===\n")
        _log_file.close()


def operation(action: str, detail: str = ""):
    if detail:
        write(f"操作: {action} — {detail}")
    else:
        write(f"操作: {action}")
