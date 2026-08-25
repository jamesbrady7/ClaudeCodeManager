"""应用级 Apple 风格深色主题 + 显示工具（app 层，各 view 共享）。"""
import os
import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect

from ccui.infra.config import ASSETS_DIR
from ccui.infra.utils import trunc  # 统一截断工具（重导出，供各 view 从 theme 引用）

# 显式颜色（QSS 下 palette() 不可靠）
COLOR_GROUP = '#a1a1a6'   # 分组标题（macOS 侧栏标签，柔和灰）
COLOR_MUTED = '#98989d'   # 次要文字
COLOR_EMPTY = '#98989d'   # 空会话 / 等待输入
COLOR_LIVE  = '#ff453a'   # LIVE 徽标（Apple 红）

ICON_PATH = os.path.join(ASSETS_DIR, 'icon.png')
ICON_ICO = os.path.join(ASSETS_DIR, 'icon.ico')  # Windows 任务栏/标题栏最认 ICO


def apply_glow(widget, color=QColor(10, 132, 255, 130), blur=22, dy=0):
    """给控件加柔光（Qt 版 box-shadow）：主按钮蓝色光晕，增加材质质感。"""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setColor(color)
    eff.setOffset(0, dy)
    widget.setGraphicsEffect(eff)
    return eff


def apply_shadow(widget, blur=18, dy=3, alpha=50):
    """柔和投影：让面板/侧栏浮起（Qt 版 box-shadow）。"""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setColor(QColor(0, 0, 0, alpha))
    eff.setOffset(0, dy)
    widget.setGraphicsEffect(eff)
    return eff


def should_reduce_motion():
    """系统关闭「显示动画」时返回 True（Windows）。动画入口都应先查它。

    减少动效 ≠ 零动效：保留不透明度/颜色过渡（辅助理解），跳过位移/进场动画。
    """
    try:
        import ctypes
        SPI_GETCLIENTAREAANIMATION = 0x1042
        v = ctypes.c_uint()
        if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(v), 0):
            return v.value == 0
    except Exception:
        pass
    return False


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
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #222226, stop:1 #18181b);
    color: #f5f5f7;
    font-size: 13px;
}

