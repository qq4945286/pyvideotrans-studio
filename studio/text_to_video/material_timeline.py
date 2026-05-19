# -*- coding: utf-8 -*-
"""
素材时间线 — 水平滚动素材卡片列表，位于播放控制栏下方
每个素材卡片：缩略图 + 来源标签 + 特效按钮
"""

import os

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QScrollArea,
    QFrame,
    QSizePolicy,
)

from videotrans.text_to_video.media.base import MaterialResult

# ── 来源标签样式 ──
_SOURCE_STYLES = {
    "local": ("[本地]", "#4caf50"),
    "pexels": ("[Pexels]", "#ff9800"),
    "pixabay": ("[Pixabay]", "#2196f3"),
    "comfyui": ("[AI生成]", "#9c27b0"),
}


def _material_to_dict(m: MaterialResult) -> dict:
    """MaterialResult → 可序列化 dict"""
    return {
        "source": m.source,
        "url": m.url,
        "preview_url": m.preview_url,
        "description": m.description,
        "author": m.author,
        "width": m.width,
        "height": m.height,
        "duration": m.duration,
        "media_type": m.media_type,
        "local_path": m.local_path,
        "effects": [
            (
                {"effect_id": e.effect_id, "params": e.params, "enabled": e.enabled}
                if hasattr(e, "effect_id")
                else {
                    "effect_id": e.get("effect_id", ""),
                    "params": e.get("params", {}),
                    "enabled": e.get("enabled", True),
                }
            )
            for e in m.effects
        ],
    }


def _dict_to_material(d: dict) -> MaterialResult:
    """dict → MaterialResult"""
    from studio.editor.models import Effect

    effects = []
    for e in d.get("effects", []):
        effects.append(
            Effect(effect_id=e.get("effect_id", ""), params=e.get("params", {}), enabled=e.get("enabled", True))
        )
    return MaterialResult(
        source=d.get("source", ""),
        url=d.get("url", ""),
        preview_url=d.get("preview_url", ""),
        description=d.get("description", ""),
        author=d.get("author", ""),
        width=d.get("width", 0),
        height=d.get("height", 0),
        duration=d.get("duration", 0.0),
        media_type=d.get("media_type", "image"),
        local_path=d.get("local_path", ""),
        effects=effects,
    )


