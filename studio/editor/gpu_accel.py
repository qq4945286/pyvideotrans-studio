# -*- coding: utf-8 -*-
"""
GPU 加速检测
"""

from dataclasses import dataclass
from typing import Optional

from .pvt_bridge import gpu_info as _rust_gpu_info


@dataclass
class GPUInfo:
    available: bool = False
    backend: str = ""
    device: str = ""
    driver: str = ""
    h264: bool = False
    hevc: bool = False
    encoder_h264: str = ""
    encoder_hevc: str = ""


_gpu_info: Optional[GPUInfo] = None


def detect_gpu() -> GPUInfo:
    global _gpu_info
    if _gpu_info is not None:
        return _gpu_info
    try:
        raw = _rust_gpu_info()
        if not raw.get("available"):
            _gpu_info = GPUInfo(available=False)
        else:
            info = GPUInfo(
                available=True,
                backend=raw.get("backend", ""),
                device=raw.get("device", ""),
                driver=raw.get("driver", ""),
                h264=raw.get("h264", False),
                hevc=raw.get("hevc", False),
            )
            if info.backend == "vaapi":
                info.encoder_h264 = "h264_vaapi" if info.h264 else ""
                info.encoder_hevc = "hevc_vaapi" if info.hevc else ""
            elif info.backend == "nvenc":
                info.encoder_h264 = "h264_nvenc" if info.h264 else ""
                info.encoder_hevc = "hevc_nvenc" if info.hevc else ""
            _gpu_info = info
    except Exception:
        _gpu_info = GPUInfo(available=False)
    return _gpu_info


def hwaccel_args(use_gpu: bool = True) -> list[str]:
    if not use_gpu:
        return []
    info = detect_gpu()
    if not info.available:
        return []
    if info.backend == "vaapi":
        return ["-hwaccel", "vaapi", "-hwaccel_device", info.device]
    elif info.backend == "nvenc":
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    return []


def encoder_args(codec: str = "h264", use_gpu: bool = True) -> dict:
    out = {"vcodec": "libx264" if codec == "h264" else "libx265", "extra": [], "pix_fmt": "yuv420p", "vf": ""}
    if not use_gpu:
        out["extra"] = ["-preset", "fast"]
        return out
    info = detect_gpu()
    if not info.available:
        out["extra"] = ["-preset", "fast"]
        return out
    if info.backend == "vaapi":
        enc = info.encoder_h264 if codec == "h264" else info.encoder_hevc
        if enc:
            out["vcodec"] = enc
            out["vf"] = "format=nv12,hwupload"
            out["pix_fmt"] = ""
        else:
            out["extra"] = ["-preset", "fast"]
    elif info.backend == "nvenc":
        enc = info.encoder_h264 if codec == "h264" else info.encoder_hevc
        if enc:
            out["vcodec"] = enc
            out["extra"] = ["-preset", "p7"]
        else:
            out["extra"] = ["-preset", "fast"]
    return out


def quality_args(quality: str = "medium", codec: str = "h264", use_gpu: bool = True) -> list[str]:
    crf_map = {"high": "18", "medium": "23", "low": "28"}
    qp = crf_map.get(quality, "23")
    if use_gpu and detect_gpu().available:
        backend = detect_gpu().backend
        if backend in ("vaapi", "nvenc"):
            return ["-qp", qp]
    return ["-crf", qp]


def summary() -> str:
    from .pvt_bridge import gpu_summary

    try:
        return gpu_summary()
    except Exception:
        return "GPU 加速: 未知"
