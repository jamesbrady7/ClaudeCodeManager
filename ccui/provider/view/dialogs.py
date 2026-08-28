"""Provider 模块对话框（view 层）。"""
import re

from PySide6.QtWidgets import (
    QVBoxLayout, QFormLayout, QLineEdit, QLabel, QCheckBox,
    QDialogButtonBox,
)

from ccui.app.dialogs import FadeDialog, mk_buttons
from ccui.app.icons import ui_icon
from ccui.provider.data.store import valid_model_name


class ProviderEditDialog(FadeDialog):
    """新建/编辑 Provider（名称/baseUrl/apiKey）。key 存 provider 级，模型在面板管理。

    编辑态传 existing=(name, url, key, model_count)；新建态 existing=None。
    """

    def __init__(self, parent=None, existing=None):
        super().__init__(parent)
        self._editing = existing is not None
        self.setWindowTitle('编辑 Provider' if self._editing else '新建 Provider')
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        if self._editing:
            tip = QLabel('修改名称即重命名 Provider（旧会话的 provider 映射会回退到模型推断）。')
            tip.setWordWrap(True)
            tip.setStyleSheet('color:#98989d; font-size:12px;')
            lay.addWidget(tip)
        form = QFormLayout()
        self.edit_name = QLineEdit(existing[0] if existing else '')
        self.edit_name.setPlaceholderText('如 deepseek / qwen / glm')
        form.addRow('名称', self.edit_name)
        self.edit_url = QLineEdit(existing[1] if existing else '')
        self.edit_url.setPlaceholderText('Anthropic 兼容端点，如 https://api.deepseek.com/anthropic')
        form.addRow('baseUrl', self.edit_url)
        self.edit_key = QLineEdit(existing[2] if existing else '')
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._eye = self.edit_key.addAction(ui_icon('eye', 14),
                                            QLineEdit.ActionPosition.TrailingPosition)
        self._eye.setCheckable(True)
        self._eye.setToolTip('显示/隐藏密钥')

        def _toggle_echo(on):
            # 图标随状态切换（eye↔eye-off），否则用户以为按钮坏了
            self.edit_key.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
            self._eye.setIcon(ui_icon('eye-off' if on else 'eye', 14))
        self._eye.toggled.connect(_toggle_echo)
        form.addRow('API Key', self.edit_key)
        if self._editing and len(existing) > 3 and existing[3]:
            hint = QLabel(f'已有 {existing[3]} 个模型（保存后在右侧模型池管理）')
            hint.setStyleSheet('color:#98989d; font-size:12px;')
            form.addRow('', hint)
        lay.addLayout(form)
        btns = mk_buttons(self, '保存' if self._editing else '创建')
        lay.addWidget(btns)
        # inline 校验：任一必填不合法 → OK 禁用（按钮态即反馈）
        self._btns = btns
        for e in (self.edit_name, self.edit_url):
            e.textChanged.connect(self._sync_ok)
        self._sync_ok()

    def _valid(self):
        name = self.edit_name.text().strip()
        ok_name = bool(name) and name != 'default provider' \
            and not re.search(r'\s|[/\\:*?"<>|]', name)
        ok_url = bool(re.match(r'^https?://', self.edit_url.text().strip()))
        return ok_name and ok_url

    def _sync_ok(self):
        self._btns.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self._valid())

    def values(self):
        return (self.edit_name.text().strip(),
                self.edit_url.text().strip(),
                self.edit_key.text().strip())


class AddModelDialog(FadeDialog):
    """为 Provider 添加模型（名称校验通过才能添加；可勾选设为默认模型）。"""

    def __init__(self, provider_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'添加模型 — {provider_name}')
        self.setMinimumWidth(360)
        lay = QVBoxLayout(self)
        self.edit_model = QLineEdit()
        self.edit_model.setPlaceholderText('模型名，如 deepseek-chat / qwen-max')
        lay.addWidget(self.edit_model)
        self.chk_main = QCheckBox('添加后设为默认模型')
        lay.addWidget(self.chk_main)
        self.lbl_hint = QLabel('')
        self.lbl_hint.setStyleSheet('color:#ff6961; font-size:12px;')
        lay.addWidget(self.lbl_hint)
        btns = mk_buttons(self, '添加')
        self.btn_ok = btns.button(QDialogButtonBox.StandardButton.Ok)
        lay.addWidget(btns)
        self.edit_model.textChanged.connect(self._sync)
        self.edit_model.returnPressed.connect(self._enter)
        self._sync()

    def _sync(self):
        text = self.edit_model.text().strip()
        ok = valid_model_name(text)
        self.lbl_hint.setText('' if (ok or not text) else '模型名不能含空格/斜杠，且不能像密钥')
        self.btn_ok.setEnabled(ok)

    def _enter(self):
        if self.btn_ok.isEnabled():
            self.accept()

    def values(self):
        return self.edit_model.text().strip(), self.chk_main.isChecked()


class RenameModelDialog(FadeDialog):
    """重命名模型。"""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle('重命名模型')
        self.setMinimumWidth(340)
        lay = QVBoxLayout(self)
        self.edit_model = QLineEdit(model)
        lay.addWidget(self.edit_model)
        btns = mk_buttons(self, '保存')
        self.btn_ok = btns.button(QDialogButtonBox.StandardButton.Ok)
        lay.addWidget(btns)
        self.edit_model.textChanged.connect(self._sync)
        self._sync()

    def _sync(self):
        self.btn_ok.setEnabled(valid_model_name(self.edit_model.text()))

    def value(self):
        return self.edit_model.text().strip()
