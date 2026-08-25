"""启动飞屏：可爱的 Claude Code 启动画面 + 启动预热。

在飞屏展示期间完成数据/单例/对话框预热，把首次打开的一次性成本
（大 transcript 全量解析、角色 uuid 回填、对话框原生窗口创建 + QSS 首帧）
挪到启动阶段，之后主界面交互不再卡顿、弹窗不再闪。
"""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPixmap, QPainter, QPainterPath, QColor, QFont, QLinearGradient, QBrush, QPen,
)
from PySide6.QtWidgets import QApplication, QSplashScreen

SPLASH_W = 520
SPLASH_H = 340

CORAL = QColor('#d97757')          # Claude 珊瑚色
CORAL_DARK = QColor('#b35c3f')     # 描边深珊瑚
FACE = QColor('#2b1d18')           # 表情深棕
CHEEK = QColor(255, 120, 120, 80)  # 腮红半透明
GOLD = QColor('#f2c98a')           # 点缀小星淡金


def _draw_cute_spark(p: QPainter, cx: float, cy: float, r: float):
    """画一只 Claude spark 小可爱：4 点星芒身体 + 大眼睛 + 微笑 + 腮红。"""
    inner = r * 0.38
    path = QPainterPath(QPointF(cx, cy - r))            # 上
    path.quadTo(cx + inner, cy - inner, cx + r, cy)     # 右
    path.quadTo(cx + inner, cy + inner, cx, cy + r)     # 下
    path.quadTo(cx - inner, cy + inner, cx - r, cy)     # 左
    path.quadTo(cx - inner, cy - inner, cx, cy - r)     # 回上闭合
    # 身体
    p.setPen(QPen(CORAL_DARK, max(2.0, r * 0.045)))
    p.setBrush(QBrush(CORAL))
    p.drawPath(path)
    # 眼睛（大圆眼 + 瞳孔 + 高光）
    eye_dx, eye_y, eye_r = r * 0.34, cy - r * 0.06, r * 0.15
    for sx in (-1, 1):
        ex = cx + sx * eye_dx
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor('#fffdfa')))
        p.drawEllipse(QPointF(ex, eye_y), eye_r, eye_r * 1.18)
        p.setBrush(QBrush(FACE))
        p.drawEllipse(QPointF(ex + sx * eye_r * 0.3, eye_y + eye_r * 0.16),
                      eye_r * 0.52, eye_r * 0.52)
        p.setBrush(QBrush(QColor('#ffffff')))
        p.drawEllipse(QPointF(ex - sx * eye_r * 0.16, eye_y - eye_r * 0.24),
                      eye_r * 0.2, eye_r * 0.2)
    # 微笑
    smile = QPainterPath()
    smile.moveTo(cx - r * 0.24, cy + r * 0.34)
    smile.quadTo(cx, cy + r * 0.52, cx + r * 0.24, cy + r * 0.34)
    p.setPen(QPen(FACE, max(2.5, r * 0.06), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(smile)
    # 腮红
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(CHEEK))
    for sx in (-1, 1):
        p.drawEllipse(QPointF(cx + sx * r * 0.66, cy + r * 0.2), r * 0.12, r * 0.07)


def _draw_tiny_star(p: QPainter, cx: float, cy: float, r: float):
    path = QPainterPath(QPointF(cx, cy - r))
    inner = r * 0.4
    path.quadTo(cx + inner, cy - inner, cx + r, cy)
    path.quadTo(cx + inner, cy + inner, cx, cy + r)
    path.quadTo(cx - inner, cy + inner, cx - r, cy)
    path.quadTo(cx - inner, cy - inner, cx, cy - r)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(GOLD))
    p.drawPath(path)


