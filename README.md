# Coding Plan 用量监控

一个 Windows 桌面小组件，定时查询各家 Coding Plan（编程套餐）的用量配额：
**Kimi、智谱 GLM、火山引擎**，并支持自定义供应商、多账号。

![Python](https://img.shields.io/badge/Python-3.11+-blue) ![PySide6](https://img.shields.io/badge/UI-PySide6-green) ![Tests](https://img.shields.io/badge/tests-37%20passed-brightgreen)

## 功能一览

- **三家供应商 + 自定义**
  - **Kimi**：`GET api.kimi.com/coding/v1/usages`（Bearer Key），兼容 `TIME_UNIT_MINUTE` 枚举、`used` 缺失时由 `limit - remaining` 推算；月度池接口不可见，内置**月度耗尽探测**（见「已知限制」）
  - **GLM（智谱）**：`GET {site}/api/monitor/usage/quota/limit`（裸 Key 无 Bearer），支持国内站 `open.bigmodel.cn` / 国际站 `api.z.ai`
  - **火山引擎**：支持 **Coding Plan** 与 **Agent Plan** 两种套餐——官方 OpenAPI（AK/SK + V4 签名），`GetAFPUsage` / `GetCodingPlanUsage` 自动检测；也兼容控制台 Cookie 粘贴 curl（Agent 侧为 `GetAgentPlanAFPUsage`），自动提取 Cookie / x-csrf-token / x-web-id
  - **自定义**：URL + 请求头模板（`{KEY}` 占位）+ 三个窗口的 JSON 路径映射，可接入任意类似接口
- **多账号**：每家可添加多个 Key，可单独启用/禁用；设置里可拖拽或按钮**调整顺序**，窄条双环与详情面板同步跟随
- **三个窗口用量**：5 小时、7 天、月度（百分比 + 重置时间；不支持的窗口显示 N/A）
- **自动刷新**：默认每 5 分钟轮询（可配 60s+），托盘/面板/窄条均可手动刷新；QThreadPool 并发查询不卡 UI
- **悬浮窄条**：无边框置顶小长条，每账号一个**双环**（**外环 = 5 小时，内环 = 7 天**，中心数字为 5h 窗口剩余分钟数，每 30 秒自减），可拖拽、可锁定位置（位置与锁定状态均持久化）
- **托盘**：静态图标（蓝底 C），tooltip 汇总全部账号用量；单击弹详情面板；鉴权失败时显示警告角标
- **详情面板**：每账号一张卡片，5h / 7 天 / 月度三个进度环 + 重置倒计时；可拖拽移动、失焦自动隐藏、✕ 关闭
- **失败降级**：查询失败保留上次成功数据并标注"刷新失败"；快照持久化，重启即有数据
- **诊断日志**：每次查询的原始 API 响应（不含凭证）写入 `%APPDATA%\coding-plan-monitor\logs\`
- **开机自启**：注册表 Run 键 + `launch.pyw` 无窗口启动，不依赖工作目录

## 快速开始

```bash
cd coding-plan-monitor
python -m venv .venv
.venv/Scripts/pip install PySide6 httpx
.venv/Scripts/python -m app.main     # 或双击 run.bat
```

启动后：右键窄条（或托盘图标）→ **设置** → 添加账号：

| 供应商 | 需要什么 |
|---|---|
| Kimi | Coding Plan 的 API Key（`sk-...`） |
| GLM | bigmodel.cn / z.ai 控制台的 API Key + 选择对应站点 |
| 火山引擎 | 推荐：IAM 密钥管理创建 AccessKey（子账号需 `ArkReadOnlyAccess`），套餐类型默认「自动检测」；或控制台对应套餐页面 F12 复制用量请求为 curl 整段粘贴 |
| 自定义 | URL、请求头模板（`{KEY}` 占位）、三个窗口的 JSON 路径（如 `data.five_hour`） |

勾选「开机自启动」保存后，下次开机自动后台运行。

## 使用说明

- **窄条双环**：外环 5h、内环 7d；颜色分级：绿 < 60% ≤ 黄 < 85% ≤ 红；灰 = 无数据/查询失败（中心显示 `!`）
- **窄条被任务栏盖住**：内置每 1.5 秒定时置顶（不抢焦点），点击任务栏后会自动浮回；弹菜单/模态对话框时暂停
- **自定义 JSON 路径**：值可以是百分数（`42.5` 或 `0.425`），也可以是 `{"percent": x, "used": x, "limit": x, "reset": x}` 对象

## 配置与数据

`%APPDATA%\coding-plan-monitor\`：

| 文件 | 内容 |
|---|---|
| `config.json` | 账号（Key/Cookie/AK）、轮询间隔、面板列数、窄条位置与锁定、开机自启 |
| `cache.json` | 各账号最近一次成功快照（失败降级/冷启动用） |
| `logs\*.json` | 每次查询的原始 API 响应（不含凭证，供诊断） |

Key 与 Cookie 仅保存在本地，不会上传到任何第三方。

## 项目结构

```
app/
├── main.py              # 入口与装配（配置/缓存/调度器/UI）、开机自启
├── core/
│   ├── models.py        # UsageSnapshot / UsageWindow / AccountResult
│   ├── config.py        # JSON 配置读写
│   ├── cache.py         # 快照持久化
│   └── scheduler.py     # QTimer 轮询 + QThreadPool 并发查询
├── providers/           # kimi / glm / volcano / custom + curl 解析，统一输出 UsageSnapshot
└── ui/
    ├── rings.py         # 进度环绘制（单环/双环/静态图标）
    ├── tray.py          # 托盘（静态图标 + 菜单）
    ├── strip.py         # 悬浮窄条（双环 + 拖拽/锁定 + 定时置顶）
    ├── panel.py         # 详情面板（账号卡片 × 三窗口环）
    └── settings.py      # 设置对话框（账号管理/间隔/形态/自启）
tests/                   # 37 个测试：解析器（真实响应 fixtures）/ 配置 / 缓存 / UI 离屏
launch.pyw               # 开机自启启动器
run.bat                  # 手动启动
```

## 测试

```bash
.venv/Scripts/python -m pytest -q
```

## 已知限制

- Windows 11 任务栏「小组件」位置不开放给第三方，悬浮窄条是最接近"嵌入任务栏"的形态
- 火山引擎 Cookie 方式会过期（托盘出现警告角标 + 面板提示后，重新粘贴 curl 即可）；AccessKey 方式不过期，推荐使用
- GLM 接口只返回百分比，不返回绝对 token 数；Kimi 套餐为次数制（limit 100 一类），7 天窗口用顶层 `usage` 汇总兜底
- Kimi **月度配额**在任何查询接口都不可见：仅当 5h/周窗口都远未满（<95%）时，每 6 小时发一次 `max_tokens=1` 的推理探测（会消耗 1 次请求额度）——返回 403「usage limit for this billing cycle」判定为月度耗尽，月度环显示 100%「已耗尽」，恢复后下次探测自动解除
