# -*- coding: utf-8 -*-
"""
特效编辑对话框 — 为选中素材添加/编辑视频特效链
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QSlider,
    QDoubleSpinBox,
    QSpinBox,
    QCheckBox,
    QLineEdit,
    QFileDialog,
    QSplitter,
    QFormLayout,
)

from .effects import (
    EFFECT_REGISTRY,
    EFFECT_CATEGORIES,
    build_ffmpeg_filter_chain,
    get_all_effects,
    get_all_categories,
    get_external_effects_dir,
    open_effects_dir,
    refresh_external_effects,
)
from .models import Effect

# ── 暗色基础样式 ──
_BASE_QSS = """
QDialog { background:#1e1e22; color:#d0d0d0; }
QLabel { color:#aaa; font-size:12px; }
QGroupBox { color:#aaa; font-size:12px; font-weight:bold;
    border:1px solid #2a2a30; border-radius:6px; margin-top:8px; padding-top:14px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; }
QListWidget { background:#1a1a1e; color:#d0d0d0; border:1px solid #2a2a30;
    border-radius:4px; font-size:12px; }
QListWidget::item { padding:4px 8px; border-radius:3px; }
QListWidget::item:hover { background:#2a2a32; }
QListWidget::item:selected { background:#3a8cff44; }
QTreeWidget { background:#1a1a1e; color:#d0d0d0; border:1px solid #2a2a30;
    border-radius:4px; font-size:12px; }
QTreeWidget::item { padding:3px 6px; }
QTreeWidget::item:hover { background:#2a2a32; }
QTreeWidget::item:selected { background:#3a8cff44; }
QPushButton { background:#2a2a32; color:#d0d0d0; border:1px solid #3a3a42;
    border-radius:4px; padding:5px 12px; font-size:12px; }
QPushButton:hover { border-color:#3a8cff; color:#fff; }
QSlider::groove:horizontal { background:#2a2a32; height:4px; border-radius:2px; }
QSlider::handle:horizontal { background:#3a8cff; width:12px; height:12px; margin:-4px 0; border-radius:6px; }
QSlider::sub-page:horizontal { background:#3a8cff; border-radius:2px; }
QDoubleSpinBox, QSpinBox { background:#2a2a32; color:#d0d0d0; border:1px solid #3a3a42;
    border-radius:4px; padding:3px 6px; font-size:12px; }
QLineEdit { background:#2a2a32; color:#d0d0d0; border:1px solid #3a3a42;
    border-radius:4px; padding:4px 8px; font-size:12px; }
QCheckBox { color:#ccc; font-size:12px; spacing:6px; }
QCheckBox::indicator { width:16px; height:16px; background:#2a2a30;
    border:1px solid #3a3a42; border-radius:3px; }
QCheckBox::indicator:checked { background:#3a8cff; border-color:#3a8cff; }
"""


class EffectsDialog(QDialog):
    """特效编辑对话框 — 左侧特效目录 + 右侧特效链 + 底部参数面板"""

    def __init__(self, clip_label: str, effects: list | None = None, parent=None, preview_callback=None):
        super().__init__(parent)
        self.setWindowTitle(f"特效编辑 — {clip_label}")
        self.setMinimumSize(680, 520)
        self.setStyleSheet(_BASE_QSS)

        self._preview_callback = preview_callback  # callable(filter_chain) 或 None

        # 深拷贝特效链，避免直接修改原数据
        self._effects: list[Effect] = []
        if effects:
            for e in effects:
                self._effects.append(Effect(effect_id=e.effect_id, params=dict(e.params), enabled=e.enabled))

        # 防抖定时器：参数变化后 200ms 触发预览
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._do_preview)

        self._setup_ui()
        self._rebuild_chain_list()
        # 对话框打开后延时触发初始预览（等渲染完成）
        if self._preview_callback is not None:
            QTimer.singleShot(80, self._do_preview)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 主区域：水平分割器 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：特效目录
        left_panel = QGroupBox("可用特效")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 12, 4, 4)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setDragEnabled(False)
        self._tree.doubleClicked.connect(self._on_tree_double_click)
        self._populate_tree()
        left_layout.addWidget(self._tree)

        # 素材目录按钮
        btn_row_ext = QHBoxLayout()
        btn_row_ext.setSpacing(4)
        self._btn_open_effects_dir = QPushButton("📂 打开素材目录")
        self._btn_open_effects_dir.setToolTip(
            "在文件管理器中打开 external effects/ 目录\n放入 .cube LUT、叠加视频、预设 .json 文件"
        )
        self._btn_open_effects_dir.clicked.connect(open_effects_dir)
        btn_row_ext.addWidget(self._btn_open_effects_dir)

        self._btn_refresh_effects = QPushButton("🔄 刷新")
        self._btn_refresh_effects.setToolTip("重新扫描素材目录")
        self._btn_refresh_effects.clicked.connect(self._on_refresh_external)
        btn_row_ext.addWidget(self._btn_refresh_effects)
        left_layout.addLayout(btn_row_ext)

        splitter.addWidget(left_panel)

        # 右侧：特效链 + 参数面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # 特效链列表
        chain_group = QGroupBox("特效链（按顺序应用）")
        chain_layout = QVBoxLayout(chain_group)
        chain_layout.setContentsMargins(4, 12, 4, 4)

        self._chain_list = QListWidget()
        self._chain_list.currentRowChanged.connect(self._on_chain_selection)
        self._chain_list.keyPressEvent = self._chain_key_press
        chain_layout.addWidget(self._chain_list)

        # 排序/删除按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._btn_up = QPushButton("▲ 上移")
        self._btn_up.setToolTip("将选中特效向上移动")
        self._btn_up.clicked.connect(self._on_move_up)
        btn_row.addWidget(self._btn_up)

        self._btn_down = QPushButton("▼ 下移")
        self._btn_down.setToolTip("将选中特效向下移动")
        self._btn_down.clicked.connect(self._on_move_down)
        btn_row.addWidget(self._btn_down)

        self._btn_remove = QPushButton("✕ 移除")
        self._btn_remove.setToolTip("移除选中特效")
        self._btn_remove.clicked.connect(self._on_remove)
        self._btn_remove.setStyleSheet(
            "QPushButton { border-color:#5a3a3a; color:#f66; } " "QPushButton:hover { border-color:#cc4444; }"
        )
        btn_row.addWidget(self._btn_remove)

        btn_row.addStretch()
        self._btn_reset = QPushButton("清空全部")
        self._btn_reset.clicked.connect(self._on_reset_all)
        self._btn_reset.setStyleSheet(
            "QPushButton { border-color:#3a3a3a; color:#888; } "
            "QPushButton:hover { border-color:#cc4444; color:#f66; }"
        )
        btn_row.addWidget(self._btn_reset)
        chain_layout.addLayout(btn_row)

        right_layout.addWidget(chain_group)

        # 参数面板
        self._param_group = QGroupBox("特效参数")
        self._param_layout = QFormLayout(self._param_group)
        self._param_layout.setContentsMargins(12, 16, 12, 8)
        self._param_layout.setSpacing(8)
        self._param_controls: dict = {}
        right_layout.addWidget(self._param_group)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        # ── 对话框按钮 ──
        dlg_btns = QHBoxLayout()
        dlg_btns.addStretch()

        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.clicked.connect(self.reject)
        dlg_btns.addWidget(self._btn_cancel)

        self._btn_ok = QPushButton("确定")
        self._btn_ok.setStyleSheet(
            "QPushButton { background:#3a8cff; color:#fff; border:none; border-radius:4px; "
            "padding:6px 28px; font-size:13px; } "
            "QPushButton:hover { background:#4a9cff; }"
        )
        self._btn_ok.clicked.connect(self._on_ok)
        dlg_btns.addWidget(self._btn_ok)

        layout.addLayout(dlg_btns)

    # ── 特效目录 ──
    def _populate_tree(self):
        self._tree.clear()
        all_effects = get_all_effects()
        all_cats = get_all_categories()
        for cat in all_cats:
            cat_item = QTreeWidgetItem([cat])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            cat_item.setExpanded(True)
            count = 0
            for eid, entry in all_effects.items():
                if entry.get("category") == cat:
                    prefix = "📁 " if entry.get("external_source") else "  "
                    child = QTreeWidgetItem([f"{prefix}{entry['name']}"])
                    child.setData(0, Qt.ItemDataRole.UserRole, eid)
                    tooltip = entry.get("name", "")
                    if entry.get("external_source"):
                        tooltip += f"\n来源: {entry['external_source']}"
                    if entry.get("mode") == "complex":
                        tooltip += "\n⚠ 需要高级合成模式"
                        child.setForeground(0, QTreeWidgetItem().foreground(0))  # reset
                        from PySide6.QtGui import QColor

                        child.setForeground(0, QColor("#ffa500"))  # 橙色标记
                    child.setToolTip(0, tooltip)
                    cat_item.addChild(child)
                    count += 1
            if count > 0:
                self._tree.addTopLevelItem(cat_item)
            else:
                # 空分类显示提示
                placeholder = QTreeWidgetItem([f"{cat}（无特效，将素材放入 effects/ 目录）"])
                placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self._tree.addTopLevelItem(placeholder)

    def _on_refresh_external(self):
        """重新扫描素材目录并刷新特效树"""
        refresh_external_effects()
        self._populate_tree()

    def _on_tree_double_click(self, index):
        item = self._tree.itemFromIndex(index)
        if not item:
            return
        eid = item.data(0, Qt.ItemDataRole.UserRole)
        if not eid:
            return
        entry = get_all_effects().get(eid)
        if not entry:
            return

        # 构建默认参数
        params = {}
        for p in entry.get("params", []):
            params[p["key"]] = p["default"]

        effect = Effect(effect_id=eid, params=params, enabled=True)
        self._effects.append(effect)
        self._rebuild_chain_list()
        # 选中新添加的
        self._chain_list.setCurrentRow(len(self._effects) - 1)

    # ── 特效链列表 ──
    def _rebuild_chain_list(self):
        self._chain_list.blockSignals(True)
        self._chain_list.clear()

        for i, e in enumerate(self._effects):
            entry = get_all_effects().get(e.effect_id)
            name = entry["name"] if entry else e.effect_id
            text = f"{i + 1}. {name}"
            if not e.enabled:
                text += "  (禁用)"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._chain_list.addItem(item)

        self._chain_list.blockSignals(False)
        if self._chain_list.count() > 0 and self._chain_list.currentRow() < 0:
            self._chain_list.setCurrentRow(0)
        self._update_param_panel()

    def _on_chain_selection(self, row):
        self._update_param_panel()
        self._update_buttons()

    def _chain_key_press(self, event):
        """覆盖键盘事件 — Delete 删除选中项"""
        from PySide6.QtGui import QKeyEvent

        if event.key() == Qt.Key.Key_Delete:
            self._on_remove()
        else:
            QListWidget.keyPressEvent(self._chain_list, event)

    # ── 排序/删除 ──
    def _on_move_up(self):
        row = self._chain_list.currentRow()
        if row <= 0:
            return
        self._effects[row], self._effects[row - 1] = self._effects[row - 1], self._effects[row]
        self._rebuild_chain_list()
        self._chain_list.setCurrentRow(row - 1)

    def _on_move_down(self):
        row = self._chain_list.currentRow()
        if row < 0 or row >= len(self._effects) - 1:
            return
        self._effects[row], self._effects[row + 1] = self._effects[row + 1], self._effects[row]
        self._rebuild_chain_list()
        self._chain_list.setCurrentRow(row + 1)

    def _on_remove(self):
        row = self._chain_list.currentRow()
        if row < 0:
            return
        self._effects.pop(row)
        self._rebuild_chain_list()
        if row < len(self._effects):
            self._chain_list.setCurrentRow(row)

    def _on_reset_all(self):
        self._effects.clear()
        self._rebuild_chain_list()
        self._clear_param_panel()

    def _update_buttons(self):
        row = self._chain_list.currentRow()
        has_sel = row >= 0
        self._btn_up.setEnabled(has_sel and row > 0)
        self._btn_down.setEnabled(has_sel and row < len(self._effects) - 1)
        self._btn_remove.setEnabled(has_sel)

    # ── 参数面板 ──
    def _clear_param_panel(self):
        self._save_current_params()
        while self._param_layout.rowCount() > 0:
            self._param_layout.removeRow(0)
        self._param_controls.clear()

    def _update_param_panel(self):
        self._save_current_params()
        self._clear_param_panel()

        row = self._chain_list.currentRow()
        if row < 0 or row >= len(self._effects):
            return

        effect = self._effects[row]
        entry = EFFECT_REGISTRY.get(effect.effect_id)
        if not entry:
            return

        # enabled 复选框
        cb = QCheckBox("启用此特效")
        cb.setChecked(effect.enabled)
        cb.toggled.connect(lambda checked, e=effect: self._on_enabled_toggle(e, checked))
        self._param_layout.addRow(cb)
        self._param_controls["__enabled__"] = cb

        # 各参数控件
        for p in entry.get("params", []):
            key = p["key"]
            val = effect.params.get(key, p["default"])
            label = QLabel(p["label"])
            label.setStyleSheet("color:#aaa; font-size:12px;")

            if p["type"] == "float":
                ctrl = self._make_float_control(p, val)
            elif p["type"] == "int":
                ctrl = self._make_int_control(p, val)
            elif p["type"] == "file":
                ctrl = self._make_file_control(p, val)
            else:
                continue

            self._param_layout.addRow(label, ctrl)
            self._param_controls[key] = ctrl

    def _make_float_control(self, p: dict, val) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        _min, _max = p["min"], p["max"]
        step = p.get("step", 0.01)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, int((_max - _min) / step))
        slider.setValue(int((val - _min) / step))

        spin = QDoubleSpinBox()
        spin.setRange(_min, _max)
        spin.setSingleStep(step)
        spin.setDecimals(3 if step < 0.1 else 2)
        spin.setValue(val)
        spin.setFixedWidth(80)

        slider.valueChanged.connect(lambda v: spin.setValue(_min + v * step))
        spin.valueChanged.connect(
            lambda v: slider.blockSignals(True) or slider.setValue(int((v - _min) / step)) or slider.blockSignals(False)
        )
        slider.valueChanged.connect(self._schedule_preview)
        spin.valueChanged.connect(self._schedule_preview)

        h.addWidget(slider, 1)
        h.addWidget(spin)

        if p.get("unit"):
            unit_lbl = QLabel(p["unit"])
            unit_lbl.setStyleSheet("color:#888; font-size:11px;")
            h.addWidget(unit_lbl)

        return w

    def _make_int_control(self, p: dict, val) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        _min, _max = p["min"], p["max"]
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(_min, _max)
        slider.setValue(val)

        spin = QSpinBox()
        spin.setRange(_min, _max)
        spin.setValue(val)
        spin.setFixedWidth(64)

        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(self._schedule_preview)
        spin.valueChanged.connect(self._schedule_preview)

        h.addWidget(slider, 1)
        h.addWidget(spin)

        if p.get("unit"):
            unit_lbl = QLabel(p["unit"])
            unit_lbl.setStyleSheet("color:#888; font-size:11px;")
            h.addWidget(unit_lbl)

        return w

    def _make_file_control(self, p: dict, val) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        edit = QLineEdit(str(val))
        edit.setPlaceholderText("选择 .cube 或 .3dl 文件...")

        btn = QPushButton("浏览...")
        btn.clicked.connect(lambda: self._browse_lut_file(edit))
        edit.textChanged.connect(self._schedule_preview)

        h.addWidget(edit, 1)
        h.addWidget(btn)
        return w

    def _browse_lut_file(self, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 LUT 文件", "", "LUT 文件 (*.cube *.3dl *.dat *.m3d);;所有文件 (*)"
        )
        if path:
            edit.setText(path)

    def _save_current_params(self):
        """将参数面板当前值写回当前选中的 Effect"""
        row = self._chain_list.currentRow()
        if row < 0 or row >= len(self._effects):
            return
        effect = self._effects[row]
        entry = EFFECT_REGISTRY.get(effect.effect_id)
        if not entry:
            return

        for p in entry.get("params", []):
            key = p["key"]
            ctrl = self._param_controls.get(key)
            if ctrl is None:
                continue
            if p["type"] == "float":
                spin = ctrl.findChildren(QDoubleSpinBox)[0] if ctrl.findChildren(QDoubleSpinBox) else None
                if spin:
                    effect.params[key] = spin.value()
            elif p["type"] == "int":
                spin = ctrl.findChildren(QSpinBox)[0] if ctrl.findChildren(QSpinBox) else None
                if spin:
                    effect.params[key] = spin.value()
            elif p["type"] == "file":
                edit = ctrl.findChildren(QLineEdit)[0] if ctrl.findChildren(QLineEdit) else None
                if edit:
                    effect.params[key] = edit.text()

    def _on_enabled_toggle(self, effect: Effect, checked: bool):
        effect.enabled = checked
        self._rebuild_chain_list()

    # ── 预览 ──

    def _schedule_preview(self, *_):
        """参数变化 → 防抖触发预览回调"""
        if self._preview_callback is None:
            return
        self._preview_timer.start()

    def _do_preview(self):
        """防抖定时器到期 → 保存参数 → 构建滤镜链 → 回调"""
        self._save_current_params()
        chain = build_ffmpeg_filter_chain(self._effects)
        try:
            self._preview_callback(chain)
        except Exception as e:
            import traceback

            traceback.print_exc()

    # ── 确定/取消 ──
    def _on_ok(self):
        self._save_current_params()
        self.accept()

    def get_effects(self) -> list:
        """返回编辑后的特效列表（Effect 对象）"""
        return list(self._effects)

    def get_filter_chain(self) -> str:
        """返回 ffmpeg filter_complex 中可用的 vf 字符串"""
        return build_ffmpeg_filter_chain(self._effects)
