"""设置对话框：账号管理（增删改/启用）、轮询间隔、显示形态、开机自启。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.config import Account, Config, CustomSpec
from app.providers import PROVIDER_LABELS
from app.providers.curl_parse import parse_curl


class AccountEditDialog(QDialog):
    """添加/编辑单个账号，字段随供应商类型切换。"""

    def __init__(self, account: Account | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("账号设置")
        self.setMinimumWidth(520)
        self.account = account or Account()
        self._original_id = self.account.id

        root = QVBoxLayout(self)
        form = QFormLayout()

        self._name = QLineEdit(self.account.name)
        self._name.setPlaceholderText("例如：主力 Kimi")
        form.addRow("名称", self._name)

        self._provider = QComboBox()
        for pid, label in PROVIDER_LABELS.items():
            self._provider.addItem(label, pid)
        idx = self._provider.findData(self.account.provider)
        if idx >= 0:
            self._provider.setCurrentIndex(idx)
        form.addRow("供应商", self._provider)
        root.addLayout(form)

        # ---- 各供应商字段页 ----
        self._stack = QStackedWidget()

        # Kimi
        kimi_page = QWidget()
        kimi_form = QFormLayout(kimi_page)
        self._kimi_key = QLineEdit(self.account.key if self.account.provider == "kimi" else "")
        self._kimi_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._kimi_key.setPlaceholderText("sk-...")
        kimi_form.addRow("API Key", self._kimi_key)
        self._stack.addWidget(kimi_page)

        # GLM
        glm_page = QWidget()
        glm_form = QFormLayout(glm_page)
        self._glm_key = QLineEdit(self.account.key if self.account.provider == "glm" else "")
        self._glm_key.setEchoMode(QLineEdit.EchoMode.Password)
        glm_form.addRow("API Key", self._glm_key)
        self._glm_site = QComboBox()
        self._glm_site.addItem("国内站 open.bigmodel.cn", "open.bigmodel.cn")
        self._glm_site.addItem("国际站 api.z.ai", "api.z.ai")
        if self.account.provider == "glm":
            i = self._glm_site.findData(self.account.site)
            if i >= 0:
                self._glm_site.setCurrentIndex(i)
        glm_form.addRow("站点", self._glm_site)
        self._stack.addWidget(glm_page)

        # 火山
        vol_page = QWidget()
        vol_form = QFormLayout(vol_page)
        hint = QLabel("从火山引擎控制台 Coding Plan 页面按 F12 → 网络 → 复制 GetCodingPlanUsage 请求为 curl，粘贴到下面：")
        hint.setWordWrap(True)
        vol_form.addRow(hint)
        self._vol_curl = QPlainTextEdit()
        self._vol_curl.setPlaceholderText("curl 'https://console.volcengine.com/...' -H 'cookie: ...' ...")
        self._vol_curl.setMaximumHeight(110)
        if self.account.provider == "volcano" and self.account.cookie:
            self._vol_curl.setPlainText(f"（已保存 Cookie，{len(self.account.cookie)} 字符；重新粘贴可更新）")
        vol_form.addRow("curl 命令", self._vol_curl)
        self._vol_project = QLineEdit(self.account.project_name or "default")
        vol_form.addRow("项目名", self._vol_project)
        self._stack.addWidget(vol_page)

        # 自定义
        cus_page = QWidget()
        cus_form = QFormLayout(cus_page)
        c = self.account.custom if self.account.provider == "custom" else CustomSpec()
        self._cus_url = QLineEdit(c.url)
        self._cus_url.setPlaceholderText("https://example.com/usage")
        cus_form.addRow("URL", self._cus_url)
        self._cus_method = QComboBox()
        self._cus_method.addItems(["GET", "POST"])
        self._cus_method.setCurrentText(c.method or "GET")
        cus_form.addRow("方法", self._cus_method)
        self._cus_key = QLineEdit(self.account.key if self.account.provider == "custom" else "")
        self._cus_key.setEchoMode(QLineEdit.EchoMode.Password)
        cus_form.addRow("API Key", self._cus_key)
        self._cus_headers = QLineEdit("; ".join(f"{k}: {v}" for k, v in c.headers.items()))
        self._cus_headers.setPlaceholderText("Authorization: Bearer {KEY}; X-Other: 1")
        cus_form.addRow("请求头", self._cus_headers)
        self._cus_5h = QLineEdit(c.paths.get("5h", ""))
        self._cus_7d = QLineEdit(c.paths.get("7d", ""))
        self._cus_month = QLineEdit(c.paths.get("monthly", ""))
        cus_form.addRow("5h 路径", self._cus_5h)
        cus_form.addRow("7d 路径", self._cus_7d)
        cus_form.addRow("月度路径", self._cus_month)
        path_hint = QLabel("路径为点号分隔的 JSON 字段，如 data.five_hour；值可以是百分数或 {percent, used, limit, reset} 对象")
        path_hint.setWordWrap(True)
        path_hint.setStyleSheet("color: #888;")
        cus_form.addRow(path_hint)
        self._stack.addWidget(cus_page)

        self._provider.currentIndexChanged.connect(self._stack.setCurrentIndex)
        self._stack.setCurrentIndex(self._provider.currentIndex())
        root.addWidget(self._stack)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def accept(self) -> None:
        pid = self._provider.currentData()
        acc = Account(provider=pid, name=self._name.text().strip())
        acc.id = self._original_id
        if pid == "kimi":
            acc.key = self._kimi_key.text().strip()
        elif pid == "glm":
            acc.key = self._glm_key.text().strip()
            acc.site = self._glm_site.currentData()
        elif pid == "volcano":
            acc.project_name = self._vol_project.text().strip() or "default"
            curl_text = self._vol_curl.toPlainText().strip()
            if curl_text and not curl_text.startswith("（已保存"):
                cred = parse_curl(curl_text)
                acc.cookie = cred.cookie
                acc.csrf_token = cred.csrf_token
                acc.web_id = cred.web_id
            elif self.account.provider == "volcano":
                acc.cookie, acc.csrf_token, acc.web_id = (
                    self.account.cookie, self.account.csrf_token, self.account.web_id)
        elif pid == "custom":
            acc.key = self._cus_key.text().strip()
            headers = {}
            for part in self._cus_headers.text().split(";"):
                if ":" in part:
                    k, v = part.split(":", 1)
                    headers[k.strip()] = v.strip()
            acc.custom = CustomSpec(
                url=self._cus_url.text().strip(),
                method=self._cus_method.currentText(),
                headers=headers,
                paths={
                    "5h": self._cus_5h.text().strip(),
                    "7d": self._cus_7d.text().strip(),
                    "monthly": self._cus_month.text().strip(),
                },
            )
        acc.enabled = self.account.enabled
        self.account = acc
        super().accept()


class SettingsDialog(QDialog):
    """主设置窗口。"""

    configSaved = Signal()

    def __init__(self, config: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(560)
        # 置顶，避免被悬浮窄条（topmost）盖住
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.config = config

        root = QVBoxLayout(self)

        # ---- 账号管理 ----
        group = QGroupBox("账号")
        gl = QVBoxLayout(group)
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _: self._edit_account())
        gl.addWidget(self._list)
        btns = QHBoxLayout()
        for text, fn in (("添加", self._add_account), ("编辑", self._edit_account),
                         ("删除", self._remove_account)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        gl.addLayout(btns)
        root.addWidget(group)

        # ---- 全局设置 ----
        form = QFormLayout()
        self._interval = QSpinBox()
        self._interval.setRange(60, 86400)
        self._interval.setSuffix(" 秒")
        self._interval.setValue(config.settings.poll_interval_sec)
        form.addRow("轮询间隔", self._interval)

        self._mode = QComboBox()
        self._mode.addItem("托盘圆圈", "tray")
        self._mode.addItem("悬浮窄条", "strip")
        i = self._mode.findData(config.settings.display_mode)
        if i >= 0:
            self._mode.setCurrentIndex(i)
        form.addRow("显示形态", self._mode)

        self._autostart = QCheckBox("开机自启动")
        self._autostart.setChecked(config.settings.autostart)
        form.addRow(self._autostart)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._reload_list()

    def _reload_list(self) -> None:
        self._list.clear()
        for acc in self.config.accounts:
            label = f"{'✓' if acc.enabled else '✗'}  {acc.display_name}  ·  {PROVIDER_LABELS.get(acc.provider, acc.provider)}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, acc.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if acc.enabled else Qt.CheckState.Unchecked)
            self._list.addItem(item)

    def _selected_index(self) -> int:
        return self._list.currentRow()

    def _add_account(self) -> None:
        dlg = AccountEditDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.config.accounts.append(dlg.account)
            self._reload_list()

    def _edit_account(self) -> None:
        i = self._selected_index()
        if i < 0 or i >= len(self.config.accounts):
            return
        dlg = AccountEditDialog(self.config.accounts[i], parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.config.accounts[i] = dlg.account
            self._reload_list()

    def _remove_account(self) -> None:
        i = self._selected_index()
        if 0 <= i < len(self.config.accounts):
            self.config.accounts.pop(i)
            self._reload_list()

    def _save(self) -> None:
        # 勾选状态 → enabled
        for row in range(self._list.count()):
            item = self._list.item(row)
            account_id = item.data(Qt.ItemDataRole.UserRole)
            acc = self.config.account_by_id(account_id)
            if acc:
                acc.enabled = item.checkState() == Qt.CheckState.Checked
        self.config.settings.poll_interval_sec = self._interval.value()
        self.config.settings.display_mode = self._mode.currentData()
        self.config.settings.autostart = self._autostart.isChecked()
        self.configSaved.emit()
        self.accept()
