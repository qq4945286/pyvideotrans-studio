# -*- coding: utf-8 -*-
"""
文字生视频管线编排引擎 — 复用现有 TTS/FFmpeg/配置
"""

import os
import json
import time
import tempfile
import shutil
import threading
from pathlib import Path
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from videotrans.configure import config as cfg
from videotrans.configure.config import ROOT_DIR, TEMP_DIR, logger
from videotrans.util.help_ffmpeg import runffmpeg
from videotrans.text_to_video.llm_service import LLMStoryboardService, StoryboardShot
from videotrans.text_to_video.media import create_sources, MaterialSource


@dataclass
class TextToVideoConfig:
    """文字生视频项目配置"""

    input_text: str = ""
    shots: list = field(default_factory=list)
    # 素材源
    use_local: bool = True
    use_pexels: bool = False
    use_pixabay: bool = False
    use_comfyui: bool = False
    local_dirs: list[str] = field(default_factory=list)
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_workflow: str = ""
    # TTS
    tts_engine: str = "edgetts"  # "edgetts" | "cosyvoice"
    tts_voice: str = "zh-CN-YunjianNeural"
    tts_speed: float = 1.2
    # 输出
    orientation: str = "landscape"
    resolution: tuple = (1920, 1080)
    fps: int = 30
    bgm_enabled: bool = False
    bgm_path: str = ""
    bgm_volume: float = 0.2
    subtitle_enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "input_text": self.input_text,
            "shots": [s.to_dict() for s in self.shots],
            "use_local": self.use_local,
            "use_pexels": self.use_pexels,
            "use_pixabay": self.use_pixabay,
            "use_comfyui": self.use_comfyui,
            "local_dirs": self.local_dirs,
            "pexels_api_key": self.pexels_api_key,
            "pixabay_api_key": self.pixabay_api_key,
            "comfyui_url": self.comfyui_url,
            "comfyui_workflow": self.comfyui_workflow,
            "tts_engine": self.tts_engine,
            "tts_voice": self.tts_voice,
            "tts_speed": self.tts_speed,
            "orientation": self.orientation,
            "resolution": list(self.resolution),
            "fps": self.fps,
            "bgm_enabled": self.bgm_enabled,
            "bgm_path": self.bgm_path,
            "bgm_volume": self.bgm_volume,
            "subtitle_enabled": self.subtitle_enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TextToVideoConfig":
        return cls(
            input_text=d.get("input_text", ""),
            shots=[StoryboardShot.from_dict(s) for s in d.get("shots", [])],
            use_local=d.get("use_local", True),
            use_pexels=d.get("use_pexels", False),
            use_pixabay=d.get("use_pixabay", False),
            use_comfyui=d.get("use_comfyui", False),
            local_dirs=d.get("local_dirs", []),
            pexels_api_key=d.get("pexels_api_key", ""),
            pixabay_api_key=d.get("pixabay_api_key", ""),
            comfyui_url=d.get("comfyui_url", "http://127.0.0.1:8188"),
            comfyui_workflow=d.get("comfyui_workflow", ""),
            tts_engine=d.get("tts_engine", "edgetts"),
            tts_voice=d.get("tts_voice", "zh-CN-YunjianNeural"),
            tts_speed=d.get("tts_speed", 1.2),
            orientation=d.get("orientation", "landscape"),
            resolution=tuple(d.get("resolution", (1920, 1080))),
            fps=d.get("fps", 30),
            bgm_enabled=d.get("bgm_enabled", False),
            bgm_path=d.get("bgm_path", ""),
            bgm_volume=d.get("bgm_volume", 0.2),
            subtitle_enabled=d.get("subtitle_enabled", True),
        )


