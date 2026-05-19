# -*- coding: utf-8 -*-
"""
首次运行安装向导 — 扫描平台、检测 GPU、检查依赖、生成安装脚本
"""

import sys
import os
import subprocess
import importlib
import shutil
import platform
from pathlib import Path


def _print_banner():
    os.system("cls" if sys.platform == "win32" else "clear")
    print("=" * 58)
    print("   pyvideotrans-studio  —  环境检测与安装向导")
    print("=" * 58)


def _step(n: int, title: str):
    print(f"\n[{n}] {title}")
    print("-" * 58)


def _ok(msg: str):
    print(f"    ✅ {msg}")


def _warn(msg: str):
    print(f"    ⚠️  {msg}")


def _info(msg: str):
    print(f"    ℹ️  {msg}")


def _fail(msg: str):
    print(f"    ❌ {msg}")


def detect_platform() -> dict:
    """Step 1: 操作系统 / Python 版本 / 架构"""
    _step(1, "检测操作系统与 Python 环境")

    info = {
        "system": sys.platform,
        "os_name": platform.system(),
        "os_release": platform.release(),
        "python": sys.version.split()[0],
        "arch": platform.machine(),
        "is_admin": False,
    }
    _ok(f"操作系统：{info['os_name']} {info['os_release']} ({info['arch']})")
    _ok(f"Python 版本：{info['python']} ({sys.executable})")

    # 检测是否为管理员/root
    if sys.platform == "win32":
        try:
            info["is_admin"] = subprocess.run(["net", "session"], capture_output=True, timeout=5).returncode == 0
        except Exception:
            pass
    else:
        info["is_admin"] = os.geteuid() == 0

    if info["is_admin"]:
        _info("以管理员/root 权限运行")
    else:
        _info("以普通用户权限运行（推荐）")

    # pip 版本
    pip_ver = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True, timeout=30)
    if pip_ver.returncode == 0:
        _ok(f"pip：{pip_ver.stdout.split()[1]}")
    else:
        _fail("未检测到 pip，请先安装 pip")

    return info


