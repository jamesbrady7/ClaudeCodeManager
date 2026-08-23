"""应用外壳（app 层）：托管各业务模块的 view 面板（tab）。"""
from PySide6.QtWidgets import QMainWindow, QTabWidget

from ccui.session.view.session_panel import SessionPanel
from ccui.role.view.role_panel import RolePanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CC 会话管理')
        self.resize(1000, 640)
        self.tabs = QTabWidget()
        # 会话模块面板
        self.session_panel = SessionPanel()
        self.session_panel.status_message.connect(
            lambda text, ms: self.statusBar().showMessage(text, ms))
        self.tabs.addTab(self.session_panel, '会话')
        # 角色模块面板（左角色列表 + 右会话/详情）
        self.role_panel = RolePanel()
        self.role_panel.status_message.connect(
            lambda text, ms: self.statusBar().showMessage(text, ms))
        self.tabs.addTab(self.role_panel, '角色')
        self.setCentralWidget(self.tabs)
