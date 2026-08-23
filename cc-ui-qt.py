# ============================================================
#  cc-ui-qt.py  —  Claude Code 会话管理桌面应用入口（PySide6）
#
#  横纵分层架构（见 ccui/ 包）：
#    横向：session / role 等业务模块
#    纵向：每个模块内部 data | service | view
#    infra：基础设施层（位于 data 之下，人人可调用）
#
#  用法:
#    cc ui                     （cc.cmd 用 pythonw 启动本应用）
#    python cc-ui-qt.py        直接启动
#
#  环境变量:
#    CLAUDE_CONFIG_DIR   配置目录（默认 D:\ClaudeCode）
#    CC_UI_READONLY=1    只读模式（禁用删除，用于安全验证）
#
#  依赖: PySide6, psutil  (pip install PySide6 psutil)
# ============================================================

import sys
import traceback

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QIcon

from ccui.infra.config import log
from ccui.app.theme import DARK_QSS, ICON_ICO, set_dark_title_bar
from ccui.app.main_window import MainWindow
from ccui.app.splash import SplashScreen, prewarm


class DarkTitleBarFilter(QObject):
    """所有顶层窗口/弹窗显示时自动切深色原生标题栏。"""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            set_dark_title_bar(obj)
        return False


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(DARK_QSS)
    app.setWindowIcon(QIcon(ICON_ICO))   # 应用级默认图标（ICO，任务栏可靠）
    app.installEventFilter(DarkTitleBarFilter(app))
    # 启动飞屏：展示期间预热数据/单例/对话框，主界面构建复用热缓存
    splash = SplashScreen()
    prewarm(splash)
    win = MainWindow()
    win.setWindowIcon(QIcon(ICON_ICO))   # 显式设到主窗口，确保任务栏/标题栏
    win.show()
    splash.finish(win)
    sys.exit(app.exec())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log('致命错误:\n' + traceback.format_exc())
        raise
