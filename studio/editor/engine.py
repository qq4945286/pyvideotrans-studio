# -*- coding: utf-8 -*-
"""
剪辑引擎 — 基于 pvt-core Rust CLI 的 QProcess 封装
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional

from PySide6.QtCore import QObject, Signal, QProcess

from . import pvt_bridge
from .models import ClipSegment


@dataclass
class ExportOptions:
    """导出参数"""

    format: str = "mp4"
    resolution: str = "original"
    video_codec: str = "h264"
    quality: str = "medium"
    audio_codec: str = "aac"
    use_gpu: bool = True


class ClipEngine(QObject):
    """异步剪辑引擎"""

    progress_changed = Signal(float)
    status_message = Signal(str)
    operation_finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[QProcess] = None
        self._cancel_flag = False
        self._total_duration = 0.0
        self._export_opts = ExportOptions()

    def set_export_options(self, opts: ExportOptions):
        self._export_opts = opts

    # ── 裁剪 ──

    def trim(self, segment, output_path: str, opts: Optional[ExportOptions] = None):
        """裁剪片段到输出文件"""
        self._cancel_flag = False
        opts = opts or self._export_opts
        self._total_duration = segment.duration
        resolution = _get_effective_resolution(segment, opts)
        cmd = pvt_bridge.cmd_trim(
            input_path=segment.source_path,
            output_path=output_path,
            start=segment.start,
            duration=segment.duration,
            codec=opts.video_codec,
            quality=opts.quality,
            resolution=resolution,
            use_gpu=opts.use_gpu,
            audio_codec=opts.audio_codec,
        )
        self._run_ffmpeg(cmd, f"裁剪: {os.path.basename(segment.source_path)}")

    # ── 分割 ──

    def split(
        self,
        source_path: str,
        split_time: float,
        output_part1: str,
        output_part2: str,
        label: str = "",
        opts: Optional[ExportOptions] = None,
    ):
        self._cancel_flag = False
        opts = opts or self._export_opts
        dur = _probe_duration(source_path)
        self._total_duration = dur
        cmd = pvt_bridge.cmd_split(
            input_path=source_path,
            at=split_time,
            output1=output_part1,
            output2=output_part2,
            codec=opts.video_codec,
            quality=opts.quality,
            use_gpu=opts.use_gpu,
        )
        self._run_ffmpeg(cmd, f"分割: {os.path.basename(source_path)}")

    # ── 合并 ──

    def merge(self, segments: list, output_path: str, opts: Optional[ExportOptions] = None):
        self._cancel_flag = False
        opts = opts or self._export_opts
        file_paths = [s.source_path for s in segments]
        self._total_duration = sum(s.duration for s in segments)
        cmd = pvt_bridge.cmd_merge(
            files=file_paths,
            output_path=output_path,
            reencode=False,
            codec=opts.video_codec,
            quality=opts.quality,
            use_gpu=opts.use_gpu,
        )
        self._run_ffmpeg(cmd, f"合并 {len(segments)} 个片段")

    # ── 带特效合并 ──

    def merge_with_effects(self, segments: list, output_path: str, opts: Optional[ExportOptions] = None):
        """使用 filter_complex 合并片段，支持逐片段特效链"""
        self._cancel_flag = False
        opts = opts or self._export_opts
        self._total_duration = sum(s.duration for s in segments)

        cmd = pvt_bridge.cmd_merge_with_effects(
            segments=segments,
            output_path=output_path,
            codec=opts.video_codec,
            quality=opts.quality,
            use_gpu=opts.use_gpu,
            audio_codec=opts.audio_codec,
        )
        self._run_ffmpeg(cmd, f"特效合并 {len(segments)} 个片段")

    # ── 导出 ──

    def export_clip(self, segment, output_path: str, subtitle_path: str = None, opts: Optional[ExportOptions] = None):
        self._cancel_flag = False
        opts = opts or self._export_opts
        resolution = _get_effective_resolution(segment, opts)
        has_speed = hasattr(segment, "speed") and segment.speed and abs(segment.speed - 1.0) > 0.01
        if has_speed and opts and opts.format in ("gif", "mp3"):
            has_speed = False  # GIF/MP3 不需要变速
        if has_speed:
            self._total_duration = segment.duration / segment.speed
            cmd = pvt_bridge.cmd_speed(
                input_path=segment.source_path,
                output_path=output_path,
                start=segment.start,
                duration=segment.duration,
                speed=segment.speed,
                audio_codec=opts.audio_codec if opts else "aac",
            )
        else:
            self._total_duration = segment.duration
            cmd = pvt_bridge.cmd_trim(
                input_path=segment.source_path,
                output_path=output_path,
                start=segment.start,
                duration=segment.duration,
                codec=opts.video_codec if opts else "h264",
                quality=opts.quality if opts else "medium",
                resolution=resolution,
                use_gpu=opts.use_gpu if opts else True,
                audio_codec=opts.audio_codec if opts else "aac",
                subtitle=subtitle_path,
            )
        self._run_ffmpeg(cmd, f"导出: {os.path.basename(output_path)}")

    # ── GIF 导出 ──

    def export_gif(self, segment, output_path: str, fps: int = 10, scale: int = 480):
        self._cancel_flag = False
        self._total_duration = segment.duration
        cmd = pvt_bridge.cmd_gif(
            input_path=segment.source_path,
            output_path=output_path,
            start=segment.start,
            duration=segment.duration,
            fps=fps,
            scale=scale,
        )
        self._run_ffmpeg(cmd, f"导出 GIF: {os.path.basename(output_path)}")

    # ── MP3 导出 ──

    def export_mp3(self, segment, output_path: str, bitrate: str = "192k"):
        self._cancel_flag = False
        self._total_duration = segment.duration
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{segment.start:.3f}",
            "-i",
            segment.source_path,
            "-t",
            f"{segment.duration:.3f}",
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            output_path,
        ]
        self._run_ffmpeg(cmd, f"导出 MP3: {os.path.basename(output_path)}")

    # ── 取消 ──

    def cancel(self):
        self._cancel_flag = True
        if self._process and self._process.state() == QProcess.ProcessState.Running:
            self._process.kill()
            self._process.waitForFinished(3000)

    # ── 内部 ──

    def _run_ffmpeg(self, args: list, description: str = ""):
        if self._process:
            # 断开旧进程信号，防止 deleteLater 延迟删除期间
            # 旧进程 finished 信号触发 _on_finished 导致段错误
            self._process.readyReadStandardOutput.disconnect(self._parse_progress)
            self._process.finished.disconnect(self._on_finished)
            self._process.deleteLater()
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._parse_progress)
        self._process.finished.connect(self._on_finished)
        self.status_message.emit(description or "处理中...")
        self.progress_changed.emit(0)
        self._process.start(args[0], args[1:])

    def _parse_progress(self):
        if not self._process:
            return
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        for line in data.split("\n"):
            t = pvt_bridge.parse_progress(line)
            if t is not None and self._total_duration > 0:
                pct = min(99.0, (t / self._total_duration) * 100)
                self.progress_changed.emit(pct)
                break

    def _on_finished(self, exit_code, exit_status):
        success = exit_code == 0 and not self._cancel_flag
        if success:
            self.progress_changed.emit(100)
            self.status_message.emit("完成")
        else:
            self.status_message.emit("失败" if not self._cancel_flag else "已取消")
        msg = "" if success else ("已取消" if self._cancel_flag else f"pvt-core 退出码 {exit_code}")
        self.operation_finished.emit(success, msg)


# ── 工具 ──


def ffmpeg_available() -> bool:
    import subprocess

    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _probe_duration(path: str) -> float:
    try:
        info = pvt_bridge.probe(path)
        return info.get("duration_secs", 0.0)
    except Exception:
        return 0


def _get_effective_resolution(segment, opts: ExportOptions) -> Optional[str]:
    """获取素材的有效导出分辨率，优先使用 clip 的 target 分辨率"""
    target_w = getattr(segment, "target_width", 0) or 0
    target_h = getattr(segment, "target_height", 0) or 0
    if target_w > 0 and target_h > 0:
        return f"{target_w}:{target_h}"
    if opts and opts.resolution and opts.resolution != "original":
        return opts.resolution
    return None
