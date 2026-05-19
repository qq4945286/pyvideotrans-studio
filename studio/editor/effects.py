# -*- coding: utf-8 -*-
"""
视频特效注册表 + 外部素材特效扫描 + FFmpeg filter_complex 构建工具
"""

import os
import json
import glob
from pathlib import Path

from .models import Effect

# ── 外部素材特效目录 ──────────────────────────────────────────────
# 用户可以从网上（达芬奇/剪映资源站等）下载 .cube LUT 文件、叠加素材、预设放入此目录
# 应用启动时自动扫描并注册为可用特效

_EFFECTS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "effects")
_EFFECTS_ROOT = os.path.abspath(_EFFECTS_ROOT)


def _ensure_effects_dirs():
    """确保素材特效目录结构存在"""
    for sub in ("luts", "overlays", "presets"):
        d = os.path.join(_EFFECTS_ROOT, sub)
        os.makedirs(d, exist_ok=True)
    # 在每个目录放一个 README.txt 说明文件
    _write_readme(
        os.path.join(_EFFECTS_ROOT, "luts"),
        "LUT 调色文件",
        "将 .cube 格式的 LUT 文件放入此目录\n" "网上搜索: '免费 LUT 下载' '达芬奇 LUT pack'",
    )
    _write_readme(
        os.path.join(_EFFECTS_ROOT, "overlays"),
        "叠加素材",
        "将带透明通道的视频/webm 或普通 mp4 放入此目录\n"
        "网上搜索: 'free light leak overlay' 'film burn overlay' '胶片灼烧素材'",
    )
    _write_readme(
        os.path.join(_EFFECTS_ROOT, "presets"),
        "ffmpeg 滤镜预设",
        "将 .json 格式的滤镜链预设放入此目录\n"
        '格式: {"name":"预设名","category":"分类","ffmpeg_filter":"滤镜链模板"}',
    )


def _write_readme(dirpath: str, title: str, body: str):
    p = os.path.join(dirpath, "README.txt")
    if not os.path.exists(p):
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"{title}\n{'=' * len(title)}\n\n{body}\n")
        except OSError:
            pass


# ── 外部特效注册表（启动时扫描填充）───────────────────────────────
_external_effects: dict = {}

# ── 特效注册表 ────────────────────────────────────────────────
# 每个条目：effect_id / name(中文) / category / ffmpeg_filter(模板) / params(参数定义列表)

