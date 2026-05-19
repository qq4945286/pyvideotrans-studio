# -*- coding: utf-8 -*-
"""
pvt-core Rust CLI 桥接
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional


def _find_binary() -> str:
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "pvt-core" / "target" / "release" / "pvt-core",
        Path(__file__).resolve().parent.parent.parent / "pvt-core" / "target" / "debug" / "pvt-core",
    ]
    for d in os.environ.get("PATH", "").split(os.pathsep):
        candidates.append(Path(d) / "pvt-core")
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return "pvt-core"


PVT_BIN = _find_binary()


def _run_json(args: list[str]) -> dict:
    full_cmd = [PVT_BIN] + args
    r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"pvt-core 失败: {r.stderr.strip() or r.stdout.strip()}")
    if not r.stdout.strip():
        return {}
    return json.loads(r.stdout)


def gpu_info() -> dict:
    """GPU 加速能力信息"""
    return _run_json(["gpu-info"])


def gpu_summary() -> str:
    info = gpu_info()
    if not info.get("available"):
        return "GPU 加速: 不可用"
    parts = [f"GPU 加速: {info.get('backend', '').upper()}"]
    if info.get("driver"):
        parts.append(f" ({info['driver']})")
    encoders = []
    if info.get("h264"):
        encoders.append("H.264")
    if info.get("hevc"):
        encoders.append("HEVC")
    if encoders:
        parts.append(f" 支持 {', '.join(encoders)} 编码")
    return "".join(parts)


def probe(path: str) -> dict:
    """媒体文件信息"""
    return _run_json(["probe", "-i", path])


def cmd_trim(
    input_path: str,
    output_path: str,
    start: float,
    duration: Optional[float] = None,
    codec: str = "h264",
    quality: str = "medium",
    resolution: Optional[str] = None,
    use_gpu: bool = True,
    audio_codec: str = "aac",
    subtitle: Optional[str] = None,
) -> list[str]:
    cmd = [PVT_BIN, "clip", "trim", "-i", input_path, "-o", output_path, "-s", str(start)]
    if duration is not None and duration > 0:
        cmd += ["-d", str(duration)]
    cmd += ["--codec", codec, "-q", quality]
    if resolution:
        cmd += ["-r", resolution]
    if not use_gpu:
        cmd += ["--no-gpu"]
    cmd += ["--audio-codec", audio_codec]
    if subtitle:
        cmd += ["--subtitle", subtitle]
    return cmd


def cmd_split(
    input_path: str,
    at: float,
    output1: str,
    output2: str,
    codec: str = "h264",
    quality: str = "medium",
    use_gpu: bool = True,
) -> list[str]:
    cmd = [
        PVT_BIN,
        "clip",
        "split",
        "-i",
        input_path,
        "--at",
        str(at),
        "--output1",
        output1,
        "--output2",
        output2,
        "--codec",
        codec,
        "-q",
        quality,
    ]
    if not use_gpu:
        cmd += ["--no-gpu"]
    return cmd


def cmd_merge(
    files: list[str],
    output_path: str,
    reencode: bool = False,
    codec: str = "h264",
    quality: str = "medium",
    use_gpu: bool = True,
) -> list[str]:
    cmd = [PVT_BIN, "clip", "merge", "-o", output_path] + files
    if reencode:
        cmd += ["--reencode", "--codec", codec, "-q", quality]
        if not use_gpu:
            cmd += ["--no-gpu"]
    return cmd


def cmd_extract_audio(input_path: str, output_path: str, codec: str = "mp3") -> list[str]:
    return [PVT_BIN, "audio", "extract", "-i", input_path, "-o", output_path, "--codec", codec]


def cmd_gif(
    input_path: str, output_path: str, start: float, duration: float, fps: int = 10, scale: int = 480
) -> list[str]:
    """生成 GIF 的 ffmpeg 命令（双步调色板）"""
    return [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        input_path,
        "-vf",
        f"fps={fps},scale={scale}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse=dither=bayer",
        "-loop",
        "0",
        output_path,
    ]


def cmd_speed(
    input_path: str, output_path: str, start: float, duration: float, speed: float, audio_codec: str = "aac"
) -> list[str]:
    """变速导出 ffmpeg 命令"""
    if abs(speed - 1.0) < 0.01:
        # 无需变速，走普通裁剪
        return cmd_trim(input_path, output_path, start, duration, audio_codec=audio_codec)
    atempo = min(2.0, max(0.5, speed))
    # 如果 speed > 2.0，需要多个 atempo 串联
    atempo_filters = []
    remaining = speed
    while remaining > 2.0:
        atempo_filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        atempo_filters.append("atempo=0.5")
        remaining /= 0.5
    atempo_filters.append(f"atempo={remaining:.3f}")

    vf = f"setpts={1.0/speed:.3f}*PTS"
    af = ",".join(atempo_filters)
    acodec_arg = "libmp3lame" if audio_codec == "mp3" else "aac"
    return [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        input_path,
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-vf",
        vf,
        "-c:a",
        acodec_arg,
        "-b:a",
        "128k",
        "-af",
        af,
        output_path,
    ]


def cmd_denoise(
    input_path: str,
    output_path: str,
    strength: float = 0.5,
    noise_floor: int = -50,
    noise_type: str = "w",
    track_enabled: bool = False,
    bands: int = 0,
    output_mode: str = "o",
) -> list[str]:
    nr = max(1, min(97, int(strength * 97)))
    nf = max(-80, min(-20, noise_floor))
    tr = 1 if track_enabled else 0
    bn = max(0, min(32, bands))
    return [
        PVT_BIN,
        "audio",
        "denoise",
        "-i",
        input_path,
        "-o",
        output_path,
        "--nr",
        str(nr),
        "--nf",
        str(nf),
        "--nt",
        noise_type,
        "--tr",
        str(tr),
        "--bn",
        str(bn),
        "--om",
        output_mode,
    ]


def cmd_thumbnails(input_path: str, output_dir: str, count: int = 20, width: int = 120, height: int = 68) -> list[str]:
    return [
        PVT_BIN,
        "clip",
        "thumbnails",
        "-i",
        input_path,
        "-o",
        output_dir,
        "-c",
        str(count),
        "--width",
        str(width),
        "--height",
        str(height),
    ]


def generate_thumbnails_blocking(
    input_path: str, output_dir: str, count: int = 20, width: int = 120, height: int = 68
) -> list[str]:
    cmd = cmd_thumbnails(input_path, output_dir, count, width, height)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"缩略图失败: {r.stderr.strip()}")
    result = json.loads(r.stdout)
    return result.get("files", [])


def parse_progress(line: str) -> Optional[float]:
    """从 ffmpeg 输出行解析当前时间（秒）"""
    import re

    m = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", line)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return float(h * 3600 + mi * 60 + s)
    return None


# ── 编码参数映射 ──────────────────────────────────────────────

_CODEC_MAP = {
    "h264": {"vcodec": "libx264", "preset": "medium", "crf": "23"},
    "h265": {"vcodec": "libx265", "preset": "medium", "crf": "28"},
    "vp9": {"vcodec": "libvpx-vp9", "preset": "", "crf": "30"},
}

_QUALITY_CRF = {
    "best": 18,
    "high": 20,
    "medium": 23,
    "low": 28,
    "fast": 35,
}


def _fx_mode(effect) -> str:
    """获取特效的执行模式: vf (简单滤镜链) 或 complex (需要 filter_complex)"""
    from .effects import get_all_effects

    entry = get_all_effects().get(effect.effect_id)
    return entry.get("mode", "vf") if entry else "vf"


def _get_fx_entry(effect) -> dict | None:
    """获取特效注册表条目"""
    from .effects import get_all_effects

    return get_all_effects().get(effect.effect_id)


def cmd_merge_with_effects(
    segments: list,
    output_path: str,
    codec: str = "h264",
    quality: str = "medium",
    use_gpu: bool = True,
    audio_codec: str = "aac",
) -> list[str]:
    """构建带特效的合并 ffmpeg 命令（使用 filter_complex）

    每个 segment 需有: source_path, start, end, effects (list[Effect])
    支持复杂特效（叠加素材等）通过 movie+overlay filter_complex 连接
    """
    from .effects import build_ffmpeg_filter_chain

    cmd = ["ffmpeg", "-y"]

    # 输入文件
    for seg in segments:
        cmd += ["-i", seg.source_path]

    # 编码参数（MVP 用 libx264，GPU 加速后续优化）
    enc = _CODEC_MAP.get(codec, _CODEC_MAP["h264"])
    crf = _QUALITY_CRF.get(quality, 23)

    # filter_complex 构建
    vf_parts = []
    af_parts = []
    v_labels = []
    overlay_idx = 0  # 全局叠加素材计数器

    for i, seg in enumerate(segments):
        vi = f"vE{i}"
        ai = f"aE{i}"

        seg_effects = getattr(seg, "effects", []) or []
        # 分离简单特效和复杂特效
        simple_fx = [e for e in seg_effects if _fx_mode(e) != "complex"]
        complex_fx = [e for e in seg_effects if _fx_mode(e) == "complex"]

        # 视频：trim → setpts → 简单特效链 → scale（如有）
        vf = f"[{i}:v]trim=start={seg.start:.3f}:end={seg.end:.3f},setpts=PTS-STARTPTS"
        chain = build_ffmpeg_filter_chain(simple_fx)
        if chain:
            vf += "," + chain
        if getattr(seg, "target_width", 0) and getattr(seg, "target_height", 0):
            vf += f",scale={seg.target_width}:{seg.target_height}"

        # 复杂特效（叠加素材等） — 使用占位标签，后续拼接
        if complex_fx:
            cur_label = f"vE{i}_base"
            vf += f"[{cur_label}]"
            vf_parts.append(vf)
            for fx in complex_fx:
                fx_entry = _get_fx_entry(fx)
                if not fx_entry:
                    continue
                fx_tpl = fx_entry.get("ffmpeg_filter", "")
                ov_label = f"ovE{overlay_idx}"
                overlay_idx += 1
                out_label = f"vE{i}" if fx is complex_fx[-1] else f"vE{i}_ov{overlay_idx}"
                # 填充模板: {vid}→当前视频标签, {i}→叠加编号
                try:
                    fx_str = fx_tpl.format(
                        **fx.params,
                        vid=cur_label,
                        i=overlay_idx - 1,
                    )
                except (KeyError, ValueError):
                    fx_str = fx_tpl.replace("{vid}", cur_label)
                fx_str = fx_str.replace("[{vid}]", f"[{cur_label}]")
                # movie 滤镜产生 [ov_{i}] 标签，后面 overlay 使用它
                vf_parts.append(fx_str + f"[{out_label}]")
                cur_label = out_label
            vi = cur_label  # 最终输出标签
        else:
            vf += f"[{vi}]"
            vf_parts.append(vf)

        # 音频：atrim → asetpts
        af = f"[{i}:a]atrim=start={seg.start:.3f}:end={seg.end:.3f},asetpts=PTS-STARTPTS[{ai}]"
        af_parts.append(af)

        v_labels.append(vi)

    # concat
    n = len(segments)
    concat_v = "".join(f"[{l}]" for l in v_labels) + f"concat=n={n}:v=1:a=0[outv]"
    a_labels = [f"aE{i}" for i in range(n)]
    concat_a = "".join(f"[{l}]" for l in a_labels) + f"concat=n={n}:v=0:a=1[outa]"

    filter_complex = ";".join(vf_parts + af_parts + [concat_v, concat_a])

    cmd += ["-filter_complex", filter_complex]
    cmd += ["-map", "[outv]", "-map", "[outa]"]

    # 编码
    cmd += ["-c:v", enc["vcodec"]]
    if enc.get("preset"):
        cmd += ["-preset", enc["preset"]]
    cmd += ["-crf", str(crf)]
    cmd += ["-c:a", audio_codec, "-b:a", "128k"]
    cmd += ["-avoid_negative_ts", "make_zero"]
    cmd.append(output_path)

    return cmd