class MaterialCard(QFrame):
    """单个素材卡片 — 缩略图 + 来源标签 + 特效按钮"""

    clicked = Signal(int)  # 卡片被点击 (index)
    effects_clicked = Signal(int)  # 特效按钮被点击 (index)

    def __init__(self, material: MaterialResult, index: int, parent=None):
        super().__init__(parent)
        self._material = material
        self._index = index
        self._selected = False
        self.setObjectName("materialCard")
        self.setFixedSize(130, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # 缩略图
        self._thumb = QLabel()
        self._thumb.setFixedSize(120, 64)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet("background-color:#0d0d0f; border-radius:4px;")
        pix = self._load_thumbnail()
        if pix and not pix.isNull():
            self._thumb.setPixmap(
                pix.scaled(120, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self._thumb.setText("🎬")
            self._thumb.setStyleSheet("background-color:#0d0d0f; border-radius:4px; color:#555; font-size:24px;")
        layout.addWidget(self._thumb, alignment=Qt.AlignmentFlag.AlignCenter)

        # 来源标签
        src_label, src_color = _SOURCE_STYLES.get(self._material.source, ("[素材]", "#888"))
        self._src_badge = QLabel(src_label)
        self._src_badge.setStyleSheet(f"color:{src_color}; font-size:10px; padding:0 4px;")
        self._src_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._src_badge)

        # 操作按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self._fx_btn = QPushButton("特效")
        self._fx_btn.setFixedSize(56, 22)
        self._fx_btn.setStyleSheet("""
            QPushButton {
                background-color:#2a2a32; color:#ccc; border:1px solid #3a3a42;
                border-radius:4px; font-size:11px; padding:2px 6px;
            }
            QPushButton:hover { background-color:#3a3a44; border-color:#3a8cff; }
        """)
        self._fx_btn.clicked.connect(lambda: self.effects_clicked.emit(self._index))
        btn_row.addWidget(self._fx_btn)

        # 如果有特效，显示橙色标记
        if self._material.effects:
            self._fx_btn.setStyleSheet("""
                QPushButton {
                    background-color:#3a2a1a; color:#ff9800; border:1px solid #ff9800;
                    border-radius:4px; font-size:11px; padding:2px 6px;
                }
                QPushButton:hover { background-color:#4a3a2a; }
            """)

        layout.addLayout(btn_row)

    def _load_thumbnail(self) -> QPixmap | None:
        """加载素材缩略图"""
        path = self._material.local_path
        if path and os.path.exists(path):
            return QPixmap(path)
        return None

    @property
    def material(self) -> MaterialResult:
        return self._material

    @material.setter
    def material(self, m: MaterialResult):
        self._material = m

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, v: bool):
        self._selected = v
        if v:
            self.setStyleSheet("""
                #materialCard {
                    background-color:#1a2a3a;
                    border:2px solid #3a8cff;
                    border-radius:8px;
                }
            """)
        else:
            self.setStyleSheet("""
                #materialCard {
                    background-color:#1e1e22;
                    border:1px solid #2a2a30;
                    border-radius:8px;
                }
                #materialCard:hover {
                    border-color:#3a8cff;
                    background-color:#222228;
                }
            """)

    def mousePressEvent(self, event):
        self.clicked.emit(self._index)
        super().mousePressEvent(event)


class MaterialTimeline(QWidget):
    """素材时间线 — 水平滚动，显示当前镜头的所有搜索素材"""

    material_selected = Signal(int, object)  # (index, MaterialResult)
    effects_requested = Signal(int, object)  # (index, MaterialResult) — 打开特效对话框

    def __init__(self, parent=None):
        super().__init__(parent)
        self._materials: list[MaterialResult] = []
        self._cards: list[MaterialCard] = []
        self._selected_index = -1
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        title_row = QHBoxLayout()
        title_row.setContentsMargins(8, 2, 8, 2)
        self._title_label = QLabel("素材时间线")
        self._title_label.setStyleSheet("color:#888; font-size:11px; font-weight:bold;")
        title_row.addWidget(self._title_label)
        title_row.addStretch()
        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color:#666; font-size:10px;")
        title_row.addWidget(self._count_label)
        layout.addLayout(title_row)

        # 水平滚动区域
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(128)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("""
            QScrollArea { border:none; background-color:#16161a; }
            QScrollBar:horizontal {
                background-color:#1a1a1e; height:6px; border:none;
            }
            QScrollBar::handle:horizontal {
                background-color:#3a3a44; border-radius:3px; min-width:20px;
            }
            QScrollBar::handle:horizontal:hover { background-color:#4a4a54; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
        """)

        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background-color:#16161a;")
        self._cards_layout = QHBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(6, 4, 6, 4)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addStretch()

        self._scroll.setWidget(self._cards_container)
        layout.addWidget(self._scroll)

        # 占位提示
        self._placeholder = QLabel("搜索素材后将在此显示，点击素材预览，点击「特效」添加效果")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color:#555; font-size:12px; padding:12px;")
        layout.addWidget(self._placeholder)

    def set_materials(self, materials: list):
        """加载素材列表"""
        self._materials = materials if materials else []
        self._rebuild_cards()

    def clear(self):
        """清空素材"""
        self._materials = []
        self._selected_index = -1
        self._rebuild_cards()

    def get_materials(self) -> list:
        return self._materials

    def get_selected_index(self) -> int:
        return self._selected_index

    def get_selected_material(self) -> MaterialResult | None:
        if 0 <= self._selected_index < len(self._materials):
            return self._materials[self._selected_index]
        return None

    def update_material_effects(self, index: int, effects: list):
        """更新指定素材的特效列表"""
        if 0 <= index < len(self._materials):
            self._materials[index].effects = effects
            if 0 <= index < len(self._cards):
                card = self._cards[index]
                card.material = self._materials[index]
                # 更新特效按钮样式
                if effects:
                    card._fx_btn.setStyleSheet("""
                        QPushButton {
                            background-color:#3a2a1a; color:#ff9800; border:1px solid #ff9800;
                            border-radius:4px; font-size:11px; padding:2px 6px;
                        }
                        QPushButton:hover { background-color:#4a3a2a; }
                    """)
                else:
                    card._fx_btn.setStyleSheet("""
                        QPushButton {
                            background-color:#2a2a32; color:#ccc; border:1px solid #3a3a42;
                            border-radius:4px; font-size:11px; padding:2px 6px;
                        }
                        QPushButton:hover { background-color:#3a3a44; border-color:#3a8cff; }
                    """)

    def select_material(self, index: int):
        """选中指定素材"""
        self._selected_index = index
        for i, card in enumerate(self._cards):
            card.selected = i == index

    def _rebuild_cards(self):
        """重建素材卡片列表"""
        # 清除旧卡片
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards = []

        has_materials = len(self._materials) > 0
        self._scroll.setVisible(has_materials)
        self._placeholder.setVisible(not has_materials)
        self._count_label.setText(f"{len(self._materials)} 个素材" if has_materials else "")

        for i, mat in enumerate(self._materials):
            card = MaterialCard(mat, i)
            card.clicked.connect(self._on_card_clicked)
            card.effects_clicked.connect(self._on_effects_clicked)
            if i == self._selected_index:
                card.selected = True
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._cards.append(card)

    def _on_card_clicked(self, index: int):
        """点击素材卡片"""
        self.select_material(index)
        if 0 <= index < len(self._materials):
            self.material_selected.emit(index, self._materials[index])

    def _on_effects_clicked(self, index: int):
        """点击特效按钮"""
        if 0 <= index < len(self._materials):
            self.effects_requested.emit(index, self._materials[index])
