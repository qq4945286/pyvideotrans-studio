# Moonshine-voice STT
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Union

import numpy as np
from pydub import AudioSegment

from videotrans.configure.config import logger, ROOT_DIR
from videotrans.recognition._base import BaseRecogn
from videotrans.util import tools

# Moonshine 模型缓存路径：项目 models/ 目录
_MOONSHINE_CACHE = Path(ROOT_DIR) / "models"
os.environ.setdefault("MOONSHINE_VOICE_CACHE", str(_MOONSHINE_CACHE))

MOONSHINE_SUPPORTED_LANGS = {"zh", "en", "ja", "ko", "es", "ar", "vi", "uk"}


@dataclass
class MoonshineRecogn(BaseRecogn):
    model_path: str = ""
    model_arch: int = -1

    def __post_init__(self):
        super().__post_init__()
        lang = (self.detect_language or "en")[:2].lower()
        if lang not in MOONSHINE_SUPPORTED_LANGS:
            raise RuntimeError(
                f"Moonshine-voice 不支持语言 '{lang}'，支持: {', '.join(sorted(MOONSHINE_SUPPORTED_LANGS))}"
            )
        self._moonshine_lang = lang

    def _download(self):
        try:
            from moonshine_voice import get_model_for_language
            from moonshine_voice.moonshine_api import ModelArch
        except ImportError:
            raise RuntimeError("Moonshine-voice 未安装，请执行: pip install moonshine-voice")

        # 模型显示名 → ModelArch 映射
        _arch_map = {
            "Tiny": ModelArch.TINY,
            "Base": ModelArch.BASE,
            "Tiny Streaming": ModelArch.TINY_STREAMING,
            "Base Streaming": ModelArch.BASE_STREAMING,
            "Small Streaming": ModelArch.SMALL_STREAMING,
            "Medium Streaming": ModelArch.MEDIUM_STREAMING,
        }
        # self.model_name = "Base(中文)"，去括号后缀匹配
        arch = _arch_map.get(self.model_name.split("(")[0], ModelArch.TINY)

        logger.info(f"[Moonshine] _download() start, lang={self._moonshine_lang}, model_name={self.model_name!r}")
        self._signal(text=f"下载 Moonshine {self._moonshine_lang} 模型...")
        try:
            path, ret_arch = get_model_for_language(
                wanted_language=self._moonshine_lang,
                wanted_model_arch=arch,
            )
            self.model_path = str(path)
            self.model_arch = int(ret_arch)
            logger.info(f"Moonshine 模型就绪: {self.model_path}, arch={self.model_arch}")
        except ValueError as e:
            # 所选架构该语言不支持（如中文选 Streaming）
            raise RuntimeError(f"Moonshine 语言 '{self._moonshine_lang}' 不支持 '{self.model_name}'，请选其他模型")
        except Exception as e:
            raise RuntimeError(f"Moonshine 模型下载失败: {e}")

    def _exec(self) -> Union[List[Dict], None]:
        if self._exit():
            return

        from moonshine_voice.transcriber import Transcriber

        self._signal(text="加载音频...")
        audio = AudioSegment.from_wav(self.audio_file)
        audio = audio.set_frame_rate(16000).set_channels(1)
        samples = np.array(audio.get_array_of_samples()).astype(np.float32) / 32768.0

        self._signal(text=f"加载 Moonshine 模型({self._moonshine_lang})...")
        from moonshine_voice.moonshine_api import ModelArch

        arch = ModelArch(self.model_arch)
        transcriber = Transcriber(model_path=self.model_path, model_arch=arch)

        self._signal(text="识别中...")
        t0 = time.time()
        transcript = transcriber.transcribe_without_streaming(
            samples.tolist(),
            sample_rate=16000,
        )
        logger.info(f"Moonshine 识别完成: {time.time() - t0:.2f}s")

        raws = []
        for line in transcript.lines:
            text = line.text.strip()
            if not text:
                continue
            start_ms = int(line.start_time * 1000)
            end_ms = int((line.start_time + line.duration) * 1000)
            raws.append(
                {
                    "line": len(raws) + 1,
                    "start_time": start_ms,
                    "end_time": end_ms,
                    "text": text,
                    "startraw": tools.ms_to_time_string(ms=start_ms),
                    "endraw": tools.ms_to_time_string(ms=end_ms),
                    "time": f"{tools.ms_to_time_string(ms=start_ms)} --> {tools.ms_to_time_string(ms=end_ms)}",
                }
            )

        return raws
