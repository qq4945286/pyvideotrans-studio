# 执行单个视频翻译任务时 暂停等待
import json
import traceback
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydub import AudioSegment
from PySide6.QtCore import QThread, Signal, QObject

from videotrans.configure._except import get_msg_from_except
from videotrans.configure.config import tr, params, settings, app_cfg, logger
from videotrans.task.taskcfg import TaskCfgVTT

from videotrans.task.trans_create import TransCreate
from videotrans.util import tools


class Worker(QThread):
    uito = Signal(str)

    def __init__(
        self,
        *,
        parent: Optional[QObject] = None,
        obj_list: Optional[List[Dict[str, Any]]] = None,
        cfg: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent=parent)
        self.cfg = cfg
        # 存放处理好的 视频路径等信息
        self.obj_list = obj_list
        self.uuid = None

    # 使用冗余的 if self._exit(): return 来处理倒计时延迟问题
    def run(self) -> None:
        obj = self.obj_list[0]
        try:
            self.uuid = obj["uuid"]
            trk = TransCreate(cfg=TaskCfgVTT(**self.cfg | obj))
            # 原始语言字幕文件
            app_cfg.onlyone_source_sub = trk.cfg.source_sub
            # 目标语言字幕文件
            app_cfg.onlyone_target_sub = trk.cfg.target_sub
            if self._exit():
                return
            app_cfg.task_countdown = 0
            trk.prepare()
            if self._exit():
                return
            trk.recogn()
            if self._exit():
                return
            trk.diariz()
            if self._exit():
                return
            self._post(text=Path(trk.cfg.source_sub).read_text(encoding="utf-8"), type="replace_subtitle")

            if float(settings.get("countdown_sec", 0)) > 0:
                app_cfg.task_countdown = 86400
                self._post(text="", type="edit_subtitle_source")
                self._post(tr("The subtitle editing interface is rendering"))
                # 等待编辑原字幕后翻译,允许修改字幕
                while app_cfg.task_countdown > 0:
                    time.sleep(1)
                    app_cfg.task_countdown -= 1
                    if self._exit():
                        return

            if trk.shoud_trans:
                app_cfg.onlyone_trans = True
                trk.trans()

            if self._exit():
                return

            # 插入指定说话人，进行倒计时处理后再返回此处继续
            # 需要配音时
            if trk.shoud_dubbing:
                self._post(text=Path(trk.cfg.target_sub).read_text(encoding="utf-8"), type="replace_subtitle")
                if float(settings.get("countdown_sec", 0)) > 0:
                    app_cfg.task_countdown = 86400
                    # 传递过去临时目录，用于获取 speaker.json
                    self._post(
                        text=f"{trk.cfg.cache_folder}<|>{trk.cfg.target_language_code}<|>{trk.cfg.tts_type}",
                        type="edit_subtitle_target",
                    )
                    self._post(tr("The subtitle editing interface is rendering"))
                    while app_cfg.task_countdown > 0:
                        if self._exit():
                            return
                        # 其他情况，字幕处理完毕，未超时，等待1s，继续倒计时
                        time.sleep(1)
                        # 倒计时中
                        app_cfg.task_countdown -= 1

                if not self._exit():
                    trk.dubbing()

                # ── 配音溢出检测循环：逐条优化直到全部通过 ──
                _overflow_round = 0
                _max_overflow_rounds = 5  # 防止无限循环
                while (
                    not self._exit()
                    and trk._dubbing_overflow
                    and float(settings.get("countdown_sec", 0)) > 0
                    and _overflow_round < _max_overflow_rounds
                ):
                    _overflow_round += 1
                    self._post(
                        text=tr("配音溢出提示")
                        + f": {len(trk._dubbing_overflow)} 条字幕配音时长超出原时段≥15%，请优化翻译文本后点击继续（第{_overflow_round}轮）",
                        type="logs",
                    )

                    # 计算每条配音时长
                    for it in trk.queue_tts:
                        if self._exit():
                            return
                        filename = it.get("filename")
                        it["dubbing_s"] = (
                            len(AudioSegment.from_file(filename)) if filename and tools.vail_file(filename) else 0
                        ) / 1000.0

                    # 保存当前 queue_tts 供 edit_dubbing 面板读取
                    Path(f"{trk.cfg.cache_folder}/queue_tts.json").write_text(
                        json.dumps(trk.queue_tts, ensure_ascii=False), encoding="utf-8"
                    )

                    # 弹出编辑面板，等待用户修改字幕
                    app_cfg.task_countdown = 86400
                    self._post(
                        text=f"{trk.cfg.cache_folder}<|>{trk.cfg.target_language_code}",
                        type="edit_dubbing",
                    )
                    self._post(tr("The subtitle editing interface is rendering"))
                    while app_cfg.task_countdown > 0:
                        if self._exit():
                            return
                        time.sleep(1)
                        app_cfg.task_countdown -= 1

                    if self._exit():
                        return

                    # 从 json 重新加载用户编辑后的字幕
                    _json_path = Path(f"{trk.cfg.cache_folder}/queue_tts.json")
                    if _json_path.exists():
                        try:
                            _edited = json.loads(_json_path.read_text(encoding="utf-8"))
                        except Exception:
                            _edited = []
                        # 找出文本有变化的条目索引
                        _changed_indices = []
                        for _i, _e in enumerate(_edited):
                            if _i < len(trk.queue_tts):
                                _old_text = trk.queue_tts[_i].get("text", "")
                                _new_text = _e.get("text", "")
                                if _new_text.strip() and _new_text.strip() != _old_text.strip():
                                    # 更新 text 和其他用户可编辑字段
                                    trk.queue_tts[_i]["text"] = _new_text.strip()
                                    trk.queue_tts[_i]["start_time"] = _e.get(
                                        "start_time", trk.queue_tts[_i]["start_time"]
                                    )
                                    trk.queue_tts[_i]["end_time"] = _e.get("end_time", trk.queue_tts[_i]["end_time"])
                                    trk.queue_tts[_i]["startraw"] = _e.get("startraw", trk.queue_tts[_i]["startraw"])
                                    trk.queue_tts[_i]["endraw"] = _e.get("endraw", trk.queue_tts[_i]["endraw"])
                                    _changed_indices.append(_i)

                        if _changed_indices:
                            self._post(text=f"重新配音 {len(_changed_indices)} 条已修改字幕...", type="logs")
                            trk._re_tts(_changed_indices)
                            # 重新检查溢出
                            trk._dubbing_overflow = trk._mitigate_dubbing_overflow()
                        else:
                            # 用户没有修改任何字幕文本，退出循环
                            self._post(text="未检测到字幕修改，继续后续步骤", type="logs")
                            break
                    else:
                        break

                if _overflow_round >= _max_overflow_rounds:
                    self._post(
                        text=f"已进行 {_max_overflow_rounds} 轮优化，仍有 {len(trk._dubbing_overflow)} 条字幕超时，将使用变速对齐",
                        type="logs",
                    )

                # 原 edit_dubbing 逻辑（无溢出或 countdown=0 时走这里）
                if not trk._dubbing_overflow and not trk.ignore_align and float(settings.get("countdown_sec", 0)) > 0:
                    for it in trk.queue_tts:
                        if self._exit():
                            return
                        filename = it.get("filename")
                        it["dubbing_s"] = (
                            len(AudioSegment.from_file(filename)) if filename and tools.vail_file(filename) else 0
                        ) / 1000.0
                    Path(f"{trk.cfg.cache_folder}/queue_tts.json").write_text(
                        json.dumps(trk.queue_tts, ensure_ascii=False), encoding="utf-8"
                    )
                    app_cfg.task_countdown = 86400
                    self._post(
                        text=f"{trk.cfg.cache_folder}<|>{trk.cfg.target_language_code}",
                        type="edit_dubbing",
                    )
                    self._post(tr("The subtitle editing interface is rendering"))
                    while app_cfg.task_countdown > 0:
                        if self._exit():
                            return
                        time.sleep(1)
                        app_cfg.task_countdown -= 1

            if not self._exit():
                trk.align()

            if not self._exit():
                trk.recogn2pass()

            if not self._exit():
                trk.assembling()

            if not self._exit():
                trk.task_done()
        except Exception as e:
            detail_back = (traceback.format_exc()).strip()
            self._post(text=get_msg_from_except(e) + f"\n{detail_back}", type="error")

    def _post(self, text="", type="logs"):
        try:
            self.uito.emit(json.dumps({"text": text, "type": type, "uuid": self.uuid}))
        except TypeError:
            pass

    def _exit(self):
        if app_cfg.exit_soft or app_cfg.current_status != "ing":
            return True
        return False
