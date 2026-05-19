# -*- coding: utf-8 -*-
"""
分镜脚本可视化面板 — 展示/编辑分镜镜头，支持拖拽调整顺序
"""

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QIcon, QFont, QPixmap, QColor, QPainter, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QDoubleSpinBox,
    QLineEdit,
    QScrollArea,
    QFrame,
    QSplitter,
    QSizePolicy,
)

from videotrans.text_to_video.llm_service import StoryboardShot


class ShotCard(QFrame):
    """单个分镜卡片"""

    edit_requested = Signal(int)  # 请求编辑 (index)
    delete_requested = Signal(int)  # 请求删除 (index)
    material_requested = Signal(int)  # 请求重新获取素材 (index)
    clicked = Signal(int)  # 单击选中 (index)

    def __init__(self, shot: StoryboardShot, parent=None):
        super().__init__(parent)
        self.shot = shot
        self.setObjectName("shotCard")
        self.setStyleSheet("""
            #shotCard {
                background-color: #1e1e22;
                border: 1px solid #2a2a30;
                border-radius: 8px;
                padding: 8px;
            }
            #shotCard:hover {
                border-color: #3a8cff;
                background-color: #222228;
            }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # 头部：序号 + 时长
        header = QHBoxLayout()
        idx_label = QLabel(f"镜头 {self.shot.index}")
        idx_label.setStyleSheet("color: #3a8cff; font-weight: bold; font-size: 14px;")
        header.addWidget(idx_label)

        dur_label = QLabel(f"⏱ {self.shot.duration:.1f}s")
        dur_label.setStyleSheet("color: #888; font-size: 12px;")
        header.addWidget(dur_label)
        header.addStretch()

        # 素材状态徽章
        src_badge = {
            "local": "[本地]",
            "pexels": "[Pexels]",
            "pixabay": "[Pixabay]",
            "comfyui": "[AI生成]",
            "none": "[无素材]",
        }.get(self.shot.material_source, "[无素材]")
        badge_color = {
            "local": "#4caf50",
            "pexels": "#ff9800",
            "pixabay": "#2196f3",
            "comfyui": "#9c27b0",
            "none": "#666",
        }.get(self.shot.material_source, "#666")
        badge = QLabel(src_badge)
        badge.setStyleSheet(f"color: {badge_color}; font-size: 11px;")
        header.addWidget(badge)
        layout.addLayout(header)

        # 描述文字
        text_label = QLabel(self.shot.text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet("color: #ccc; font-size: 13px; padding: 4px 0;")
        layout.addWidget(text_label)

        # 关键词
        if self.shot.keywords:
            kw_text = " / ".join(self.shot.keywords[:4])
            kw_label = QLabel(f"🔑 {kw_text}")
            kw_label.setStyleSheet("color: #777; font-size: 11px;")
            layout.addWidget(kw_label)

    def mousePressEvent(self, event):
        self.clicked.emit(self.shot.index - 1)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.edit_requested.emit(self.shot.index - 1)


class StoryboardPanel(QWidget):
    """分镜脚本编辑面板"""

    shot_edited = Signal(int, object)  # (index, updated_shot)
    shot_deleted = Signal(int)  # (index)
    material_reacquire = Signal(int)  # (index)
    shots_reordered = Signal(list)  # 新排序后的分镜列表
    shot_selected = Signal(int, object)  # (index, shot) — 单击选中镜头

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shots: list[StoryboardShot] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 标题行
        title_row = QHBoxLayout()
        title = QLabel("分镜脚本")
        title.setStyleSheet("color: #aaa; font-size: 12px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        # 滚动区域 — 存放 ShotCard 列表
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("""
            QScrollArea { border: none; background-color: transparent; }
            QScrollBar:vertical {
                background-color: #1a1a1e; width: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #3a3a42; border-radius: 3px; min-height: 20px;
            }
        """)

        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(4, 4, 4, 4)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addStretch()
        self._scroll.setWidget(self._cards_container)
        layout.addWidget(self._scroll, 1)

    def set_shots(self, shots: list[StoryboardShot]):
        """加载分镜列表"""
        self._shots = shots
        self._rebuild_cards()

    def _rebuild_cards(self):
        # 清除旧卡片（保留 stretch）
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for shot in self._shots:
            card = ShotCard(shot)
            card.edit_requested.connect(self._on_shot_edit)
            card.delete_requested.connect(self.shot_deleted.emit)
            card.material_requested.connect(self.material_reacquire.emit)
            card.clicked.connect(self._on_shot_clicked)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

    def update_shot(self, index: int, shot: StoryboardShot):
        """更新单个分镜"""
        if 0 <= index < len(self._shots):
            self._shots[index] = shot
            self._rebuild_cards()
            self.shot_edited.emit(index, shot)

    def remove_shot(self, index: int):
        """删除单个分镜"""
        if 0 <= index < len(self._shots):
            self._shots.pop(index)
            # 重新编号
            for i, shot in enumerate(self._shots):
                shot.index = i + 1
            self._rebuild_cards()
            self.shot_deleted.emit(index)

    def get_shots(self) -> list[StoryboardShot]:
        return self._shots

    def _on_shot_clicked(self, index: int):
        """单击镜头卡片 → 选中并通知素材时间线"""
        if 0 <= index < len(self._shots):
            self.shot_selected.emit(index, self._shots[index])

    def _on_shot_edit(self, index: int):
        """双击卡片弹出简单编辑"""
        if index < 0 or index >= len(self._shots):
            return
        shot = self._shots[index]

        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout

        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑镜头 {shot.index}")
        dlg.setMinimumWidth(400)
        dlg.setStyleSheet("""
            QDialog { background-color: #1e1e22; }
            QLabel { color: #ccc; }
            QLineEdit, QDoubleSpinBox {
                background-color: #2a2a30; color: #e0e0e0; border: 1px solid #3a3a42;
                border-radius: 4px; padding: 6px;
            }
        """)

        form = QFormLayout(dlg)
        text_edit = QLineEdit(shot.text)
        form.addRow("描述:", text_edit)

        dur_spin = QDoubleSpinBox()
        dur_spin.setRange(1.0, 30.0)
        dur_spin.setSingleStep(0.5)
        dur_spin.setValue(shot.duration)
        form.addRow("时长 (秒):", dur_spin)

        kw_edit = QLineEdit(" ".join(shot.keywords))
        form.addRow("关键词:", kw_edit)

        prompt_edit = QLineEdit(shot.ai_prompt)
        form.addRow("AI提示词:", prompt_edit)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        form.addRow(btn_box)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            shot.text = text_edit.text()
            shot.duration = dur_spin.value()
            shot.keywords = [k.strip() for k in kw_edit.text().split() if k.strip()]
            shot.ai_prompt = prompt_edit.text()
            self.update_shot(index, shot)
