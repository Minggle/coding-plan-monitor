"""轮询调度器：QTimer 定时 + QThreadPool 并发查询，结果通过 Qt 信号回主线程。"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from app.core.config import Account
from app.core.models import AccountResult
from app.providers import fetch_account


class _Signals(QObject):
    done = Signal(object)  # AccountResult


class _FetchJob(QRunnable):
    def __init__(self, account: Account):
        super().__init__()
        self.account = account
        self.signals = _Signals()

    def run(self) -> None:
        self.signals.done.emit(fetch_account(self.account))


class RefreshScheduler(QObject):
    """管理所有启用账号的定时刷新。

    - 每 interval_sec 全量刷新一次（默认 300s）
    - force_refresh(account_id=None) 手动刷新全部或指定账号
    - 各账号查询在 QThreadPool 中并发执行，互不阻塞
    """

    resultReady = Signal(object)          # AccountResult，每账号一次
    refreshStarted = Signal()

    def __init__(self, interval_sec: int = 300, parent: QObject | None = None):
        super().__init__(parent)
        self._accounts: list[Account] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_all)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self.set_interval(interval_sec)

    def set_interval(self, sec: int) -> None:
        self._timer.setInterval(max(30, sec) * 1000)

    def set_accounts(self, accounts: list[Account]) -> None:
        self._accounts = [a for a in accounts if a.enabled]

    def start(self, immediate: bool = True) -> None:
        self._timer.start()
        if immediate:
            # 立即刷新一次，但稍微延迟让 UI 先出来
            QTimer.singleShot(300, self.refresh_all)

    def stop(self) -> None:
        self._timer.stop()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def refresh_all(self) -> None:
        if not self._accounts:
            return
        self.refreshStarted.emit()
        for acc in self._accounts:
            self._start_job(acc)

    def force_refresh(self, account_id: str | None = None) -> None:
        if account_id is None:
            self.refresh_all()
            return
        for acc in self._accounts:
            if acc.id == account_id:
                self._start_job(acc)

    def _start_job(self, account: Account) -> None:
        job = _FetchJob(account)
        job.signals.done.connect(self.resultReady)
        self._pool.start(job)