def detect_gpu() -> dict:
    """Step 2: GPU 检测"""
    _step(2, "检测 GPU 加速硬件")

    gpu = {"type": "cpu", "vendor": None, "name": None, "driver": None}

    def _run_cmd(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess | None:
        """安全执行命令，FileNotFoundError / 超时 / 非零返回 统一返回 None"""
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r if r.returncode == 0 else None
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            return None

    # NVIDIA
    nv = _run_cmd(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"])
    if nv is not None:
        parts = nv.stdout.strip().split(", ")
        gpu["type"] = "cuda"
        gpu["vendor"] = "nvidia"
        gpu["name"] = parts[0] if len(parts) > 0 else "NVIDIA GPU"
        gpu["driver"] = parts[1] if len(parts) > 1 else "unknown"
        _ok(f"NVIDIA GPU：{gpu['name']}")
        _ok(f"驱动版本：{gpu['driver']}")
        _info("可使用 CUDA 加速，推荐安装 torch + torchaudio (CUDA 版)")
        return gpu

    # AMD ROCm
    rocm = _run_cmd(["rocminfo"])
    if rocm is not None:
        gpu["type"] = "rocm"
        gpu["vendor"] = "amd"
        _ok("AMD ROCm 环境可用")
        _info("可使用 ROCm 加速，推荐安装 torch + torchaudio (ROCm 版)")

        lspci = _run_cmd(["lspci"])
        if lspci is not None:
            for line in lspci.stdout.splitlines():
                if "VGA" in line or "3D" in line:
                    gpu["name"] = line.strip()
                    _ok(f"显卡：{line.strip()}")
                    break
        return gpu

    # Intel oneAPI / GPU Top
    if sys.platform == "win32":
        sycl = _run_cmd(["sycl-ls"])
        if sycl is not None:
            gpu["type"] = "xpu"
            gpu["vendor"] = "intel"
            _ok("Intel GPU (oneAPI) 环境可用")
            return gpu
    else:
        igt = _run_cmd(["intel_gpu_top", "-L"], timeout=10)
        if igt is not None:
            gpu["type"] = "xpu"
            gpu["vendor"] = "intel"
            _ok("Intel GPU 环境可用")
            return gpu

    # Apple Metal
    if sys.platform == "darwin":
        gpu["type"] = "mps"
        gpu["vendor"] = "apple"
        _ok("Apple Silicon / Metal 环境")
        _info("可使用 MPS 加速")
        return gpu

    _info("未检测到专用 GPU，将使用 CPU 模式运行")
    _info("CPU 模式下部分功能（如 Whisper 识别）会较慢，但仍可正常使用")
    return gpu


def check_dependencies(requirements_path: Path) -> list:
    """Step 3: 检查依赖安装情况"""
    _step(3, "检查 Python 依赖包安装情况")

    # 读取 requirements
    if not requirements_path.is_file():
        _fail(f"未找到 {requirements_path}，跳过依赖检查")
        return []

    required = []
    with open(requirements_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            pkg = line.split(">=")[0].split("<")[0].split("=")[0].strip()
            required.append(pkg)

    missing = []
    print("    全部依赖：")
    for pkg in required:
        _check_one(pkg, missing)

    return missing


def _check_one(pkg: str, missing: list):
    _pkg_mod_map = {"beautifulsoup4": "bs4", "deepgram-sdk": "deepgram", "google-genai": "google.genai"}
    mod_name = _pkg_mod_map.get(pkg, pkg.replace("-", "_"))
    spec = importlib.util.find_spec(mod_name)
    if spec is not None:
        ver = _get_pkg_version(pkg)
        _ok(f"{pkg} {ver}")
    else:
        _fail(f"{pkg} 未安装")
        missing.append(pkg)


def _get_pkg_version(pkg: str) -> str:
    try:
        _pkg_mod_map = {"beautifulsoup4": "bs4", "deepgram-sdk": "deepgram", "google-genai": "google.genai"}
        mod_name = _pkg_mod_map.get(pkg, pkg.replace("-", "_").replace(".", ""))
        # try importlib.metadata first
        try:
            from importlib.metadata import version

            return version(pkg)
        except Exception:
            pass
        m = __import__(mod_name)
        return getattr(m, "__version__", "") or getattr(m, "VERSION", "") or ""
    except Exception:
        return ""


def generate_install_script(platform_info: dict, gpu_info: dict, missing: list, output_dir: Path):
    """Step 4: 生成平台专用安装脚本"""
    _step(4, "生成平台专用安装脚本")

    is_win = platform_info["system"] == "win32"
    ext = ".bat" if is_win else ".sh"
    script_path = output_dir / f"install_deps{ext}"

    lines = []
    if is_win:
        lines.append("@echo off")
        lines.append("chcp 65001 >nul")
        lines.append("echo ============================================")
        lines.append("echo  pyvideotrans-studio 依赖安装脚本")
        lines.append("echo ============================================")
        lines.append("")

        # Python 检测
        lines.append("where python >nul 2>nul")
        lines.append("if %ERRORLEVEL% neq 0 (")
        lines.append("    echo [错误] 未检测到 Python，请先安装 Python 3.10+")
        lines.append("    pause")
        lines.append("    exit /b 1")
        lines.append(")")
        lines.append("")

        # 镜像速度检测
        lines.append("echo [检测] 测试 PyPI 连接速度...")
        lines.append(
            "python -c \"import time,urllib.request;t0=time.time();urllib.request.urlopen('https://pypi.org/simple/',timeout=10);exit(0 if time.time()-t0<1.5 else 1)\" 2>nul"
        )
        lines.append("if errorlevel 1 (")
        lines.append("    echo   ⏳ 下载速度较慢，自动切换为国内镜像 (mirrors.tuna.tsinghua.edu.cn)")
        lines.append('    set "MIRROR_ARG=-i https://pypi.tuna.tsinghua.edu.cn/simple"')
        lines.append(") else (")
        lines.append("    echo   ✅ 网络连接正常，使用官方源")
        lines.append('    set "MIRROR_ARG="')
        lines.append(")")
        lines.append("echo.")
        lines.append("")

        # GPU 对应 torch（带 CPU 回退）
        _torch_urls = {
            "cuda": "https://download.pytorch.org/whl/cu124",
            "rocm": "https://download.pytorch.org/whl/rocm6.2",
            "xpu": "https://download.pytorch.org/whl/xpu",
        }
        _torch_url = _torch_urls.get(gpu_info["type"], "https://download.pytorch.org/whl/cpu")
        _tag = gpu_info["type"].upper()
        lines.append(f"echo [PyTorch] 安装 {_tag} 版...")
        lines.append(f"pip install torch torchaudio --index-url {_torch_url}")
        lines.append(f"if errorlevel 1 pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu")
        lines.append("")

        # 核心依赖
        lines.append("echo [核心依赖] 安装基础包...")
        lines.append("pip install PySide6 pydub tqdm numpy requests beautifulsoup4 %MIRROR_ARG%")
        lines.append("")

        # 全部依赖（除 torch 外）
        lines.append("echo [依赖] 安装全部 Python 包...")
        lines.append(
            "pip install PySide6 pydub tqdm numpy requests beautifulsoup4 transformers sentencepiece librosa soundfile pandas scipy %MIRROR_ARG%"
        )
        lines.append("")

        lines.append("echo.")
        lines.append("echo ============================================")
        lines.append("echo  安装完成！运行 python main.py 启动程序")
        lines.append("echo ============================================")
        lines.append("pause")
    else:
        lines.append("#!/usr/bin/env bash")
        lines.append("set -e")
        lines.append('echo "============================================"')
        lines.append('echo " pyvideotrans-studio 依赖安装脚本"')
        lines.append('echo "============================================"')
        lines.append("")

        # Python 检测
        lines.append('command -v python3 >/dev/null 2>&1 || { echo "[错误] 未检测到 Python3"; exit 1; }')
        lines.append("")
        lines.append("# ---- 镜像源速度检测 ----")
        lines.append('echo "[检测] 测试 PyPI 连接速度..."')
        lines.append('MIRROR_ARG=""')
        lines.append(
            "if ! python3 -c \"import time,urllib.request;t0=time.time();urllib.request.urlopen('https://pypi.org/simple/',timeout=10);exit(0 if time.time()-t0<1.5 else 1)\" 2>/dev/null; then"
        )
        lines.append('  echo "  ⏳ 下载速度较慢，自动切换为国内镜像 (mirrors.tuna.tsinghua.edu.cn)"')
        lines.append('  MIRROR_ARG="-i https://pypi.tuna.tsinghua.edu.cn/simple"')
        lines.append("else")
        lines.append('  echo "  ✅ 网络连接正常，使用官方源"')
        lines.append("fi")
        lines.append("")
        lines.append("# pip 升级")
        lines.append('echo "[pip] 升级 pip..."')
        lines.append("python3 -m pip install --upgrade pip $MIRROR_ARG")
        lines.append("")

        # GPU 对应 torch（带 CPU 回退）
        _torch_urls = {
            "cuda": "https://download.pytorch.org/whl/cu124",
            "rocm": "https://download.pytorch.org/whl/rocm6.2",
            "xpu": "https://download.pytorch.org/whl/xpu",
        }
        _torch_url = _torch_urls.get(gpu_info["type"], "https://download.pytorch.org/whl/cpu")
        _tag = gpu_info["type"].upper()
        lines.append(f'echo "[PyTorch] 安装 {_tag} 版..."')
        lines.append(f"pip install torch torchaudio --index-url {_torch_url} || \\")
        lines.append(
            f"  (echo '  {_tag} 版失败，回退 CPU 版...' && pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu)"
        )
        lines.append("")

        # 全部依赖（除 torch 外）
        lines.append('echo "[依赖] 安装全部 Python 包..."')
        lines.append(
            "pip install PySide6 pydub tqdm numpy requests beautifulsoup4 transformers sentencepiece librosa soundfile pandas scipy $MIRROR_ARG"
        )
        lines.append("")

        lines.append('echo ""')
        lines.append('echo "============================================"')
        lines.append('echo " 安装完成！运行 python main.py 启动程序"')
        lines.append('echo "============================================"')

    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not is_win:
        script_path.chmod(0o755)

    _ok(f"安装脚本已生成：{script_path}")
    return script_path


def _wait_for_enter():
    try:
        input("\n    按 Enter 键继续启动程序...")
    except (EOFError, KeyboardInterrupt):
        pass


def run(force: bool = False) -> bool:
    """
    执行环境检测与安装向导。

    返回 True 表示可以继续启动 GUI，False 表示应退出。
    """
    # 检测是否已安装所有核心依赖
    requirements_path = Path(__file__).resolve().parent.parent / "requirements.txt"
    all_installed = True
    if requirements_path.is_file():
        with open(requirements_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.split("#")[0].strip()
                if not line or line.startswith("#"):
                    continue
                pkg = line.split(">=")[0].split("<")[0].split("=")[0].strip()
                spec = importlib.util.find_spec(pkg.replace("-", "_"))
                if spec is None:
                    all_installed = False
                    break

    if all_installed and not force:
        return True

    _print_banner()

    try:
        platform_info = detect_platform()
        gpu_info = detect_gpu()
        missing = check_dependencies(requirements_path)

        # 生成安装脚本
        output_dir = Path(__file__).resolve().parent.parent
        generate_install_script(platform_info, gpu_info, missing, output_dir)

        # 汇总
        print("\n" + "=" * 58)
        print("   📋 环境检测汇总")
        print("=" * 58)
        print(f"   操作系统：{platform_info['os_name']} {platform_info['os_release']}")
        print(f"   Python：{platform_info['python']}")
        print(f"   GPU：{gpu_info['name'] or gpu_info['type']}")
        if missing:
            print(f"   缺失依赖：{', '.join(missing)}")
        else:
            print("   核心依赖：全部已安装 ✅")
        print()
        print(f"   安装脚本已生成：install_deps{'.bat' if platform_info['system'] == 'win32' else '.sh'}")
        if missing:
            print("   运行该脚本即可安装缺失的依赖。")
        else:
            print("   如需重新安装全部依赖，可直接运行该脚本。")
        print()
        print("   💡 下次启动请改用 python sv.py，跳过检测直接启动。")
        print("     如遇依赖问题无法启动，再次运行 python main.py 即可。")
        print("=" * 58)

        if missing:
            _wait_for_enter()
        else:
            print("\n    继续启动程序...\n")

    except Exception as e:
        print(f"\n    ⚠️  环境检测异常：{e}")
        print("    将继续启动程序。\n")

    return True
