"""管线断点续跑检查点管理器"""

import json
import os
from typing import Optional


class PipelineCheckpoint:
    """管理翻译管线步骤的断点状态"""

    STEPS = ["prepare", "recogn", "diariz", "trans", "dubbing", "align", "recogn2pass", "assembling"]

    # 每个步骤对应的验证文件（cfg 属性名）
    _STEP_FILES = {
        "recogn": "source_sub",
        "trans": "target_sub",
        "dubbing": "target_wav",
        "assembling": "targetdir_mp4",
    }

    def __init__(self, target_dir: str, cfg=None):
        self._path = os.path.join(target_dir, ".pipeline_state.json")
        self._cfg = cfg  # TransCreate.cfg，用于验证文件存在
        self._state: dict[str, bool] = {}
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._state = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._state = {}

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    def is_done(self, step: str) -> bool:
        """检查步骤是否已完成（检查点记录 + 输出文件存在）"""
        if step not in self.STEPS:
            return False
        if not self._state.get(step):
            return False

        # 验证关联文件仍存在
        attr = self._STEP_FILES.get(step)
        if attr and self._cfg:
            path = getattr(self._cfg, attr, None)
            if path and not os.path.exists(path):
                self.invalidate_from(step)
                return False
            if path and os.path.getsize(path) == 0:
                self.invalidate_from(step)
                return False
        return True

    def mark_done(self, step: str):
        """标记步骤完成"""
        if step not in self.STEPS:
            return
        self._state[step] = True
        self._save()

    def completed_steps(self) -> list:
        """返回已完成步骤列表"""
        return [s for s in self.STEPS if self._state.get(s)]

    def invalidate_from(self, step: str):
        """从指定步骤起全部失效"""
        if step not in self.STEPS:
            return
        idx = self.STEPS.index(step)
        for s in self.STEPS[idx:]:
            self._state.pop(s, None)
        self._save()

    def clear(self):
        self._state = {}
        if os.path.exists(self._path):
            os.remove(self._path)
