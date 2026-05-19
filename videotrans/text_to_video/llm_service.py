# -*- coding: utf-8 -*-
"""
LLM 分镜分析服务 — 复用现有 OpenAI 兼容 API 调用模式
"""

import os
import json
import re
from dataclasses import dataclass, field

import httpx
from openai import OpenAI

from videotrans.configure import config as cfg


@dataclass
class StoryboardShot:
    """分镜镜头数据"""

    index: int
    text: str  # 镜头描述文字
    duration: float  # 时长 (秒)
    keywords: list[str] = field(default_factory=list)
    ai_prompt: str = ""  # 给 ComfyUI 的图片提示词
    material_source: str = ""  # "local" | "pexels" | "pixabay" | "comfyui" | "none"
    material_path: str = ""  # 本地素材文件路径（首选素材）
    materials: list = field(default_factory=list)  # list[dict]，全部搜索到的素材（含 effects）
    effects: list = field(default_factory=list)  # list[dict]，镜头级特效（应用于整个镜头）

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "text": self.text,
            "duration": self.duration,
            "keywords": self.keywords,
            "ai_prompt": self.ai_prompt,
            "material_source": self.material_source,
            "material_path": self.material_path,
            "materials": self.materials,
            "effects": self.effects,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StoryboardShot":
        return cls(
            index=d.get("index", 0),
            text=d.get("text", ""),
            duration=d.get("duration", 3.0),
            keywords=d.get("keywords", []),
            ai_prompt=d.get("ai_prompt", ""),
            material_source=d.get("material_source", ""),
            material_path=d.get("material_path", ""),
            materials=d.get("materials", []),
            effects=d.get("effects", []),
        )


# LLM 分镜分析 System Prompt
STORYBOARD_SYSTEM_PROMPT = """你是一个专业的视频分镜脚本策划师。根据用户输入的文字内容，生成详细的分镜脚本。

## 规则
1. 将用户文字拆分为 3-8 个镜头
2. 每个镜头 2-5 秒
3. 为每个镜头生成 2-4 个中文搜索关键词
4. 为每个镜头生成 1 个英文 AI 图片提示词 (用于 Stable Diffusion)
5. 提示词风格：cinematic, 4K, high quality, photorealistic

## 输出格式 (严格 JSON)
{
  "shots": [
    {
      "text": "镜头描述(中文)",
      "duration": 3.0,
      "keywords": ["关键词1", "关键词2"],
      "ai_prompt": "English prompt for SD image generation"
    }
  ]
}

只输出 JSON，不要包含任何其他文字。"""


class LLMStoryboardService:
    """LLM 分镜分析服务 — 复用现有 OpenAI 兼容 API"""

    def __init__(self):
        self._params = cfg.AppParams()

    def _get_llm_client(self) -> OpenAI:
        """LLM 客户端 — 优先使用 T2V 专用配置，回退到全局 chatgpt 配置"""
        # T2V 专用配置优先
        api_key = cfg.params.get("t2v_llm_key", "") or self._params.get("chatgpt_key", "")
        api_url = cfg.params.get("t2v_llm_api", "") or self._params.get("chatgpt_api", "")
        if not api_url:
            api_url = "https://api.deepseek.com/v1"
        if not api_url.startswith("http"):
            api_url = "https://" + api_url

        # 代理优先级：T2V 专用 > 全局 > 环境变量
        proxy = cfg.params.get("t2v_llm_proxy", "") or cfg.app_cfg.proxy or os.environ.get("HTTPS_PROXY", "") or None
        if not proxy:
            proxy = None

        http_client_kwargs = {"timeout": 120}
        if proxy:
            http_client_kwargs["proxy"] = proxy

        return OpenAI(
            api_key=api_key,
            base_url=api_url,
            http_client=httpx.Client(**http_client_kwargs),
        )

    def generate_storyboard(self, text: str) -> tuple[list[StoryboardShot], str]:
        """输入文字，返回 (分镜列表, 状态消息)。状态消息为空表示 LLM 成功。"""
        if not text.strip():
            raise ValueError("输入文字不能为空")

        try:
            shots = self._llm_generate(text)
            return shots, ""
        except Exception as e:
            err_msg = str(e)
            if "403" in err_msg or "unsupported_country" in err_msg:
                hint = (
                    "API 不可用（地域限制），已改用简单拆分。"
                    "解决方法：在「文字生视频设置 → LLM API」中切换为 DeepSeek"
                    "（api.deepseek.com，国内可直接访问），或配置代理地址"
                )
            elif "401" in err_msg:
                hint = "API Key 无效，请在「文字生视频设置 → LLM API」中检查 Key 配置"
            elif "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                hint = "API 连接超时，请检查网络或配置代理"
            else:
                hint = f"LLM 请求失败: {err_msg[:120]}"
            cfg.logger.warning(f"[文字生视频] {hint}")
            return self._fallback_split(text), hint

    def _llm_generate(self, text: str) -> list[StoryboardShot]:
        """通过 LLM 生成分镜脚本"""
        client = self._get_llm_client()
        model = cfg.params.get("t2v_llm_model", "") or self._params.get("chatgpt_model", "") or "deepseek-chat"

        response = client.chat.completions.create(
            model=model,
            timeout=120,
            temperature=0.7,
            max_completion_tokens=4096,
            messages=[
                {"role": "system", "content": STORYBOARD_SYSTEM_PROMPT},
                {"role": "user", "content": f"请为以下内容生成分镜脚本：\n\n{text}"},
            ],
        )

        content = response.choices[0].message.content.strip()
        return self._parse_response(content)

    def _parse_response(self, content: str) -> list[StoryboardShot]:
        """解析 LLM 返回的 JSON"""
        # 尝试提取 JSON 块
        json_match = re.search(r'\{[\s\S]*"shots"[\s\S]*\}', content)
        if json_match:
            content = json_match.group(0)

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 尝试修复常见问题: 尾部逗号、单引号等
            content = re.sub(r",\s*}", "}", content)
            content = re.sub(r",\s*]", "]", content)
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                raise RuntimeError(f"无法解析 LLM 返回的 JSON: {content[:200]}")

        shots = []
        for i, shot_data in enumerate(data.get("shots", [])):
            shots.append(
                StoryboardShot(
                    index=i + 1,
                    text=shot_data.get("text", f"镜头{i + 1}"),
                    duration=max(1.0, min(10.0, float(shot_data.get("duration", 3.0)))),
                    keywords=shot_data.get("keywords", []),
                    ai_prompt=shot_data.get("ai_prompt", ""),
                )
            )

        if not shots:
            raise RuntimeError("LLM 返回的分镜列表为空")

        return shots

    def _fallback_split(self, text: str) -> list[StoryboardShot]:
        """LLM 不可用时：按句号/换行简单拆分"""
        # 按句号、问号、感叹号、换行拆分
        sentences = re.split(r"[。！？\n]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            sentences = [text.strip()]

        shots = []
        for i, sentence in enumerate(sentences):
            # 估算时长: 中文约 3 字/秒
            est_duration = max(2.0, min(8.0, len(sentence) / 3.0))
            shots.append(
                StoryboardShot(
                    index=i + 1,
                    text=sentence,
                    duration=round(est_duration, 1),
                    keywords=[sentence[:6]],
                    ai_prompt=sentence,
                )
            )
        return shots
