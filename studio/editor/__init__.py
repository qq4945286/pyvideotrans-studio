# -*- coding: utf-8 -*-
"""
剪辑模块 — 单轨时间线 + 视频预览 + ffmpeg 引擎

使用:
    from editor import TimelineWidget, PreviewWidget, ClipEngine, models
"""

from .models import TimelineClip, ClipSegment, SubtitleEntry, Effect
from .engine import ClipEngine, ExportOptions
from .export_dialog import ExportDialog
from .preview_widget import PreviewWidget, FrameExtractor
from .timeline_widget import TimelineWidget
from .effects import (
    EFFECT_REGISTRY,
    build_ffmpeg_filter_chain,
    get_all_effects,
    get_all_categories,
    get_external_effects_dir,
    open_effects_dir,
    refresh_external_effects,
)
from .effects_dialog import EffectsDialog
from . import pvt_bridge
from . import gpu_accel

# 启动时扫描外部素材特效目录
refresh_external_effects()

__all__ = [
    "TimelineClip",
    "SubtitleEntry",
    "ClipSegment",
    "Effect",
    "ExportOptions",
    "ClipEngine",
    "ExportDialog",
    "PreviewWidget",
    "FrameExtractor",
    "TimelineWidget",
    "EffectsDialog",
    "EFFECT_REGISTRY",
    "build_ffmpeg_filter_chain",
    "get_all_effects",
    "get_all_categories",
    "get_external_effects_dir",
    "open_effects_dir",
    "refresh_external_effects",
    "pvt_bridge",
    "gpu_accel",
]
