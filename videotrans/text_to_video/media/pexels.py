# -*- coding: utf-8 -*-
"""Pexels API 素材源 — https://www.pexels.com/api/"""

import json
import urllib.parse

from videotrans.text_to_video.media.base import MaterialSource, MaterialResult, urlread


class PexelsSource(MaterialSource):
    """Pexels 免费图库 API — 支持图片和视频搜索"""

    BASE_URL = "https://api.pexels.com/v1"
    VIDEO_URL = "https://api.pexels.com/videos"

    def name(self) -> str:
        return "pexels"

    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, keywords: list[str], count: int = 10, media_type: str = "all") -> list[MaterialResult]:
        if not self.api_key:
            return []

        search_images = media_type in ("image", "all")
        search_videos = media_type in ("video", "all")

        all_results = []
        per_kw = max(1, count // len(keywords)) if keywords else count

        for kw in keywords:
            if search_images:
                try:
                    results = self._search_photos(kw, per_kw)
                    all_results.extend(results)
                except Exception:
                    pass
            if search_videos:
                try:
                    results = self._search_videos(kw, per_kw)
                    all_results.extend(results)
                except Exception:
                    pass

        seen = set()
        unique = []
        for r in all_results:
            if r.url not in seen:
                seen.add(r.url)
                unique.append(r)
        return unique[:count]

    def _search_photos(self, keyword: str, count: int) -> list[MaterialResult]:
        params = urllib.parse.urlencode(
            {
                "query": keyword,
                "per_page": str(min(count, 20)),
                "orientation": "landscape",
                "size": "large",
                "locale": "zh-CN",
            }
        )
        url = f"{self.BASE_URL}/search?{params}"
        data = json.loads(urlread(url, timeout=15, headers={"Authorization": self.api_key}, proxy=self.proxy))

        results = []
        for photo in data.get("photos", []):
            src = photo.get("src", {})
            img_url = src.get("large2x") or src.get("large") or src.get("original") or ""
            preview = src.get("medium") or src.get("small") or img_url
            if img_url:
                results.append(
                    MaterialResult(
                        source="pexels",
                        url=img_url,
                        preview_url=preview,
                        description=photo.get("alt", keyword),
                        author=photo.get("photographer", ""),
                        width=photo.get("width", 0),
                        height=photo.get("height", 0),
                        media_type="image",
                    )
                )
        return results

    def _search_videos(self, keyword: str, count: int) -> list[MaterialResult]:
        params = urllib.parse.urlencode(
            {
                "query": keyword,
                "per_page": str(min(count, 20)),
                "orientation": "landscape",
                "size": "large",
                "locale": "zh-CN",
            }
        )
        url = f"{self.VIDEO_URL}/search?{params}"
        data = json.loads(urlread(url, timeout=15, headers={"Authorization": self.api_key}, proxy=self.proxy))

        quality_order = {"4k": 5, "hd": 4, "sd": 3, "hls": 2}
        results = []
        for video in data.get("videos", []):
            video_files = video.get("video_files", [])
            best = max(video_files, key=lambda vf: quality_order.get(vf.get("quality", ""), 0), default=None)
            if best:
                preview = (video.get("video_pictures") or [{}])[0].get("picture", "")
                results.append(
                    MaterialResult(
                        source="pexels",
                        url=best.get("link", ""),
                        preview_url=preview,
                        description=video.get("url", "").split("/")[-2] if video.get("url") else keyword,
                        author=video.get("user", {}).get("name", ""),
                        width=best.get("width", 0),
                        height=best.get("height", 0),
                        duration=float(video.get("duration", 0)),
                        media_type="video",
                    )
                )
        return results
