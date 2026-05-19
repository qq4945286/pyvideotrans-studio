"""虚拟环境自举 — 自动检测/创建 venv，平台自适应安装依赖"""

import sys
import os
import subprocess
import time
import platform
from pathlib import Path

_VENV_FLAG = "_PV_STUDIO_VENV_ACTIVE"


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _venv_has_pip(python_path: Path) -> bool:
    """检查 venv 的 python 是否有 pip 可用"""
    try:
        r = subprocess.run(
            [str(python_path), "-m", "pip", "--version"],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _detect_gpu() -> dict:
    """检测 GPU 类型，返回 torch --index-url 参数"""
    info = {"type": "cpu", "name": None, "torch_index": "https://download.pytorch.org/whl/cpu"}

    # NVIDIA CUDA
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            info["type"] = "cuda"
            info["name"] = r.stdout.strip().split("\n")[0]
            info["torch_index"] = "https://download.pytorch.org/whl/cu124"
            return info
    except Exception:
        pass

    # AMD ROCm
    try:
        r = subprocess.run(["rocminfo"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            info["type"] = "rocm"
            _rocm_ver = "6.2"
            try:
                _v = subprocess.run(["hipconfig", "--version"], capture_output=True, text=True, timeout=10)
                if _v.returncode == 0:
                    _rocm_ver = _v.stdout.strip().split(".")[:2]
                    _rocm_ver = ".".join(_rocm_ver)
            except Exception:
                pass
            info["torch_index"] = f"https://download.pytorch.org/whl/rocm{_rocm_ver}"
            try:
                r2 = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10)
                for line in r2.stdout.splitlines():
                    if "VGA" in line or "3D" in line:
                        info["name"] = line.strip()
                        break
            except Exception:
                pass
            return info
    except Exception:
        pass

    # Apple Metal
    if sys.platform == "darwin":
        info["type"] = "mps"
        info["name"] = "Apple Silicon / Metal"
        info["torch_index"] = None
        return info

    return info


def _pypi_is_slow() -> bool:
    import urllib.request

    try:
        t0 = time.time()
        urllib.request.urlopen("https://pypi.org/simple/", timeout=10)
        return time.time() - t0 >= 1.5
    except Exception:
        return True


def _detect_platform() -> dict:
    """检测操作系统与 Python 环境"""
    info = {
        "system": sys.platform,
        "os_name": platform.system(),
        "os_release": platform.release(),
        "arch": platform.machine(),
        "python": sys.version.split()[0],
        "is_admin": False,
    }
    print(f"  操作系统：{info['os_name']} {info['os_release']} ({info['arch']})")
    print(f"  Python 版本：{info['python']}")
    if sys.platform == "win32":
        try:
            info["is_admin"] = subprocess.run(["net", "session"], capture_output=True, timeout=5).returncode == 0
        except Exception:
            pass
    else:
        info["is_admin"] = os.geteuid() == 0
    print(f"  权限：{'管理员/root' if info['is_admin'] else '普通用户'}")
    return info


# ── 虚拟环境查找与创建 ──


def _find_venv(project_root: Path) -> Path | None:
    """按优先级扫描已有虚拟环境（不检查具体包，有 python+pip 即可）"""
    # 1. 已在虚拟环境中（sys.prefix 检测最可靠）
    if hasattr(sys, "base_prefix") and sys.prefix != sys.base_prefix:
        ve = Path(sys.prefix)
        if _venv_python(ve).is_file():
            return ve
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        val = os.environ.get(var)
        if val:
            ve = Path(val).resolve()
            if _venv_python(ve).is_file():
                return ve

    # 2. 项目本地 venv（需有 pip）
    for name in ("venv", ".venv", "env"):
        p = _venv_python(project_root / name)
        if p.is_file() and _venv_has_pip(p):
            return project_root / name

    # 3. 用户主目录（需有 pip）
    home = Path.home()
    for name in ("venv", ".venv", "env"):
        p = _venv_python(home / name)
        if p.is_file() and _venv_has_pip(p):
            return home / name

    # 4. find 快速扫描（深度 ≤ 3，限时 2 秒）
    try:
        r = subprocess.run(
            [
                "find",
                str(home),
                "-maxdepth",
                "3",
                "-type",
                "d",
                "(",
                "-name",
                "venv",
                "-o",
                "-name",
                ".venv",
                "-o",
                "-name",
                "env",
                ")",
                "-print",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in r.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            p = Path(line)
            if _venv_python(p).is_file():
                return p
    except Exception:
        pass

    return None


def _create_venv(project_root: Path) -> Path | None:
    """在项目目录下创建虚拟环境"""
    import venv as _vm

    venv_dir = project_root / "venv"
    if venv_dir.exists() and _venv_python(venv_dir).is_file():
        return venv_dir

    # 尝试一：with_pip=True
    try:
        _vm.create(str(venv_dir), with_pip=True)
        if _venv_python(venv_dir).is_file():
            return venv_dir
    except Exception:
        pass

    # 尝试二：不带 ensurepip，再手动装 pip
    try:
        _vm.create(str(venv_dir), with_pip=False)
        python_path = _venv_python(venv_dir)
        if python_path.is_file():
            subprocess.run([str(python_path), "-m", "ensurepip", "--upgrade"], capture_output=True, timeout=60)
            r = subprocess.run([str(python_path), "-m", "pip", "--version"], capture_output=True, timeout=30)
            if r.returncode == 0:
                return venv_dir
    except Exception:
        pass

    return None


# ── 依赖检查 ──


def _check_missing_deps(python_path: Path, requirements_path: Path) -> list:
    """逐包检查，返回缺失列表。torch/torchaudio 视为一对，已装 torch 则 torchaudio 不报缺失。"""
    if not requirements_path.is_file():
        return []

    required = []
    with open(requirements_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            pkg = line.split(">=")[0].split("<")[0].split("=")[0].strip()
            required.append(pkg)

    # 包名 → 导入名映射（pip 包名 ≠ import 名的特例）
    _PKG_MOD_MAP = {"beautifulsoup4": "bs4", "deepgram-sdk": "deepgram", "google-genai": "google.genai"}

    # 构造 Python 检测脚本（真导入检测，find_spec 会漏掉半残包）
    lines = ["import sys, importlib"]
    for pkg in required:
        mod = _PKG_MOD_MAP.get(pkg, pkg.replace("-", "_").replace(".", ""))
        lines.append(f"try: importlib.import_module({mod!r})")
        lines.append(f"except Exception: print({pkg!r})")
    code = "\n".join(lines)

    try:
        r = subprocess.run(
            [str(python_path), "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
        missing = [p for p in r.stdout.strip().split("\n") if p]
    except Exception:
        missing = list(required)

    # torch/torchaudio 是一对：torch 已装则 torchaudio 不算缺
    if "torch" in required and "torch" not in missing:
        missing = [p for p in missing if p != "torchaudio"]

    return missing


# ── 依赖安装（逐包、GPU 自适应） ──


def _pip_install_safe(
    python_path: Path,
    args: list[str],
    *,
    timeout: int = 600,
    desc: str = "",
) -> bool:
    """运行 pip install，显示实时进度。检测 PEP 668 自动用 --break-system-packages 重试。"""
    cmd = [str(python_path), "-m", "pip", "install"] + args
    try:
        r = subprocess.run(cmd, timeout=timeout)
        if r.returncode == 0:
            return True
        # 失败 → 检查是否为 PEP 668 限制，尝试绕过
        print(f"    ⚠️  安装失败，尝试绕过系统限制 (--break-system-packages)...")
        r2 = subprocess.run(cmd + ["--break-system-packages"], timeout=timeout)
        if r2.returncode == 0:
            return True
        print(f"    ❌ 重试仍失败，退出码 {r2.returncode}")
        return False
    except subprocess.TimeoutExpired:
        print(f"    ⏱️  安装超时 (>{timeout}s) — {desc}")
        return False
    except Exception as e:
        print(f"    ❌ pip 调用异常 ({desc})：{e}")
        return False


def _install_missing(python_path: Path, requirements_path: Path, gpu_info: dict, missing: list):
    """只安装缺失的依赖（已装的不碰）。PyTorch 按显卡驱动装对应版本。"""
    if not missing:
        return

    # 镜像检测
    mirror = []
    if _pypi_is_slow():
        print("    检测到下载速度较慢，切换为国内镜像源 → pypi.tuna.tsinghua.edu.cn")
        mirror = ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
    else:
        print("    网络连接正常，使用官方源")

    # 升级 pip
    print("  [-] 升级 pip...")
    _pip_install_safe(python_path, ["--upgrade", "pip"] + mirror, timeout=120, desc="pip 升级")

    # ── 安装 PyTorch（如果缺失） ──
    needs_torch = "torch" in missing
    if needs_torch:
        gpu_tag = gpu_info["type"].upper()
        gpu_name = gpu_info["name"] or ""
        torch_url = gpu_info.get("torch_index", "") or "默认源"
        print(f"  [-] 安装 PyTorch（{gpu_tag} 版）")
        print(f"      来源: {torch_url}")
        print(f"      包: torch, torchaudio")
        if gpu_tag in ("ROCM", "CUDA"):
            print(f"      ⚠️  约 2~4 GB，耐心等待...")
        print()
        torch_args = []
        if gpu_info["torch_index"]:
            torch_args += ["--index-url", gpu_info["torch_index"]]
        torch_args += ["torch", "torchaudio"]

        ok = _pip_install_safe(python_path, torch_args, timeout=900, desc=f"PyTorch ({gpu_tag})")
        if not ok:
            print(f"  [-] {gpu_tag} 版安装失败，回退 CPU 版...")
            ok = _pip_install_safe(
                python_path,
                ["--index-url", "https://download.pytorch.org/whl/cpu", "torch", "torchaudio"],
                timeout=600,
                desc="PyTorch (CPU)",
            )
            if not ok:
                print("  ❌ PyTorch 安装失败，请手动安装：pip install torch torchaudio")
                sys.exit(1)

    # ── 安装其余缺失包 ──
    other = [p for p in missing if p not in ("torch", "torchaudio")]
    if other:
        print(f"  [-] 安装以下 {len(other)} 个依赖:")
        print(f"      {'  '.join(other)}")
        print()
        ok = _pip_install_safe(python_path, other + mirror, timeout=600, desc=", ".join(other))
        if not ok:
            print("  ❌ 依赖安装失败，请手动执行：pip install -r requirements.txt")
            sys.exit(1)

    print("  ✅ 所有依赖安装完成")


# ── 生成安装脚本 ──


def _generate_install_script(project_root: Path, gpu_info: dict):
    """根据当前平台生成专属 install_deps.sh / .bat"""
    is_win = sys.platform == "win32"
    ext = ".bat" if is_win else ".sh"
    path = project_root / f"install_deps{ext}"

    torch_url = gpu_info.get("torch_index") or "https://download.pytorch.org/whl/cpu"
    gpu_tag = gpu_info["type"].upper()
    gpu_name = gpu_info["name"] or gpu_tag

    if is_win:
        lines = [
            "@echo off",
            "chcp 65001 >nul",
            "echo ============================================",
            "echo  pyvideotrans-studio 依赖安装脚本",
            f"echo  平台: {platform.system()} {platform.release()} / {gpu_name}",
            "echo ============================================",
            "echo.",
            "",
            "where python >nul 2>nul",
            "if %ERRORLEVEL% neq 0 (",
            "    echo [错误] 未检测到 Python，请安装 Python 3.10+",
            "    pause",
            "    exit /b 1",
            ")",
            "",
            "# ── 虚拟环境自举 ──",
            "if not defined VIRTUAL_ENV if not defined CONDA_PREFIX (",
            '    if not exist "venv\\Scripts\\python.exe" (',
            "        echo [venv] 创建虚拟环境...",
            "        python -m venv venv",
            "    )",
            '    if exist "venv\\Scripts\\pip.exe" (',
            '        set "PIP_CMD=venv\\Scripts\\pip.exe"',
            "        echo [venv] 使用: venv",
            "    ) else (",
            '        set "PIP_CMD=pip"',
            "    )",
            ") else (",
            '    set "PIP_CMD=pip"',
            ")",
            "",
            "echo [检测] 测试 PyPI 下载速度...",
            "python -c \"import time,urllib.request;t0=time.time();urllib.request.urlopen('https://pypi.org/simple/',timeout=10);exit(0 if time.time()-t0<1.5 else 1)\" 2>nul",
            "if errorlevel 1 (",
            '    set "MIRROR_ARG=-i https://pypi.tuna.tsinghua.edu.cn/simple"',
            ") else (",
            '    set "MIRROR_ARG="',
            ")",
            "echo.",
            "",
            "echo [pip] 升级 pip...",
            "%%PIP_CMD%% install --upgrade pip %%MIRROR_ARG%%",
            "echo.",
            "",
            "echo [PyTorch] 安装...",
            f"%%PIP_CMD%% install torch torchaudio --index-url {torch_url}",
            "if errorlevel 1 (",
            f"    echo [PyTorch] {gpu_tag} 版失败，回退 CPU 版...",
            "    %%PIP_CMD%% install torch torchaudio --index-url https://download.pytorch.org/whl/cpu",
            ")",
            "echo.",
            "",
            "echo [依赖] 安装其余包...",
            "%%PIP_CMD%% install -r requirements.txt %%MIRROR_ARG%%",
            "if errorlevel 1 (",
            "    echo [错误] 安装失败，请检查网络后重试",
            "    pause",
            "    exit /b 1",
            ")",
            "echo.",
            "echo ============================================",
            "echo  安装完成！运行 python main.py 启动程序",
            "echo ============================================",
            "pause",
        ]
    else:
        lines = [
            "#!/usr/bin/env bash",
            "set -e",
            'echo "============================================"',
            'echo " pyvideotrans-studio 依赖安装脚本"',
            f'echo " 平台: {platform.system()} {platform.release()} / {gpu_name}"',
            'echo "============================================"',
            'echo ""',
            "",
            'command -v python3 >/dev/null 2>&1 || { echo "[错误] 未检测到 Python3"; exit 1; }',
            "",
            "# ── 虚拟环境自举（如未激活 venv，自动在本目录创建） ──",
            'PIP="pip"',
            'if [ -z "$VIRTUAL_ENV" -a -z "$CONDA_PREFIX" ]; then',
            '  VENV_DIR="$(cd "$(dirname "$0")" && pwd)/venv"',
            '  if [ ! -f "$VENV_DIR/bin/python" ]; then',
            '    echo "[venv] 创建虚拟环境 ..."',
            '    python3 -m venv "$VENV_DIR" 2>/dev/null || true',
            "  fi",
            '  if [ -f "$VENV_DIR/bin/pip" ]; then',
            '    PIP="$VENV_DIR/bin/pip"',
            '    echo "[venv] 使用: $VENV_DIR"',
            "  else",
            '    echo "  ⚠️  python3-venv 不可用，使用 --break-system-packages"',
            '    PIP="pip --break-system-packages"',
            "  fi",
            "fi",
            'echo ""',
            "",
            'echo "[检测] 测试 PyPI 下载速度..."',
            'MIRROR_ARG=""',
            "if ! python3 -c \"import time,urllib.request;t0=time.time();urllib.request.urlopen('https://pypi.org/simple/',timeout=10);exit(0 if time.time()-t0<1.5 else 1)\" 2>/dev/null; then",
            '  echo "  ⏳ 下载速度较慢，切换国内镜像"',
            '  MIRROR_ARG="-i https://pypi.tuna.tsinghua.edu.cn/simple"',
            "else",
            '  echo "  ✅ 网络正常"',
            "fi",
            'echo ""',
            "",
            'echo "[pip] 升级 pip..."',
            "$PIP install --upgrade pip $MIRROR_ARG",
            'echo ""',
            "",
            'echo "[PyTorch] 安装..."',
            f"$PIP install torch torchaudio --index-url {torch_url} || \\",
            f'  (echo "  {gpu_tag} 版失败，回退 CPU 版..." && $PIP install torch torchaudio --index-url https://download.pytorch.org/whl/cpu)',
            'echo ""',
            "",
            'echo "[依赖] 安装其余包..."',
            "$PIP install -r requirements.txt $MIRROR_ARG",
            'echo ""',
            'echo "============================================"',
            'echo " 安装完成！运行 python main.py 启动程序"',
            'echo "============================================"',
        ]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not is_win:
        path.chmod(0o755)
    return path


# ── 主入口 ──


def ensure_venv():
    """确保程序在虚拟环境中运行（分步检测 → 复用已有 venv → 逐包安装缺失依赖）。"""
    if os.environ.get(_VENV_FLAG):
        return

    # 已在可用 venv 中 → 直接共享，跳过部署
    if hasattr(sys, "base_prefix") and sys.prefix != sys.base_prefix:
        _py = _venv_python(Path(sys.prefix))
        if _py.is_file() and _venv_has_pip(_py):
            os.environ[_VENV_FLAG] = "1"
            return

    project_root = Path(__file__).resolve().parent
    requirements_path = project_root / "requirements.txt"

    print()
    print("=" * 58)
    print("   🎬 pyvideotrans-studio  —  环境部署")
    print("=" * 58)
    print("   首次运行将自动完成以下步骤，请耐心等待。")
    print("   如已安装过，检测通过后会自动跳过。")
    print()

    # ═══════════════════════════════════════════
    #  [1/5]  操作系统与 Python 环境检测
    # ═══════════════════════════════════════════
    print("[1/5] 检测操作系统与 Python 环境")
    print("-" * 58)
    _detect_platform()
    print()

    # ═══════════════════════════════════════════
    #  [2/5]  GPU 加速硬件检测
    # ═══════════════════════════════════════════
    print("[2/5] 检测 GPU 加速硬件")
    print("-" * 58)
    gpu_info = _detect_gpu()
    if gpu_info["name"]:
        print(f"  检测到显卡：{gpu_info['name']}")
    print(f"  加速模式：{gpu_info['type'].upper()}")
    if gpu_info["type"] == "cpu":
        print("  ⚠️  未检测到专用 GPU，使用 CPU 模式运行。")
        print("     Whisper 语音识别等任务会较慢，但软件仍可正常使用。")
    # 生成安装脚本
    script_path = _generate_install_script(project_root, gpu_info)
    print(f"  📄 已生成平台专属安装脚本：{script_path.name}")
    print()
    print("     请在 pyvideotrans-studio 目录打开终端，按系统运行：")
    print("       Linux/macOS  →  sh install_deps.sh")
    print("       Windows      →  双击 install_deps.bat")
    print("     或直接继续，程序将自动完成安装。")
    print()

    # ═══════════════════════════════════════════
    #  [3/5]  虚拟环境设置
    # ═══════════════════════════════════════════
    print("[3/5] 设置虚拟环境")
    print("-" * 58)

    venv_dir = _find_venv(project_root)
    if venv_dir:
        desc = str(venv_dir.relative_to(project_root)) if venv_dir.is_relative_to(project_root) else str(venv_dir)
        print(f"  ✅ 发现已有虚拟环境：{desc}")
        print(f"     直接复用，无需重新创建。")
    else:
        print("  ℹ️  未找到可复用的虚拟环境，正在创建...")
        venv_dir = _create_venv(project_root)
        if not venv_dir:
            print("  ❌ 虚拟环境创建失败。")
            print("      Linux 下通常需要安装 python3-venv：")
            print("        sudo apt install python3-venv")
            print()
            print("     安装后重新运行即可，或手动执行：")
            print(f"        cd {project_root}")
            print("        python3 -m venv venv")
            print("        source venv/bin/activate")
            print("        pip install -r requirements.txt")
            print("        python main.py")
            sys.exit(1)
        print(f"  ✅ 虚拟环境已创建：venv/")

    python_path = _venv_python(venv_dir)
    if not python_path.is_file():
        print(f"  ❌ 未找到 Python 解释器：{python_path}")
        sys.exit(1)

    print(f"  解释器：{python_path}")
    print()

    # ═══════════════════════════════════════════
    #  [4/5]  检查与安装依赖
    # ═══════════════════════════════════════════
    print("[4/5] 检查与安装依赖")
    print("-" * 58)

    # 逐包检查
    missing = _check_missing_deps(python_path, requirements_path) if requirements_path.is_file() else []
    if not missing:
        print("  ✅ 全部依赖已安装，无需操作。")
        print(f"     当前环境：{venv_dir.name}")
    else:
        # 显示哪些已装、哪些缺失
        print(f"  检查完成。缺失 {len(missing)} 个依赖，开始安装...")
        print()
        _install_missing(python_path, requirements_path, gpu_info, missing)
    print()

    # ═══════════════════════════════════════════
    #  [5/5]  启动程序
    # ═══════════════════════════════════════════
    print("[5/5] 启动程序")
    print("-" * 58)
    print("  正在切换到虚拟环境并启动...")
    print()
    print("=" * 58)
    print("   环境部署完成！正在启动 pyvideotrans-studio...")
    print("   下次启动建议使用 python sv.py（快速启动）")
    print("=" * 58)
    print()

    env = os.environ.copy()
    env[_VENV_FLAG] = "1"
    try:
        os.execve(str(python_path), [str(python_path)] + sys.argv, env)
    except Exception as e:
        print(f"  ❌ 切换到虚拟环境失败：{e}")
        sys.exit(1)