/* ---- 应用外壳：分段式选项卡 ---- */
QTabWidget::pane { border: none; background: #1b1b1e; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: #9a9aa0;
    padding: 7px 18px;
    border-radius: 9px;
    margin: 3px 2px;
    font-weight: 500;
}
QTabBar::tab:selected { background: #3a3a3e; color: #f5f5f7; }
QTabBar::tab:hover:!selected { color: #d4d4d8; }

/* ---- 会话列表（柔化描边、无斑马纹、留白） ---- */
QTreeWidget {
    background: #242428;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 6px;
    outline: none;
}
QTreeWidget::item {
    padding: 7px 10px;
    border-radius: 7px;
    /* 注意：不要设 color —— 会覆盖 setForeground（LIVE 呼吸/红色全靠它） */
}
QTreeWidget::item:hover {
    background: rgba(255, 255, 255, 0.06);
    border-left: 2px solid rgba(10, 132, 255, 0.45);  /* 悬停左缘淡蓝条 */
}
QTreeWidget::item:disabled { color: #6b6b70; }
QTreeWidget::item:selected { background: #0a84ff; color: #ffffff; }
QTreeWidget::item:selected:!active { background: #3a3a3e; color: #f5f5f7; }
QTreeWidget::indicator {
    width: 16px; height: 16px;
    border: 1px solid rgba(255, 255, 255, 0.20);
    background: #242428;
    border-radius: 4px;
}
QTreeWidget::indicator:checked { background: #0a84ff; border-color: #0a84ff; }
QTreeWidget::indicator:indeterminate { background: #0a84ff; border-color: #0a84ff; }
QTreeWidget::indicator:disabled { background: #242428; border-color: rgba(255, 255, 255, 0.10); }

/* ---- 技能分组列表（按类型分组勾选：选中=灰而非蓝，与全局一致） ---- */
QTreeWidget#skillGroupTree::item:selected { background: #3a3a3e; color: #f5f5f7; }
QTreeWidget#skillGroupTree::item:selected:!active { background: #3a3a3e; color: #f5f5f7; }

/* ---- 键盘焦点可见性：树/列表聚焦时外圈淡蓝（不刺眼但有迹可循） ---- */
QTreeWidget:focus, QListWidget:focus {
    border: 1px solid rgba(10, 132, 255, 0.45);
}
QListWidget::indicator {
    width: 16px; height: 16px;
    border: 1px solid rgba(255, 255, 255, 0.20);
    background: #242428;
    border-radius: 4px;
}
QListWidget::indicator:checked { background: #0a84ff; border-color: #0a84ff; }
QListWidget::indicator:indeterminate { background: #0a84ff; border-color: #0a84ff; }

/* ---- QListWidget 统一（角色列表/技能列表：浅表面 + 大留白 + 灰选中而非蓝） ---- */
QListWidget {
    background: #202024;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    color: #f5f5f7;               /* 钉死文字色：失焦不变 */
    padding: 8px 10px;
    border-radius: 8px;
    margin: 1px 2px;
}
QListWidget::item:hover { background: rgba(255, 255, 255, 0.06); }
QListWidget::item:selected { background: #3a3a3e; color: #f5f5f7; }
QListWidget::item:selected:!active { background: #3a3a3e; color: #f5f5f7; }
QListWidget::item:disabled { color: #6b6b70; }
QHeaderView::section {
    background: transparent;
    color: #9a9aa0;
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
    padding: 8px 10px;
    font-weight: 600;
}

/* ---- 按钮（垂直渐变质感 + 柔化描边） ---- */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #46464a, stop:1 #343438);
    color: #f5f5f7;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 8px;
    padding: 6px 16px;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #4e4e52, stop:1 #3b3b3f);
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #313135, stop:1 #404044);
}
QPushButton:disabled {
    color: #6b6b70;
    background: #2a2a2e;
    border-color: rgba(255, 255, 255, 0.05);
}
/* 注意：Qt QSS 的 background 简写会忽略 rgba 的 alpha（渲染成不透明），
   危险按钮改用不透明暗红近似 14% 红染的意图，避免纯红块遮挡图标 */
QPushButton[danger="true"] {
    background: #3d2423;
    border-color: rgba(255, 69, 58, 0.4);
    color: #ff6961;
}
QPushButton[danger="true"]:hover { background: #472a28; }
QPushButton#btnNew {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #2b93ff, stop:1 #0a84ff);
    border: 1px solid rgba(255, 255, 255, 0.18);
    color: white;
    font-weight: 600;
    padding: 6px 20px;
}
QPushButton#btnNew:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #3a9dff, stop:1 #158eff);
}
QPushButton#btnNew:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #0876e8, stop:1 #1b8bf0);
}
QPushButton#btnResume {
    padding: 3px 8px;
    min-height: 20px;
    border-radius: 6px;
    font-size: 12px;
}

/* 纯图标按钮：去掉全局 padding，图标在固定尺寸框内真正居中 */
QPushButton#iconBtn {
    padding: 0;
    border-radius: 8px;
}

/* ---- 输入框（QLineEdit 与 QTextEdit 统一样式 + 聚焦蓝框） ---- */
QLineEdit, QTextEdit {
    background: #202024;
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: #f5f5f7;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #0a84ff;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus { border-color: #0a84ff; }

/* ---- 细圆角滚动条（半透明柔和） ---- */
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.16); border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.26); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: rgba(255, 255, 255, 0.16); border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ---- 右键菜单（浅表面 + 留白 + 悬停） ---- */
QMenu {
    background: #2c2c30;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 20px;
    border-radius: 6px;
    color: #f5f5f7;
}
QMenu::item:selected { background: #3a3a3e; }
QMenu::item:disabled { color: #6b6b70; }
QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 0.08);
    margin: 4px 10px;
}

/* ---- 工具栏条带（底部细分割，层次分明） ---- */
QFrame#toolbarBar {
    background: transparent;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}

/* ---- 状态栏 ---- */
QStatusBar { background: #1b1b1e; color: #9a9aa0; border-top: 1px solid rgba(255, 255, 255, 0.06); }

/* ---- 悬停提示框 ---- */
QToolTip {
    background-color: #2c2c30;
    color: #f5f5f7;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
}
"""


# 技能树分组箭头（独立可点；收起=指向右、展开=指向下）。QSS url 需正斜杠。
_chevron_dir = os.path.join(ASSETS_DIR, 'icons').replace(os.sep, '/')
_branch_qss = (
    'QTreeWidget#skillGroupTree::branch:has-children:!has-siblings:closed,\n'
    'QTreeWidget#skillGroupTree::branch:closed:has-children {\n'
    f'    image: url("{_chevron_dir}/chevron-right-color.svg");\n'
    '}\n'
    'QTreeWidget#skillGroupTree::branch:open:has-children {\n'
    f'    image: url("{_chevron_dir}/chevron-down-color.svg");\n'
    '}\n'
)
DARK_QSS += _branch_qss


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


def fmt_relative(ts):
    """相对时间：刚刚 / N 分钟前 / N 小时前 / N 天前 / MM-DD HH:MM（超一周回退）。"""
    if not ts:
        return ''
    try:
        dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
    except Exception:
        return fmt_time(ts)
    secs = (datetime.datetime.now().astimezone() - dt).total_seconds()
    if secs < 0:
        return fmt_time(ts)
    if secs < 60:
        return '刚刚'
    if secs < 3600:
        return f'{int(secs // 60)} 分钟前'
    if secs < 86400:
        return f'{int(secs // 3600)} 小时前'
    if secs < 7 * 86400:
        return f'{int(secs // 86400)} 天前'
    return fmt_time(ts)
