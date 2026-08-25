"""通用可复用控件（app 层）。"""
import time

from PySide6.QtCore import Qt, QSize, QPropertyAnimation, QVariantAnimation, QEasingCurve, QRect, QEvent, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QBrush
from PySide6.QtWidgets import (
    QLabel, QMenu, QStyledItemDelegate, QStyle, QTabBar,
    QTreeWidget, QTreeWidgetItem, QAbstractItemView,
    QPushButton, QGraphicsDropShadowEffect,
)

from ccui.app.theme import should_reduce_motion
from ccui.app.splash import spark_pixmap


class ElidedLabel(QLabel):
    """自动省略号标签：文字超宽时按可用宽度省略，不撑大布局。

    用于可能很长的单行文本（如角色技能列表），避免挤压同排/相邻控件，
    保证界面宽度统一。
    """

    def __init__(self, text='', parent=None, min_width=48, max_hint_width=240):
        super().__init__(text, parent)
        self._full = text or ''
        self._min_width = min_width
        self._max_hint_width = max_hint_width
        self.setToolTip(self._full)

    def setText(self, text):
        self._full = text or ''
        super().setText(self._full)
        self.setToolTip(self._full)

    def text(self):
        return self._full

    def sizeHint(self):
        sh = super().sizeHint()
        w = min(sh.width(), self._max_hint_width)
        return QSize(max(self._min_width, w), sh.height())

    def minimumSizeHint(self):
        return QSize(self._min_width, self.sizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        elided = painter.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), int(self.alignment()), elided)
        painter.end()


class FadeMenu(QMenu):
    """右键菜单淡入（140ms OutCubic）。

    按 emil-design-eng 原则：弹层属「偶尔出现」→ 标准动画 <250ms、进场 ease-out。
    """

    def showEvent(self, event):
        self.setWindowOpacity(0.0)
        super().showEvent(event)
        anim = QPropertyAnimation(self, b'windowOpacity', self)
        anim.setDuration(140)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim = anim
        anim.start()


