## Coding Plan Monitor v0.1.0 — 首个发布版

Windows 桌面小组件，定时查询各家 Coding Plan 用量配额（Kimi / 智谱 GLM / 火山引擎 / 自定义），多账号、悬浮窄条 + 托盘 + 详情面板。

### 安装

下载 **`CodingPlanMonitor-Setup-0.1.0.exe`** 双击安装：

- 免 UAC（安装到用户目录），无需 Python 环境
- 安装完成自动在**桌面创建快捷方式**（可选开机自启）
- 卸载通过「设置 → 应用」或开始菜单中的卸载项

### 功能

- 三家供应商 + 自定义接口；多账号管理、排序、启停
- 三个用量窗口：5 小时 / 7 天 / 月度（百分比 + 重置倒计时）
- 悬浮窄条（双环进度、可拖拽锁定）、托盘汇总、详情面板卡片
- 每 5 分钟自动刷新（可调），失败保留上次快照
- 数据仅保存在本地 `%APPDATA%\coding-plan-monitor\`

### 校验

- 版本：0.1.0 · 测试：80 passed
- 打包：PyInstaller 6.22（onedir / windowed）· 安装包：Inno Setup 6.7（LZMA2）