"""应用级 Apple 风格深色主题 + 显示工具（app 层，各 view 共享）。"""
import os
import datetime

# 显式颜色（QSS 下 palette() 不可靠）
COLOR_GROUP = '#a1a1a6'   # 分组标题（macOS 侧栏标签，柔和灰）
COLOR_MUTED = '#98989d'   # 次要文字
COLOR_EMPTY = '#98989d'   # 空会话 / 等待输入
COLOR_LIVE  = '#ff453a'   # LIVE 徽标（Apple 红）

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
ICON_PATH = os.path.join(ASSETS_DIR, 'icon.png')
ICON_ICO = os.path.join(ASSETS_DIR, 'icon.ico')  # Windows 任务栏/标题栏最认 ICO


def set_dark_title_bar(window):
    """让 Windows 原生标题栏跟随深色主题（Qt QSS 管不到原生标题栏）。

    DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win11) / 19 (Win10)。
    """
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(window.winId())
        value = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi
        for attr in (20, 19):
            try:
                if dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr,
                                             ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
            except Exception:
                continue
    except Exception:
        pass

DARK_QSS = """
QMainWindow, QWidget {
    background: #1e1e1e;
    color: #f5f5f7;
    font-size: 13px;
}

/* ---- 应用外壳：分段式选项卡 ---- */
QTabWidget::pane { border: none; background: #1e1e1e; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: #a1a1a6;
    padding: 6px 18px;
    border-radius: 9px;
    margin: 3px 2px;
    font-weight: 500;
}
QTabBar::tab:selected { background: #3a3a3c; color: #f5f5f7; }
QTabBar::tab:hover:!selected { color: #d4d4d8; }

/* ---- 会话列表 ---- */
QTreeWidget {
    background: #232326;
    border: 1px solid #38383a;
    border-radius: 10px;
    padding: 4px;
    outline: none;
    alternate-background-color: #262629;
}
QTreeWidget::item {
    padding: 2px 4px;
    border-radius: 6px;
}
QTreeWidget::item:hover { background: #2c2c2e; }
QTreeWidget::item:disabled { color: #6b6b70; }
QTreeWidget::item:selected { background: #0a84ff; color: #ffffff; }
QTreeWidget::item:selected:!active { background: #3a3a3c; color: #f5f5f7; }
QTreeWidget::indicator {
    width: 16px; height: 16px;
    border: 1px solid #55555a;
    background: #2a2a2c;
    border-radius: 4px;
}
QTreeWidget::indicator:checked { background: #0a84ff; border-color: #0a84ff; }
QTreeWidget::indicator:indeterminate { background: #0a84ff; border-color: #0a84ff; }
QTreeWidget::indicator:disabled { background: #2a2a2c; border-color: #3f3f46; }
QHeaderView::section {
    background: #232326;
    color: #a1a1a6;
    border: none;
    border-bottom: 1px solid #38383a;
    padding: 6px 8px;
    font-weight: 500;
}

/* ---- 按钮（macOS 圆角风格） ---- */
QPushButton {
    background: #3a3a3c;
    color: #f5f5f7;
    border: 1px solid #4a4a4e;
    border-radius: 8px;
    padding: 6px 16px;
}
QPushButton:hover { background: #454549; }
QPushButton:pressed { background: #2f2f31; }
QPushButton:disabled { color: #6b6b70; background: #2a2a2c; border-color: #3f3f46; }
QPushButton[danger="true"] {
    background: rgba(255, 69, 58, 0.14);
    border-color: rgba(255, 69, 58, 0.4);
    color: #ff6961;
}
QPushButton[danger="true"]:hover { background: rgba(255, 69, 58, 0.24); }
QPushButton#btnNew {
    background: #0a84ff;
    border: none;
    color: white;
    font-weight: 600;
    padding: 6px 20px;
}
QPushButton#btnNew:hover { background: #2b93ff; }
QPushButton#btnNew:pressed { background: #0068d6; }
QPushButton#btnResume {
    padding: 3px 8px;
    min-height: 20px;
    border-radius: 6px;
    font-size: 12px;
}

/* ---- 输入框 ---- */
QLineEdit {
    background: #2a2a2c;
    border: 1px solid #3f3f46;
    color: #f5f5f7;
    border-radius: 8px;
    padding: 5px 10px;
}
QLineEdit:focus { border-color: #0a84ff; }

/* ---- 细圆角滚动条 ---- */
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #4a4a4e; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #5a5a5e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: #4a4a4e; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ---- 状态栏 ---- */
QStatusBar { background: #1e1e1e; color: #a1a1a6; border-top: 1px solid #2a2a2c; }

/* ---- 悬停提示框 ---- */
QToolTip {
    background-color: #2e2e30;
    color: #f5f5f7;
    border: 1px solid #4a4a4e;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
}
"""


def fmt_size(n):
    if n < 1024:
        return f'{n} B'
    if n < 1024 * 1024:
        return f'{n / 1024:.1f} KB'
    return f'{n / 1024 / 1024:.2f} MB'


def fmt_time(ts):
    if not ts:
        return ''
    try:
        dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
        return dt.strftime('%m-%d %H:%M')
    except Exception:
        return ts


def trunc(s, n):
    return s if len(s) <= n else s[:n] + '…'