def draw_splash_pixmap():
    """用 QPainter 画启动画面：深色圆角卡片 + 可爱的 Claude spark + 标题。"""
    pm = QPixmap(SPLASH_W, SPLASH_H)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 圆角卡片（深色渐变 + 细描边）
    card = QRectF(0, 0, SPLASH_W, SPLASH_H)
    grad = QLinearGradient(0, 0, 0, SPLASH_H)
    grad.setColorAt(0.0, QColor('#2d2d31'))
    grad.setColorAt(1.0, QColor('#1c1c1e'))
    p.setPen(QPen(QColor('#3d3d42'), 1.5))
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(card, 26, 26)
    # 角色与点缀小星
    _draw_cute_spark(p, SPLASH_W // 2, 128, 80)
    _draw_tiny_star(p, 128, 88, 10)
    _draw_tiny_star(p, 396, 72, 8)
    _draw_tiny_star(p, 402, 168, 6)
    # 标题
    p.setPen(QColor('#f5f5f7'))
    f = QFont()
    f.setPointSize(22)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 228, SPLASH_W, 44), Qt.AlignmentFlag.AlignCenter, 'CC 会话管理')
    # 副标题
    p.setPen(QColor('#98989d'))
    f2 = QFont()
    f2.setPointSize(10)
    p.setFont(f2)
    p.drawText(QRectF(0, 276, SPLASH_W, 26), Qt.AlignmentFlag.AlignCenter,
               'Claude Code · 本地会话管理')
    p.end()
    return pm


def spark_pixmap(size):
    """单个 Claude spark 小可爱的透明 pixmap（空状态等复用，品牌一致）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_cute_spark(p, size / 2, size / 2, size * 0.42)
    p.end()
    return pm


def warning_pixmap(size):
    """小三角警告图标（警示场景，替代 emoji ⚠）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    tri = QPainterPath(QPointF(size / 2, size * 0.08))
    tri.lineTo(size * 0.94, size * 0.90)
    tri.lineTo(size * 0.06, size * 0.90)
    tri.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor('#ff9f0a')))
    p.drawPath(tri)
    p.setPen(QPen(QColor('#2b1d18'), max(1.6, size * 0.09), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(size / 2, size * 0.34), QPointF(size / 2, size * 0.62))
    p.drawPoint(QPointF(size / 2, size * 0.76))
    p.end()
    return pm


class SplashScreen(QSplashScreen):
    """启动飞屏：置顶显示可爱画面，支持阶段状态文案。"""

    def __init__(self):
        super().__init__(draw_splash_pixmap(), Qt.WindowType.WindowStaysOnTopHint)
        self.show()
        QApplication.processEvents()

    def status(self, text):
        self.showMessage(text, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                         QColor('#a1a1a6'))
        QApplication.processEvents()


def prewarm(splash=None):
    """飞屏期间预热：数据缓存 + 单例 + 对话框首开成本。"""
    from ccui.session.data.manager import SessionManager
    from ccui.role.data.manager import RoleManager

    def status(t):
        if splash:
            splash.status(t)

    status('预热会话数据…')
    sm = SessionManager.instance()
    sm.by_id()      # 预热 transcript 解析缓存（大文件全读只在启动做一次）
    status('检查运行中会话…')
    sm.live_ids()   # 预热进程存活检测
    status('加载角色…')
    RoleManager.instance().roles()  # 预热角色（含 uuid 回填）
    status('加载技能…')
    from ccui.skill.data.manager import SkillManager
    SkillManager.instance().skills()          # 触发技能 uuid 自动回填
    from ccui.skill.migrate import run as _migrate
    _migrate()                                # 幂等：角色 meta 名→uuid 自愈
    status('预热界面组件…')
    _prewarm_dialogs()
    if splash:
        splash.clearMessage()


def _prewarm_dialogs():
    """show+hide（不绘制）：把原生窗口创建 + QSS 首帧成本挪到启动阶段。"""
    from ccui.session.view.dialogs import DeleteDialog, ResumeDialog, InheritDialog
    try:
        for d in (
            DeleteDialog([('预热', '')], 0),
            ResumeDialog('normal', '预热', ['(无)'], '(无)'),
            InheritDialog([]),
        ):
            d.show()
            d.hide()
    except Exception:
        pass
