# -*- coding: utf-8 -*-
"""文字生视频核心引擎 — 复用现有 TTS/LLM/FFmpeg 管线"""

from .engine import TextToVideoEngine
from .llm_service import LLMStoryboardService
