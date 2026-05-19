#!/usr/bin/env python3
"""pyvideotrans-studio 部署向导 — 跨平台环境检测与依赖安装"""

import sys, os, subprocess, re, shutil, platform, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# ── 工具函数 ──────────────────────────────────────────────


def _sep(char="="):
    print(char * 58)


def _section(n, title):
    print(f"\n  [{n}/6] {title}")
    _sep("-")


def _ok(msg):
    print(f"    ✅ {msg}")


def _warn(msg):
    print(f"    ⚠️  {msg}")


def _info(msg):
    print(f"    ℹ️  {msg}")


def _fail(msg):
    print(f"    ❌ {msg}")


def _run(cmd, timeout=30, **kw):
    """运行命令，返回 (success, stdout, stderr)"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return r.returncode == 0, r.stdout, r.stderr
    except Exception as e:
        return False, "", str(e)


def _which(name):
    return shutil.which(name)


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


# ── [1/6] 扫描硬件环境 ────────────────────────────────────


def step1_detect_hardware():
    _section(1, "扫描硬件环境")

    info = {
        "os": platform.system(),
        "os_ver": platform.release(),
        "arch": platform.machine(),
        "python": sys.version.split()[0],
        "cpu": None,
        "ram_gb": 0,
        "gpu": {"vendor": "cpu", "name": None, "driver_ok": False},
    }

    _ok(f"操作系统: {info['os']} {info['os_ver']} ({info['arch']})")
    _ok(f"Python:   {info['python']}")

    # CPU
    try:
        if sys.platform == "linux":
            _, out, _ = _run(["lscpu"], timeout=5)
            for line in out.splitlines():
                if "Model name" in line:
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
                if "CPU max MHz" in line or "CPU MHz" in line:
                    pass
        elif sys.platform == "win32":
            _, out, _ = _run(["wmic", "cpu", "get", "name"], timeout=5)
            for line in out.splitlines():
                line = line.strip()
                if line and "Name" not in line:
                    info["cpu"] = line
                    break
        elif sys.platform == "darwin":
            _, out, _ = _run(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=5)
            info["cpu"] = out.strip()
    except Exception:
        pass
    _ok(f"CPU: {info['cpu'] or '未知'}")

    # RAM
    try:
        import psutil

        info["ram_gb"] = round(psutil.virtual_memory().total / (1024**3))
    except Exception:
        pass
    if info["ram_gb"]:
        _ok(f"内存: {info['ram_gb']} GB")

    # GPU
    gpu = _detect_gpu()
    info["gpu"] = gpu
    gpu_name = gpu['name'] or '未检测到独立显卡'
    gpu_vram = f" / {gpu['vram_mb']} MB" if gpu.get('vram_mb') else ""
    _ok(f"显卡: {gpu_name}{gpu_vram}")
    if gpu["vendor"] != "cpu":
        _ok(f"加速模式: {gpu['vendor'].upper()}")
    else:
        _info("将使用 CPU 模式运行")

    return info


def _detect_gpu():
    gpu = {"vendor": "cpu", "name": None, "vram_mb": 0, "driver_ok": False}
    # NVIDIA
    if _which("nvidia-smi"):
        ok, out, _ = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], timeout=10)
        if ok and out.strip():
            parts = out.strip().split("\n")[0].split(",")
            name = parts[0].strip()
            vram = int(parts[1].strip()) if len(parts) > 1 else 0
            gpu = {"vendor": "cuda", "name": name, "vram_mb": vram, "driver_ok": True}
            return gpu
    # AMD ROCm
    if _which("rocminfo"):
        ok, out, _ = _run(["rocminfo"], timeout=10)
        if ok:
            name = None
            lines = out.splitlines()
            # 找到 GPU 段：从 "Name: gfx" 或 "Vendor Name: AMD" 的 GPU 段取 Marketing Name
            for i, line in enumerate(lines):
                if "Name:" in line and "gfx" in line.lower():
                    # 向前查找 Marketing Name
                    for j in range(max(0, i - 10), min(len(lines), i + 5)):
                        if "Marketing Name:" in lines[j]:
                            name = lines[j].split(":", 1)[1].strip()
                            break
                    if not name:
                        name = line.split(":", 1)[1].strip()
                    break
            if name:
                vram = 0
                # 尝试从 /sys/class/drm 获取显存
                try:
                    for card in Path("/sys/class/drm").glob("card*"):
                        vram_file = card / "device" / "mem_info_vram_total"
                        if vram_file.is_file():
                            vram = int(vram_file.read_text().strip()) // (1024 * 1024)
                            break
                except Exception:
                    pass
                # 回退: rocm-smi
                if not vram and _which("rocm-smi"):
                    ok2, out2, _ = _run(["rocm-smi", "--showmeminfo", "vram"], timeout=10)
                    if ok2:
                        for line in out2.splitlines():
                            if "VRAM Total Memory" in line:
                                try:
                                    vram = int(line.split(":")[1].strip().split("(")[0].strip()) // (1024 * 1024)
                                except Exception:
                                    pass
                                break
                gpu = {"vendor": "rocm", "name": name, "vram_mb": vram, "driver_ok": True}
                return gpu
    # lspci fallback
    if _which("lspci"):
        ok, out, _ = _run(["lspci", "-v"], timeout=10)
        if ok:
            for line in out.splitlines():
                if "VGA" in line or "3D" in line:
                    gpu["name"] = line.split(":", 2)[-1].strip()
                    break
    return gpu


# ── [2/6] 虚拟环境 ────────────────────────────────────────


def step2_venv(hw_info):
    _section(2, "设置虚拟环境")

    # 检查是否已在 venv 中
    if hasattr(sys, "base_prefix") and sys.prefix != sys.base_prefix:
        py = _venv_python(Path(sys.prefix))
        if py.is_file():
            _ok(f"已在虚拟环境中: {sys.prefix}")
            _ok("直接共享，无需额外创建。")
            return Path(sys.prefix), True

    # 查找现有 venv
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        val = os.environ.get(var)
        if val:
            ve = Path(val).resolve()
            if _venv_python(ve).is_file():
                _ok(f"发现已有虚拟环境: {ve}")
                _ok("直接共享，无需额外创建。")
                return ve, True

    # 项目本地
    for name in ("venv", ".venv", "env"):
        ve = PROJECT_ROOT / name
        py = _venv_python(ve)
        if py.is_file():
            _ok(f"发现项目虚拟环境: {ve.name}/")
            _ok("直接共享，无需额外创建。")
            return ve, True

    # 用户主目录
    home = Path.home()
    for name in ("venv", ".venv", "env"):
        ve = home / name
        py = _venv_python(ve)
        if py.is_file():
            _ok(f"发现用户虚拟环境: {ve}")
            _ok("直接共享，无需额外创建。")
            return ve, True

    # 没找到 → 创建
    _info("未找到可共享的虚拟环境，正在创建...")
    ve = PROJECT_ROOT / "venv"
    try:
        import venv

        venv.create(str(ve), with_pip=True)
        _ok(f"虚拟环境已创建: venv/")
        return ve, False
    except Exception:
        try:
            venv.create(str(ve), with_pip=False)
            py = _venv_python(ve)
            subprocess.run([str(py), "-m", "ensurepip", "--upgrade"], capture_output=True, timeout=60)
            _ok(f"虚拟环境已创建: venv/")
            return ve, False
        except Exception as e:
            _fail(f"虚拟环境创建失败: {e}")
            _info("请手动创建: python3 -m venv venv")
            sys.exit(1)


# ── [3/6] 显卡驱动 ────────────────────────────────────────


def step3_gpu_driver(hw_info):
    _section(3, "检测显卡驱动")
    gpu = hw_info["gpu"]
    vendor = gpu["vendor"]
    name = gpu["name"] or "未知"

    if vendor == "cuda":
        ok, out, _ = _run(["nvidia-smi"], timeout=10)
        if ok:
            ver = ""
            for line in out.splitlines():
                if "Driver Version" in line:
                    ver = line.split(":", 1)[1].strip()
                    break
            _ok(f"NVIDIA 驱动正常: {ver} — {name}")
        else:
            _warn("NVIDIA 驱动异常，将使用 CPU 模式")
            hw_info["gpu"]["vendor"] = "cpu"
    elif vendor == "rocm":
        ok, out, _ = _run(["rocminfo"], timeout=10)
        if ok:
            _ok(f"ROCm 驱动正常 — {name}")
        else:
            _warn("ROCm 驱动异常，将使用 CPU 模式")
            hw_info["gpu"]["vendor"] = "cpu"
    else:
        _info("未检测到独立显卡驱动，使用 CPU 模式")


# ── [4/6] 依赖检查 ────────────────────────────────────────


def step4_check_deps(venv_dir: Path):
    _section(4, "检查虚拟环境中已安装的依赖")

    py = _venv_python(venv_dir)
    if not py.is_file():
        _fail(f"Python 解释器不存在: {py}")
        return []

    # 基础包检查
    base_pkgs = [
        ("PySide6", "PySide6"),
        ("numpy", "numpy"),
        ("requests", "requests"),
        ("pydub", "pydub"),
        ("tqdm", "tqdm"),
        ("librosa", "librosa"),
        ("soundfile", "soundfile"),
        ("pandas", "pandas"),
        ("scipy", "scipy"),
        ("transformers", "transformers"),
        ("sentencepiece", "sentencepiece"),
        ("httpx", "httpx"),
        ("openai", "openai"),
        ("beautifulsoup4", "bs4"),
        ("edge_tts", "edge_tts"),
        ("gtts", "gtts"),
        ("deepgram-sdk", "deepgram"),
        ("google-genai", "google.genai"),
        ("gradio_client", "gradio_client"),
        ("aiohttp", "aiohttp"),
        ("elevenlabs", "elevenlabs"),
        ("tenacity", "tenacity"),
        ("ten_vad", "ten_vad"),
    ]

    installed = []
    missing = []
    for pkg_name, mod_name in base_pkgs:
        try:
            importlib = __import__("importlib")
            importlib.import_module(mod_name)
            installed.append(pkg_name)
        except ImportError:
            missing.append(pkg_name)

    _ok(f"已安装: {len(installed)} 个")
    for pkg in installed:
        print(f"      ✓ {pkg}")

    if missing:
        _warn(f"缺失: {len(missing)} 个")
        for pkg in missing:
            print(f"      ✗ {pkg}")
    else:
        _ok("全部依赖已安装！")

    return missing


# ── [5/6] 生成安装脚本 ─────────────────────────────────────


def step5_generate_install_script(hw_info, venv_dir, missing):
    _section(5, "制定专属依赖安装脚本")

    gpu = hw_info["gpu"]
    vendor = gpu["vendor"]
    is_win = sys.platform == "win32"
    is_mac = sys.platform == "darwin"

    if is_win:
        script_name = "install_deps.bat"
    else:
        script_name = "install_deps.sh"

    script_path = PROJECT_ROOT / script_name

    # 构建 torch 安装参数
    torch_index = "https://download.pytorch.org/whl/cpu"
    if vendor == "cuda":
        torch_index = "https://download.pytorch.org/whl/cu124"
    elif vendor == "rocm":
        # 检测 ROCm 版本
        rocm_ver = "6.2"
        try:
            ok, out, _ = _run(["hipconfig", "--version"], timeout=10)
            if ok and out.strip():
                parts = out.strip().split(".")
                if len(parts) >= 2:
                    rocm_ver = f"{parts[0]}.{parts[1]}"
        except Exception:
            pass
        torch_index = f"https://download.pytorch.org/whl/rocm{rocm_ver}"

    # 镜像源
    mirror = ""
    mirror_name = "清华源"
    if not is_win:
        mirror = " -i https://pypi.tuna.tsinghua.edu.cn/simple"

    py_bin = str(_venv_python(venv_dir))

    if is_win:
        lines = [
            "@echo off",
            "echo ============================================",
            f"echo   pyvideotrans-studio — {hw_info['os']} {hw_info['os_ver']} / {gpu.get('name', 'CPU')}",
            "echo ============================================",
            "echo.",
            f"echo   [1/3] 安装 PyTorch ({vendor.upper()})",
            f'"{py_bin}" -m pip install torch torchaudio --index-url {torch_index} || (',
            "echo   回退 CPU 版...",
            f'"{py_bin}" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu',
            ")",
            "echo.",
        ]
        for pkg in missing:
            if pkg in ("torch", "torchaudio"):
                continue
            lines.append(f"echo   安装: {pkg}")
            lines.append(f'"{py_bin}" -m pip install {pkg} || echo    安装 {pkg} 失败，跳过...')
        lines += [
            "echo.",
            "echo   ✅ 依赖安装完成！",
            "echo   日常运行: python sv.py",
            "echo   遇到问题: python main.py",
            "pause",
        ]
    else:
        lines = [
            "#!/bin/bash",
            "set -e",
            f'echo "============================================"',
            f'echo "  pyvideotrans-studio — {hw_info["os"]} {hw_info["os_ver"]} / {gpu.get("name", "CPU")}"',
            f'echo "============================================"',
            'echo ""',
            f'echo "  [1/3] 安装 PyTorch ({vendor.upper()})"',
            f'"{py_bin}" -m pip install torch torchaudio --index-url {torch_index} || (',
            f'  echo "  回退 CPU 版..."',
            f'  "{py_bin}" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu',
            f")",
            'echo ""',
        ]
        other_pkgs = [p for p in missing if p not in ("torch", "torchaudio")]
        if other_pkgs:
            if is_mac:
                lines.append(f'echo "  [2/3] 安装依赖 ({len(other_pkgs)} 个)"')
                lines.append(f'"{py_bin}" -m pip install {" ".join(other_pkgs)}')
            else:
                lines.append(f'echo "  [2/3] 安装依赖 ({len(other_pkgs)} 个) 镜像: {mirror_name}"')
                lines.append(f'"{py_bin}" -m pip install {" ".join(other_pkgs)}{mirror}')
        lines += [
            'echo ""',
            'echo "  ✅ 依赖安装完成！"',
            'echo "  日常运行: python sv.py"',
            'echo "  遇到问题: python main.py"',
        ]

    with open(script_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    if not is_win:
        os.chmod(script_path, 0o755)

    _ok(f"专属安装脚本已生成: {script_name}")
    _info(f"PyTorch 加速: {vendor.upper()} ({torch_index})")
    _info(f"需安装依赖: {len(missing)} 个")

    return script_name


# ── [6/6] 完成提示 ────────────────────────────────────────


def step6_finish(script_name, is_existing_venv):
    _section(6, "部署完成")

    if is_existing_venv:
        _ok("使用共享虚拟环境，无需重复安装依赖。")
    else:
        _ok("虚拟环境已创建，依赖已就绪。")

    print(f"""
  {'='*58}
  {'🎬 pyvideotrans-studio 环境部署完毕':^46}
  {'='*58}

  日常使用:
      python sv.py

  遇到问题或缺少依赖时:
      python main.py

  如果安装脚本未完成，请执行:
      {'./' if sys.platform != 'win32' else ''}{script_name}

  {'='*58}
""")


# ── 主入口 ────────────────────────────────────────────────


def main():
    """部署向导主流程"""
    os.system("cls" if sys.platform == "win32" else "clear")

    print("=" * 58)
    print("   🎬 pyvideotrans-studio  —  环境部署向导")
    print("=" * 58)
    print("   首次运行将自动检测环境并生成专属安装脚本，")
    print("   请耐心等待每个步骤完成。")
    print("=" * 58)

    hw_info = step1_detect_hardware()
    venv_dir, is_existing = step2_venv(hw_info)
    step3_gpu_driver(hw_info)
    missing = step4_check_deps(venv_dir)
    script_name = step5_generate_install_script(hw_info, venv_dir, missing)
    step6_finish(script_name, is_existing and not missing)


if __name__ == "__main__":
    main()
