"""对话框通用（app 层）：淡入入场动画，避免弹窗生硬闪现。

按 emil-design-eng / find-animation-opportunities 原则：弹窗属「偶尔出现」
→ 标准动画（<300ms、进场 ease-out）。淡入从 opacity 0 开始，
顺带盖住首次显示的原生窗口白闪。

**不做退场淡出**：windowOpacity 动画让对话框变透明时会暴露并强制重混合底下
的主窗口，主窗口上的投影/光晕等 graphics effect 会闪烁一下（用户实测）。
关闭保持即时；进场（从不透明往上盖）无此问题。
"""
from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from ccui.app.theme import should_reduce_motion

FADE_MS = 220


def mk_buttons(dialog, ok_text, cancel_text='取消', danger_ok=False):
    """统一装配对话框 OK/Cancel 按钮并连接 accept/reject。返回 QDialogButtonBox。

    省去各对话框重复的 6 行装配；danger_ok 给危险操作（删除）用红字确认按钮。
    """
    btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    ok = btns.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(ok_text)
    if danger_ok:
        ok.setStyleSheet('background:rgba(255,69,58,.2);color:#ff6961;'
                         'border:1px solid rgba(255,69,58,.4);border-radius:8px;padding:6px 16px;')
    btns.button(QDialogButtonBox.StandardButton.Cancel).setText(cancel_text)
    btns.accepted.connect(dialog.accept)
    btns.rejected.connect(dialog.reject)
    return btns


def fade_in(dialog):
    """对话框淡入：windowOpacity 0→1，OutCubic 220ms。"""
    if should_reduce_motion():
        return
    dialog.setWindowOpacity(0.0)
    anim = QPropertyAnimation(dialog, b'windowOpacity', dialog)
    anim.setDuration(FADE_MS)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    dialog._fade_anim = anim   # 持有引用，防止动画被 GC
    anim.start()


class FadeDialog(QDialog):
    """带淡入入场动画的对话框基类（关闭即时，避免退场动画引发主窗闪烁）。"""

    def showEvent(self, event):
        super().showEvent(event)
        fade_in(self)