EFFECT_REGISTRY: dict = {
    # ── 调色 ──
    "brightness": {
        "effect_id": "brightness",
        "name": "亮度",
        "category": "调色",
        "ffmpeg_filter": "eq=brightness={value:.2f}",
        "params": [
            {
                "key": "value",
                "label": "亮度",
                "type": "float",
                "min": -1.0,
                "max": 1.0,
                "default": 0.0,
                "step": 0.01,
            }
        ],
    },
    "contrast": {
        "effect_id": "contrast",
        "name": "对比度",
        "category": "调色",
        "ffmpeg_filter": "eq=contrast={value:.2f}",
        "params": [
            {
                "key": "value",
                "label": "对比度",
                "type": "float",
                "min": 0.5,
                "max": 2.0,
                "default": 1.0,
                "step": 0.01,
            }
        ],
    },
    "saturation": {
        "effect_id": "saturation",
        "name": "饱和度",
        "category": "调色",
        "ffmpeg_filter": "eq=saturation={value:.2f}",
        "params": [
            {
                "key": "value",
                "label": "饱和度",
                "type": "float",
                "min": 0.0,
                "max": 3.0,
                "default": 1.0,
                "step": 0.01,
            }
        ],
    },
    "hue": {
        "effect_id": "hue",
        "name": "色相",
        "category": "调色",
        "ffmpeg_filter": "hue=h={value}",
        "params": [
            {
                "key": "value",
                "label": "色相角度",
                "type": "int",
                "min": 0,
                "max": 360,
                "default": 0,
                "unit": "°",
            }
        ],
    },
    "colorbalance": {
        "effect_id": "colorbalance",
        "name": "色彩平衡",
        "category": "调色",
        "ffmpeg_filter": "colorbalance=rs={rs:.2f}:gs={gs:.2f}:bs={bs:.2f}",
        "params": [
            {
                "key": "rs",
                "label": "红-青",
                "type": "float",
                "min": -1.0,
                "max": 1.0,
                "default": 0.0,
                "step": 0.01,
            },
            {
                "key": "gs",
                "label": "绿-品红",
                "type": "float",
                "min": -1.0,
                "max": 1.0,
                "default": 0.0,
                "step": 0.01,
            },
            {
                "key": "bs",
                "label": "蓝-黄",
                "type": "float",
                "min": -1.0,
                "max": 1.0,
                "default": 0.0,
                "step": 0.01,
            },
        ],
    },
    # ── 模糊/锐化 ──
    "boxblur": {
        "effect_id": "boxblur",
        "name": "模糊",
        "category": "模糊/锐化",
        "ffmpeg_filter": "boxblur={value}",
        "params": [
            {
                "key": "value",
                "label": "模糊半径",
                "type": "int",
                "min": 1,
                "max": 20,
                "default": 2,
            }
        ],
    },
    "unsharp": {
        "effect_id": "unsharp",
        "name": "锐化",
        "category": "模糊/锐化",
        "ffmpeg_filter": "unsharp=luma_msize_x=3:luma_msize_y=3:luma_amount={value:.2f}",
        "params": [
            {
                "key": "value",
                "label": "锐化强度",
                "type": "float",
                "min": 0.0,
                "max": 5.0,
                "default": 1.0,
                "step": 0.1,
            }
        ],
    },
    # ── 几何变换 ──
    "hflip": {
        "effect_id": "hflip",
        "name": "水平翻转",
        "category": "几何变换",
        "ffmpeg_filter": "hflip",
        "params": [],
    },
    "rotate": {
        "effect_id": "rotate",
        "name": "旋转",
        "category": "几何变换",
        "ffmpeg_filter": "rotate(angle={value}*PI/180)",
        "params": [
            {
                "key": "value",
                "label": "旋转角度",
                "type": "int",
                "min": 0,
                "max": 360,
                "default": 0,
                "unit": "°",
            }
        ],
    },
    # ── 高级 ──
    "vignette": {
        "effect_id": "vignette",
        "name": "暗角",
        "category": "高级",
        "ffmpeg_filter": "vignette=angle=PI/4:{value:.2f}",
        "params": [
            {
                "key": "value",
                "label": "暗角强度",
                "type": "float",
                "min": 0.0,
                "max": 1.0,
                "default": 0.5,
                "step": 0.01,
            }
        ],
    },
    "lut3d": {
        "effect_id": "lut3d",
        "name": "LUT 调色",
        "category": "高级",
        "ffmpeg_filter": "lut3d=file='{path}'",
        "params": [
            {
                "key": "path",
                "label": "LUT 文件路径",
                "type": "file",
                "min": "",
                "max": "",
                "default": "",
            }
        ],
    },
    # ── 过渡 ──
    "fade_in": {
        "effect_id": "fade_in",
        "name": "淡入",
        "category": "过渡",
        "ffmpeg_filter": "fade=t=in:st=0:d={duration:.2f}",
        "params": [
            {
                "key": "duration",
                "label": "淡入时长",
                "type": "float",
                "min": 0.1,
                "max": 10.0,
                "default": 1.0,
                "step": 0.1,
                "unit": "秒",
            }
        ],
    },
    "fade_out": {
        "effect_id": "fade_out",
        "name": "淡出",
        "category": "过渡",
        "ffmpeg_filter": "fade=t=out:st={start_time:.2f}:d={duration:.2f}",
        "params": [
            {
                "key": "duration",
                "label": "淡出时长",
                "type": "float",
                "min": 0.1,
                "max": 10.0,
                "default": 1.0,
                "step": 0.1,
                "unit": "秒",
            },
            {
                "key": "start_time",
                "label": "开始时间(相对)",
                "type": "float",
                "min": 0.0,
                "max": 3600.0,
                "default": 0.0,
                "step": 0.1,
                "unit": "秒",
            },
        ],
    },
}

# 分类排序（UI 展示用）
EFFECT_CATEGORIES = ["调色", "模糊/锐化", "几何变换", "高级", "过渡"]
# 外部素材特效分类前缀
EXTERNAL_CATEGORIES_EXPAND = ["LUT 调色", "叠加素材", "自定义预设"]


def get_effect_by_id(effect_id: str) -> dict | None:
    """根据 ID 获取特效定义（先查内置，再查外部）"""
    return EFFECT_REGISTRY.get(effect_id) or _external_effects.get(effect_id)


def get_all_categories() -> list[str]:
    """获取所有分类列表（含外部特效分类）"""
    cats = list(EFFECT_CATEGORIES)
    if any(e.get("category") == "LUT 调色" for e in _external_effects.values()):
        cats.append("LUT 调色")
    if any(e.get("category") == "叠加素材" for e in _external_effects.values()):
        cats.append("叠加素材")
    if any(e.get("category") == "自定义预设" for e in _external_effects.values()):
        cats.append("自定义预设")
    return cats


def get_all_effects() -> dict:
    """获取完整特效注册表（内置 + 外部）"""
    merged = dict(EFFECT_REGISTRY)
    merged.update(_external_effects)
    return merged


def get_external_effects_dir() -> str:
    """获取外部素材特效目录路径"""
    return _EFFECTS_ROOT


