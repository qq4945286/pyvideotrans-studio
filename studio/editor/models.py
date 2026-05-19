# -*- coding: utf-8 -*-
"""
剪辑模块数据模型
"""

import copy
from dataclasses import dataclass, field


@dataclass
class Effect:
    """视频特效"""

    effect_id: str  # 特效标识符，如 "brightness", "boxblur"
    params: dict = field(default_factory=dict)  # 参数字典，如 {"brightness": 0.1}
    enabled: bool = True  # 是否启用

    def to_ffmpeg_filter(self) -> str:
        """将特效转换为 ffmpeg filter 字符串（用于简单 -vf 链）"""
        from .effects import get_all_effects

        entry = get_all_effects().get(self.effect_id)
        if not entry:
            return ""
        # 需要 filter_complex 的特效（如叠加素材）不能在 -vf 中使用
        if entry.get("mode") == "complex":
            return ""
        template = entry.get("ffmpeg_filter", "")
        if not template:
            return ""
        try:
            return template.format(**self.params)
        except KeyError:
            return template  # 无参数特效如 hflip


@dataclass
class TimelineClip:
    """时间线片段"""

    source_path: str  # 源文件路径
    source_start: float = 0.0  # 在源文件中的起始偏移（秒），分割时继承
    start: float = 0.0  # 在时间线上的起始位置（秒）
    duration: float = 0.0  # 时长（秒）
    source_duration: float = 0.0  # 源文件总时长
    label: str = ""
    link_group: str = ""  # 链接组 ID，同一组素材拖拽时同步移动
    display_scale: float = 1.0  # 显示倍率，Shift+滚轮仅调节本素材
    locked: bool = False  # 锁定素材（禁止任何操作）
    position_fixed: bool = False  # 固定位置（禁止拖拽移动）
    merge_parts: list = field(default_factory=list)  # 合并前各段信息，用于取消合并
    speed: float = 1.0  # 播放速度倍率
    muted: bool = False  # 静音此素材
    track_type: str = ""  # "" = 普通, "video" = 视频轨, "audio" = 音频轨
    proxy_path: str = ""  # 代理文件路径（低分辨率预览用）
    target_width: int = 0  # 导出时目标分辨率宽度（0=保持原始）
    target_height: int = 0  # 导出时目标分辨率高度（0=保持原始）
    effects: list = field(default_factory=list)  # list[Effect]，特效链，按顺序应用

    @property
    def end(self) -> float:
        return self.start + self.duration

    def snapshot(self) -> "TimelineClip":
        """深拷贝当前状态，供撤销系统使用"""
        return copy.deepcopy(self)


@dataclass(unsafe_hash=True)
class SubtitleEntry:
    """字幕条目"""

    index: int
    start: float  # 开始时间（秒）
    end: float  # 结束时间（秒）
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class ClipSegment:
    """导出用片段 — 标记源文件中要裁剪的范围"""

    source_path: str
    start: float = 0.0
    end: float = 0.0
    label: str = ""
    speed: float = 1.0
    effects: list = field(default_factory=list)  # list[Effect]

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def is_valid(self) -> bool:
        return bool(self.source_path) and self.duration > 0.1
