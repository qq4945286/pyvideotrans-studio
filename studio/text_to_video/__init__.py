# -*- coding: utf-8 -*-
"""文字生视频 UI 模块"""

from .input_panel import TextToVideoPanel
from .storyboard_panel import StoryboardPanel, ShotCard
from .media_browser import MediaBrowser, MaterialCard
from .material_timeline import (
    MaterialTimeline,
    MaterialCard as MaterialTimelineCard,
    _material_to_dict,
    _dict_to_material,
)
from .settings_dialog import TextToVideoSettingsDialog
