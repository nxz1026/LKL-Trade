# LKL-Trade

自动交易端：连接掘金仿真（金矿终端），按策略端投递的 `decisions.json` 实单买卖，并把执行回报 `results.json` 与真实持仓快照 `holdings.json` 写回交换目录供策略端消费。**本仓只做交易，不含任何策略/数据库代码。**

> 安全语义（2026-09 加固）：防重账本 `executed.json` **只记录「已确认成交 FILLED」**；
> 拒单、无持仓、部分成交的剩余量一律可自动重试，绝不静默记成完成。同一交换目录**同一时刻只允许一个执行器**（进程锁），重复启动直接拒绝；下单前先写意图、重启先对账，防崩溃重复下单。订单回报以券商最终状态为准（已报/部分成交/已成交/已拒），不以 `order_id` 是否存在当成交。

## 架构与数据流

```
DB策略端(独立仓)                     LKL-Trade（本仓，只交易）
  EOD 出决策  decisions.json ──同步──▶  trade check / watch / sup
                                          │ 连金矿终端(127.0.0.1:7001) 单向门禁下单
                                          ▼
               results.json ◀──本机 写──┘    executions.json / pending.json / 心跳
                 holdings.json(真实持仓快照)
  import 消费(更新 position/signal) ◀─同步──
```

- **JSON 契约**（`~/trade/`，schema=2，见 `docs/exchange-contract.v2.md`）：
  - `decisions.json`（策略→本机）：当日 `for_date` + `actions[]`（每条 code/action/exec/volume/reason/window；exec 是执行分发依据：OPEN_POS↔BUY、CLOSE_ALL↔SELL，缺失按 action 兜底）
  - `results.json`（本机→策略/DB）：当日执行明细，DB 消费 `action/code/ok/price/shares/order_id/reason`
    （另带 status/status_label/filled/remaining/note/traded_at 供看板与审计，DB 可忽略）。
    **status 语义（v2 契约）**：回报自带显式 `status`，消费端优先取该值，不得用 reason 含字启发式
    猜状态——`REJECTED`=门禁/券商拒（**可重试**，非终态），`CANCELLED`=撤单（终态），
    `EXCLUDED`=决策排除（历史/人工，不再产生）。
  - `holdings.json`（`lkl sim sync` 刷新）：真实持仓快照（供策略端对账）
  - `manual_orders.json`（`lkl sim sync` 顺带回捞）：终端**当日全部委托**（含手动单与 LKL 自动单），
    行结构同 results，带 `source: manual|decision`（order_id 不在当日 results = manual）与
    order 级 `ref`（`{for_date}|{code}|{action}|{order_id}`，幂等键）；增量回捞，仅当委托
    集合（order_id×status）有新增/状态变化才写新文件并上传，DB 对账手动操作消费 `source=manual` 行
  - `executed.json`（本机）：防重账本，**只记已确认成交**（防 results 丢后重复下单）
  - `pending.json`（本机）：下单意图日志（防崩溃在「已下单-未记账」窗口重复提交）
  - `heartbeat.json`：本地进程脉冲（本地看板判 sup 存活；不进 v2 契约、不上传远端）
- **执行日一致性**：所有业务日期一律 **Asia/Shanghai**。
- **交易时段**：盘内(9:30-11:30/13:00-15:00)自动执行；周末与休市日（`GM_HOLIDAYS`）不开市；
  任何 `trade / watch / sup` 入口统一在订单层做交易时段门禁（盘外拒单，开市后再试）。
- **window**（契约 v2 起仅为展示标签，不参与执行判断）：MORNING/AFTERNOON/NONE 等原买入口径不再有执行语义；SELL 清仓与 window=NONE 并存是正常组合，照样下单。
- **调度窗口**：盘内自动执行当日决策；工作日 12:01-12:59 与 17:30-18:01 每 1 分钟轮询同步决策。
- **文件命名**：`{kind}_YYYYMMDD_HHMMSS.json` 秒级时间戳、Asia/Shanghai(+8)（v2 契约，日内多版本不覆盖）；读取一次拉取远端**全部** decisions，按文件名时间**升序**（旧→新）逐份执行——同一 code 多份跨 action 决策严格按投递顺序处理（先 BUY 后 SELL，绝不倒序）；每份完成后归档本地 + 删远端（for_date 守卫），不留积压。

## 安装

本仓库用 Python 3.10（`gmtrade` 仅 cp≤3.10）+ 掘金发布终端（已登录模拟账户）。

```bash
uv venv --python 3.10 .venv-trade
uv pip install --python .venv-trade/Scripts/python.exe -e '.[trade]'   # 可编辑安装 + gmtrade
```

> **必须用可编辑（-e）安装**：凭据默认从 `<仓库>/.secrets/gm.env` 读取（`config.py` 按模块路径找仓库根）。
> 普通 `pip install .` 会把模块装进 site-packages，`lkl` 命令将找不到 `.secrets`。测试也建议对源码运行。