class EmptyHint(QLabel):
    """列表/树空状态提示：作为 view 的子控件，随 view 缩放居中，空时显示。

    上面画启动画面的 Claude spark 小可爱（品牌一致，替代 emoji），下面文字。
    """

    SPARK_SIZE = 56

    def __init__(self, text, parent_view):
        # 作为 viewport 的子控件：覆盖内容区（不含表头），坐标即 viewport 坐标系
        self._message = text
        super().__init__(text, parent_view.viewport())
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('color:#6b6b70; background: transparent; font-size: 13px;')
        self.setWordWrap(True)
        self.hide()
        self._view = parent_view
        parent_view.viewport().installEventFilter(self)

    def setText(self, text):
        self._message = text
        super().setText(text)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        spark = spark_pixmap(self.SPARK_SIZE)
        sx = rect.center().x() - spark.width() // 2
        sy = rect.top() + max(12, rect.height() // 2 - spark.height() - 6)
        p.drawPixmap(sx, sy, spark)
        p.setPen(QColor('#6b6b70'))
        font = p.font()
        font.setPointSize(11)
        p.setFont(font)
        tr = QRect(rect)
        tr.setTop(sy + spark.height() + 8)
        p.drawText(tr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap, self._message)
        p.end()

    def refresh(self):
        self.setGeometry(self._view.viewport().rect())

    def set_empty(self, empty):
        if empty:
            self.show()
            # 布局稳定后再定位（首次打开时 viewport 可能还没定型）
            QTimer.singleShot(0, self.refresh)
        else:
            self.hide()

    def eventFilter(self, obj, event):
        if obj is self._view.viewport() and event.type() == QEvent.Type.Resize:
            self.refresh()  # 始终刷新（隐藏时也便宜，避免可见性标志问题）
        return super().eventFilter(obj, event)


class AnimatedTabBar(QTabBar):
    """选中 tab 底部蓝色指示条，随切换滑动（220ms OutCubic）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._indicator = QRect()
        self._anim = None
        self.currentChanged.connect(self._on_current_changed)

    def _indicator_rect(self, index):
        r = self.tabRect(index)
        if r.isNull():
            return QRect()
        return QRect(r.left() + 10, r.bottom() - 3, max(4, r.width() - 20), 3)

    def showEvent(self, e):
        super().showEvent(e)
        self._set_indicator(self._indicator_rect(self.currentIndex()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._set_indicator(self._indicator_rect(self.currentIndex()))

    def _on_current_changed(self, index):
        target = self._indicator_rect(index)
        if self._indicator.isNull():
            self._set_indicator(target)
            return
        anim = QVariantAnimation(self)
        anim.setDuration(220)
        anim.setStartValue(self._indicator)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: self._set_indicator(v))
        anim.finished.connect(lambda: self._set_indicator(target))
        self._anim = anim
        anim.start()

    def _set_indicator(self, rect):
        self._indicator = QRect(round(rect.x()), round(rect.y()),
                                round(rect.width()), round(rect.height()))
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._indicator.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor('#0a84ff')))
        p.drawRoundedRect(self._indicator, 1.5, 1.5)
        p.end()


class AccentBarDelegate(QStyledItemDelegate):
    """选中项左侧蓝色指示条（微信式活跃指示）。"""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = option.rect
            bar = QRect(r.left() + 3, r.top() + 5, 3, max(8, r.height() - 10))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor('#0a84ff')))
            painter.drawRoundedRect(bar, 1.5, 1.5)
            painter.restore()


class SkillGroupList(QTreeWidget):
    """按类型分组的技能勾选列表（分类头 + 技能行），以 **uuid** 为标识。

    - 分类头：粗体弱色、浅色底条，显示「类型 · 已选/总数」；点击整行 = 全选/全不选。
    - 技能行：勾选框 + 名称（— 描述）。
      · row_select_toggles=True（新建角色）：点行任意位置切换勾选（_changed_at 防双重切换）。
      · row_select_toggles=False（技能管理）：点勾选框才切换，点行仅选中（供编辑），
        双击行发 doubleClickedSkill 信号（宿主直接打开编辑）。
    - 勾选/选中/双击都按 uuid 传递（角色 meta 以 uuid 引用技能）。
    """

    doubleClickedSkill = Signal(str)

    def __init__(self, skills, checked_ids=(), category_order=(),
                 row_select_toggles=True, parent=None):
        super().__init__(parent)
        self.setObjectName('skillGroupTree')
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)              # 无展开箭头，纯分组展示
        self.setIndentation(16)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._changed_at = 0
        self._current_uuid = ''
        self._row_select_toggles = row_select_toggles
        self.itemChanged.connect(self._on_changed)
        self.itemClicked.connect(self._on_clicked)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        self._build(skills, checked_ids, category_order)
        self.expandAll()
        self._changed_at = 0  # 构建期 setCheckState 会触发 itemChanged，须清零

    # ---- 构建 ----

    def rebuild(self, skills, checked_ids=(), category_order=()):
        """整体重建（新建/编辑技能后刷新分组与勾选态）。"""
        self.clear()
        self._current_uuid = ''
        self._build(skills, checked_ids, category_order)
        self.expandAll()
        self._changed_at = 0

    def find_item(self, skill_uuid):
        """按技能 uuid 找条目（跨分组）。"""
        for i in range(self.topLevelItemCount()):
            header = self.topLevelItem(i)
            for j in range(header.childCount()):
                c = header.child(j)
                if c.data(0, Qt.ItemDataRole.UserRole) == skill_uuid:
                    return c
        return None

    def _build(self, skills, checked_ids, category_order):
        groups = {}
        for s in skills:
            cat = getattr(s, 'category', '') or '其他'
            groups.setdefault(cat, []).append(s)
        ordered = [c for c in category_order if c in groups]
        ordered += [c for c in groups if c not in ordered]
        checked = set(checked_ids or ())
        for cat in ordered:
            header = QTreeWidgetItem()
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)  # 不可勾选/选中，点击=全选
            header.setData(0, Qt.ItemDataRole.UserRole, cat)
            header.setToolTip(0, '点击整行：全选 / 全不选')
            font = header.font(0)
            font.setBold(True)
            header.setFont(0, font)
            header.setForeground(0, QColor('#9a9aa0'))
            header.setBackground(0, QBrush(QColor('#2b2b30')))
            header.setSizeHint(0, QSize(0, 30))
            self.addTopLevelItem(header)
            for s in groups[cat]:
                label = s.name
                if getattr(s, 'description', ''):
                    label += f'   —   {s.description}'
                item = QTreeWidgetItem([label])
                item.setData(0, Qt.ItemDataRole.UserRole, getattr(s, 'uuid', ''))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if getattr(s, 'uuid', '') in checked
                                   else Qt.CheckState.Unchecked)
                item.setForeground(0, QColor('#d4d4d8'))
                item.setToolTip(0, label)
                header.addChild(item)
            self._refresh_group(header)

    def _refresh_group(self, header):
        n = header.childCount()
        checked = sum(1 for i in range(n)
                      if header.child(i).checkState(0) == Qt.CheckState.Checked)
        cat = header.data(0, Qt.ItemDataRole.UserRole)
        header.setText(0, f'{cat}   ·   {checked}/{n} 已选')

    # ---- 交互 ----

    def _toggle_group(self, header):
        n = header.childCount()
        if n == 0:
            return
        checked = sum(1 for i in range(n)
                      if header.child(i).checkState(0) == Qt.CheckState.Checked)
        new_state = Qt.CheckState.Unchecked if checked == n else Qt.CheckState.Checked
        for i in range(n):
            header.child(i).setCheckState(0, new_state)
        self._refresh_group(header)

    def _on_changed(self, item):
        self._changed_at = time.time()
        if item.parent() is not None:
            self._refresh_group(item.parent())

    def _on_clicked(self, item):
        if item.parent() is None:
            self._toggle_group(item)
            return
        self._current_uuid = item.data(0, Qt.ItemDataRole.UserRole)
        if not self._row_select_toggles:
            return  # 技能管理：点行仅选中（供编辑），勾选只靠勾选框
        if time.time() - self._changed_at < 0.1:  # 勾选框默认已切换，避免双重切换
            return
        item.setCheckState(0, Qt.CheckState.Unchecked
                           if item.checkState(0) == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)
        self._refresh_group(item.parent())

    def _on_double_clicked(self, item, column):
        if self._row_select_toggles or item.parent() is None:
            return
        skill_uuid = item.data(0, Qt.ItemDataRole.UserRole)
        if skill_uuid:
            self.doubleClickedSkill.emit(skill_uuid)

    # ---- 查询 ----

    def selected_uuids(self):
        out = []
        for i in range(self.topLevelItemCount()):
            header = self.topLevelItem(i)
            for j in range(header.childCount()):
                c = header.child(j)
                if c.checkState(0) == Qt.CheckState.Checked:
                    out.append(c.data(0, Qt.ItemDataRole.UserRole))
        return out

    def current_skill_uuid(self):
        return self._current_uuid


class PressButton(QPushButton):
    """主按钮光晕 = 交互状态指示（非装饰性常驻效果）。

    - 静止：无光晕（干净的蓝主按钮，`#btnNew` QSS 已够醒目）
    - 悬停：浮现柔光（表示可操作）
    - 按下：光晕增强、松开 160ms 衰减（按压反馈）

    对应 emil-design-eng「Buttons must feel responsive」与「效果必须有目的」——
    常驻不变的光晕会让人误以为是状态/加载指示。减少动效时退化为瞬态。
    """

    _GLOW = (10, 132, 255)
    _HOVER_T = 0.5          # 悬停强度（0..1）
    _PRESS_T = 1.0
    _PRESS_ALPHA = 215
    _PRESS_BLUR = 38

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._glow_t = 0.0
        self._hovered = False
        self._press_anim = None
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._glow_eff = QGraphicsDropShadowEffect(self)
        self._glow_eff.setOffset(0, 0)
        self.setGraphicsEffect(self._glow_eff)
        self._set_glow(0.0)

    def _set_glow(self, t):
        self._glow_t = t
        r, g, b = self._GLOW
        self._glow_eff.setColor(QColor(r, g, b, int(round(self._PRESS_ALPHA * t))))
        self._glow_eff.setBlurRadius(round(self._PRESS_BLUR * t))
        # 完全静止时关闭效果，避免常驻离屏渲染开销
        self._glow_eff.setEnabled(t > 0.001)

    def _stop_press_anim(self):
        if self._press_anim is not None:
            self._press_anim.stop()
            self._press_anim = None

    def _animate_to(self, target):
        if should_reduce_motion():
            self._set_glow(target)
            return
        self._stop_press_anim()
        anim = QVariantAnimation(self)
        anim.setDuration(160)
        anim.setStartValue(self._glow_t)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._set_glow)
        self._press_anim = anim   # 持有引用，防 GC
        anim.start()

    def _rest_target(self):
        return self._HOVER_T if self._hovered else 0.0

    def enterEvent(self, e):
        self._hovered = True
        if not self.isDown():
            self._animate_to(self._HOVER_T)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        if not self.isDown():
            self._animate_to(0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._stop_press_anim()
            self._set_glow(self._PRESS_T)  # 按下即刻全亮（瞬时反馈）
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._animate_to(self._rest_target())  # 松开衰减到悬停态/静止
        super().mouseReleaseEvent(e)
