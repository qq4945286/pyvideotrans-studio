# -*- coding: utf-8 -*-
"""素材源抽象基类 — 带代理支持"""

import os
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class MaterialResult:
    """素材搜索结果"""

    source: str  # "local" | "pexels" | "pixabay" | "comfyui"
    url: str  # 原始 URL
    preview_url: str  # 缩略图/预览 URL
    description: str = ""  # 描述文字
    author: str = ""  # 作者
    width: int = 0
    height: int = 0
    duration: float = 0.0  # 视频时长（秒），图片为 0
    media_type: str = "image"  # "image" | "video"
    local_path: str = ""  # 下载后的本地路径
    effects: list = field(default_factory=list)  # list[Effect]，素材特效链


def _build_opener(proxy: str = ""):
    """创建带代理的 URL opener。
    代理优先级：显式传入 > app_cfg.proxy > HTTPS_PROXY 环境变量
    """
    handlers = []
    actual_proxy = proxy

    if not actual_proxy:
        try:
            from videotrans.configure import config as cfg

            actual_proxy = cfg.app_cfg.proxy or ""
        except Exception:
            pass

    if not actual_proxy:
        actual_proxy = os.environ.get("HTTPS_PROXY", "") or os.environ.get("HTTP_PROXY", "")

    if actual_proxy:
        handlers.append(urllib.request.ProxyHandler({"https": actual_proxy, "http": actual_proxy}))

    return urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()


def urlread(url: str, timeout: int = 15, headers: dict = None, proxy: str = "") -> bytes:
    """代理感知的 HTTP GET，返回响应体 bytes"""
    opener = _build_opener(proxy)
    if headers is None:
        headers = {}
    headers.setdefault("User-Agent", "pyvideotrans/1.0")
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


class MaterialSource(ABC):
    """素材源抽象基类"""

    def __init__(self, api_key: str = "", proxy: str = ""):
        self.api_key = api_key
        self.proxy = proxy

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def search(self, keywords: list[str], count: int = 10, media_type: str = "all") -> list[MaterialResult]: ...

    def download(self, material: MaterialResult, save_dir: str) -> str:
        url = material.url if material.url else material.preview_url
        if not url:
            return ""

        os.makedirs(save_dir, exist_ok=True)
        ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        filename = f"{material.source}_{hash(url) & 0x7FFFFFFF:08x}{ext}"
        local_path = os.path.join(save_dir, filename)

        if os.path.exists(local_path):
            return local_path

        try:
            data = urlread(url, timeout=20, proxy=self.proxy)
            with open(local_path, "wb") as f:
                f.write(data)
            return local_path
        except Exception:
            return ""

    def enabled(self) -> bool:
        return True
