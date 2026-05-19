# -*- coding: utf-8 -*-
"""素材获取层 — 统一入口，带代理支持"""

import os

from .base import MaterialSource, MaterialResult
from .local import LocalMaterialSource
from .pexels import PexelsSource
from .pixabay import PixabaySource
from .comfyui import ComfyUISource


def _get_proxy() -> str:
    """获取全局代理配置"""
    try:
        from videotrans.configure import config as cfg

        return cfg.params.get("t2v_llm_proxy", "") or cfg.app_cfg.proxy or os.environ.get("HTTPS_PROXY", "") or ""
    except Exception:
        return os.environ.get("HTTPS_PROXY", "") or ""


def create_sources(config: dict) -> list[MaterialSource]:
    """根据配置创建启用的素材源列表（按优先级排序）"""
    proxy = _get_proxy()
    sources = []

    if config.get("use_local", True):
        sources.append(LocalMaterialSource(config.get("local_dirs", [])))

    if config.get("use_pexels", False):
        pex_key = config.get("pexels_api_key", "")
        if pex_key:
            sources.append(PexelsSource(pex_key, proxy=proxy))

    if config.get("use_pixabay", False):
        pix_key = config.get("pixabay_api_key", "")
        if pix_key:
            sources.append(PixabaySource(pix_key, proxy=proxy))

    if config.get("use_comfyui", False):
        comfy = ComfyUISource(
            base_url=config.get("comfyui_url", "http://127.0.0.1:8188"),
            workflow_file=config.get("comfyui_workflow", ""),
        )
        if comfy.enabled():
            sources.append(comfy)

    return sources
