# LKL-Trade

自动交易端：连接掘金仿真（金矿终端），按策略端投递的 `decisions.json` 实单买卖，并把成交回报 `results.json` 与真实持仓快照 `holdings.json` 写回交换目录供策略端消费。**本仓只做交易，不含任何策略/数据库代码。**

## 架构与数据流

```
DB策略端(独立仓)                     LKL-Trade（本仓，只交易）
  EOD 出决策  decisions.json ──同步──▶  trade check / watch
                                          │ 连金矿终端(127.0.0.1:7001) 实单
                                          ▼
               results.json ◀──本机 写──┘  holdings.json(真实持仓快照)
  import 消费(更新 position/signal) ◀─同步──
```

- **JSON 契约**（`~/trade/`，schema=1）：
  - `decisions.json`（策略端→本机）：当日 BUY/SELL；`for_date` = 执行日
  - `results.json`（本机→策略端）：成交回报（`ref` 幂等）
  - `holdings.json`（`lkl sim sync` 刷新）：真实持仓快照（供策略端对账 `position`）
  - `executed.json`：本地防重账本，**即使 results 丢失也不重复下单**
- **执行日一致**：所有日期一律 **Asia/Shanghai**（防海外端时区漂移导致一整日错位）。

## 安装

需 Python 3.10（gmtrade 仅 cp≤310）+ 掘金金矿终端已运行并登录模拟账户。

```bash
uv venv --python 3.10 .venv-trade
uv pip install --python .venv-trade/Scripts/python.exe .
# 凭据：写 <repo>/.secrets/gm.env（GM_TOKEN / GM_ACCOUNT_ID）
```

## 环境变量（唯一出口 `lpl/broker/config.py`；模板 `.env.example`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `GM_TOKEN` | — | 掘金仿真实 token（env 或 `.secrets/gm.env`） |
| `GM_ACCOUNT_ID` | — | 仿真账户 id |
| `GM_ENDPOINT` | `127.0.0.1:7001` | 金矿终端本地服务地址 |
| `TRADE_DIR` | `~/trade` | JSON 交换目录（两端须指向同一目录） |
| `GM_ENV_FILE` | `<repo>/.secrets/gm.env` | 凭据文件覆盖 |

## 用法（`.venv-trade/Scripts/python -m lkl.main …`）

```bash
lkl sim                  # 账户资金/持仓
lkl sim sync             # 真实持仓 → holdings.json
lkl trade check          # 三文件日期一致性 + 决策执行覆盖(出错返回非0)
lkl trade [YYYY-MM-DD]   # 执行当日 decisions → results.json
lkl sup [interval=60]    # 常驻调度器：跨日sync/check + 盘中自动实单(终端离线自愈)
lkl dash [port=8200]     # 本地看板 http://127.0.0.1:8200
lkl archive [date]    # 盘后归档已消费文件→ archive/<日期>/（防同名覆盖丢历史）
# 消费 decisions 后立即归档到 archive/ 并删除远端对应文件（不等待跨日）
```

### 开机自启（Windows 计划任务，需管理员）
```bash
python scripts/install_tasks.py install     # 注册 LKLGoldminer(终端自启)+LKLTradeSup(调度器)
python scripts/install_tasks.py uninstall   # 卸载
```

## 目录

```
lkl/
  broker/     核心交易(连接/订单/JSON交换/账本/日期/审计/sync/watch)
  models/     Signal / Position(交易所需的领域最小子集)
  services/   Executor 协议 + BrokerExecutor(gmtrade 实单)
  main.py     单入口 `lkl`(sim/trade/dash)
dashboard/    标准库 HTML + /api/state 看板
```

只做交易；无策略、无 DB。