## 环境变量（唯一出口 `lkl/broker/config.py`；模板 `.env.example`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `GM_TOKEN` | — | 仿真 token（env 或 `.secrets/gm.env`） |
| `GM_ACCOUNT_ID` | — | 仿真账户 id |
| `GM_ENDPOINT` | `127.0.0.1:7001` | 金矿终端本地服务 |
| `TRADE_DIR` | `~/trade` | JSON 交换目录（两端同一目录） |
| `GM_ENV_FILE` | `<repo>/.secrets/gm.env` | 凭据文件覆盖 |
| `GM_HOLIDAYS` | — | 休市日补充（逗号分隔 `YYYY-MM-DD`） |
| `GM_RISK_MAX_QTY` | 0 | 风控：单笔最大股数（0=不限） |
| `GM_RISK_MAX_ORDERS` | 0 | 风控：当日最大下单次数（0=不限） |
| `GM_RISK_MAX_CODES` | 0 | 风控：当日最多操作只数（0=不限） |
| `GM_RECON_ORDERS` | 0 | 对账时联券商当日委托核验（需终端登录） |
| `GM_KEEP_REMOTE` | 0 | 0(默认)=已执行决策**先归档本地再删远端**(for_date 守卫)；1=保留远端原文件作审计追溯 |
| `GM_REMOTE_HOST/KEY/DIR` | — | 受限 SFTP 同步（v2）；`DIR`=你的用户子目录（如 `user1`），禁 `..`/绝对路径 |

## 用法（`.venv-trade/Scripts/python -m lkl.main …`）

```bash
lkl sim                  # 账户资金/持仓
lkl sim sync             # 真实持仓 → holdings.json；顺带回捞终端当日全部委托(含手动单) → manual_orders.json
lkl trade check          # 三文件日期一致性 + 决策成交覆盖(缺/损返回非0)
lkl trade [YYYY-MM-DD]   # 执行当日 decisions → results.json（先拉远、绑定文件、锁、防重）
lkl trade watch          # 循环盯盘（受交易日/盘中门禁约束，盘外不下单）
lkl trade govern <status|dry|arm|halt|resume>  # 安全治理：默认 dry 演练；arm=实盘；halt=急停(持久)
lkl trade preview [date] # 交易前预演：逐条可执行/受阻原因，不下单不落盘
lkl trade recon [date]   # 对账：决策/成交/持仓(±委托) 四源一致，异常返回非0
lkl trade alerts         # 告警中心：CRIT/WARN 汇总 + 明细
lkl trade resolve <ref> <retry|ignore|complete> [note]  # 人工处置拒单/部分成交/不符
lkl doctor               # 首次使用自检向导（切实盘前置要求关键项通过）
lkl sup [interval=60]    # 常驻调度器：跨日归档/sync/check + 盘中自动下单(单轮异常自动续)
                                #   GM_KEEP_REMOTE=1：成交/对账前保留远端决策不自动删
lkl dash [port=8200]     # 本地看板 http://127.0.0.1:8200
lkl archive [YYYY-MM-DD] # 归档已消费文件 → archive/<日期>/
```

### 开机自启（Windows 计划任务，需管理员）——托盘托管，无黑框

```bash
# 先卸载旧版（会一并清掉旧 LKLTradeSup/LKLDash 黑框任务），再安装
python scripts/install_tasks.py uninstall
python scripts/install_tasks.py install     # 注册 LKLGoldminer + LKLTray(托盘, pythonw 无控制台)
python scripts/lkl_tray.py health           # 托盘依赖/路径自检
pythonw scripts/lkl_tray.py                 # 手动试跑托盘（零第三方依赖，图标在通知区）
```

托盘（`scripts/lkl_tray.py`，**零第三方依赖**，ctypes+Win32）开机自动隐藏启动 **sup(调度) + dash(看板)**，
日志在 `logs/sup.log` `logs/dash.log`，异常写 `logs/lkl_tray.err`。
右键菜单：sup/dash 状态、启停服务、演练/实盘/紧急停止/解除、打开看板、退出（退出停止托管服务）；
左键双击=打开看板。
**切换前先关闭旧的两个 python 黑框**，避免 8200 端口/双调度冲突。

## 目录

```
lkl/
  broker/    核心交易（连接/订单/JSON 交换/账本/意图/锁/状态机/策略门禁/安全治理/对账/告警/watch）
  services/  BrokerExecutor（gmtrade 实单）
  dashboard/ 标准库 HTML 看板（账户/决策/回报/委托/对账/告警/治理）
tests/       pytest 故障注入与契约测试
docs/        exchange-contract.v2.md(字段契约) · TESTING.md(测试步骤) · DB-CONFIRM.md(联调确认清单)
```

只做交易；无策略、无 DB。

## 安全语义速记

- 默认 **dry（演练/只读）**：`lkl trade govern arm` 才允许自动下单；`halt` 紧急停止即时且持久。
- **只有已成交(FILLED)** 进 `executed.json` 防重账本；拒单/部分成交可自动重试（≤3 次留人工）。
- **REJECTED（含门禁拒，如盘外「非交易日或不在盘中时段」）与 EXCLUDED 是两回事**：REJECTED 可重试、
  留档待开市再试；EXCLUDED 是历史/人工语义、不再重试。结果文件里的 `status` 字段是唯一权威，别猜。
- 单执行器进程锁；先记意图(pending.json)再下单、重启对账，防崩溃重复提交。
- 风控护栏（`GM_RISK_*`）在订单前拦截；对账不符/风控拦截/急停/调度异常进 `alerts.jsonl` 分级告警。
- 测试与双端联调：见 `docs/TESTING.md`（分级步骤）与 `docs/DB-CONFIRM.md`（DB 需拍板项）。