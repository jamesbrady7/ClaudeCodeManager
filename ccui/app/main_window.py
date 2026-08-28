"""应用外壳（app 层）：托管各业务模块的 view 面板（tab）。

含全局快捷键（对 Claude Code 这类键盘重度用户是刚需）与 tab 内容淡切。
"""
from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QApplication,
    QLineEdit, QTextEdit, QComboBox, QGraphicsOpacityEffect,
)

from ccui.app.theme import should_reduce_motion
from ccui.app.widgets import AnimatedTabBar
from ccui.app.icons import ui_icon
from ccui.infra.config import load_ui_state, save_ui_state
from ccui.session.view.session_panel import SessionPanel
from ccui.role.view.role_panel import RolePanel
from ccui.skill.view.skill_panel import SkillPanel
from ccui.provider.view.provider_panel import ProviderPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CC 会话管理')
        self.resize(1440, 820)
        self.tabs = QTabWidget()
        self.tabs.setTabBar(AnimatedTabBar(self.tabs))  # 选中蓝条滑动指示
        # 会话模块面板
        self.session_panel = SessionPanel()
        self.session_panel.status_message.connect(
            lambda text, ms: self.statusBar().showMessage(text, ms))
        self.tabs.addTab(self.session_panel,
                         ui_icon('message-square', 14), '会话')
        # 角色模块面板（左角色列表 + 右会话/详情）
        self.role_panel = RolePanel()
        self.role_panel.status_message.connect(
            lambda text, ms: self.statusBar().showMessage(text, ms))
        self.tabs.addTab(self.role_panel, ui_icon('users', 14), '角色')
        # 技能模块面板（技能库：浏览/新建/编辑/删除 + 被引用计数）
        self.skill_panel = SkillPanel()
        self.skill_panel.status_message.connect(
            lambda text, ms: self.statusBar().showMessage(text, ms))
        self.tabs.addTab(self.skill_panel, ui_icon('wrench', 14), '技能')
        # Provider 配置面板（「模型」tab：两层 provider+模型，写 cc-config.json）
        self.provider_panel = ProviderPanel()
        self.provider_panel.status_message.connect(
            lambda text, ms: self.statusBar().showMessage(text, ms))
        # 「用此 Provider 新建会话」→ 复用会话面板的新建向导（带 provider/model 预置）
        self.provider_panel.new_session_requested.connect(
            lambda prov, model: (self.tabs.setCurrentIndex(0),
                                 self.session_panel.on_new_session(prov, model)))
        self.tabs.addTab(self.provider_panel, ui_icon('boxes', 14), '模型')
        self.setCentralWidget(self.tabs)
        # 快捷键 + tab 淡切：在 tab 全部加入后再接线，避免首次设置即触发
        self._setup_shortcuts()
        # 恢复上次选中的 tab（连线前，避免触发淡切）
        state = load_ui_state()
        last = state.get('last_tab', 0)
        self.tabs.setCurrentIndex(max(0, min(last, self.tabs.count() - 1)))
        self.tabs.currentChanged.connect(self._fade_tab_in)
        self.tabs.currentChanged.connect(self._save_tab)

    def _save_tab(self, index):
        save_ui_state({'last_tab': index})

    # ---- 全局快捷键 ----
    def _setup_shortcuts(self):
        sc = lambda *seq: QShortcut(QKeySequence(*seq), self)
        sc('Ctrl+N').activated.connect(self.session_panel.on_new_session)
        sc('Ctrl+F').activated.connect(self._focus_search)
        sc('Ctrl+R').activated.connect(self.session_panel._rescan)
        self._sc_delete = sc('Delete')
        self._sc_delete.activated.connect(self._delete_context)

    def _focus_search(self):
        self.session_panel.edit_search.setFocus()
        self.session_panel.edit_search.selectAll()

    def _delete_context(self):
        """Delete：删除选中会话（仅会话 tab；输入框内不触发，避免误删）。"""
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QTextEdit, QComboBox)):
            return
        if self.tabs.currentIndex() == 0:
            self.session_panel.on_delete()

    # ---- tab 内容淡切 ----
    def _fade_tab_in(self, index):
        """切换到新 tab 时内容 200ms 淡入（动画后移除 effect，避免常驻栅格化）。"""
        if should_reduce_motion():
            return
        w = self.tabs.widget(index)
        if w is None:
            return
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b'opacity', w)
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: w.setGraphicsEffect(None))
        self._tab_anim = anim   # 持有引用，防 GC
        anim.start()