def open_effects_dir():
    """在文件管理器中打开素材特效目录"""
    import platform
    import subprocess

    _ensure_effects_dirs()
    path = _EFFECTS_ROOT
    system = platform.system()
    if system == "Linux":
        subprocess.Popen(["xdg-open", path])
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    elif system == "Windows":
        os.startfile(path)


# ── 素材扫描器 ────────────────────────────────────────────────────


def _scan_luts(root: str) -> dict:
    """扫描 luts/ 目录下的 .cube 文件"""
    result = {}
    lut_dir = os.path.join(root, "luts")
    if not os.path.isdir(lut_dir):
        return result
    for f in sorted(glob.glob(os.path.join(lut_dir, "*.cube"))):
        name = os.path.splitext(os.path.basename(f))[0]
        # 美化显示名：下划线转空格，首字母大写
        display_name = name.replace("_", " ").replace("-", " ").title()
        eid = f"lut_{name}"
        escaped_path = f.replace("\\", "\\\\").replace(":", "\\:")
        result[eid] = {
            "effect_id": eid,
            "name": display_name,
            "category": "LUT 调色",
            "mode": "vf",  # 可用在 -vf 滤镜链
            "external_source": f,
            "ffmpeg_filter": f"lut3d=file='{escaped_path}'",
            "params": [
                {
                    "key": "intensity",
                    "label": "强度",
                    "type": "float",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 1.0,
                    "step": 0.01,
                    "note": "1.0=全量, 0.5=50%混合",
                }
            ],
        }
    return result


def _scan_overlays(root: str) -> dict:
    """扫描 overlays/ 目录下的视频素材"""
    result = {}
    ov_dir = os.path.join(root, "overlays")
    if not os.path.isdir(ov_dir):
        return result
    exts = (".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif", ".png", ".apng")
    for f in sorted(Path(ov_dir).iterdir()):
        if f.suffix.lower() not in exts:
            continue
        name = f.stem
        display_name = name.replace("_", " ").replace("-", " ").title()
        eid = f"overlay_{name}"
        abs_path = str(f.resolve())
        escaped_path = abs_path.replace("\\", "\\\\").replace(":", "\\:")
        result[eid] = {
            "effect_id": eid,
            "name": display_name,
            "category": "叠加素材",
            "mode": "complex",  # 需要 filter_complex 支持
            "external_source": abs_path,
            "ffmpeg_filter": f"movie='{escaped_path}':loop=1,format=rgba[ov_{{i}}];[{{vid}}][ov_{{i}}]overlay=format=auto:eval=frame",
            "params": [
                {
                    "key": "opacity",
                    "label": "不透明度",
                    "type": "float",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.5,
                    "step": 0.01,
                },
                {
                    "key": "x",
                    "label": "水平偏移",
                    "type": "int",
                    "min": -4096,
                    "max": 4096,
                    "default": 0,
                },
                {
                    "key": "y",
                    "label": "垂直偏移",
                    "type": "int",
                    "min": -4096,
                    "max": 4096,
                    "default": 0,
                },
            ],
        }
    return result


def _scan_presets(root: str) -> dict:
    """扫描 presets/ 目录下的 .json 预设文件"""
    result = {}
    preset_dir = os.path.join(root, "presets")
    if not os.path.isdir(preset_dir):
        return result
    for f in sorted(glob.glob(os.path.join(preset_dir, "*.json"))):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if not isinstance(data, dict):
                continue
            name = data.get("name", os.path.splitext(os.path.basename(f))[0])
            eid = f"preset_{os.path.splitext(os.path.basename(f))[0]}"
            result[eid] = {
                "effect_id": eid,
                "name": name,
                "category": "自定义预设",
                "mode": data.get("mode", "vf"),
                "external_source": f,
                "ffmpeg_filter": data.get("ffmpeg_filter", ""),
                "params": data.get("params", []),
            }
        except (json.JSONDecodeError, OSError):
            continue
    return result


def refresh_external_effects():
    """重新扫描外部素材特效目录并更新注册表（启动时调用一次）"""
    global _external_effects
    _ensure_effects_dirs()
    _external_effects = {}
    _external_effects.update(_scan_luts(_EFFECTS_ROOT))
    _external_effects.update(_scan_overlays(_EFFECTS_ROOT))
    _external_effects.update(_scan_presets(_EFFECTS_ROOT))
    return _external_effects


def build_ffmpeg_filter_chain(effects: list) -> str:
    """将 Effect 列表转为 ffmpeg -vf 滤镜链字符串（逗号分隔）"""
    parts = []
    for e in effects:
        if not isinstance(e, Effect):
            continue
        if not e.enabled:
            continue
        filt = e.to_ffmpeg_filter()
        if filt:
            parts.append(filt)
    return ",".join(parts)