class TextToVideoEngine(QObject):
    """文字生视频管线编排引擎 — 协调 LLM/TTS/素材/合成"""

    # 信号
    progress = Signal(str, int)  # (步骤描述, 百分比 0-100)
    shots_ready = Signal(list)  # 分镜列表就绪
    shot_material_ready = Signal(int)  # 某个分镜素材就绪 (index)
    narration_ready = Signal(str)  # 旁白音频就绪 (path)
    finished = Signal(str)  # 输出视频路径
    error = Signal(str)  # 错误信息

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = TextToVideoConfig()
        self._llm = LLMStoryboardService()
        self._work_dir: str = ""
        self._cancel_flag = threading.Event()

    # ── 步骤 1: 生成分镜 ──
    def generate_storyboard(self, text: str):
        """在后台线程生成分镜脚本"""
        self._cancel_flag.clear()
        self.progress.emit("正在分析文字，生成分镜脚本...", 5)

        def _run():
            try:
                shots, llm_msg = self._llm.generate_storyboard(text)
                self._config.input_text = text
                self._config.shots = shots
                self.shots_ready.emit(shots)
                if llm_msg:
                    self.progress.emit(f"分镜脚本已生成（{llm_msg}），共 {len(shots)} 个镜头", 20)
                else:
                    self.progress.emit(f"分镜脚本生成完成，共 {len(shots)} 个镜头", 20)
            except Exception as e:
                self.error.emit(f"分镜生成失败: {e}")

        threading.Thread(target=_run, daemon=True).start()

    # ── 步骤 2: 获取素材 ──
    def acquire_materials(self, shots: list[StoryboardShot]):
        """为每个分镜获取素材（按优先级: 本地 → 在线 → ComfyUI）"""
        self._cancel_flag.clear()
        sources = self._get_sources()
        total = len(shots)

        # 检查素材源可用性
        enabled = [s.name() for s in sources if s.enabled()]
        if not enabled:
            self.error.emit(
                "没有可用的素材源。请检查：\n"
                "1. 是否在设置中填写了 Pexels / Pixabay API Key\n"
                "2. 是否勾选了对应的在线素材源\n"
                "3. 或者勾选「本地素材」并指定素材文件夹"
            )
            return

        offline_sources = [s for s in sources if s.name() in ("pexels", "pixabay")]
        if offline_sources:
            self.progress.emit(f"在线素材源需代理访问，超时 15 秒/请求...", 22)

        def _run():
            failed_sources: set[str] = set()
            for i, shot in enumerate(shots):
                if self._cancel_flag.is_set():
                    self.progress.emit("素材获取已取消", 0)
                    return
                pct = 20 + int((i / total) * 40)
                keywords_preview = ", ".join(shot.keywords[:3])
                self.progress.emit(f"搜索素材 ({i + 1}/{total}): {keywords_preview}...", pct)

                shot.materials = []  # 清空旧素材列表
                for src in sources:
                    src_name = src.name()
                    if src_name in failed_sources:
                        continue
                    if self._cancel_flag.is_set():
                        return
                    try:
                        results = src.search(shot.keywords, count=5)
                        if results:
                            dl_dir = os.path.join(self._ensure_work_dir(), "materials")
                            # 下载所有搜索结果
                            for ri, r in enumerate(results):
                                local_path = src.download(r, dl_dir)
                                if local_path:
                                    r.local_path = local_path
                            # 存储全部素材到 shot.materials
                            shot.materials = [
                                {
                                    "source": r.source,
                                    "url": r.url,
                                    "preview_url": r.preview_url,
                                    "description": r.description,
                                    "author": r.author,
                                    "width": r.width,
                                    "height": r.height,
                                    "duration": r.duration,
                                    "media_type": r.media_type,
                                    "local_path": r.local_path,
                                    "effects": [],
                                }
                                for r in results
                                if r.local_path
                            ]
                            # 首选素材（第一个下载成功的）
                            if shot.materials:
                                shot.material_source = src_name
                                shot.material_path = shot.materials[0]["local_path"]
                                self.shot_material_ready.emit(shot.index)
                                break
                    except Exception as e:
                        err = str(e)[:80]
                        logger.warning(f"[文字生视频] 素材源 {src_name} 搜索失败: {err}")
                        failed_sources.add(src_name)
                        self.progress.emit(f"素材源 {src_name} 不可用，已跳过后续查询", pct)
                        continue
                else:
                    shot.material_source = "none"
                    shot.material_path = ""
                    shot.materials = []
                    self.shot_material_ready.emit(shot.index)

            # 统计结果
            found = sum(1 for s in shots if s.material_path)
            self._config.shots = shots
            self.progress.emit(f"素材获取完成: {found}/{total} 个镜头有素材", 60)

        threading.Thread(target=_run, daemon=True).start()

    def _get_sources(self) -> list:
        return create_sources(
            {
                "use_local": self._config.use_local,
                "local_dirs": self._config.local_dirs,
                "use_pexels": self._config.use_pexels,
                "pexels_api_key": self._config.pexels_api_key,
                "use_pixabay": self._config.use_pixabay,
                "pixabay_api_key": self._config.pixabay_api_key,
                "use_comfyui": self._config.use_comfyui,
                "comfyui_url": self._config.comfyui_url,
                "comfyui_workflow": self._config.comfyui_workflow,
            }
        )

    # ── 步骤 3: TTS 旁白 ──
    def generate_narration(
        self, text: str, voice: str = "zh-CN-YunjianNeural", speed: float = 1.2, tts_engine: str = "edgetts"
    ):
        """生成旁白配音 — 支持 Edge-TTS（在线）和 CosyVoice（本地）"""
        self._cancel_flag.clear()
        work_dir = self._ensure_work_dir()

        if tts_engine == "cosyvoice":
            self._generate_narration_cosyvoice(text, voice, speed, work_dir)
        else:
            self._generate_narration_edgetts(text, voice, speed, work_dir)

    def _generate_narration_edgetts(self, text: str, voice: str, speed: float, work_dir: str):
        """Edge-TTS 在线配音"""
        self.progress.emit("正在生成配音旁白 (Edge-TTS)...", 65)

        def _run():
            try:
                import asyncio
                from edge_tts import Communicate

                audio_path = os.path.join(work_dir, "narration.mp3")
                srt_path = os.path.join(work_dir, "narration.srt")

                async def _tts():
                    import edge_tts

                    tts_proxy = (
                        cfg.params.get("t2v_llm_proxy", "")
                        or cfg.app_cfg.proxy
                        or os.environ.get("HTTPS_PROXY", "")
                        or None
                    )
                    communicate = Communicate(
                        text=text,
                        voice=voice,
                        rate=f"{int(round((speed - 1) * 100)):+d}%",
                        proxy=tts_proxy,
                    )
                    submaker = edge_tts.SubMaker()
                    with open(audio_path, "wb") as f:
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                f.write(chunk["data"])
                            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                                submaker.feed(chunk)
                    try:
                        with open(srt_path, "w", encoding="utf-8") as sf:
                            sf.write(submaker.get_srt())
                    except Exception:
                        pass

                asyncio.run(_tts())

                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                    self.narration_ready.emit(audio_path)
                    self.progress.emit("配音旁白生成完成", 75)
                else:
                    self.error.emit("配音生成失败：未生成有效音频文件")
            except Exception as e:
                self.error.emit(f"Edge-TTS 配音失败: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _generate_narration_cosyvoice(self, text: str, voice: str, speed: float, work_dir: str):
        """CosyVoice 本地配音 — 通过 Gradio API 调用"""
        self.progress.emit("正在生成配音旁白 (CosyVoice 本地)...", 65)

        def _run():
            try:
                from pathlib import Path
                from gradio_client import Client, handle_file

                cosy_url = cfg.params.get("cosyvoice_url", "").strip().rstrip("/")
                if not cosy_url:
                    self.error.emit("CosyVoice 服务地址未配置，请在「文字生视频设置 → 配音与输出」中填写")
                    return

                audio_path = os.path.join(work_dir, "narration.wav")
                audio_mp3 = os.path.join(work_dir, "narration.mp3")

                # 获取参考音频
                rolelist = self._get_cosyvoice_roles()
                ref_wav = ""
                ref_text = ""
                if voice == "clone":
                    # 克隆模式：使用用户指定的参考音频
                    ref_wav = cfg.params.get("cosyvoice_clone_wav", "")
                    ref_text = cfg.params.get("cosyvoice_clone_text", "")
                    if not ref_wav or not Path(ref_wav).exists():
                        self.error.emit("CosyVoice 克隆模式需要指定参考音频文件")
                        return
                elif voice in rolelist:
                    info = rolelist[voice]
                    ref_wav = info.get("reference_audio", "")
                    ref_text = info.get("reference_text", "")
                else:
                    # 使用默认角色（第一个非 No/clone）
                    for k, v in rolelist.items():
                        if k not in ("No", "clone"):
                            ref_wav = v.get("reference_audio", "")
                            ref_text = v.get("reference_text", "")
                            break

                if not ref_wav or not Path(ref_wav).exists():
                    self.error.emit(f"CosyVoice 参考音频不存在: {ref_wav}")
                    return

                self.progress.emit(f"连接 CosyVoice 服务 {cosy_url}...", 67)
                client = Client(cosy_url, ssl_verify=False)

                # 构建提示词
                instruct_text = cfg.params.get("cosyvoice_instruct_text", "")
                prompt_text = ref_text
                if instruct_text:
                    prompt_text = f"You are a helpful assistant.{instruct_text}<|endofprompt|>{prompt_text}"

                self.progress.emit("CosyVoice 合成中...", 70)
                result = client.predict(
                    tts_text=text,
                    mode_checkbox_group="3s极速复刻",
                    prompt_wav_upload=handle_file(ref_wav),
                    prompt_wav_record=handle_file(ref_wav),
                    prompt_text=prompt_text,
                    instruct_text=instruct_text,
                    seed=0,
                    stream=False,
                    speed=speed,
                    api_name="/generate_audio",
                )

                wav_file = result[0] if isinstance(result, (list, tuple)) and result else result
                if isinstance(wav_file, dict) and "value" in wav_file:
                    wav_file = wav_file["value"]

                if isinstance(wav_file, str) and Path(wav_file).is_file():
                    # 转换为 mp3
                    import shutil

                    if wav_file.endswith(".wav"):
                        shutil.copy2(wav_file, audio_path)
                    else:
                        shutil.copy2(wav_file, audio_path)

                    # 用 ffmpeg 转 mp3
                    try:
                        from videotrans.util.help_ffmpeg import runffmpeg

                        runffmpeg(
                            [
                                "-i",
                                audio_path,
                                "-c:a",
                                "libmp3lame",
                                "-b:a",
                                "128k",
                                "-y",
                                audio_mp3,
                            ],
                            force_cpu=True,
                        )
                    except Exception:
                        # ffmpeg 转换失败，尝试直接用 wav
                        import shutil

                        shutil.copy2(audio_path, audio_mp3)

                    if os.path.exists(audio_mp3) and os.path.getsize(audio_mp3) > 0:
                        self.narration_ready.emit(audio_mp3)
                        self.progress.emit("CosyVoice 配音生成完成", 75)
                    elif os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                        self.narration_ready.emit(audio_path)
                        self.progress.emit("CosyVoice 配音生成完成", 75)
                    else:
                        self.error.emit("CosyVoice 配音失败：未生成有效音频文件")
                else:
                    self.error.emit(f"CosyVoice 返回异常: {str(result)[:200]}")
            except Exception as e:
                self.error.emit(f"CosyVoice 配音失败: {e}")

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _get_cosyvoice_roles() -> dict:
        """获取 CosyVoice 音色列表"""
        from videotrans.configure import config as _cfg

        rolelist = {"No": "No", "clone": "clone"}
        for it in _cfg.params.get("cosyvoice_role", "").strip().split("\n"):
            tmp = it.strip().split("#")
            if len(tmp) != 2:
                continue
            rolelist[tmp[0]] = {"reference_audio": tmp[0], "reference_text": tmp[1]}
        return rolelist

    # ── 步骤 4: 合成视频 ──
    def compose_video(self, config: TextToVideoConfig):
        """FFmpeg 合成最终视频"""
        self._cancel_flag.clear()
        self._config = config
        work_dir = self._ensure_work_dir()
        audio_path = os.path.join(work_dir, "narration.mp3")
        output_path = os.path.join(work_dir, "output.mp4")

        w, h = config.resolution
        fps = config.fps

        self.progress.emit("正在合成视频...", 80)

        def _run():
            try:
                segment_files = []
                for shot in config.shots:
                    if self._cancel_flag.is_set():
                        return
                    seg_path = os.path.join(work_dir, f"seg_{shot.index:03d}.mp4")
                    self._render_shot_segment(shot, seg_path, w, h, fps)
                    if os.path.exists(seg_path):
                        segment_files.append(seg_path)

                if not segment_files:
                    self.error.emit("没有可合成的素材片段")
                    return

                self.progress.emit("正在拼接片段...", 90)

                concat_file = os.path.join(work_dir, "concat.txt")
                with open(concat_file, "w", encoding="utf-8") as f:
                    for seg in segment_files:
                        f.write(f"file '{seg}'\n")

                vf_parts = [
                    f"fps={fps}",
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease",
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
                    "format=yuv420p",
                ]

                # 输入部分
                cmd = ["-f", "concat", "-safe", "0", "-i", concat_file]

                has_audio = os.path.exists(audio_path)
                has_bgm = config.bgm_enabled and config.bgm_path and os.path.exists(config.bgm_path)

                if has_audio:
                    cmd += ["-i", audio_path]
                if has_bgm:
                    cmd += ["-i", config.bgm_path]

                # 输出选项（必须在所有 -i 之后）
                cmd += [
                    "-c:v",
                    self._detect_encoder(),
                    "-preset",
                    "fast",
                    "-vf",
                    ",".join(vf_parts),
                    "-pix_fmt",
                    "yuv420p",
                ]

                if has_bgm and has_audio:
                    cmd += [
                        "-filter_complex",
                        f"[1:a]volume=1.0[a1];[2:a]volume={config.bgm_volume}[a2];[a1][a2]amix=inputs=2:duration=first[aout]",
                        "-map",
                        "0:v",
                        "-map",
                        "[aout]",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "128k",
                    ]
                elif has_audio:
                    cmd += [
                        "-map",
                        "0:v",
                        "-map",
                        "1:a",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "128k",
                        "-shortest",
                    ]

                cmd += ["-movflags", "+faststart", "-y", output_path]
                runffmpeg(cmd, force_cpu=False)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    self.progress.emit("视频合成完成", 100)
                    self.finished.emit(output_path)
                else:
                    self.error.emit("视频合成失败：未生成有效输出文件")
            except Exception as e:
                self.error.emit(f"视频合成失败: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _render_shot_segment(self, shot: StoryboardShot, output: str, w: int, h: int, fps: int):
        """渲染单个分镜片段 — 图片/视频/纯色背景"""
        duration = shot.duration
        fade_in, fade_out = 0.3, 0.3
        base_vf = (
            f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
        )
        # 素材特效（首选素材的 effects）
        fx_chain = self._build_material_fx_chain(shot)
        if fx_chain:
            base_vf += f",{fx_chain}"
        geq_fade = self._build_fade_geq(duration, fade_in, fade_out)
        vf_chain = f"{base_vf},{geq_fade}"
        # 镜头字幕（固定 Y 坐标，所有镜头位置一致）
        safe_text = self._escape_drawtext(shot.text)
        sub_dt = (
            f"drawtext=text='{safe_text}':"
            f"fontcolor=white@0.95:fontsize=26:"
            f"bordercolor=black@0.8:borderw=4:"
            f"shadowcolor=black@0.7:shadowx=2:shadowy=2:"
            f"line_spacing=6:"
            f"x=(w-text_w)/2:y=h-line_h-40"
        )
        vf_chain += f",{sub_dt}"
        enc = self._detect_encoder()

        if shot.material_path and os.path.exists(shot.material_path):
            ext = os.path.splitext(shot.material_path)[1].lower()
            if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
                runffmpeg(
                    [
                        "-i",
                        shot.material_path,
                        "-t",
                        str(duration),
                        "-vf",
                        vf_chain,
                        "-c:v",
                        enc,
                        "-preset",
                        "fast",
                        "-pix_fmt",
                        "yuv420p",
                        "-an",
                        "-y",
                        output,
                    ],
                    force_cpu=False,
                )
            else:
                runffmpeg(
                    [
                        "-loop",
                        "1",
                        "-i",
                        shot.material_path,
                        "-t",
                        str(duration),
                        "-vf",
                        vf_chain,
                        "-c:v",
                        enc,
                        "-preset",
                        "fast",
                        "-pix_fmt",
                        "yuv420p",
                        "-an",
                        "-y",
                        output,
                    ],
                    force_cpu=False,
                )
        else:
            color = "0x1a1a2e"
            text_vf = (
                f"fps={fps},drawtext=text='{safe_text}':fontcolor=white:fontsize=48:"
                f"x=(w-text_w)/2:y=(h-text_h)/2,scale={w}:{h},format=yuv420p,{geq_fade}"
            )
            runffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={color}:s={w}x{h}:d={duration}:r={fps}",
                    "-vf",
                    text_vf,
                    "-c:v",
                    enc,
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    "-y",
                    output,
                ],
                force_cpu=False,
            )

    @staticmethod
    def _build_fade_geq(duration: float, fade_in: float = 0.3, fade_out: float = 0.3) -> str:
        """用 geq 滤镜实现淡入淡出 — 替代 ffmpeg 6.1.1 损坏的 fade 滤镜"""
        fi = fade_in
        fo = fade_out
        d = duration
        # 亮度衰减因子 F: 0→1 淡入, 1 正常, 1→0 淡出
        f_expr = f"if(lt(T,{fi}),T/{fi},if(gt(T,{d - fo}),({d}-T)/{fo},1))"
        return (
            f"geq=lum='p(X,Y)*{f_expr}':"
            f"cb='128*(1-{f_expr})+p(X,Y)*{f_expr}':"
            f"cr='128*(1-{f_expr})+p(X,Y)*{f_expr}'"
        )

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        """转义 ffmpeg drawtext 滤镜中的特殊字符
        drawtext 用 : 分隔选项，用 \\ 做转义符。
        文本被单引号包裹：text='...'，所以内部：
          \\ → \\\\
          :  → \\:
          '  → \\'
        """
        text = text.replace("\\", "\\\\")
        text = text.replace(":", "\\:")
        text = text.replace("'", "\\'")
        return text

    @staticmethod
    def _build_material_fx_chain(shot: StoryboardShot) -> str:
        """从素材特效构建 ffmpeg 滤镜链"""
        from studio.editor.effects import build_ffmpeg_filter_chain
        from studio.editor.models import Effect

        effects = []
        # 镜头级特效
        for e in getattr(shot, "effects", []) or []:
            if isinstance(e, dict):
                effects.append(
                    Effect(effect_id=e.get("effect_id", ""), params=e.get("params", {}), enabled=e.get("enabled", True))
                )
            else:
                effects.append(e)
        # 首选素材特效
        if shot.materials:
            mat = shot.materials[0]
            for e in mat.get("effects", []) or []:
                if isinstance(e, dict):
                    effects.append(
                        Effect(
                            effect_id=e.get("effect_id", ""), params=e.get("params", {}), enabled=e.get("enabled", True)
                        )
                    )
                else:
                    effects.append(e)
        if not effects:
            return ""
        return build_ffmpeg_filter_chain(effects)

    def _detect_encoder(self) -> str:
        """复用现有 GPU 检测逻辑"""
        try:
            from studio.editor.gpu_accel import detect_gpu

            gpu_type = detect_gpu()
            enc_map = {"nvidia": "h264_nvenc", "amd": "h264_vaapi", "intel": "h264_qsv"}
            return enc_map.get(gpu_type, "libx264")
        except Exception:
            return "libx264"

    def _ensure_work_dir(self) -> str:
        if not self._work_dir:
            os.makedirs(TEMP_DIR, exist_ok=True)
            self._work_dir = tempfile.mkdtemp(prefix="t2v_", dir=TEMP_DIR)
        return self._work_dir

    def cancel(self):
        self._cancel_flag.set()

    def cleanup(self):
        if self._work_dir and os.path.isdir(self._work_dir):
            shutil.rmtree(self._work_dir, ignore_errors=True)
            self._work_dir = ""
