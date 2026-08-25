"""图标工厂（app 层）：provider / 角色 徽章 + Lucide UI 图标。

优先用自定义图片（provider: assets/providers/<name>.png；角色: roles/<name>/icon.png），
否则 QPainter 画首字母彩色徽章。ui_icon 从 assets/icons/<name>.svg（Lucide）渲染。
"""
import os
import zlib

from PySide6.QtCore import Qt, QRectF, QByteArray
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QBrush
from PySide6.QtWidgets import QApplication

from ccui.infra.config import ASSETS_DIR

_PROVIDER_INITIALS = {'deepseek': 'DS', 'glm': 'GL'}
_PROVIDER_COLORS = {
    'deepseek': QColor('#4d6bfe'),
    'glm': QColor('#3b9eff'),
}
_ROLE_COLORS = [
    QColor('#5e9cff'), QColor('#ff7a5c'), QColor('#5fd08a'),
    QColor('#b583ff'), QColor('#ffcc66'), QColor('#3ec6c0'),
]


def _badge_pixmap(initials, color, size):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
    f = QFont()
    f.setPointSizeF(max(5.0, size * 0.40))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor('#ffffff'))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, initials)
    p.end()
    return pm


_UI_ICON_CACHE = {}  # (name, size, color) → QIcon（树重建/工具栏热路径，渲染一次复用）


def ui_icon(name, size=16, color='#c8c8cc'):
    """Lucide 图标：读 assets/icons/<name>.svg，把 currentColor 换成指定色，HiDPI 渲染 QIcon。

    color 传十六进制如 '#f5f5f7'；danger 用 '#ff6961' 等。按 (name,size,color) 缓存避免重复渲染。
    """
    key = (name, size, color)
    cached = _UI_ICON_CACHE.get(key)
    if cached is not None:
        return cached
    path = os.path.join(ASSETS_DIR, 'icons', f'{name}.svg')
    if not os.path.exists(path):
        return QIcon()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            svg = f.read()
        svg = svg.replace('currentColor', color)
        from PySide6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
        app = QApplication.instance()
        dpr = app.devicePixelRatio() if app and app.devicePixelRatio() > 1.0 else 1.0
        px = int(round(size * dpr))
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 关键：DPR pixmap 上 QPainter 用逻辑坐标，渲染矩形必须传 size（逻辑），
        # 传 px（物理）会让图标放大并右/下溢出被裁剪（高 DPI 下右缘被挡住）
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
        icon = QIcon(pm)
        _UI_ICON_CACHE[key] = icon
        return icon
    except Exception:
        return QIcon()


def provider_icon(name, size=16):
    """provider 徽章：assets/providers/<name>.png|.svg 存在则用之，否则画品牌色首字母徽章。"""
    name = name or ''
    if name:
        for ext in ('.png', '.svg'):
            p = os.path.join(ASSETS_DIR, 'providers', f'{name.lower()}{ext}')
            if os.path.exists(p):
                return QIcon(p)
    initials = _PROVIDER_INITIALS.get(name.lower())
    if not initials:
        initials = ''.join(ch for ch in name if ch.isalnum())[:2].upper() or '?'
    color = _PROVIDER_COLORS.get(name.lower(), QColor('#6e6e73'))
    return QIcon(_badge_pixmap(initials, color, size))


def role_icon(name, icon_path=None, size=20):
    """角色图标：icon_path（roles/<name>/icon.*）存在则用之，否则画首字母彩色徽章。"""
    if icon_path and os.path.exists(icon_path):
        return QIcon(icon_path)
    name = name or '?'
    initial = (name[:1] or '?').upper()
    colors = _ROLE_COLORS
    color = colors[zlib.crc32(name.encode('utf-8')) % len(colors)]
    return QIcon(_badge_pixmap(initial, color, size))


def role_icon_full(name, icon_path=None, size=44):
    """详情区大头像：无灰底容器，图标裁剪透明边距后铺满（彩色 logo 在深色底清晰）。"""
    if icon_path and os.path.exists(icon_path):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        content = _svg_content_pixmap(icon_path) if icon_path.lower().endswith('.svg') else QPixmap(icon_path)
        inner = round(size * 0.9)
        content = content.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap((size - content.width()) // 2, (size - content.height()) // 2, content)
        p.end()
        return QIcon(pm)
    return role_icon(name, None, size)


_SVG_CACHE = {}  # (path, mtime, size) → 裁剪后 pixmap


def _svg_content_pixmap(path):
    """渲染 SVG 并裁剪透明边距，得到仅含图标的 pixmap（避免 logo 自带留白显小）。

    缓存按 (path, mtime, size) 键——角色换头像会**覆盖写同一文件**，若只按 path
    缓存会返回旧图（头像保存不生效）。文件 mtime/size 变化即自动失效。
    """
    try:
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
    except Exception:
        key = path
    if key in _SVG_CACHE:
        return _SVG_CACHE[key]
    from PySide6.QtSvg import QSvgRenderer
    tmp = QPixmap(128, 128)
    tmp.fill(Qt.GlobalColor.transparent)
    tp = QPainter(tmp)
    renderer = QSvgRenderer(path)
    renderer.render(tp, QRectF(0, 0, 128, 128))
    tp.end()
    img = tmp.toImage()
    min_x = min_y = 127
    max_x = max_y = 0
    for x in range(128):
        for y in range(128):
            if img.pixelColor(x, y).alpha() > 8:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    if max_x <= min_x or max_y <= min_y:
        result = QPixmap(path)
    else:
        result = QPixmap.fromImage(img.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))
    if len(_SVG_CACHE) >= 200:
        _SVG_CACHE.clear()
    _SVG_CACHE[key] = result
    return result


def role_avatar(name, icon_path=None, size=28):
    """微信式角色头像：自定义图标裁剪透明边距后铺满圆角浅底容器（黑色图标也可见）。"""
    if icon_path and os.path.exists(icon_path):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor('#3f3f46')))   # 浅灰底，衬托黑色图标
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.26, size * 0.26)
        # 源图标（SVG 裁剪透明边距，PNG 原样）
        content = _svg_content_pixmap(icon_path) if icon_path.lower().endswith('.svg') else QPixmap(icon_path)
        inner = round(size * 0.86)
        content = content.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap((size - content.width()) // 2, (size - content.height()) // 2, content)
        p.end()
        return QIcon(pm)
    return role_icon(name, None, size)
