# -*- coding: utf-8 -*-
"""Pixabay API 素材源 — https://pixabay.com/api/docs/"""

import json
import urllib.parse

from videotrans.text_to_video.media.base import MaterialSource, MaterialResult, urlread


class PixabaySource(MaterialSource):
    """Pixabay 免费图库 API — 支持图片和视频搜索"""

    IMAGE_API = "https://pixabay.com/api"
    VIDEO_API = "https://pixabay.com/api/videos"

    def name(self) -> str:
        return "pixabay"

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
                    results = self._search_images(kw, per_kw)
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

    def _search_images(self, keyword: str, count: int) -> list[MaterialResult]:
        params = urllib.parse.urlencode(
            {
                "key": self.api_key,
                "q": keyword,
                "per_page": str(min(count, 20)),
                "image_type": "photo",
                "orientation": "horizontal",
                "safesearch": "true",
                "lang": "zh",
            }
        )
        url = f"{self.IMAGE_API}/?{params}"
        data = json.loads(urlread(url, timeout=15, proxy=self.proxy))

        results = []
        for hit in data.get("hits", []):
            img_url = hit.get("largeImageURL") or hit.get("webformatURL") or ""
            preview = hit.get("webformatURL") or hit.get("previewURL") or img_url
            if img_url:
                results.append(
                    MaterialResult(
                        source="pixabay",
                        url=img_url,
                        preview_url=preview,
                        description=hit.get("tags", keyword),
                        author=hit.get("user", ""),
                        width=hit.get("imageWidth", 0),
                        height=hit.get("imageHeight", 0),
                        media_type="image",
                    )
                )
        return results

    def _search_videos(self, keyword: str, count: int) -> list[MaterialResult]:
        params = urllib.parse.urlencode(
            {
                "key": self.api_key,
                "q": keyword,
                "per_page": str(min(count, 20)),
                "orientation": "horizontal",
                "safesearch": "true",
                "lang": "zh",
            }
        )
        url = f"{self.VIDEO_API}/?{params}"
        data = json.loads(urlread(url, timeout=15, proxy=self.proxy))

        results = []
        for hit in data.get("hits", []):
            videos = hit.get("videos", {})
            for quality in ("large", "medium", "small"):
                v = videos.get(quality, {})
                if v.get("url"):
                    results.append(
                        MaterialResult(
                            source="pixabay",
                            url=v["url"],
                            preview_url=hit.get("userImageURL") or v["url"],
                            description=hit.get("tags", keyword),
                            author=hit.get("user", ""),
                            width=v.get("width", 0),
                            height=v.get("height", 0),
                            duration=float(hit.get("duration", 0)),
                            media_type="video",
                        )
                    )
                    break
        return results
