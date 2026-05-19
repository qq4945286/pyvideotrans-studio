# -*- coding: utf-8 -*-
"""本地素材扫描器 — 关键词模糊匹配文件名"""

import os
import difflib

from videotrans.text_to_video.media.base import MaterialSource, MaterialResult


class LocalMaterialSource(MaterialSource):
    """本地文件系统素材源"""

    def __init__(self, search_dirs: list[str] = None):
        super().__init__()
        self.search_dirs = search_dirs or []
        self._cache: list[str] = []
        self._cache_valid = False

    def name(self) -> str:
        return "local"

    def enabled(self) -> bool:
        """只有配置了至少一个有效目录才启用"""
        return any(os.path.isdir(d) for d in self.search_dirs)

    def set_dirs(self, dirs: list[str]):
        self.search_dirs = dirs
        self._cache_valid = False

    def _build_cache(self):
        """递归扫描目录，缓存所有媒体文件路径"""
        if self._cache_valid:
            return
        self._cache = []
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".mp4", ".mov", ".avi", ".mkv", ".webm"}
        for d in self.search_dirs:
            if not os.path.isdir(d):
                continue
            for root, _, files in os.walk(d):
                for f in files:
                    if os.path.splitext(f)[1].lower() in exts:
                        self._cache.append(os.path.join(root, f))
        self._cache_valid = True

    def search(self, keywords: list[str], count: int = 10, media_type: str = "all") -> list[MaterialResult]:
        self._build_cache()
        if not self._cache:
            return []

        # 根据 media_type 过滤文件
        video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}

        def _match_type(ext: str) -> bool:
            if media_type == "video":
                return ext in video_exts
            elif media_type == "image":
                return ext in image_exts
            return True  # "all"

        scored: list[tuple[float, str]] = []
        for path in self._cache:
            ext = os.path.splitext(path)[1].lower()
            if not _match_type(ext):
                continue
            name = os.path.splitext(os.path.basename(path))[0].lower()
            score = 0.0
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in name:
                    score += 1.0
                else:
                    s = difflib.SequenceMatcher(None, kw_lower, name).ratio()
                    score += s * 0.3
            if score > 0.15:
                scored.append((score, path))

        scored.sort(key=lambda x: x[1], reverse=True)
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, path in scored[:count]:
            name = os.path.basename(path)
            ext = os.path.splitext(path)[1].lower()
            results.append(
                MaterialResult(
                    source="local",
                    url=path,
                    preview_url=path,
                    description=f"{name} (匹配度: {score:.0%})",
                    local_path=path,
                    media_type="video" if ext in video_exts else "image",
                )
            )
        return results

    def download(self, material: MaterialResult, save_dir: str = "") -> str:
        # 本地文件直接返回路径
        return material.local_path or material.url
