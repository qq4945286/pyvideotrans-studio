# -*- coding: utf-8 -*-
"""ComfyUI 集成 — 通过 REST API 提交 workflow 生成 AI 图片/视频"""

import os
import json
import time
import urllib.request
import urllib.error

from videotrans.text_to_video.media.base import MaterialSource, MaterialResult
from videotrans.configure import config as cfg


class ComfyUISource(MaterialSource):
    """ComfyUI AI 图片/视频生成"""

    def __init__(self, base_url: str = "http://127.0.0.1:8188", workflow_file: str = ""):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.workflow_file = workflow_file
        self._timeout = 300  # 单张图片生成最长等待 5 分钟

    def name(self) -> str:
        return "comfyui"

    def enabled(self) -> bool:
        """检查 ComfyUI 服务是否可达"""
        try:
            url = f"{self.base_url}/system_stats"
            req = urllib.request.Request(url, headers={"User-Agent": "pyvideotrans/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def set_workflow(self, workflow_file: str):
        """设置 workflow JSON 模板文件路径"""
        self.workflow_file = workflow_file

    def search(self, keywords: list[str], count: int = 10, media_type: str = "all") -> list[MaterialResult]:
        """ComfyUI 不是搜索引擎，search() 每次调用触发一次图片生成"""
        if not self.enabled():
            return []

        prompt = ", ".join(keywords)
        results = []
        for i in range(min(count, 4)):  # 最多生成 4 张
            try:
                local_path = self._generate_image(prompt, seed=i * 1000)
                if local_path:
                    results.append(
                        MaterialResult(
                            source="comfyui",
                            url=local_path,
                            preview_url=local_path,
                            description=f"AI 生成: {prompt[:50]}",
                            local_path=local_path,
                        )
                    )
            except Exception as e:
                cfg.logger.warning(f"[ComfyUI] 生成失败: {e}")
                continue
        return results

    def _generate_image(self, prompt: str, seed: int = 0) -> str:
        """提交文生图 workflow 到 ComfyUI，等待完成后返回本地路径"""
        # 加载 workflow 模板
        if not self.workflow_file or not os.path.exists(self.workflow_file):
            workflow = self._default_txt2img_workflow(prompt, seed)
        else:
            with open(self.workflow_file, "r", encoding="utf-8") as f:
                workflow = json.load(f)
            workflow = self._inject_prompt(workflow, prompt, seed)

        # 提交 workflow
        prompt_id = self._queue_prompt(workflow)
        if not prompt_id:
            raise RuntimeError("ComfyUI 提交 workflow 失败")

        # 轮询等待生成完成
        output_path = self._wait_for_result(prompt_id)
        return output_path

    def _queue_prompt(self, workflow: dict) -> str:
        """提交 prompt 到 ComfyUI 队列"""
        url = f"{self.base_url}/prompt"
        body = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "pyvideotrans/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                return data.get("prompt_id", "")
        except urllib.error.URLError as e:
            cfg.logger.error(f"[ComfyUI] 连接失败: {e}")
            return ""

    def _wait_for_result(self, prompt_id: str) -> str:
        """轮询等待 ComfyUI 生成完成，下载结果"""
        start = time.time()
        while time.time() - start < self._timeout:
            try:
                url = f"{self.base_url}/history/{prompt_id}"
                req = urllib.request.Request(url, headers={"User-Agent": "pyvideotrans/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())

                if prompt_id in data:
                    history = data[prompt_id]
                    outputs = history.get("outputs", {})
                    for node_id, node_output in outputs.items():
                        images = node_output.get("images", [])
                        if images:
                            img = images[0]
                            filename = img.get("filename", "")
                            subfolder = img.get("subfolder", "")
                            output_type = img.get("type", "output")
                            return self._download_output(filename, subfolder, output_type)
            except Exception:
                pass
            time.sleep(2)

        raise TimeoutError(f"ComfyUI 生成超时 ({self._timeout}s)")

    def _download_output(self, filename: str, subfolder: str, output_type: str) -> str:
        """从 ComfyUI 下载生成结果"""
        params = f"filename={urllib.request.quote(filename)}"
        if subfolder:
            params += f"&subfolder={subfolder}"
        if output_type:
            params += f"&type={output_type}"

        url = f"{self.base_url}/view?{params}"
        save_dir = os.path.join(cfg.TEMP_DIR, "comfyui_outputs")
        os.makedirs(save_dir, exist_ok=True)
        local_path = os.path.join(save_dir, filename)

        req = urllib.request.Request(url, headers={"User-Agent": "pyvideotrans/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(local_path, "wb") as f:
                f.write(resp.read())
        return local_path

    def _default_txt2img_workflow(self, prompt: str, seed: int) -> dict:
        """最简文生图 workflow（需用户实际 ComfyUI 中有对应节点）"""
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": 1920, "height": 1080, "batch_size": 1},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": f"{prompt}, cinematic, 4K, high quality, photorealistic", "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "blurry, low quality, distorted, watermark, text", "clip": ["4", 1]},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "pyvideotrans", "images": ["8", 0]},
            },
        }

    def _inject_prompt(self, workflow: dict, prompt: str, seed: int) -> dict:
        """向现有 workflow 注入 prompt 和 seed"""
        import copy

        wf = copy.deepcopy(workflow)
        for node_id, node in wf.items():
            if node.get("class_type") == "KSampler":
                node["inputs"]["seed"] = seed
            if node.get("class_type") == "CLIPTextEncode":
                text = node["inputs"].get("text", "")
                if "blurry" not in text and "low quality" not in text:
                    node["inputs"]["text"] = f"{prompt}, cinematic, 4K, high quality, photorealistic"
        return wf
