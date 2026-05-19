# -*- coding: utf-8 -*-
"""
素材浏览器 — 展示搜索结果，支持预览和拖拽替换分镜素材
"""

import os
import threading

from PySide6.QtCore import Qt, Signal, QSize, QUrl, QTimer
from PySide6.QtGui import QIcon, QPixmap, QImage, QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QScrollArea,
    QGridLayout,
    QFrame,
    QLineEdit,
    QSizePolicy,
    QProgressBar,
    QListWidget,
    QListWidgetItem,
)

from videotrans.text_to_video.media import create_sources, MaterialResult, MaterialSource


class MaterialCard(QFrame):
    """单个素材卡片 — 缩略图 + 来源标签"""

    clicked = Signal(object)  # MaterialResult
    double_clicked = Signal(object)  # MaterialResult (用于快速替换)

    def __init__(self, material: MaterialResult, parent=None):
        super().__init__(parent)
        self.material = material
        self.setObjectName("materialCard")
        self.setFixedSize(140, 130)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            #materialCard {
                background-color: #1e1e22;
                border: 1px solid #2a2a30;
                border-radius: 6px;
            }
            #materialCard:hover {
                border-color: #3a8cff;
            }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # 缩略图占位
        self._thumb = QLabel()
        self._thumb.setFixedSize(130, 80)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet("background-color: #2a2a30; border-radius: 4px; color: #666; font-size: 24px;")
        self._thumb.setText("🖼")
        layout.addWidget(self._thumb, alignment=Qt.AlignmentFlag.AlignCenter)

        # 来源标签
        src_text = {"local": "本地", "pexels": "Pexels", "pixabay": "Pixabay", "comfyui": "AI"}.get(
            self.material.source, "未知"
        )
        src_color = {"local": "#4caf50", "pexels": "#ff9800", "pixabay": "#2196f3", "comfyui": "#9c27b0"}.get(
            self.material.source, "#666"
        )
        src_label = QLabel(src_text)
        src_label.setStyleSheet(f"color: {src_color}; font-size: 10px; font-weight: bold;")
        layout.addWidget(src_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # 描述
        desc = self.material.description or ""
        if len(desc) > 15:
            desc = desc[:15] + "..."
        desc_label = QLabel(desc)
        desc_label.setStyleSheet("color: #777; font-size: 10px;")
        layout.addWidget(desc_label, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_thumbnail(self, pixmap: QPixmap):
        """设置缩略图"""
        scaled = pixmap.scaled(130, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._thumb.setPixmap(scaled)

    def mousePressEvent(self, event):
        self.clicked.emit(self.material)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.material)


class MediaBrowser(QWidget):
    """素材浏览器 — 搜索 + 展示"""

    material_selected = Signal(object)  # MaterialResult
    material_double_clicked = Signal(object)  # MaterialResult (快速替换当前分镜)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sources: list[MaterialSource] = []
        self._results: list[MaterialResult] = []
        self._current_kw_index = 0
        self._all_keywords: list[str] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 搜索栏
        search_row = QHBoxLayout()
        self._kw_input = QLineEdit()
        self._kw_input.setPlaceholderText("搜索关键词...")
        self._kw_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e22; color: #e0e0e0;
                border: 1px solid #2a2a30; border-radius: 4px; padding: 6px;
            }
            QLineEdit:focus { border-color: #3a8cff; }
        """)
        self._kw_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self._kw_input)

        search_btn = QPushButton("搜索")
        search_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a8cff; color: #fff; border: none;
                border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #4a9cff; }
        """)
        search_btn.clicked.connect(self._on_search)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        # 来源标签
        src_row = QHBoxLayout()
        self._src_label = QLabel("素材源: —")
        self._src_label.setStyleSheet("color: #888; font-size: 11px;")
        src_row.addWidget(self._src_label)
        src_row.addStretch()
        layout.addLayout(src_row)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(4)
        layout.addWidget(self._progress)

        # 素材网格
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("""
            QScrollArea { border: none; background-color: transparent; }
        """)

        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(8)
        self._scroll.setWidget(self._grid_container)
        layout.addWidget(self._scroll, 1)

        # 状态
        self._status = QLabel("就绪")
        self._status.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self._status)

    def set_sources(self, config: dict):
        """设置启用的素材源"""
        self._sources = create_sources(config)
        names = [s.name() for s in self._sources]
        self._src_label.setText(f"素材源: {', '.join(names) if names else '—'}")

    def set_keywords(self, keywords: list[str]):
        """设置搜索关键词"""
        self._all_keywords = keywords
        self._kw_input.setText(" ".join(keywords))
        self._current_kw_index = 0

    def search_next_source(self):
        """切换到下一组关键词/下一个源进行搜索"""
        if not self._all_keywords:
            return
        self._on_search()

    def _on_search(self):
        """执行搜索"""
        kw_text = self._kw_input.text().strip()
        if not kw_text:
            return
        keywords = [k.strip() for k in kw_text.split() if k.strip()]
        if not keywords:
            return
        self._all_keywords = keywords

        self._progress.setVisible(True)
        self._progress.setValue(10)
        self._status.setText("搜索中...")

        # 清除旧结果
        self._results.clear()
        self._clear_cards()

        def _run():
            for src in self._sources:
                if not src.enabled():
                    continue
                try:
                    results = src.search(keywords, count=10)
                    for r in results:
                        self._results.append(r)
                except Exception:
                    continue

            # 在主线程更新 UI
            QTimer.singleShot(0, self._show_results)

        threading.Thread(target=_run, daemon=True).start()

    def _show_results(self):
        """在主线程展示搜索结果"""
        self._clear_cards()
        cols = max(1, (self._scroll.width() - 20) // 148)

        for i, mat in enumerate(self._results[:30]):
            card = MaterialCard(mat)
            card.clicked.connect(self.material_selected.emit)
            card.double_clicked.connect(self.material_double_clicked.emit)
            row, col = i // cols, i % cols
            self._grid.addWidget(card, row, col)

        self._progress.setVisible(False)
        self._status.setText(f"找到 {len(self._results)} 个素材")

    def _clear_cards(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def clear(self):
        self._results.clear()
        self._clear_cards()
        self._status.setText("就绪")
